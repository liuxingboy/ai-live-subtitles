"""Windows global shortcuts and native click-through for our own window."""
import ctypes as C
from ctypes import wintypes as W
from PySide6.QtCore import QAbstractNativeEventFilter

user32 = C.WinDLL('user32', use_last_error=True)
user32.RegisterHotKey.argtypes = [W.HWND, C.c_int, W.UINT, W.UINT]
user32.RegisterHotKey.restype = W.BOOL
user32.UnregisterHotKey.argtypes = [W.HWND, C.c_int]
user32.UnregisterHotKey.restype = W.BOOL
get_style = user32.GetWindowLongPtrW if C.sizeof(C.c_void_p) == 8 else user32.GetWindowLongW
set_style = user32.SetWindowLongPtrW if C.sizeof(C.c_void_p) == 8 else user32.SetWindowLongW
get_style.argtypes = [W.HWND, C.c_int]
get_style.restype = C.c_ssize_t
set_style.argtypes = [W.HWND, C.c_int, C.c_ssize_t]
set_style.restype = C.c_ssize_t


def click_through(hwnd, enabled):
    style = get_style(hwnd, -20)
    C.set_last_error(0)
    set_style(hwnd, -20, (style | 0x80000 | 0x20) if enabled else (style & ~0x20))
    if C.get_last_error():
        raise C.WinError(C.get_last_error())


class Hotkeys(QAbstractNativeEventFilter):
    def __init__(self, app, actions):
        super().__init__()
        self.app = app
        self.actions = {}
        for modifiers, prefix in ((0x4003, 'Ctrl+Alt'), (0x4007, 'Ctrl+Alt+Shift')):
            for index, (key, action) in enumerate(actions.items(), 0x5230):
                if not user32.RegisterHotKey(None, index, modifiers, key):
                    break
                self.actions[index] = action
            else:
                self.prefix = prefix
                app.installNativeEventFilter(self)
                return
            self.close()
        raise OSError('Ctrl+Alt 和 Ctrl+Alt+Shift 快捷键均不可用，锁定未启用。请关闭其他字幕实例或检查快捷键冲突。')

    def nativeEventFilter(self, event_type, message):
        msg = W.MSG.from_address(int(message))
        if msg.message == 0x312 and msg.wParam in self.actions:
            self.actions[msg.wParam]()
            return True, 0
        return False, 0

    def close(self):
        self.app.removeNativeEventFilter(self)
        for index in self.actions:
            user32.UnregisterHotKey(None, index)
        self.actions.clear()
