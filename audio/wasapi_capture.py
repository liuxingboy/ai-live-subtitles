"""Windows process loopback via ctypes; no endpoint/system-loopback fallback.

ABI definitions follow Windows SDK audioclient.h, mmdeviceapi.h and
audioclientactivationparams.h. All audio COM calls run on the calling MTA.
"""
import ctypes as C
from dataclasses import dataclass
import sys
import threading
import time
import uuid

if sys.platform != "win32":
    raise ImportError("WASAPI 捕获仅支持 Windows。")

P = C.c_void_p
U32 = C.c_uint32
HRESULT = C.c_int32
U64 = C.c_uint64
CALL = C.WINFUNCTYPE


class GUID(C.Structure):
    _fields_ = [("data", C.c_ubyte * 16)]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


IID_CLIENT = GUID.parse("1CB9AD4C-DBFA-4c32-B178-C2F568A703B2")
IID_CAPTURE = GUID.parse("C8ADBD64-E71E-48a0-A4DE-185C395CD317")
IID_HANDLER = GUID.parse("41D949AB-9862-444A-80F6-C261334DA5EB")
IID_UNKNOWN = GUID.parse("00000000-0000-0000-C000-000000000046")
IID_MARSHAL = GUID.parse("00000003-0000-0000-C000-000000000046")
IID_AGILE = GUID.parse("94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90")


class ActivationParams(C.Structure):
    _fields_ = [("activation_type", U32), ("pid", U32), ("mode", U32)]


class Blob(C.Structure):
    _fields_ = [("size", U32), ("data", P)]


class PropVariant(C.Structure):
    _fields_ = [("vt", C.c_uint16), ("reserved", C.c_uint16 * 3), ("blob", Blob)]


class WaveFormat(C.Structure):
    _pack_ = 1
    _fields_ = [("tag", C.c_uint16), ("channels", C.c_uint16),
                ("rate", U32), ("bytes_per_sec", U32), ("block_align", C.c_uint16),
                ("bits", C.c_uint16), ("extra", C.c_uint16)]


def check(hr, action):
    if hr < 0:
        raise OSError(f"{action} 失败，HRESULT=0x{hr & 0xffffffff:08X}")


def method(pointer, index, result, *args):
    table = C.cast(pointer, C.POINTER(C.POINTER(P))).contents
    return CALL(result, P, *args)(table[index])


def release(pointer):
    if pointer:
        method(pointer, 2, U32)(pointer)


ole32 = C.WinDLL("ole32")
ole32.CoInitializeEx.argtypes = [P, U32]
ole32.CoInitializeEx.restype = HRESULT
ole32.CoUninitialize.argtypes = []
ole32.CoCreateFreeThreadedMarshaler.argtypes = [P, C.POINTER(P)]
ole32.CoCreateFreeThreadedMarshaler.restype = HRESULT
mmdev = C.WinDLL("Mmdevapi")
mmdev.ActivateAudioInterfaceAsync.argtypes = [C.c_wchar_p, C.POINTER(GUID), C.POINTER(PropVariant), P, C.POINTER(P)]
mmdev.ActivateAudioInterfaceAsync.restype = HRESULT
kernel = C.WinDLL("kernel32", use_last_error=True)
kernel.CreateEventW.argtypes = [P, C.c_int, C.c_int, C.c_wchar_p]
kernel.CreateEventW.restype = P
kernel.WaitForSingleObject.argtypes = [P, U32]
kernel.WaitForSingleObject.restype = U32
kernel.CloseHandle.argtypes = [P]
kernel.CloseHandle.restype = C.c_int

# Native activation may complete after a timeout. Keep callback/parameter memory
# alive until process exit in that exceptional case (this is a short-lived CLI).
_pending = []


