"""Capture the default Windows output loopback or input, without recording files."""
import ctypes as C
import time
from audio.wasapi_capture import (
    GUID, P, U32, HRESULT, WaveFormat, CaptureResult, IID_CLIENT, IID_CAPTURE,
    ole32, method, check, release,
)

CLSID_ENUMERATOR = GUID.parse('BCDE0395-E52F-467C-8E3D-C4579291692E')
IID_ENUMERATOR = GUID.parse('A95664D2-9614-4F35-A746-DE8DB63617E6')
ole32.CoCreateInstance.argtypes = [C.POINTER(GUID), P, U32, C.POINTER(GUID), C.POINTER(P)]
ole32.CoCreateInstance.restype = HRESULT


def capture_endpoint(kind, seconds, stop, on_audio):
    """Each invocation resolves the current default multimedia device anew."""
    if kind not in ('system', 'microphone'):
        raise ValueError('未知设备声源')
    if seconds is not None and seconds <= 0:
        raise ValueError('采集时长必须为正数')
    label = '系统声音' if kind == 'system' else '系统麦克风'
    check(ole32.CoInitializeEx(None, 0), '初始化音频 COM')
    enumerator, device, client, capture = P(), P(), P(), P()
    started = False
    packets = discontinuities = timestamp_errors = 0
    began = time.monotonic()
    try:
        check(ole32.CoCreateInstance(C.byref(CLSID_ENUMERATOR), None, 1,
              C.byref(IID_ENUMERATOR), C.byref(enumerator)), '创建设备枚举器')
        check(method(enumerator, 4, HRESULT, C.c_int, C.c_int, C.POINTER(P))(
              enumerator, 0 if kind == 'system' else 1, 1, C.byref(device)),
              f'获取默认{label}设备，请检查 Windows 声音设置')
        check(method(device, 3, HRESULT, C.POINTER(GUID), U32, P, C.POINTER(P))(
              device, C.byref(IID_CLIENT), 1, None, C.byref(client)), f'激活{label}')
        fmt = WaveFormat(1, 1, 16000, 32000, 2, 16, 0)
        flags = 0x80000000 | 0x08000000  # automatic PCM conversion / resampling
        if kind == 'system':
            flags |= 0x00020000  # render endpoint loopback, never microphone
        check(method(client, 3, HRESULT, C.c_int32, U32, C.c_int64, C.c_int64,
              C.POINTER(WaveFormat), P)(client, 0, flags, 1000000, 0, C.byref(fmt), None),
              f'初始化{label}，请检查设备格式及麦克风权限')
        check(method(client, 14, HRESULT, C.POINTER(GUID), C.POINTER(P))(
              client, C.byref(IID_CAPTURE), C.byref(capture)), '获取设备捕获接口')
        check(method(client, 10, HRESULT)(client), f'开始采集{label}')
        started = True
        began = last_audio = time.monotonic()
        while not stop.is_set():
            now = time.monotonic()
            if seconds is not None and now - began >= seconds:
                break
            received = False
            while not stop.is_set():
                frames = U32()
                check(method(capture, 5, HRESULT, C.POINTER(U32))(
                      capture, C.byref(frames)), f'读取{label}包大小，设备可能已断开')
                if not frames.value:
                    break
                data, count, status = P(), U32(), U32()
                check(method(capture, 3, HRESULT, C.POINTER(P), C.POINTER(U32),
                      C.POINTER(U32), P, P)(capture, C.byref(data), C.byref(count),
                      C.byref(status), None, None), f'读取{label}')
                try:
                    size = count.value * 2
                    if status.value & 2:
                        chunk = bytes(size)
                    elif size and not data:
                        raise RuntimeError('音频设备返回空数据指针')
                    else:
                        chunk = C.string_at(data, size)
                    if packets and status.value & 1:
                        discontinuities += 1
                    if status.value & 4:
                        timestamp_errors += 1
                    packets += 1
                finally:
                    check(method(capture, 4, HRESULT, U32)(capture, count.value), '释放设备音频包')
                on_audio(chunk)
                received = True
                last_audio = time.monotonic()
                if seconds is not None and last_audio - began >= seconds:
                    break
            # Render loopback may deliver no packets when no application plays.
            # Feed bounded silence so the shared idle detector can pause cloud use.
            now = time.monotonic()
            if not received and now - last_audio >= .1:
                if kind == 'system':
                    on_audio(bytes(3200))
                    last_audio = now
                elif now - last_audio > 5:
                    raise RuntimeError('系统麦克风未返回音频，请检查设备及权限')
            stop.wait(.01)
        return CaptureResult(b'', 16000, 1, packets, discontinuities,
                             timestamp_errors, time.monotonic() - began, stop.is_set())
    finally:
        if started:
            method(client, 11, HRESULT)(client)
        for pointer in (capture, client, device, enumerator):
            release(pointer)
        ole32.CoUninitialize()
