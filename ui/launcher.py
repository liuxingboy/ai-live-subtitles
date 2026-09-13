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
    lock = threading.Lock()
    live = '--final-only' not in (argv or [])
    manager = SubtitleManager(partial=live)
    state = ['connecting', '正在连接…']

    def event_received(event):
        with lock:
            manager.feed(event)

    def status_changed(kind, message):
        with lock:
            state[:] = [kind, message]
            if kind in ('connecting', 'reconnecting', 'paused'):
                manager.reset()

    from app.translation_controller import TranslationController
    from ui.tray import SubtitleTray
    from audio.sources import SOURCE_REGISTRY
    from app.preferences import SPEED_MODES, TARGET_LANGUAGES
    import argparse
    source_parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    source_parser.add_argument('--source', choices=tuple(SOURCE_REGISTRY), default='chrome')
    source_parser.add_argument('--speed', choices=tuple(SPEED_MODES), default='normal')
    source_parser.add_argument('--target-language', choices=tuple(TARGET_LANGUAGES), default='zh')
    options = source_parser.parse_known_args(argv or [])[0]
    initial_source = options.source
    controller = TranslationController(translate, argv, event_received, status_changed, speed=options.speed, target_language=options.target_language)
    tray = SubtitleTray(app.windowIcon(), initial_source, window)
    tray.select_speed(options.speed)
    tray.select_language(options.target_language)

    def select_source(key):
        if window.stopping:
            return
        if controller.select(key):
            window.running = True
            tray.select(key)
        else:
            tray.select(controller.selected)

    def select_speed(key):
        if window.stopping:
            return
        if controller.select_speed(key):
            window.running = True
        tray.select_speed(controller.speed)

    def select_language(key):
        if window.stopping:
            return
        if controller.select_language(key):
            window.running = True
        tray.select_language(controller.target_language)

    def sync_lock_state():
        tray.set_lock_state(window.locked, window.lock_available and not window.stopping,
                            window.shortcut_prefix)

    def toggle_lock():
        window.toggle_lock()
        sync_lock_state()

    tray.lock_requested.connect(toggle_lock)
    tray.menu.aboutToShow.connect(sync_lock_state)
    tray.language_selected.connect(select_language)
    tray.speed_selected.connect(select_speed)
    tray.source_selected.connect(select_source)
    tray.exit_requested.connect(window.close)
    tray.source_menu.setEnabled(not demo)
    tray.speed_menu.setEnabled(not demo)
    tray.language_menu.setEnabled(not demo)
    if tray.isSystemTrayAvailable():
        tray.show()
    else:
        print('[WARN] 系统托盘不可用；可用 --source 参数选择声源。', flush=True)

    last = [None]
    def refresh():
        controller.poll()
        if controller.blocked:
            tray.source_menu.setEnabled(False)
            tray.speed_menu.setEnabled(False)
            tray.language_menu.setEnabled(False)
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
        if controller.done.is_set() and controller.pending is None and not controller.thread.is_alive():
            window.running = False
            if window.stopping:
                window.close()
            elif controller.result == 0:
                window.set_status('stopped', '会话已结束 · 可关闭窗口')
            elif status[0] != 'error':
                window.set_status('error', '会话未正常结束，请查看终端')
            window.close_button.setEnabled(True)

    window.stop_requested.connect(controller.close)
    timer = QTimer()
    timer.setInterval(100)
    timer.timeout.connect(refresh)
    old_signal = signal.signal(signal.SIGINT, lambda *_: window.close())
    window.show()
    hotkeys = None
    if app.platformName() == 'windows':
        from ui.hotkeys import Hotkeys
        try:
            hotkeys = Hotkeys(app, {ord('L'): toggle_lock, ord('Q'): window.close,
                                  0xBB: lambda: window.change_font(2), 0xBD: lambda: window.change_font(-2)})
            window.lock_available = True
            window.shortcut_prefix = hotkeys.prefix
            print(f'[INFO] {hotkeys.prefix}+L 锁定/解锁，{hotkeys.prefix}+=/- 调字号，{hotkeys.prefix}+Q 退出。', flush=True)
        except OSError as exc:
            print(f'[WARN] {exc}', flush=True)
    sync_lock_state()
    if demo:
        window.running = False
        window.set_status('connected', '离线预览 · 不采集音频')
        window.show_subtitles('We knew the first map would be difficult, but we adapted really well.',
                              '我们知道第一张地图会很难打，但我们的调整做得非常好。')
    else:
        timer.start()
        select_source(initial_source)
    try:
        app.exec()
    finally:
        controller.close()
        timer.stop()
        tray.shutdown()
        save_timer.stop()
        persist()
        if hotkeys:
            hotkeys.close()
        signal.signal(signal.SIGINT, old_signal)
        controller.join(timeout=45)
    return controller.result