class Completion:
    def __init__(self, pid):
        self.done = threading.Event()
        self.lock = threading.Lock()
        self.refs = 1
        self.marshaler = P()
        self.operation = P()
        self.params = ActivationParams(1, pid, 0)  # INCLUDE_TARGET_PROCESS_TREE
        self.variant = PropVariant(65, (C.c_uint16 * 3)(), Blob(C.sizeof(self.params), C.addressof(self.params)))
        self.callbacks = (
            CALL(HRESULT, P, C.POINTER(GUID), C.POINTER(P))(self.query),
            CALL(U32, P)(self.add_ref),
            CALL(U32, P)(self.release_ref),
            CALL(HRESULT, P, P)(self.completed),
        )
        self.table = (P * 4)(*[C.cast(f, P).value for f in self.callbacks])
        self.interface = C.pointer(C.cast(self.table, P))
        self.pointer = C.cast(self.interface, P)
        check(ole32.CoCreateFreeThreadedMarshaler(self.pointer, C.byref(self.marshaler)), "创建 COM 自由线程封送器")

    def query(self, this, iid, output):
        output[0] = None
        wanted = bytes(iid.contents)
        if wanted in (bytes(IID_UNKNOWN), bytes(IID_HANDLER), bytes(IID_AGILE)):
            output[0] = self.pointer.value
            self.add_ref(this)
            return 0
        if wanted == bytes(IID_MARSHAL) and self.marshaler:
            return method(self.marshaler, 0, HRESULT, C.POINTER(GUID), C.POINTER(P))(self.marshaler, iid, output)
        return -2147467262  # E_NOINTERFACE

    def add_ref(self, this):
        with self.lock:
            self.refs += 1
            return self.refs

    def release_ref(self, this):
        with self.lock:
            self.refs -= 1
            return self.refs

    def completed(self, this, operation):
        self.done.set()
        return 0

    def activate(self):
        check(mmdev.ActivateAudioInterfaceAsync("VAD\\Process_Loopback", C.byref(IID_CLIENT),
              C.byref(self.variant), self.pointer, C.byref(self.operation)), "激活进程音频")
        if not self.done.wait(15):
            _pending.append(self)
            raise TimeoutError("激活进程音频超时（15 秒）。请关闭本工具后重试。")
        status, unknown, client = HRESULT(), P(), P()
        try:
            check(method(self.operation, 3, HRESULT, C.POINTER(HRESULT), C.POINTER(P))(
                self.operation, C.byref(status), C.byref(unknown)), "读取激活结果")
            check(status.value, "激活 IAudioClient")
            if not unknown:
                raise RuntimeError("Windows 未返回音频接口。")
            check(method(unknown, 0, HRESULT, C.POINTER(GUID), C.POINTER(P))(
                unknown, C.byref(IID_CLIENT), C.byref(client)), "查询 IAudioClient")
            return client
        finally:
            release(unknown)

    def close(self):
        if self in _pending:
            return
        release(self.operation)
        self.operation = P()
        release(self.marshaler)
        self.marshaler = P()


@dataclass
class CaptureResult:
    pcm: bytes
    sample_rate: int
    channels: int
    packets: int
    discontinuities: int
    timestamp_errors: int
    elapsed: float
    interrupted: bool


