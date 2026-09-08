"""Qt stays on the main thread; a bounded mailbox carries worker updates."""
import signal
import threading
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from subtitle.manager import SubtitleManager
from ui.overlay import Overlay


def run(argv=None, demo=False):
    from tools.chrome_translate import main as translate
    app = QApplication.instance() or QApplication([])
    from pathlib import Path
    from PySide6.QtGui import QIcon
    app.setWindowIcon(QIcon(str(Path(__file__).resolve().parents[1] / 'assets/subtitle-avatar.ico')))
    window = Overlay()
    from app.preferences import read_window, save_window
    window.restore_preferences(read_window())
    def persist():
        try:
            save_window(window.preferences())
        except OSError as exc:
            print(f'[WARN] 无法保存窗口设置：{exc}', flush=True)
    save_timer = QTimer()
    save_timer.setSingleShot(True)
    save_timer.setInterval(500)
    save_timer.timeout.connect(persist)
    window.settings_changed.connect(lambda: save_timer.start())
    stop = threading.Event()
    done = threading.Event()
    lock = threading.Lock()
    live = '--final-only' not in (argv or [])
    manager = SubtitleManager(partial=live)
    state = ['connecting', '正在连接…']
    result = [0]

    def event_received(event):
        with lock:
            manager.feed(event)

    def status_changed(kind, message):
        with lock:
            state[:] = [kind, message]
            if kind in ('connecting', 'reconnecting', 'paused'):
                manager.reset()

    def worker():
        try:
            result[0] = translate(argv, stop_event=stop, on_event=event_received, on_state=status_changed)
        except SystemExit as exc:
            result[0] = int(exc.code or 0)
            status_changed('error', '启动参数无效，请查看终端帮助')
        except Exception as exc:
            result[0] = 1
            # Full diagnostics are provided by the terminal runner.
            status_changed('error', f'程序异常：{type(exc).__name__}，请查看终端')
        finally:
            done.set()

    last = [None]
    def refresh():
        with lock:
            texts = manager.snapshot()
            status = tuple(state)
        if texts != last[0]:
            window.show_subtitles(*texts)
            last[0] = texts
        if not window.stopping:
            if status[0] == 'connected' and any(texts):
                status = ('connected', '已连接 · 流式字幕' if live else '已连接 · 最终字幕')
            window.set_status(*status)
        if done.is_set():
            window.running = False
            if window.stopping:
                window.close()
            elif result[0] == 0:
                window.set_status('stopped', '会话已结束 · 可关闭窗口')
            elif status[0] != 'error':
                window.set_status('error', '会话未正常结束，请查看终端')
            window.close_button.setEnabled(True)

    window.stop_requested.connect(stop.set)
    timer = QTimer()
    timer.setInterval(100)
    timer.timeout.connect(refresh)
    old_signal = signal.signal(signal.SIGINT, lambda *_: window.close())
    window.show()
    hotkeys = None
    if app.platformName() == 'windows':
        from ui.hotkeys import Hotkeys
        try:
            hotkeys = Hotkeys(app, {ord('L'): window.toggle_lock, ord('Q'): window.close,
                                  0xBB: lambda: window.change_font(2), 0xBD: lambda: window.change_font(-2)})
            window.lock_available = True
            window.shortcut_prefix = hotkeys.prefix
            print(f'[INFO] {hotkeys.prefix}+L 锁定/解锁，{hotkeys.prefix}+=/- 调字号，{hotkeys.prefix}+Q 退出。', flush=True)
        except OSError as exc:
            print(f'[WARN] {exc}', flush=True)
    thread = None
    if demo:
        window.running = False
        window.set_status('connected', '离线预览 · 不采集音频')
        window.show_subtitles('We knew the first map would be difficult, but we adapted really well.',
                              '我们知道第一张地图会很难打，但我们的调整做得非常好。')
    else:
        timer.start()
        thread = threading.Thread(target=worker, name='translation-worker')
        thread.start()
    try:
        app.exec()
    finally:
        stop.set()
        save_timer.stop()
        persist()
        if hotkeys:
            hotkeys.close()
        signal.signal(signal.SIGINT, old_signal)
        if thread is not None:
            thread.join(timeout=45)
    return result[0]
