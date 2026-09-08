"""Retry policy for transport failures, distinct from capture/configuration errors."""
import time
import json
import re


class ConnectionLost(RuntimeError):
    pass


class ServiceError(RuntimeError):
    pass


def service_error(detail):
    """Classify server events; unknown ASR errors remain terminal by default."""
    code = str(detail.get('code', '')).lower()
    message = str(detail.get('message', ''))
    retryable = code in ('server_error', 'rate_limit_exceeded', 'session_expired', 'session_timeout')
    # Observed after paused playback: ASR's upstream response stream times out,
    # even though WebSocket ping/pong and audio uploads are still functioning.
    asr_timeout = (
        code == 'unexpected_asr_error'
        and re.search(r'\bstatusCode\s*=\s*504\b', message, re.IGNORECASE)
        and 'response stream timeout' in message.lower()
    )
    error_type = ConnectionLost if retryable or asr_timeout else ServiceError
    return error_type(json.dumps(detail, ensure_ascii=False))


def network_error(exc):
    """Only call at a network boundary: native audio OSErrors are not retryable."""
    import websocket
    if isinstance(exc, websocket.WebSocketBadStatusException):
        if exc.status_code not in (408, 429) and not (exc.status_code and exc.status_code >= 500):
            return ServiceError(f"WebSocket HTTP {exc.status_code}，请检查 Key、工作空间和模型权限。")
    return ConnectionLost(str(exc))


def run_with_reconnect(operation, stop, report, seconds=None, alive=lambda: True, clock=time.monotonic):
    deadline = clock() + seconds if seconds is not None else None
    failures = 0
    while not stop.is_set():
        remaining = None if deadline is None else deadline - clock()
        if remaining is not None and remaining <= 0:
            return
        if not alive():
            raise RuntimeError("目标 Chrome 已退出，请重新运行。")
        began = clock()
        try:
            operation(remaining)
            return
        except ConnectionLost as exc:
            report['disconnects'] = report.get('disconnects', 0) + 1
            if stop.is_set():
                return
            if clock() - began >= 30:
                failures = 0
            delay = (1, 2, 4, 8, 15)[min(failures, 4)]
            failures += 1
            if deadline is not None:
                delay = min(delay, max(0, deadline - clock()))
            if delay <= 0:
                return
            print(f"[RECONNECTING] {exc}；{delay:g} 秒后重试。断线期间的音频不会补发。", flush=True)
            if stop.wait(delay):
                return
            if deadline is not None and clock() >= deadline:
                return
            report['reconnect_attempts'] = report.get('reconnect_attempts', 0) + 1
