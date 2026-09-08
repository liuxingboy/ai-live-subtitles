"""Phase 1: Chrome process tree -> local 16 kHz mono WAV."""
import argparse
from pathlib import Path
import signal
import sys
import threading
import wave

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="仅列出 Chrome 进程")
    parser.add_argument("--pid", type=int, help="指定 Chrome PID，默认检测主进程")
    parser.add_argument("--seconds", type=float, default=10, help="录制秒数（默认 10，最多 300）")
    parser.add_argument("--output", type=Path, default=ROOT / "debug_capture.wav")
    args = parser.parse_args()
    if not 0 < args.seconds <= 300:
        parser.error("--seconds 须大于 0 且不超过 300")
    from audio.chrome_detector import find_chrome_processes, choose_chrome, still_running
    processes = find_chrome_processes()
    if args.list:
        for p in processes:
            print(f"PID={p.pid} parent={p.parent_pid} {'browser' if p.is_browser else 'child'}")
        if not processes:
            print("未检测到 Chrome。")
        return 0
    target = choose_chrome(processes, args.pid)
    from audio.audio_converter import to_pcm16_mono, levels
    from audio.wasapi_capture import capture_process
    output = args.output.resolve()
    # Avoid replacing an earlier user recording when rerunning the command.
    if output.exists():
        from datetime import datetime
        output = output.with_name(f"{output.stem}_{datetime.now():%Y%m%d_%H%M%S_%f}{output.suffix}")
    print(f"[INFO] Chrome PID={target.pid}，捕获该进程及其子进程。", flush=True)
    print(f"[INFO] 请保持 Chrome 播放声音。开始录制 {args.seconds:g} 秒；Ctrl+C 可提前停止。", flush=True)
    stop = threading.Event()
    previous = signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        result = capture_process(target.pid, args.seconds, stop,
                                 alive=lambda: still_running(target),
                                 progress=lambda elapsed, frames: print(
                                     f"[INFO] {elapsed:.0f}s，已捕获 {frames / 16000:.2f}s 音频", flush=True))
    finally:
        signal.signal(signal.SIGINT, previous)
    pcm = to_pcm16_mono(result.pcm, result.sample_rate, result.channels)
    if not pcm:
        raise RuntimeError("未捕获音频，未生成 WAV。")
    with output.open("xb") as file:
        with wave.open(file, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(pcm)
    peak, rms = levels(pcm)
    print(f"[INFO] WAV：{output}")
    print(f"[INFO] PCM16 / mono / 16000 Hz，时长 {len(pcm) / 32000:.3f}s，峰值 {peak:.4f}，RMS {rms:.1f} dBFS")
    print(f"[INFO] 数据包 {result.packets}，不连续 {result.discontinuities}，时间戳异常 {result.timestamp_errors}")
    if result.interrupted:
        print("[WARN] 已提前停止，本次只保存实际捕获部分。")
    if rms < -70:
        print("[WARN] 文件为静音或接近静音（RMS < -70 dBFS），尚未通过验收。请检查播放音量、状态和所选 PID。")
    elif result.discontinuities:
        print("[WARN] 捕获存在不连续，可能有丢帧，本次稳定性验证未通过。")
    else:
        print("[OK] 已生成有声音的录音；请试听确认仅包含 Chrome。")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)
