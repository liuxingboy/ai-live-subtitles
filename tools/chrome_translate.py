"""Audio source -> Bailian -> bilingual terminal subtitles."""
import argparse
import base64
import json
import math
import os
from pathlib import Path
import signal
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.api_debug import Session, configure_console, connection_config, safe_error, session_config
from audio.output_device import OutputDeviceChanged
from audio.sources import SOURCE_REGISTRY, resolve_source, SourceShutdownError
from app.preferences import SPEED_MODES, TARGET_LANGUAGES, add_hotword_arguments
from tools.reconnect import ConnectionLost, network_error, run_with_reconnect


def stream_audio(session, source, stop, report):
    """Drain the final queued audio before session.finish; receiver stays active."""
    source.thread.start()
    uploaded = report.get('uploaded_bytes', 0)
    last_report = time.monotonic()
    while True:
        if stop.is_set():
            source.stop.set()
        if session.failed.is_set():
            session.raise_failure()
        if session.finished.is_set():
            raise ConnectionLost("百炼会话提前结束。")
        if source.error is not None:
            raise source.error
        data = source.audio.get()
        if data is not None:
            try:
                session.heartbeat()
                session.send("input_audio_buffer.append", audio=base64.b64encode(data).decode("ascii"))
            except Exception as exc:
                raise network_error(exc) from exc
            uploaded += len(data)
            report['uploaded_bytes'] = uploaded
        elif source.done.is_set():
            # Producer sets error before done, including errors in final flush.
            if source.error is not None:
                raise source.error
            break
        now = time.monotonic()
        report["uploaded_seconds"] = round(uploaded / 32000, 3)
        if now - last_report >= 30:
            last_report = now
            print(f"[STATUS] 已发送 {uploaded / 32000:.0f}s 音频，"
                  f"原文 {report.get('english_finals', 0) + session.english_finals} 段，译文 {report.get('chinese_finals', 0) + session.chinese_finals} 段，"
                  f"重连 {report.get('reconnect_attempts', 0)} 次，"
                  f"待发送 {source.audio.queue.qsize() / 10:.1f}s", flush=True)
    report["uploaded_seconds"] = round(uploaded / 32000, 3)


def run_attempt(target, key, url, args, seconds, stop, report):
    """Each attempt owns a fresh source and queue; old audio never crosses sessions."""
    import websocket
    began = time.monotonic()
    ws = session = source = None
    thread_stuck = False
    report['normal_finish'] = False
    try:
        print('[CONNECTING] 正在连接百炼…', flush=True)
        if args.on_state:
            args.on_state('connecting', '正在连接…')
        try:
            ws = websocket.create_connection(url, header={'Authorization': f'Bearer {key}'}, timeout=10)
        except Exception as exc:
            raise network_error(exc) from exc
        ws.settimeout(1)
        if args.on_event:
            args.on_event({'type': '_session_reset'})
        session = Session(ws, key, show_partial=args.partial, on_event=args.on_event, target_language=getattr(args, 'target_language', 'zh'))
        session.reader.start()
        try:
            session.send('session.update', session=session_config(args.hotwords, speed=getattr(args, 'speed', 'normal'), target_language=getattr(args, 'target_language', 'zh')))
        except Exception as exc:
            raise network_error(exc) from exc
        try:
            ready = session.wait(session.ready, 15, stop)
        except TimeoutError as exc:
            raise ConnectionLost('等待 session.updated 超时。') from exc
        remaining = None if seconds is None else seconds - (time.monotonic() - began)
        if not ready or (remaining is not None and remaining <= 0):
            session.finish()
            report['normal_finish'] = True
            return
        report['successful_connections'] = report.get('successful_connections', 0) + 1
        print(f'[CONNECTED] {target.label}音频上传已就绪；Ctrl+C 结束。', flush=True)
        if args.on_state:
            args.on_state('connected', '已连接 · 等待语音')
        source = target.create(remaining)
        stream_audio(session, source, stop, report)
        try:
            session.finish()
        except Exception as exc:
            if session.failed.is_set():
                session.raise_failure()
            raise network_error(exc) from exc
        report['normal_finish'] = True
    finally:
        if source is not None:
            source.stop.set()
            if source.thread.ident is not None:
                source.thread.join(timeout=17)
            thread_stuck = source.thread.is_alive()
            report['captured_seconds'] = round(report.get('captured_seconds', 0) + source.audio.total_bytes / 32000, 3)
            report['queue_high_water_blocks'] = max(report.get('queue_high_water_blocks', 0), source.audio.high_water)
            if source.result:
                for name in ('discontinuities', 'timestamp_errors'):
                    report[name] = report.get(name, 0) + getattr(source.result, name)
        if session is not None:
            # Best effort finalization for local capture failures, never for a dead connection.
            if not report['normal_finish'] and not session.failed.is_set() and not session.finished.is_set():
                try:
                    session.finish(timeout=3)
                except Exception:
                    pass
            session.closing.set()
        if ws is not None:
            try:
                ws.close(timeout=1)
            except Exception:
                pass
        if session is not None:
            session.reader.join(timeout=2)
            for name in ('english_finals', 'chinese_finals'):
                report[name] = report.get(name, 0) + getattr(session, name)
            if session.close_code is not None:
                report['last_close_code'] = session.close_code
        if thread_stuck:
            raise SourceShutdownError('音频线程未及时退出，不能安全重启捕获。')


