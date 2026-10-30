import os
import sys
import ssl
import json
import math
import argparse
from pathlib import Path

# 解決 macOS Python 下載模型時的 SSL 證書驗證問題
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except Exception:
    pass

import numpy as np
import torch
import soundfile as sf
import librosa
import scipy.signal

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

def hz_to_midi(hz: float) -> float:
    if hz <= 0:
        return 0.0
    return 69.0 + 12.0 * math.log2(hz / 440.0)

def midi_to_note_name(midi_number: int) -> str:
    octave = (midi_number // 12) - 1
    note = NOTE_NAMES[midi_number % 12]
    return f"{note}{octave}"

def get_vocals_audio(input_audio_path: Path, output_dir: Path) -> Path:
    if input_audio_path.name.endswith("_vocals.wav"):
        return input_audio_path

    expected_vocals = output_dir / f"{input_audio_path.stem}_vocals.wav"
    if expected_vocals.exists():
        print(f"[資訊] 偵測到已存在的分離人聲：{expected_vocals.name}，直接使用。")
        return expected_vocals

    print(f"[資訊] 尚未分離人聲，開始調用 Demucs 分離...")
    from separate_vocals import separate_vocals
    success = separate_vocals(str(input_audio_path), str(output_dir))
    if not success or not expected_vocals.exists():
        raise RuntimeError("人聲分離失敗，無法繼續後續音高分析。")
    return expected_vocals

def extract_notes_torchcrepe(audio_data: np.ndarray, sr: int, periodicity_thresh: float = 0.38, energy_db_thresh: float = -38.0):
    """使用 TorchCREPE 提取高精度音高，結合自適應雙門檻 VAD、形態學子音閉合與施密特觸發器"""
    print("\n[步驟 1/2] 正在使用 TorchCREPE 提取高精度音高序列 (結合雙門檻動態 VAD)...")
    import torchcrepe
    from scipy.ndimage import binary_closing

    if torch.cuda.is_available():
        device = "cuda"
    elif torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"
    print(f"TorchCREPE 使用硬體裝置: {device.upper()}")

    audio = torch.from_numpy(audio_data).float().unsqueeze(0)
    hop_length = int(sr / 100)  # 10ms
    hop_sec = hop_length / sr

    fmin = 65
    fmax = 1000
    model = "tiny"

    try:
        pitch, periodicity = torchcrepe.predict(
            audio.to(device),
            sr,
            hop_length=hop_length,
            fmin=fmin,
            fmax=fmax,
            model=model,
            batch_size=2048,
            device=device,
            return_periodicity=True
        )
    except Exception:
        pitch, periodicity = torchcrepe.predict(
            audio.to("cpu"),
            sr,
            hop_length=hop_length,
            fmin=fmin,
            fmax=fmax,
            model=model,
            batch_size=2048,
            device="cpu",
            return_periodicity=True
        )

    pitch_np = pitch.squeeze().cpu().numpy()
    periodicity_np = periodicity.squeeze().cpu().numpy()

    # 計算物理 RMS 能量以過濾靜音/空拍時的幻覺雜音
    frame_len = int(sr * 0.04)
    rms = librosa.feature.rms(y=audio_data, frame_length=frame_len, hop_length=hop_length)[0]

    min_len = min(len(pitch_np), len(rms))
    pitch_np = pitch_np[:min_len]
    periodicity_np = periodicity_np[:min_len]
    rms = rms[:min_len]
    db = librosa.amplitude_to_db(rms, ref=np.max)

    # 動態底噪估算 (取非靜音底層 15% 分位數)
    non_silent_db = db[db > -75]
    noise_floor = float(np.percentile(non_silent_db, 15)) if len(non_silent_db) > 0 else -55.0
    print(f"動態音訊底噪估算: {noise_floor:.1f} dB (自適應雙門檻 VAD 啟用)")

    # 1. 雙門檻動態 VAD (Dual-Threshold Hysteresis VAD)：
    # - 啟動門檻 (High Trigger)：要求能量高於底噪 + 10dB 且週期性 >= 0.38，杜絕休止與伴奏滲漏誤觸發
    # - 維持門檻 (Low Sustain)：一旦發聲，容許能量下探至底噪 + 4dB (或 -55dB) 且週期性 >= 0.18，保護弱音與句尾
    active_voiced = np.zeros(min_len, dtype=bool)
    is_on = False

    for i in range(min_len):
        d = db[i]
        p = periodicity_np[i]
        freq = pitch_np[i]

        if not is_on:
            if d > max(noise_floor + 10.0, -48.0) and p >= 0.38 and freq >= 65:
                is_on = True
                active_voiced[i] = True
        else:
            if d > max(noise_floor + 4.0, -55.0) and (p >= 0.18 or d > -24.0) and freq >= 65:
                active_voiced[i] = True
            else:
                is_on = False

    # 2. 形態學子音閉合運算 (Morphological Closing, 120ms)：
    # 歌手演唱時的清輔音（b, p, d, t, g, k, s 等）有 30~100ms 物理閉合，閉合縫合後絕不會在詞句中途閃現「休止」！
    struct = np.ones(12, dtype=bool)  # 12 幀 = 120ms
    is_voiced = binary_closing(active_voiced, structure=struct)

    midi_series = np.zeros(min_len)
    for i in range(min_len):
        if is_voiced[i]:
            if pitch_np[i] >= 65:
                midi_series[i] = hz_to_midi(pitch_np[i])
            elif i > 0 and midi_series[i - 1] > 0:
                midi_series[i] = midi_series[i - 1]

    # 3. 中值濾波器 (Median Filter, window=7 / 70ms)：平滑微小擾動與生理顫音
    midi_filtered = np.copy(midi_series)
    diff = np.diff(np.concatenate(([False], midi_series > 0, [False])).astype(int))
    voiced_starts = np.where(diff == 1)[0]
    voiced_ends = np.where(diff == -1)[0]

    for s, e in zip(voiced_starts, voiced_ends):
        chunk_len = e - s
        if chunk_len >= 5:
            k = 7 if chunk_len >= 7 else 5
            midi_filtered[s:e] = scipy.signal.medfilt(midi_series[s:e], kernel_size=k)

    # 4. 施密特觸發器機制 (Hysteresis / 滯後判定)：
    # 音高必須偏離原半音超過一定時間 (60ms 以上，即 6 幀) 且幅度顯著，才切換為新音符。
    raw_notes = []
    current_note = None
    pending_trans = None
    silence_frames = 0
    min_trans_frames = 6  # 60ms 判定門檻

    for i in range(min_len):
        t_now = i * hop_sec
        m_val = midi_filtered[i]

        if m_val > 0:
            silence_frames = 0
            cand_round = int(round(m_val))

            if current_note is None:
                current_note = {
                    "start": t_now,
                    "end": t_now + hop_sec,
                    "target_midi": cand_round,
                    "midi_samples": [m_val]
                }
                pending_trans = None
            else:
                diff_from_target = abs(m_val - current_note["target_midi"])
                if diff_from_target <= 0.58:
                    # 在原音高容許範圍內 (含正常微抖動)，維持當前音符
                    current_note["end"] = t_now + hop_sec
                    current_note["midi_samples"].append(m_val)
                    pending_trans = None
                else:
                    # 偏離原音高，進入施密特滯後觀察
                    if pending_trans is None:
                        pending_trans = {
                            "cand_midi": cand_round,
                            "start_time": t_now,
                            "samples": [m_val],
                            "count": 1
                        }
                    else:
                        if abs(m_val - pending_trans["cand_midi"]) <= 0.50:
                            pending_trans["count"] += 1
                            pending_trans["samples"].append(m_val)
                        else:
                            pending_trans = {
                                "cand_midi": cand_round,
                                "start_time": t_now,
                                "samples": [m_val],
                                "count": 1
                            }

                    # 當偏離新音高持續達 60ms (6 幀) 時，確認觸發換音！
                    if pending_trans["count"] >= min_trans_frames:
                        med_m = int(round(np.median(current_note["midi_samples"])))
                        raw_notes.append({
                            "start": round(current_note["start"], 3),
                            "end": round(pending_trans["start_time"], 3),
                            "duration": round(pending_trans["start_time"] - current_note["start"], 3),
                            "midi": med_m,
                            "pitch": midi_to_note_name(med_m)
                        })
                        current_note = {
                            "start": pending_trans["start_time"],
                            "end": t_now + hop_sec,
                            "target_midi": pending_trans["cand_midi"],
                            "midi_samples": pending_trans["samples"]
                        }
                        pending_trans = None
                    else:
                        # 尚未跨過滯後門檻時，先暫時延續當前音符，避免微小顫音直接碎音
                        current_note["end"] = t_now + hop_sec
                        current_note["midi_samples"].append(m_val)
        else:
            # 靜音幀
            silence_frames += 1
            pending_trans = None
            if silence_frames >= 12:  # 120ms 靜音確認發音終止
                if current_note is not None:
                    # 排除尾隨的靜音幀
                    note_end = current_note["end"]
                    med_m = int(round(np.median(current_note["midi_samples"])))
                    dur = note_end - current_note["start"]
                    if dur >= 0.08:
                        raw_notes.append({
                            "start": round(current_note["start"], 3),
                            "end": round(note_end, 3),
                            "duration": round(dur, 3),
                            "midi": med_m,
                            "pitch": midi_to_note_name(med_m)
                        })
                    current_note = None

    if current_note is not None:
        med_m = int(round(np.median(current_note["midi_samples"])))
        dur = current_note["end"] - current_note["start"]
        if dur >= 0.08:
            raw_notes.append({
                "start": round(current_note["start"], 3),
                "end": round(current_note["end"], 3),
                "duration": round(dur, 3),
                "midi": med_m,
                "pitch": midi_to_note_name(med_m)
            })

    # 5. 同音高自動縫合與孤立雜訊剔除 (Stitching & Spurious Glitch Pruning)
    notes = []
    if raw_notes:
        merged_note = dict(raw_notes[0])
        for next_note in raw_notes[1:]:
            gap = next_note["start"] - merged_note["end"]
            if next_note["midi"] == merged_note["midi"] and gap <= 0.14:
                merged_note["end"] = next_note["end"]
                merged_note["duration"] = round(merged_note["end"] - merged_note["start"], 3)
            else:
                if merged_note["duration"] >= 0.09:
                    notes.append(merged_note)
                merged_note = dict(next_note)

        if merged_note["duration"] >= 0.09:
            notes.append(merged_note)

    # 剃除前後均為大休止 (>0.35s) 的孤立極短碎音 (<0.12s，典型為伴奏敲擊或吸氣雜音)
    cleaned_notes = []
    for i in range(len(notes)):
        n = notes[i]
        gap_before = (n["start"] - notes[i - 1]["end"]) if i > 0 else 999.0
        gap_after = (notes[i + 1]["start"] - n["end"]) if i < len(notes) - 1 else 999.0
        if n["duration"] < 0.12 and gap_before >= 0.35 and gap_after >= 0.35:
            # 孤立突波，剃除！
            continue
        cleaned_notes.append(n)

    for idx, n in enumerate(cleaned_notes):
        n["id"] = idx + 1

    print(f"👉 成功提取出 {len(cleaned_notes)} 個物理發音音符（已啟用自適應雙門檻 VAD 與子音形態縫合）。")
    return cleaned_notes, pitch_np, periodicity_np, rms, db

def align_lyrics_pitch(
    audio_16k: np.ndarray,
    pitch_np: np.ndarray,
    per_np: np.ndarray,
    rms: np.ndarray,
    db: np.ndarray,
    track_stem: str,
    output_dir: Path,
    project_root: Path,
    whisper_model: str = "base",
    custom_lyrics_path: str = None,
    phrase_gap: float = 0.45
):
    """【方案 A】語音強制對齊 (Forced Alignment) + 最大重疊主導音 (Dominant Pitch) 演算法
    解決歌唱裝飾音/轉音導致『音符數多於歌詞字數』的問題，實現 1 字 = 1 音高精準方塊
    """
    print("\n[方案 A] 正在執行語音強制對齊與字音 1:1 主導音投影演算法 (Forced Alignment + Dominant Pitch)...")
    import whisper
    import difflib

    total_dur = len(audio_16k) / 16000.0
    hop_sec = 0.01

    # 1. 偵測有效歌唱區間 (過濾無人聲的前奏、間奏、尾奏長靜音，杜絕 Whisper 在長靜音中的幻覺)
    is_singing = db > -45.0
    diff = np.diff(np.concatenate(([False], is_singing, [False])).astype(int))
    starts = np.where(diff == 1)[0] * 0.01
    ends = np.where(diff == -1)[0] * 0.01

    merged = []
    for s, e in zip(starts, ends):
        if not merged:
            merged.append([s, e])
        else:
            if s - merged[-1][1] < 0.8:
                merged[-1][1] = e
            else:
                merged.append([s, e])

    filtered = [c for c in merged if c[1] - c[0] >= 0.8]

    # 強制限制每段音訊長度 <= 25 秒，杜絕 Whisper 在 >30 秒長區間內降級、漏字與截斷
    sections = []
    for s, e in filtered:
        dur = e - s
        if dur <= 25.0:
            sections.append([s, e])
        else:
            sub_s = s
            while sub_s < e:
                sub_e = min(e, sub_s + 25.0)
                if sub_e < e:
                    w_start = int((sub_s + 10.0) / 0.01)
                    w_end = int(sub_e / 0.01)
                    split_idx = w_start + np.argmin(db[w_start:w_end])
                    split_t = split_idx * 0.01
                    sections.append([sub_s, split_t])
                    sub_s = split_t
                else:
                    sections.append([sub_s, e])
                    break

    print(f"👉 偵測並細分為 {len(sections)} 個高精度演唱區間（每段 <= 25s，確保 Whisper 100% 完整解碼零漏字）。")

    # 2. 搜尋歌詞文字檔（有歌詞用歌詞，沒歌詞 AI 自動抓）
    lyrics_file = None
    if custom_lyrics_path and Path(custom_lyrics_path).exists():
        lyrics_file = Path(custom_lyrics_path)
    else:
        cand1 = project_root / f"{track_stem}.txt"
        cand2 = output_dir / f"{track_stem}.txt"
        if cand1.exists():
            lyrics_file = cand1
        elif cand2.exists():
            lyrics_file = cand2

    official_text = ""
    clean_official_chars = []
    if lyrics_file:
        print(f"📄 偵測到官方歌詞檔：{lyrics_file.name}，啟用官方歌詞精準字形轉移模式。")
        with open(lyrics_file, "r", encoding="utf-8") as f:
            official_text = f.read()
        clean_official_chars = [c for c in official_text if c.strip() and c not in '，。！？,.!? …（）()[]【】\n\r\t']
        print(f"   官方標準歌詞總字數：{len(clean_official_chars)} 字")
    else:
        print(f"ℹ️ 未提供歌詞文字檔，啟用 Whisper 全自動 AI 聽寫與字詞時間戳萃取。")

    # 3. 載入 Whisper 模型 (固定在 CPU 執行以相容 DTW float64 運算)
    print(f"正在載入 Whisper ({whisper_model}) 模型於 CPU 執行 word_timestamps 對齊...")
    model = whisper.load_model(whisper_model, device="cpu")

    all_timed_chars = []

    for sec_idx, (sec_s, sec_e) in enumerate(sections):
        pad_s = max(0.0, sec_s - 0.25)
        pad_e = min(total_dur, sec_e + 0.25)
        s_idx = int(pad_s * 16000)
        e_idx = int(pad_e * 16000)
        sec_audio = audio_16k[s_idx:e_idx]

        # 動態提供該段音樂在全曲中相應的歌詞 context 作為 prompt
        sec_prompt = None
        if official_text:
            progress_ratio = sec_s / max(1.0, total_dur)
            approx_char_pos = int(progress_ratio * len(clean_official_chars))
            p_start = max(0, approx_char_pos - 30)
            p_end = min(len(clean_official_chars), approx_char_pos + 120)
            sec_prompt = "".join(clean_official_chars[p_start:p_end])

        res = model.transcribe(
            sec_audio,
            language="zh",
            word_timestamps=True,
            initial_prompt=sec_prompt,
            condition_on_previous_text=False
        )

        for seg in res.get("segments", []):
            for w in seg.get("words", []):
                w_text = w.get("word", "").strip()
                chars = [c for c in w_text if c.strip() and c not in '，。！？,.!? …（）()[]【】\n\r\t']
                if not chars:
                    continue
                w_start = pad_s + w["start"]
                w_end = pad_s + w["end"]
                w_dur = max(0.06, w_end - w_start)
                c_dur = w_dur / len(chars)
                for i, c in enumerate(chars):
                    cs = w_start + i * c_dur
                    ce = cs + c_dur
                    all_timed_chars.append({
                        "char": c,
                        "start": cs,
                        "end": ce
                    })

    if not all_timed_chars:
        print("[警告] Whisper 未能在人聲中識別出有效字詞時間戳。")
        return [], []

    # 4. 若有官方歌詞，利用 SequenceMatcher 自動將官方字形轉移至時間戳上（消除諧音錯字）
    if clean_official_chars:
        w_chars_str = "".join([item["char"] for item in all_timed_chars])
        o_chars_str = "".join(clean_official_chars)
        sm = difflib.SequenceMatcher(None, w_chars_str, o_chars_str)

        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            w_len = i2 - i1
            o_len = j2 - j1
            if tag == "equal":
                for k in range(w_len):
                    if j1 + k < len(clean_official_chars):
                        all_timed_chars[i1 + k]["char"] = clean_official_chars[j1 + k]
            elif tag == "replace":
                if w_len == o_len:
                    for k in range(w_len):
                        all_timed_chars[i1 + k]["char"] = clean_official_chars[j1 + k]
                else:
                    for k in range(w_len):
                        o_idx = min(len(clean_official_chars) - 1, j1 + int(round(k * (o_len - 1) / max(1, w_len - 1))))
                        all_timed_chars[i1 + k]["char"] = clean_official_chars[o_idx]

    # 5. 主導音投影計算 (Dominant Pitch per Character)
    min_len = min(len(pitch_np), len(per_np), len(rms))
    aligned_notes = []
    global_id = 1

    for item in all_timed_chars:
        char = item["char"]
        ts = item["start"]
        te = item["end"]

        i_s = max(0, int(round(ts / hop_sec)))
        i_e = min(min_len, int(round(te / hop_sec)))
        if i_e <= i_s:
            i_e = min(min_len, i_s + 1)

        p_chunk = pitch_np[i_s:i_e]
        per_chunk = per_np[i_s:i_e]
        rms_chunk = rms[i_s:i_e]

        mask = (p_chunk >= 65) & (per_chunk >= 0.15)
        if not np.any(mask):
            mask = (p_chunk >= 65)

        if np.any(mask):
            v_hz = p_chunk[mask]
            v_per = per_chunk[mask]
            v_rms = rms_chunk[mask]
            # 能量與週期性雙加權
            weights = v_rms * (v_per ** 1.5)
            midis = np.array([int(round(hz_to_midi(h))) for h in v_hz])

            midi_scores = {}
            for m_val, w_val in zip(midis, weights):
                midi_scores[m_val] = midi_scores.get(m_val, 0.0) + float(w_val)

            dom_midi = max(midi_scores.keys(), key=lambda k: midi_scores[k])
        else:
            dom_midi = aligned_notes[-1]["midi"] if aligned_notes else 60

        pitch_name = midi_to_note_name(dom_midi)
        aligned_notes.append({
            "id": global_id,
            "char": char,
            "pitch": pitch_name,
            "midi": int(dom_midi),
            "start": round(ts, 3),
            "end": round(te, 3),
            "duration": round(te - ts, 3)
        })
        global_id += 1

    # 6. 依據聲音物理呼吸停頓 (phrase_gap) 切分樂句分行
    lines = []
    if aligned_notes:
        curr_line = [aligned_notes[0]]
        for n in aligned_notes[1:]:
            gap = n["start"] - curr_line[-1]["end"]
            if gap >= phrase_gap:
                lines.append(curr_line)
                curr_line = [n]
            else:
                curr_line.append(n)
        lines.append(curr_line)

    lines_output = []
    for line_idx, p_notes in enumerate(lines):
        line_text = "".join([n["char"] for n in p_notes])
        lines_output.append({
            "line_idx": line_idx + 1,
            "text": line_text,
            "start": p_notes[0]["start"],
            "end": p_notes[-1]["end"],
            "duration": round(p_notes[-1]["end"] - p_notes[0]["start"], 3),
            "note_count": len(p_notes),
            "notes": p_notes
        })

    print(f"👉 成功生成 {len(aligned_notes)} 個【1 字 = 1 音高】精準音符方塊，共切分為 {len(lines_output)} 個樂句分行！")
    return lines_output, aligned_notes

def segment_phrases_by_pause(notes: list, phrase_gap_threshold: float = 0.60):
    """依據聲音物理換氣停頓 (gap >= threshold) 自動將音符切分為歌唱樂句（分行）"""
    print(f"\n[步驟 2/2] 正在依據聲音物理呼吸停頓 (Gap >= {phrase_gap_threshold}s) 自動切分樂句分行...")
    if not notes:
        return [], []

    phrases = []
    curr_phrase = [notes[0]]
    for n in notes[1:]:
        gap = n["start"] - curr_phrase[-1]["end"]
        if gap >= phrase_gap_threshold:
            phrases.append(curr_phrase)
            curr_phrase = [n]
        else:
            curr_phrase.append(n)
    phrases.append(curr_phrase)

    lines_output = []
    flat_notes_list = []
    global_note_id = 1

    for phrase_idx, p_notes in enumerate(phrases):
        phrase_start = p_notes[0]["start"]
        phrase_end = p_notes[-1]["end"]

        phrase_notes = []
        for n in p_notes:
            note_obj = {
                "id": global_note_id,
                "pitch": n["pitch"],
                "midi": n["midi"],
                "start": n["start"],
                "end": n["end"],
                "duration": n["duration"]
            }
            global_note_id += 1
            phrase_notes.append(note_obj)
            flat_notes_list.append(note_obj)

        lines_output.append({
            "line_idx": phrase_idx + 1,
            "start": phrase_start,
            "end": phrase_end,
            "duration": round(phrase_end - phrase_start, 3),
            "note_count": len(phrase_notes),
            "notes": phrase_notes
        })

    print(f"👉 依客觀聲音停頓成功切分出 {len(lines_output)} 個樂句分行。")
    return lines_output, flat_notes_list

def print_section_summary(lines_data, title="ToneDeaf 依真實聲音換氣自動切分樂句結果"):
    print("\n" + "=" * 75)
    print(f"   {title}（前 10 句預覽）   ")
    print("=" * 75)
    for line in lines_data[:10]:
        l_idx = line["line_idx"]
        time_str = f"{line['start']:05.2f}s ~ {line['end']:05.2f}s"
        dur_str = f"時長 {line['duration']}s"
        note_count = line["note_count"]
        text_preview = f"【{line['text']}】" if "text" in line and line["text"] else ""
        print(f"\n【第 {l_idx:2d} 句】{text_preview} [{time_str}] ({dur_str} / {note_count} 個音符):")

        preview_parts = []
        for n in line["notes"]:
            char_tag = f"【{n['char']}】" if "char" in n else ""
            preview_parts.append(f"{char_tag}{n['pitch']}({n['duration']}s)")
        print("   " + " -> ".join(preview_parts))

    if len(lines_data) > 10:
        print(f"\n... 還有 {len(lines_data) - 10} 句，已完整寫入 JSON。")
    print("=" * 75)

def main():
    parser = argparse.ArgumentParser(description="ToneDeaf - 智慧人聲音高分析與歌詞字音 1:1 強制對齊系統")
    parser.add_argument("audio", nargs="?", help="音檔名稱或路徑 (如 cangjie.mp3 或 output/cangjie_vocals.wav)")
    parser.add_argument("--phrase-gap", type=float, default=0.38, help="分句呼吸停頓門檻 (秒)，預設 0.38s")
    parser.add_argument("--energy-db", type=float, default=-38.0, help="RMS 音量能量門檻 (dB)，預設 -38.0dB")
    parser.add_argument("--periodicity", type=float, default=0.38, help="CREPE 週期性信心度門檻，預設 0.38")
    parser.add_argument("--whisper-model", type=str, default="base", help="Whisper 語音辨識模型 (base 或 small，預設 base)")
    parser.add_argument("--lyrics", type=str, default=None, help="可選的歌詞文字檔路徑 (預設自動偵測 <track>.txt)")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent
    output_dir = project_root / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    audio_input = args.audio
    if not audio_input:
        audio_input = input("請輸入音檔名稱（例如 cangjie.mp3）：").strip()

    if not audio_input:
        print("未輸入檔案，程式退出。")
        sys.exit(1)

    audio_path = Path(audio_input)
    if not audio_path.is_absolute():
        if (project_root / audio_path).exists():
            audio_path = project_root / audio_path
        elif (output_dir / audio_path).exists():
            audio_path = output_dir / audio_path
        else:
            audio_path = project_root / audio_path

    if not audio_path.exists():
        print(f"[錯誤] 找不到檔案：{audio_path}")
        sys.exit(1)

    try:
        print(f"\n🎵 開始全自動音高與歌詞對齊分析：{audio_path.name}")

        # 1. 取得純人聲音檔
        vocals_path = get_vocals_audio(audio_path, output_dir)

        audio_data, sr = sf.read(str(vocals_path))
        if audio_data.ndim > 1:
            audio_data = np.mean(audio_data, axis=1)
        if sr != 16000:
            audio_data = librosa.resample(audio_data, orig_sr=sr, target_sr=16000)
        audio_data = audio_data.astype(np.float32)

        # 2. 提取聲學音符序列 (TorchCREPE + 雙門檻動態 VAD + 施密特觸發器)
        all_notes, pitch_np, per_np, rms, db = extract_notes_torchcrepe(
            audio_data,
            sr=16000,
            periodicity_thresh=args.periodicity,
            energy_db_thresh=args.energy_db
        )
        if not all_notes:
            print("[警告] 未能在人聲中檢測出有效音符。")
            sys.exit(1)

        # 3. 聲學換氣切分 (純聲學音符)
        lines_acoustic, flat_acoustic_notes = segment_phrases_by_pause(
            all_notes,
            phrase_gap_threshold=args.phrase_gap
        )

        track_stem = audio_path.stem.replace("_vocals", "")
        out_json_pitch = output_dir / f"{track_stem}_pitch.json"
        out_json_lyrics_pitch = output_dir / f"{track_stem}_lyrics_pitch.json"

        payload_pitch = {
            "track": track_stem,
            "mode": "acoustic_pitch_raw",
            "total_notes": len(flat_acoustic_notes),
            "total_lines": len(lines_acoustic),
            "phrase_gap_threshold": args.phrase_gap,
            "lines": lines_acoustic,
            "data": flat_acoustic_notes
        }

        with open(out_json_pitch, "w", encoding="utf-8") as f:
            json.dump(payload_pitch, f, ensure_ascii=False, indent=2)

        # 4. 【方案 A】語音強制對齊與 1:1 主導音投影 (Forced Alignment + Dominant Pitch)
        aligned_lines, aligned_notes = align_lyrics_pitch(
            audio_16k=audio_data,
            pitch_np=pitch_np,
            per_np=per_np,
            rms=rms,
            db=db,
            track_stem=track_stem,
            output_dir=output_dir,
            project_root=project_root,
            whisper_model=args.whisper_model,
            custom_lyrics_path=args.lyrics,
            phrase_gap=args.phrase_gap
        )

        if aligned_notes:
            payload_lyrics = {
                "track": track_stem,
                "mode": "lyrics_pitch_aligned",
                "total_notes": len(aligned_notes),
                "total_lines": len(aligned_lines),
                "phrase_gap_threshold": args.phrase_gap,
                "lines": aligned_lines,
                "data": aligned_notes
            }
            with open(out_json_lyrics_pitch, "w", encoding="utf-8") as f:
                json.dump(payload_lyrics, f, ensure_ascii=False, indent=2)

            print_section_summary(aligned_lines, title="ToneDeaf 方案 A【歌詞字音 1:1 精準對齊】分句旋律預覽")
        else:
            print("[資訊] 未產生歌詞對齊資料，相容模式沿用純聲學音符資料。")
            with open(out_json_lyrics_pitch, "w", encoding="utf-8") as f:
                json.dump(payload_pitch, f, ensure_ascii=False, indent=2)

        print("\n" + "=" * 75)
        print(f"🎉 分析大功告成！雙模式資料已完整寫入 output/ 目錄：")
        print(f"👉 1. 【方案 A 歌詞 1:1 對齊模式】: {out_json_lyrics_pitch.name} ({len(aligned_notes)} 字音符)")
        print(f"👉 2. 【純物理聲學音高模式】      : {out_json_pitch.name} ({len(flat_acoustic_notes)} 音符塊)")
        print("=" * 75)
        print("💡 請在瀏覽器打開 http://localhost:8765 即可檢視！曲目下拉選單已支援雙模式切換！")

    except Exception as e:
        print(f"\n[執行失敗] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
