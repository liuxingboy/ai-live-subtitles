"""Phase 0: microphone -> Bailian -> English / Chinese console events."""

import argparse
import base64
import json
import os
from pathlib import Path
import re
import signal
import sys
import threading
import time
import uuid

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.reconnect import ConnectionLost, ServiceError, service_error

MODEL = "qwen3.5-livetranslate-flash-realtime"
ROOT = Path(__file__).resolve().parents[1]


def configure_console():
    for output in (sys.stdout, sys.stderr):
        if hasattr(output, "reconfigure"):
            output.reconfigure(encoding="utf-8", errors="replace")


def connection_config(environ):
    key = environ.get("DASHSCOPE_API_KEY", "").strip()
    workspace = environ.get("DASHSCOPE_WORKSPACE_ID", "").strip()
    host = environ.get("DASHSCOPE_WS_HOST", "").strip()
    if not key:
        raise ValueError("请在 .env 中填写 DASHSCOPE_API_KEY。")
    if not host:
        if not re.fullmatch(r"[A-Za-z0-9-]+", workspace):
            raise ValueError("请填写有效的 DASHSCOPE_WORKSPACE_ID 或 DASHSCOPE_WS_HOST。")
        host = f"{workspace}.cn-beijing.maas.aliyuncs.com"
    if not re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", host):
        raise ValueError("DASHSCOPE_WS_HOST 只能填写主机名，不能包含协议、端口或路径。")
    return key, f"wss://{host}/api-ws/v1/realtime?model={MODEL}"


def session_config(hotwords=None, speed='normal', target_language='zh'):
    from app.preferences import SPEED_MODES, TARGET_LANGUAGES
    if speed not in SPEED_MODES:
        raise ValueError(f'未知速度模式：{speed}')
    if target_language not in TARGET_LANGUAGES:
        raise ValueError(f'不支持的目标语言：{target_language}')
    config = {
        "modalities": ["text"],
        "input_audio_format": "pcm",
        "sample_rate": 16000,
        "input_audio_transcription": {
            "model": "qwen3-asr-flash-realtime", "language": "en"
        },
        "translation": {"language": target_language, **({"corpus": {"phrases": hotwords}} if hotwords and target_language == "zh" else {})},
        "turn_detection": {"type": "server_vad"},
    }
    if speed == 'fast':
        # Earlier VAD boundaries trade sentence context for responsiveness.
        config['turn_detection']['silence_duration_ms'] = 300
    return config


def subtitle_line(event, target_language='zh'):
    """Print each partial event separately; do not assume cross-language pairing."""
    kind = event.get("type", "")
    if kind == "conversation.item.input_audio_transcription.completed":
        return f"[EN] {event.get('transcript', '')}"
    if kind == "response.text.done":
        return f"[{target_language.upper()}] {event.get('text', '')}"
    language = {
        "conversation.item.input_audio_transcription.text": "EN",
        "response.text.text": target_language.upper(),
    }.get(kind)
    if language:
        return f"[{language} partial] {event.get('text', '')}{event.get('stash', '')}"
    return None


def safe_error(error, key=""):
    message = str(error)
    if key:
        message = message.replace(key, "<redacted>")
    return re.sub(r"sk-[A-Za-z0-9_-]+", "<redacted>", message)


