"""Detect default render endpoint changes without retaining COM interfaces."""
import time


class OutputDeviceChanged(RuntimeError):
    def __init__(self, message='Windows 默认播放设备已变化，正在重建采集和翻译会话'):
        super().__init__(message)


def endpoint_id(device):
    import ctypes as C
    from audio.wasapi_capture import P, HRESULT, ole32, method, check
    value = P()
    ole32.CoTaskMemFree.argtypes = [P]
    ole32.CoTaskMemFree.restype = None
    try:
        check(method(device, 5, HRESULT, C.POINTER(P))(device, C.byref(value)), '读取音频设备标识')
        return C.wstring_at(value)
    finally:
        if value:
            ole32.CoTaskMemFree(value)


def default_output_id():
    import ctypes as C
    from audio.wasapi_capture import GUID, P, U32, HRESULT, ole32, method, check, release
    clsid = GUID.parse('BCDE0395-E52F-467C-8E3D-C4579291692E')
    iid = GUID.parse('A95664D2-9614-4F35-A746-DE8DB63617E6')
    check(ole32.CoInitializeEx(None, 0), '初始化设备检测 COM')
    enumerator, device = P(), P()
    try:
        ole32.CoCreateInstance.argtypes = [C.POINTER(GUID), P, U32, C.POINTER(GUID), C.POINTER(P)]
        ole32.CoCreateInstance.restype = HRESULT
        check(ole32.CoCreateInstance(C.byref(clsid), None, 1, C.byref(iid), C.byref(enumerator)), '创建设备检测器')
        hr = method(enumerator, 4, HRESULT, C.c_int, C.c_int, C.POINTER(P))(
            enumerator, 0, 1, C.byref(device))
        if hr & 0xffffffff == 0x80070490:  # E_NOTFOUND during device handover
            return None
        check(hr, '检测默认播放设备')
        return endpoint_id(device)
    finally:
        release(device)
        release(enumerator)
        ole32.CoUninitialize()


class OutputDeviceWatcher:
    def __init__(self, read_id=None, clock=time.monotonic):
        self.read_id = read_id or default_output_id
        self.clock = clock
        self.original = self.read_id()
        self.next_check = 0
        if self.original is None:
            raise OutputDeviceChanged('暂时没有默认播放设备，等待设备就绪')

    def check(self, force=False):
        now = self.clock()
        if not force and now < self.next_check:
            return
        self.next_check = now + .5
        if self.read_id() != self.original:
            raise OutputDeviceChanged()
