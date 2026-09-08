"""Keep local capture alive, while closing the paid cloud session during silence."""
from collections import deque
import base64
import time
import websocket
from audio.live_source import ChromeAudioSource, PCMQueue
from audio.silence import ActivityDetector
from tools.api_debug import Session, session_config
from tools.reconnect import ConnectionLost, network_error


def run_idle_attempt(target, key, url, args, seconds, stop, report):
    # Buffer is bounded to 20 seconds during handshakes/finalization. On actual
    # transport failure this entire source is stopped and never reused by retry.
    source = ChromeAudioSource(target, seconds, audio_queue=PCMQueue(200, drop_oldest=True))
    detector = ActivityDetector(args.silence_db)
    preroll = deque(maxlen=10)  # one second, including wake-up confirmation
    ws = session = None
    last_status = time.monotonic()
    last_dropped = 0
    report['normal_finish'] = True  # Idle without a cloud session is a valid exit.

    def state(kind, text):
        print(f'[{kind.upper()}] {text}', flush=True)
        if args.on_state:
            args.on_state(kind, text)

    def close_session(graceful):
        nonlocal ws, session
        current = session
        try:
            if current and graceful:
                current.finish()
                report['normal_finish'] = True
        finally:
            if current:
                current.closing.set()
            if ws:
                try:
                    ws.close(timeout=1)
                except Exception:
                    pass
            if current:
                current.reader.join(timeout=2)
                for name in ('english_finals', 'chinese_finals'):
                    report[name] = report.get(name, 0) + getattr(current, name)
                if current.close_code is not None:
                    report['last_close_code'] = current.close_code
            ws = session = None

    def send(data):
        try:
            session.heartbeat()
            session.send('input_audio_buffer.append', audio=base64.b64encode(data).decode('ascii'))
        except Exception as exc:
            raise network_error(exc) from exc
        report['uploaded_bytes'] = report.get('uploaded_bytes', 0) + len(data)
        report['uploaded_seconds'] = round(report['uploaded_bytes'] / 32000, 3)

    source.thread.start()
    state('paused', '等待 Chrome 声音 · 云端已暂停')
    try:
        while True:
            if stop.is_set():
                source.stop.set()
            if source.error:
                raise source.error
            if session and session.failed.is_set():
                session.raise_failure()
            if session and session.finished.is_set():
                raise ConnectionLost('百炼会话提前结束。')
            data = source.audio.get()
            if data is None:
                if source.done.is_set():
                    if source.error:
                        raise source.error
                    break
                continue
            detector.feed(data)
            if source.audio.dropped_bytes != last_dropped:
                last_dropped = source.audio.dropped_bytes
                print('[WARN] 连接耗时超过本地缓冲容量，部分开头音频已丢弃。', flush=True)
            if session is None:
                preroll.append(data)
                if detector.active_seconds >= .29 and not stop.is_set():
                    state('connecting', '检测到声音 · 正在恢复云端')
                    report['normal_finish'] = False
                    try:
                        ws = websocket.create_connection(url, header={'Authorization': f'Bearer {key}'}, timeout=10)
                    except Exception as exc:
                        raise network_error(exc) from exc
                    ws.settimeout(1)
                    if args.on_event:
                        args.on_event({'type': '_session_reset'})
                    session = Session(ws, key, show_partial=args.partial, on_event=args.on_event)
                    session.reader.start()
                    try:
                        session.send('session.update', session=session_config(args.hotwords))
                        ready = session.wait(session.ready, 15, stop)
                    except TimeoutError as exc:
                        raise ConnectionLost('等待 session.updated 超时。') from exc
                    except (OSError, websocket.WebSocketException) as exc:
                        raise network_error(exc) from exc
                    if not ready:
                        break
                    report['successful_connections'] = report.get('successful_connections', 0) + 1
                    state('connected', '已连接 · 实时字幕')
                    for buffered in preroll:
                        send(buffered)
                    preroll.clear()
            else:
                send(data)
                if detector.quiet_seconds >= args.silence_seconds and not stop.is_set():
                    try:
                        close_session(True)
                    except Exception as exc:
                        raise ConnectionLost(f'静音会话收尾失败：{exc}') from exc
                    report['silence_pauses'] = report.get('silence_pauses', 0) + 1
                    state('paused', '长时间静音 · 云端已暂停，等待声音恢复')
            if time.monotonic() - last_status >= 30:
                last_status = time.monotonic()
                print(f"[STATUS] 已发送 {report.get('uploaded_seconds', 0)}s，云端{'运行中' if session else '暂停'}，"
                      f"静音暂停 {report.get('silence_pauses', 0)} 次，重连 {report.get('reconnect_attempts', 0)} 次", flush=True)
        close_session(True)
    finally:
        source.stop.set()
        source.thread.join(timeout=17)
        # A failed connection must not be labelled as graceful completion.
        try:
            if session and not session.failed.is_set():
                close_session(True)
            else:
                close_session(False)
        finally:
            report['captured_seconds'] = round(report.get('captured_seconds', 0) + source.audio.total_bytes / 32000, 3)
            report['buffer_dropped_seconds'] = round(report.get('buffer_dropped_seconds', 0) + source.audio.dropped_bytes / 32000, 3)
            report['queue_high_water_blocks'] = max(report.get('queue_high_water_blocks', 0), source.audio.high_water)
            if source.result:
                for name in ('discontinuities', 'timestamp_errors'):
                    report[name] = report.get(name, 0) + getattr(source.result, name)
            if source.thread.is_alive():
                raise RuntimeError('音频线程未及时退出，停止重连。')