def main(argv=None, stop_event=None, on_event=None, on_state=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target-language', choices=tuple(TARGET_LANGUAGES), default='zh', help='翻译目标语言，默认 zh 中文')
    parser.add_argument('--speed', choices=tuple(SPEED_MODES), default='normal', help='速度与准度：normal 正常 / fast 速度优先')
    parser.add_argument('--source', choices=tuple(SOURCE_REGISTRY), default='chrome', help='声源：chrome / system / microphone')
    parser.add_argument('--pid', type=int, help='指定 Chrome PID')
    parser.add_argument('--seconds', type=float, help='限时运行秒数（包括重连等待）；默认到 Ctrl+C')
    parser.add_argument('--silence-seconds', type=float, default=30, help='静音多久暂停云端，默认 30 秒；0 禁用')
    parser.add_argument('--silence-db', type=float, default=-55, help='静音阈值 dBFS，默认 -55')
    add_hotword_arguments(parser)
    display = parser.add_mutually_exclusive_group()
    display.add_argument('--partial', action='store_true', help='终端也打印流式临时结果（悬浮窗默认已显示）')
    display.add_argument('--final-only', action='store_true', help='悬浮窗仅显示最终结果，更稳定但等待更久')
    args = parser.parse_args(argv)
    args.on_event = on_event
    args.on_state = on_state
    if not math.isfinite(args.silence_seconds) or args.silence_seconds < 0:
        parser.error('--silence-seconds 必须为非负有限数')
    if not math.isfinite(args.silence_db) or not -90 <= args.silence_db <= -10:
        parser.error('--silence-db 须在 -90 到 -10 之间')
    if args.seconds is not None and (not math.isfinite(args.seconds) or args.seconds <= 0):
        parser.error('--seconds 必须为有限正数')
    stop = stop_event if stop_event is not None else threading.Event()
    old_signal = None
    if threading.current_thread() is threading.main_thread():
        old_signal = signal.signal(signal.SIGINT, lambda *_: stop.set())
    key = ''
    code = 0
    started = time.monotonic()
    report = {'phase': 2, 'uploaded_seconds': 0, 'normal_finish': False,
              'disconnects': 0, 'reconnect_attempts': 0}
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / '.env', encoding='utf-8-sig')
        from app.preferences import load_hotwords
        hotwords_requested = args.hotwords is not None and not args.no_hotwords
        args.hotwords = load_hotwords(None if args.no_hotwords or args.target_language != 'zh' else args.hotwords)
        print(f'[INFO] 已加载 {len(args.hotwords)} 条术语；静音暂停阈值 {args.silence_seconds:g} 秒。', flush=True)
        if args.target_language != 'zh' and hotwords_requested:
            print('[INFO] 非中文目标暂不应用中译热词，词库文件保留。', flush=True)
        key, url = connection_config(os.environ)
        target = resolve_source(args.source, args.pid)
        print(f'[INFO] 声源：{target.label}；自动重连已启用。', flush=True)
        report['source'] = target.key
        report['speed'] = args.speed
        report['target_language'] = args.target_language
        print(f'[INFO] 目标语言：{TARGET_LANGUAGES[args.target_language]}。', flush=True)
        print(f'[INFO] 速度与准度：{SPEED_MODES[args.speed]}。', flush=True)
        if target.pid is not None:
            report['chrome_pid'] = target.pid
        def attempt(remaining):
            try:
                if args.silence_seconds:
                    from tools.idle_translate import run_idle_attempt
                    run_idle_attempt(target, key, url, args, remaining, stop, report)
                else:
                    run_attempt(target, key, url, args, remaining, stop, report)
            except (ConnectionLost, OutputDeviceChanged) as exc:
                if on_state:
                    on_state('reconnecting', '播放设备变化 · 恢复采集中' if isinstance(exc, OutputDeviceChanged) else '连接中断 · 自动重连中')
                raise type(exc)(safe_error(exc, key)) from None
        run_with_reconnect(attempt, stop, report, args.seconds, alive=target.alive)
    except Exception as exc:
        print(f'[ERROR] {safe_error(exc, key)}', file=sys.stderr, flush=True)
        report['error_type'] = type(exc).__name__
        if on_state:
            on_state('error', safe_error(exc, key))
        code = 2 if isinstance(exc, SourceShutdownError) else 1
    finally:
        if old_signal is not None:
            signal.signal(signal.SIGINT, old_signal)
        report['elapsed_seconds'] = round(time.monotonic() - started, 2)
        if not report['normal_finish']:
            print('[WARN] 退出时没有可正常收尾的会话，最后一句可能不完整。', flush=True)
            if not stop.is_set() and code == 0:
                code = 1
        report['exit_code'] = code
        path = ROOT / 'logs' / 'phase2_last_run.json'
        try:
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f'[INFO] 运行统计：{path}', flush=True)
        except OSError:
            print('[WARN] 无法保存运行统计。', file=sys.stderr)
        print(f"[INFO] 已发送 {report['uploaded_seconds']}s；原文 {report.get('english_finals', 0)} 段，"
              f"译文 {report.get('chinese_finals', 0)} 段；断线 {report['disconnects']} 次，"
              f"重连尝试 {report['reconnect_attempts']} 次。", flush=True)
        if code == 0 and (not report.get('english_finals') or not report.get('chinese_finals')):
            print('[WARN] 本次未同时获得双语最终结果，请播放清晰英文验证。', flush=True)
    return code


if __name__ == "__main__":
    configure_console()
    sys.exit(main())