class Session:
    def __init__(self, ws, key, show_partial=True, on_event=None, target_language='zh'):
        self.ws = ws
        self.key = key
        self.show_partial = show_partial
        self.on_event = on_event
        self.target_language = target_language
        self.english_finals = 0
        self.chinese_finals = 0  # Legacy counter name: counts target-language results.
        self.failure = None
        self.close_code = None
        self.last_ping = 0.0
        self.last_pong = 0.0
        self.ping_payload = b"live-subtitle"
        self.ready = threading.Event()
        self.finished = threading.Event()
        self.failed = threading.Event()
        self.closing = threading.Event()
        self.reader = threading.Thread(target=self.receive, daemon=True)

    def send(self, kind, **fields):
        self.ws.send(json.dumps({
            "event_id": "event_" + uuid.uuid4().hex, "type": kind, **fields
        }))

    def receive(self):
        # Keep receiving through shutdown, so the last sentence can arrive.
        import websocket
        try:
            while not self.closing.is_set():
                try:
                    opcode, raw = self.ws.recv_data(control_frame=True)
                except websocket.WebSocketTimeoutException:
                    continue
                if opcode == websocket.ABNF.OPCODE_PONG:
                    if raw == self.ping_payload:
                        self.last_pong = time.monotonic()
                    continue
                if opcode == websocket.ABNF.OPCODE_PING:
                    continue  # websocket-client already sends the pong response.
                if opcode == websocket.ABNF.OPCODE_CLOSE:
                    self.close_code = int.from_bytes(raw[:2], 'big') if len(raw) >= 2 else None
                    reason = raw[2:].decode('utf-8', errors='replace') if len(raw) > 2 else ''
                    if not self.finished.is_set():
                        error = ServiceError if self.close_code in (1002, 1003, 1007, 1008, 1009) else ConnectionLost
                        raise error(f"连接关闭 code={self.close_code} reason={safe_error(reason, self.key)}")
                    return
                if not raw:
                    if not self.finished.is_set():
                        raise ConnectionLost("连接提前关闭，尚未收到 session.finished。")
                    return
                event = json.loads(raw)
                kind = event.get("type", "")
                if self.on_event is not None:
                    self.on_event(event)
                if kind == "session.updated":
                    self.ready.set()
                elif kind == "session.finished":
                    self.finished.set()
                    print("[INFO] session.finished", flush=True)
                    return
                elif kind == "error" or kind.endswith("transcription.failed"):
                    detail = event.get("error", {})
                    raise service_error(detail)
                elif kind == "response.done" and event.get("response", {}).get("status") in {"failed", "incomplete"}:
                    raise ServiceError("翻译响应未完成，请检查模型权限与网络。")
                line = subtitle_line(event, self.target_language)
                if kind == "conversation.item.input_audio_transcription.completed" and event.get("transcript", "").strip():
                    self.english_finals += 1
                if kind == "response.text.done" and event.get("text", "").strip():
                    self.chinese_finals += 1
                if line and " partial]" in line and not self.show_partial:
                    line = None
                if line and not line.split("]", 1)[1].strip():
                    line = None
                if line:
                    print(line, flush=True)
        except Exception as exc:
            if not self.closing.is_set():
                self.failure = exc if isinstance(exc, (ConnectionLost, ServiceError)) else ConnectionLost(safe_error(exc, self.key))
                print(f"[ERROR] 接收失败：{safe_error(exc, self.key)}", flush=True)
                self.failed.set()

    def raise_failure(self):
        raise self.failure or ConnectionLost("百炼连接失败。")

    def heartbeat(self, now=None):
        now = time.monotonic() if now is None else now
        if self.last_ping > self.last_pong:
            if now - self.last_ping >= 15:
                raise ConnectionLost("WebSocket 心跳 15 秒未收到 pong。")
            return
        if now - self.last_ping >= 15:
            self.last_ping = now
            self.ws.ping(self.ping_payload)

    def wait(self, target, timeout, stop=None):
        deadline = time.monotonic() + timeout
        while not target.wait(0.1):
            if self.failed.is_set():
                self.raise_failure()
            if stop is not None and stop.is_set():
                return False
            if time.monotonic() >= deadline:
                raise TimeoutError("等待服务端事件超时。")
        return True

    def finish(self, timeout=20):
        if self.finished.is_set():
            return
        print("[INFO] 发送 session.finish，等待最后一句（最多 20 秒）…", flush=True)
        self.send("session.finish")
        self.wait(self.finished, timeout)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-devices", action="store_true", help="仅列出输入设备，不连接云端")
    parser.add_argument("--device", type=int, help="输入设备编号，默认使用系统默认麦克风")
    parser.add_argument("--check-config", action="store_true", help="离线检查配置，不显示密钥")
    args = parser.parse_args(argv)
    key = ""
    stream = ws = session = None
    previous_handler = None
    exit_code = 0
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", encoding="utf-8-sig")
        if not args.list_devices:
            key, url = connection_config(os.environ)
        if args.check_config:
            print(f"[OK] 配置格式正确；模型：{MODEL}。尚未验证云端权限。")
            return 0
        import sounddevice as sd
        if args.list_devices:
            for index, info in enumerate(sd.query_devices()):
                if info["max_input_channels"] > 0:
                    print(f"{index}: {info['name']} (输入声道 {info['max_input_channels']})")
            return 0
        import websocket
        # Validate microphone format before establishing a paid cloud session.
        stream = sd.RawInputStream(dtype="int16", channels=1, samplerate=16000,
                                   device=args.device, blocksize=1600)
        stop = threading.Event()
        previous_handler = signal.signal(signal.SIGINT, lambda *_: stop.set())
        print("[INFO] 正在连接百炼…", flush=True)
        ws = websocket.create_connection(url, header={"Authorization": f"Bearer {key}"}, timeout=10)
        ws.settimeout(1)
        session = Session(ws, key)
        session.reader.start()
        session.send("session.update", session=session_config())
        if session.wait(session.ready, 15, stop):
            stream.start()
            print("[INFO] 已开始上传麦克风音频。请说英文；Ctrl+C 结束。", flush=True)
            while not stop.is_set() and not session.failed.is_set() and not session.finished.is_set():
                # Report overflow rather than silently losing speech.
                data, overflow = stream.read(1600)
                if overflow:
                    raise RuntimeError("麦克风输入溢出，部分语音丢失，请重新测试。")
                session.send("input_audio_buffer.append", audio=base64.b64encode(data).decode("ascii"))
    except Exception as exc:
        print(f"[ERROR] {safe_error(exc, key)}", file=sys.stderr, flush=True)
        exit_code = 1
    finally:
        # Cleanup must continue even if microphone shutdown fails.
        if stream is not None:
            try:
                stream.close()
            except Exception as exc:
                print(f"[ERROR] 关闭麦克风：{safe_error(exc, key)}", file=sys.stderr)
                exit_code = 1
        if session is not None:
            try:
                session.finish()
            except Exception as exc:
                print(f"[ERROR] 会话未正常结束，最后一句可能不完整：{safe_error(exc, key)}", file=sys.stderr)
                exit_code = 1
            finally:
                session.closing.set()
        if ws is not None:
            ws.close()
        if session is not None:
            session.reader.join(timeout=2)
            if session.failed.is_set():
                exit_code = 1
        if previous_handler is not None:
            signal.signal(signal.SIGINT, previous_handler)
    return exit_code


if __name__ == "__main__":
    configure_console()
    sys.exit(main())
