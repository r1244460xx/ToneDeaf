import os
import sys
import shutil
import subprocess
from pathlib import Path

def separate_vocals(audio_input: str, output_dir: str = "output"):
    project_root = Path(__file__).resolve().parent
    audio_path = Path(audio_input)

    # 若傳入的是相對路徑，優先從專案根目錄解析
    if not audio_path.is_absolute():
        audio_path = project_root / audio_path

    if not audio_path.exists():
        print(f"\n[錯誤] 找不到音檔：{audio_path}")
        print("請確認檔案是否已放置在專案目錄下，並檢查檔名是否正確。")
        return False

    out_path = project_root / output_dir
    out_path.mkdir(parents=True, exist_ok=True)

    print(f"\n=== 開始處理音檔 ===")
    print(f"輸入檔案: {audio_path.name}")
    print(f"完整路徑: {audio_path}")
    print("正在使用 Demucs 進行人聲分離（初次執行會自動下載模型，請稍候）...")

    # 使用目前虛擬環境中的 demucs
    venv_python = sys.executable
    temp_demucs_dir = out_path / "_temp_demucs"
    temp_demucs_dir.mkdir(parents=True, exist_ok=True)

    # 自動選擇最佳裝置 (Apple Silicon MPS / NVIDIA CUDA / CPU)
    import torch
    if torch.cuda.is_available():
        device = "cuda"
    elif torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"
    print(f"使用的運算裝置: {device.upper()}")

    # 執行 demucs 命令列
    # -n htdemucs: 使用輕量高品質的預設模型
    # --two-stems=vocals: 僅提取 vocals 與 no_vocals，速度更快
    cmd = [
        venv_python,
        "-m",
        "demucs",
        "-n",
        "htdemucs",
        "--two-stems=vocals",
        "-d",
        device,
        "-o",
        str(temp_demucs_dir),
        str(audio_path)
    ]

    try:
        process = subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"\n[錯誤] 人聲分離執行失敗，錯誤碼: {e.returncode}")
        return False
    except Exception as e:
        print(f"\n[錯誤] 發生未預期的例外：{e}")
        return False

    # Demucs 預設會輸出到: temp_demucs_dir / htdemucs / <track_name> / [vocals.wav, no_vocals.wav]
    track_stem_name = audio_path.stem
    demucs_vocals_file = temp_demucs_dir / "htdemucs" / track_stem_name / "vocals.wav"
    demucs_no_vocals_file = temp_demucs_dir / "htdemucs" / track_stem_name / "no_vocals.wav"

    if not demucs_vocals_file.exists():
        # 有些情況檔名包含特殊字元，嘗試搜尋 temp 目錄下的 vocals.wav
        found = list(temp_demucs_dir.glob("**/vocals.wav"))
        if found:
            demucs_vocals_file = found[0]
        else:
            print(f"\n[錯誤] 未能找到分離出的 vocals.wav 檔案。")
            return False

    if not demucs_no_vocals_file.exists():
        found_no_vocals = list(temp_demucs_dir.glob("**/no_vocals.wav"))
        if found_no_vocals:
            demucs_no_vocals_file = found_no_vocals[0]

    # 將提取出的人聲移動/複製到 output_dir，以乾淨易讀的檔名呈現
    final_output_file = out_path / f"{track_stem_name}_vocals.wav"
    shutil.copy2(demucs_vocals_file, final_output_file)

    # 同步將伴奏（去除人聲後的純音樂軌）儲存為獨立音檔
    final_accompaniment_file = out_path / f"{track_stem_name}_accompaniment.wav"
    final_instrumental_file = out_path / f"{track_stem_name}_instrumental.wav"
    has_accompaniment = False
    if demucs_no_vocals_file.exists():
        shutil.copy2(demucs_no_vocals_file, final_accompaniment_file)
        shutil.copy2(demucs_no_vocals_file, final_instrumental_file)
        has_accompaniment = True

    # 清理臨時檔案
    try:
        shutil.rmtree(temp_demucs_dir)
    except Exception:
        pass

    print(f"\n=== 音軌分離完成！ ===")
    print(f"🎤 純人聲音檔已儲存至：")
    print(f"👉 {final_output_file.resolve()}")
    if has_accompaniment:
        print(f"🎹 純伴奏音檔（去人聲背景音樂）已儲存至：")
        print(f"👉 {final_accompaniment_file.resolve()}")
        print(f"👉 {final_instrumental_file.resolve()}")
    return True

def main():
    print("========================================")
    print("    ToneDeaf 人聲分離工具 (Demucs)     ")
    print("========================================")

    if len(sys.argv) > 1:
        audio_input = sys.argv[1].strip()
    else:
        audio_input = input("請輸入音檔名稱（例如 song.mp3）：").strip()

    if not audio_input:
        print("未輸入檔案名稱，程式結束。")
        sys.exit(1)

    success = separate_vocals(audio_input)
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()
