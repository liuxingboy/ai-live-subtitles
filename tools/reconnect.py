"""Retry policy for transport failures, distinct from capture/configuration errors."""
import time
import json
import re
from audio.output_device import OutputDeviceChanged


class ConnectionLost(RuntimeError):
    pass


class UnspecifiedASRError(ConnectionLost):
    """Observed ASR failure without diagnostics; recovery has a strict budget."""


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
    # ASR may wrap upstream capacity errors inside UNEXPECTED_ASR_ERROR.
    # Match the observed capacity diagnostic, not every ASR/429 failure.
    asr_capacity = (
        code == 'unexpected_asr_error'
        and re.search(r'\bstatusCode\s*=\s*429\b', message, re.IGNORECASE)
        and re.search(r'\bthread\s+pool\s+(?:exausted|exhausted)\b', message, re.IGNORECASE)
    )
    # Observed model repetition failure: start a fresh session to recover.
    model_repetition = (
        code == 'common_error'
        and message.strip().lower() == 'model repeat output happened'
    )
    unspecified_asr = (
        code == 'unexpected_asr_error'
        and detail.get('type') == 'transcription_error'
        and (detail.get('message') is None or not message.strip())
        and set(detail) <= {'type', 'code', 'message'}
    )
    error_type = (UnspecifiedASRError if unspecified_asr else
                  ConnectionLost if retryable or asr_timeout or asr_capacity or model_repetition else ServiceError)
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
    asr_recoveries = 0
    device_failures = 0
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
        except OutputDeviceChanged as exc:
            report['output_device_changes'] = report.get('output_device_changes', 0) + 1
            if stop.is_set():
                return
            if clock() - began >= 30:
                device_failures = 0
            device_failures += 1
            if device_failures > 5:
                raise RuntimeError('播放设备持续变化或不可用，请检查 Windows 声音设置后重试') from exc
            delay = 1 if deadline is None else min(1, max(0, deadline - clock()))
            print(f'[AUDIO] {exc}；等待设备稳定后重新采集。', flush=True)
            if delay <= 0 or stop.wait(delay):
                return
            if deadline is not None and clock() >= deadline:
                return
            report['output_device_recovery_attempts'] = report.get('output_device_recovery_attempts', 0) + 1
        except ConnectionLost as exc:
            report['disconnects'] = report.get('disconnects', 0) + 1
            if stop.is_set():
                return
            if isinstance(exc, UnspecifiedASRError) and asr_recoveries >= 2:
                raise ServiceError('云端语音识别错误未提供原因，自动恢复两次后仍失败。可尝试正常模式；若仍失败请稍后重试。') from exc
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
            if isinstance(exc, UnspecifiedASRError):
                asr_recoveries += 1
                report['asr_recovery_attempts'] = asr_recoveries
            report['reconnect_attempts'] = report.get('reconnect_attempts', 0) + 1