def capture_process(pid, seconds=10, stop=None, alive=None, progress=None, on_audio=None, monitor_output=False):
    """Capture 16 kHz mono PCM16; WASAPI performs stateful format conversion."""
    if sys.getwindowsversion().build < 20348:
        raise RuntimeError("按进程捕获要求 Windows build 20348 或更高。")
    if pid <= 0 or (seconds is not None and seconds <= 0):
        raise ValueError("PID 和录制时长必须为正数。")
    if seconds is None and on_audio is None:
        raise ValueError("无限时捕获必须提供流式音频回调。")
    check(ole32.CoInitializeEx(None, 0), "初始化 COM MTA")
    watcher = None
    completion = client = capture = handle = None
    started = False
    rate, channels = 16000, 1
    block_align = channels * 2
    limit = round(seconds * rate) if seconds is not None else None
    total_frames = 0
    output = bytearray()
    packets = discontinuities = timestamp_errors = 0
    interrupted = False
    try:
        if monitor_output:
            from audio.output_device import OutputDeviceWatcher
            watcher = OutputDeviceWatcher()
        completion = Completion(pid)
        client = completion.activate()
        fmt = WaveFormat(1, channels, rate, rate * block_align, block_align, 16, 0)
        # LOOPBACK | EVENTCALLBACK | AUTOCONVERTPCM | SRC_DEFAULT_QUALITY
        flags = 0x00020000 | 0x00040000 | 0x80000000 | 0x08000000
        check(method(client, 3, HRESULT, C.c_int32, U32, C.c_int64, C.c_int64, C.POINTER(WaveFormat), P)(
            client, 0, flags, 0, 0, C.byref(fmt), None), "初始化音频流")
        capture = P()
        check(method(client, 14, HRESULT, C.POINTER(GUID), C.POINTER(P))(
            client, C.byref(IID_CAPTURE), C.byref(capture)), "获取捕获接口")
        handle = kernel.CreateEventW(None, False, False, None)
        if not handle:
            raise C.WinError(C.get_last_error())
        check(method(client, 13, HRESULT, P)(client, handle), "绑定音频事件")
        check(method(client, 10, HRESULT)(client), "开始捕获")
        started = True
        start = time.monotonic()
        last_packet = start
        last_progress = -1
        while limit is None or total_frames < limit:
            elapsed = time.monotonic() - start
            if stop is not None and stop.is_set():
                interrupted = True
                break
            if watcher:
                watcher.check()
            if alive is not None and not alive():
                raise RuntimeError("目标 Chrome 已退出或 PID 已变化，请重新运行。")
            if time.monotonic() - last_packet > 5:
                raise RuntimeError("未及时收到足够音频帧；请确认 Chrome 正在播放声音。")
            if progress and int(elapsed) != last_progress:
                last_progress = int(elapsed)
                progress(elapsed, total_frames)
            wait = kernel.WaitForSingleObject(handle, 100)
            if wait == 0xffffffff:
                raise C.WinError(C.get_last_error())
            frames = U32()
            while True:
                check(method(capture, 5, HRESULT, C.POINTER(U32))(capture, C.byref(frames)), "读取数据包大小")
                if not frames.value:
                    break
                data, count, status = P(), U32(), U32()
                check(method(capture, 3, HRESULT, C.POINTER(P), C.POINTER(U32), C.POINTER(U32), P, P)(
                    capture, C.byref(data), C.byref(count), C.byref(status), None, None), "读取音频数据")
                try:
                    if packets and status.value & 1:
                        discontinuities += 1
                    if status.value & 4:
                        timestamp_errors += 1
                    packet_frames = count.value if limit is None else min(count.value, limit - total_frames)
                    size = packet_frames * block_align
                    if status.value & 2:
                        chunk = bytes(size)
                    elif size:
                        if not data:
                            raise RuntimeError("非静音数据包返回了空指针。")
                        chunk = C.string_at(data, size)
                    else:
                        chunk = b""
                    total_frames += packet_frames
                    last_packet = time.monotonic()
                    packets += 1
                finally:
                    check(method(capture, 4, HRESULT, U32)(capture, count.value), "释放音频数据包")
                # Release native buffer before invoking Python consumers.
                if on_audio is not None:
                    on_audio(chunk)
                else:
                    output.extend(chunk)
                if stop is not None and stop.is_set():
                    break
                if limit is not None and total_frames >= limit:
                    break
        return CaptureResult(bytes(output), rate, channels, packets, discontinuities,
                             timestamp_errors, time.monotonic() - start, interrupted)
    except OSError:
        if watcher:
            watcher.check(force=True)
        raise
    finally:
        if started:
            method(client, 11, HRESULT)(client)
        release(capture)
        release(client)
        if handle:
            kernel.CloseHandle(handle)
        if completion:
            completion.close()
        ole32.CoUninitialize()
