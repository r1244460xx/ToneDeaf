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
    """使用 TorchCREPE 提取真實音高，並結合 RMS 能量門檻做降噪、同音縫合與去碎片化"""
    print("\n[步驟 1/2] 正在使用 TorchCREPE 提取高精度音高序列...")
    import torchcrepe

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

    fmin = 60
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

    is_voiced = (periodicity_np > periodicity_thresh) & (db > energy_db_thresh)

    midi_series = np.zeros_like(pitch_np)
    for i in range(min_len):
        if is_voiced[i] and pitch_np[i] > 0:
            midi_series[i] = hz_to_midi(pitch_np[i])

    # 1. 中值濾波器 (Median Filter, window=7 / 70ms)：平滑微小擾動與生理顫音
    midi_filtered = np.copy(midi_series)
    diff = np.diff(np.concatenate(([False], midi_series > 0, [False])).astype(int))
    voiced_starts = np.where(diff == 1)[0]
    voiced_ends = np.where(diff == -1)[0]

    for s, e in zip(voiced_starts, voiced_ends):
        chunk_len = e - s
        if chunk_len >= 5:
            k = 7 if chunk_len >= 7 else 5
            midi_filtered[s:e] = scipy.signal.medfilt(midi_series[s:e], kernel_size=k)

    # 2. 施密特觸發器機制 (Hysteresis / 滯後判定)：
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
            if silence_frames >= 8:  # 80ms 靜音確認發音終止
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

    # 同音高自動縫合與微小雜音過濾
    notes = []
    if raw_notes:
        merged_note = dict(raw_notes[0])
        for next_note in raw_notes[1:]:
            gap = next_note["start"] - merged_note["end"]
            if next_note["midi"] == merged_note["midi"] and gap <= 0.12:
                merged_note["end"] = next_note["end"]
                merged_note["duration"] = round(merged_note["end"] - merged_note["start"], 3)
            else:
                if merged_note["duration"] >= 0.08:
                    notes.append(merged_note)
                merged_note = dict(next_note)

        if merged_note["duration"] >= 0.08:
            notes.append(merged_note)

    for idx, n in enumerate(notes):
        n["id"] = idx + 1

    print(f"👉 成功提取出 {len(notes)} 個物理發音音符（經中值濾波與施密特觸發器去抖動）。")
    return notes

def segment_phrases_by_pause(notes: list, phrase_gap_threshold: float = 0.38):
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

def print_section_summary(lines_data):
    print("\n" + "=" * 70)
    print("   ToneDeaf 依真實聲音換氣自動切分樂句結果（前 10 句預覽）   ")
    print("=" * 70)
    for line in lines_data[:10]:
        l_idx = line["line_idx"]
        time_str = f"{line['start']:05.2f}s ~ {line['end']:05.2f}s"
        dur_str = f"時長 {line['duration']}s"
        note_count = line["note_count"]
        print(f"\n【第 {l_idx:2d} 句】[{time_str}] ({dur_str} / {note_count} 個音符):")

        preview_parts = [f"{n['pitch']}({n['duration']}s)" for n in line["notes"]]
        print("   " + " -> ".join(preview_parts))

    if len(lines_data) > 10:
        print(f"\n... 還有 {len(lines_data) - 10} 句，已完整寫入 JSON。")
    print("=" * 70)

def main():
    parser = argparse.ArgumentParser(description="ToneDeaf - 純聲音音高分析與客觀換氣分句工具（無歌詞依賴）")
    parser.add_argument("audio", nargs="?", help="音檔名稱或路徑 (如 test.mp3 或 output/test_vocals.wav)")
    parser.add_argument("--phrase-gap", type=float, default=0.38, help="分句呼吸停頓門檻 (秒)，預設 0.38s")
    parser.add_argument("--energy-db", type=float, default=-38.0, help="RMS 音量能量門檻 (dB)，預設 -38.0dB")
    parser.add_argument("--periodicity", type=float, default=0.38, help="CREPE 週期性信心度門檻，預設 0.38")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent
    output_dir = project_root / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    audio_input = args.audio
    if not audio_input:
        audio_input = input("請輸入音檔名稱（例如 test.mp3）：").strip()

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
        print(f"\n🎵 開始分析音訊音高：{audio_path.name}")

        # 1. 取得純人聲音檔
        vocals_path = get_vocals_audio(audio_path, output_dir)

        audio_data, sr = sf.read(str(vocals_path))
        if audio_data.ndim > 1:
            audio_data = np.mean(audio_data, axis=1)
        if sr != 16000:
            audio_data = librosa.resample(audio_data, orig_sr=sr, target_sr=16000)
        audio_data = audio_data.astype(np.float32)

        # 2. 提取音符序列 (TorchCREPE)
        all_notes = extract_notes_torchcrepe(
            audio_data,
            sr=16000,
            periodicity_thresh=args.periodicity,
            energy_db_thresh=args.energy_db
        )
        if not all_notes:
            print("[警告] 未能在人聲中檢測出有效音符。")
            sys.exit(1)

        # 3. 依據聲音物理呼吸停頓自動切分樂句
        lines_output, flat_notes_list = segment_phrases_by_pause(
            all_notes,
            phrase_gap_threshold=args.phrase_gap
        )

        # 4. 輸出 JSON
        track_stem = audio_path.stem.replace("_vocals", "")
        out_json_pitch = output_dir / f"{track_stem}_pitch.json"
        out_json_legacy = output_dir / f"{track_stem}_lyrics_pitch.json"

        payload = {
            "track": track_stem,
            "total_notes": len(flat_notes_list),
            "total_lines": len(lines_output),
            "phrase_gap_threshold": args.phrase_gap,
            "lines": lines_output,
            "data": flat_notes_list
        }

        # 同時寫入 _pitch.json 與相容性 _lyrics_pitch.json
        with open(out_json_pitch, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        with open(out_json_legacy, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        print_section_summary(lines_output)
        print(f"\n🎉 分析完成！純音高與樂句分段資料已寫入：")
        print(f"👉 {out_json_pitch.resolve()}")
        print(f"👉 {out_json_legacy.resolve()}\n")
        print("💡 請在瀏覽器打開 http://localhost:8765 即可檢視按真實呼吸換氣排版的純簡譜旋律！")

    except Exception as e:
        print(f"\n[執行失敗] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
