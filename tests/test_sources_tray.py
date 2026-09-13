import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from audio.sources import SOURCE_REGISTRY, resolve_source, SourceShutdownError
from app.translation_controller import TranslationController
from ui.tray import SubtitleTray


def setUpModule():
    from tools.api_debug import configure_console
    configure_console()


class SourceTests(unittest.TestCase):
    def test_devices_do_not_require_chrome(self):
        with patch('audio.chrome_detector.find_chrome_processes', side_effect=AssertionError('Chrome queried')):
            for key in ('system', 'microphone'):
                selected = resolve_source(key)
                self.assertTrue(selected.alive())
                self.assertEqual(selected.create().kind, key)
                with self.assertRaises(ValueError):
                    resolve_source(key, 123)

    def test_capture_error_is_exposed_and_done_is_set(self):
        source = resolve_source('microphone').create()
        with patch('audio.endpoint_capture.capture_endpoint', side_effect=OSError('device unavailable')):
            source.thread.start()
            source.thread.join(2)
        self.assertTrue(source.done.is_set())
        self.assertIsInstance(source.error, OSError)
        self.assertEqual(source.audio.total_bytes, 0)

    def test_unknown_source_rejected(self):
        with self.assertRaises(ValueError):
            resolve_source('unknown')

    def test_shutdown_failure_keeps_fatal_exit_code(self):
        from tools.chrome_translate import main
        from types import SimpleNamespace
        with patch('tools.chrome_translate.connection_config', return_value=('fake', 'wss://example.invalid')), \
             patch('tools.chrome_translate.resolve_source', return_value=SimpleNamespace(key='system', label='系统声音', pid=None, alive=lambda: True)), \
             patch('tools.chrome_translate.run_with_reconnect', side_effect=SourceShutdownError('still capturing')), \
             patch('pathlib.Path.write_text'):
            self.assertEqual(main(['--source', 'system', '--no-hotwords']), 2)


class ControllerTests(unittest.TestCase):
    def test_handover_is_serial_and_drops_old_events(self):
        entered, stopping, release = threading.Event(), threading.Event(), threading.Event()
        calls, events = [], []
        def translate(argv, stop_event, on_event, on_state):
            key = argv[-1]
            calls.append(key)
            if key == 'chrome':
                entered.set()
                stop_event.wait(2)
                stopping.set()
                release.wait(2)
                on_event({'stale': True})
            return 0
        controller = TranslationController(translate, ['--pid', '123', '--hotwords', 'custom.json'], events.append, Mock())
        try:
            controller.select('chrome')
            self.assertTrue(entered.wait(1))
            controller.select('system')
            self.assertTrue(stopping.wait(1))
            controller.select('microphone')
            controller.poll()
            self.assertEqual(calls, ['chrome'])
            release.set()
            controller.join(2)
            controller.poll()
            controller.join(2)
            self.assertEqual(calls, ['chrome', 'microphone'])
            self.assertNotIn({'stale': True}, events)
        finally:
            release.set()
            controller.close()
            controller.join(2)

    def test_close_cancels_pending_switch(self):
        entered = threading.Event()
        calls = []
        def translate(argv, stop_event, **kwargs):
            calls.append(argv[-1])
            entered.set()
            stop_event.wait(2)
            return 0
        controller = TranslationController(translate, [], Mock(), Mock())
        try:
            controller.select('chrome')
            self.assertTrue(entered.wait(1))
            controller.select('system')
            controller.close()
            controller.join(2)
            controller.poll()
            self.assertEqual(calls, ['chrome'])
        finally:
            controller.close()
            controller.join(2)

    def test_fatal_shutdown_prevents_new_capture(self):
        controller = TranslationController(Mock(return_value=2), [], Mock(), Mock())
        controller.select('chrome')
        controller.join(2)
        controller.select('system')
        self.assertTrue(controller.blocked)
        self.assertEqual(controller.translate.call_count, 1)
        self.assertFalse(controller.select('microphone'))

    def test_source_override_retains_hotwords_removes_pid_for_devices(self):
        translate = Mock(return_value=0)
        controller = TranslationController(translate, ['--source=chrome', '--pid', '123', '--hotwords', 'custom.json'], Mock(), Mock())
        controller.select('microphone')
        controller.join(2)
        self.assertEqual(translate.call_args.args[0], ['--hotwords', 'custom.json', '--target-language', 'zh', '--speed', 'normal', '--source', 'microphone'])


class TrayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_menu_is_exclusive_and_uses_application_icon(self):
        icon = QIcon(str(Path(__file__).resolve().parents[1] / 'assets/subtitle-avatar.ico'))
        tray = SubtitleTray(icon)
        try:
            selected = []
            tray.source_selected.connect(selected.append)
            self.assertEqual(tray.icon().cacheKey(), icon.cacheKey())
            self.assertEqual(tray.source_menu.title(), '声源选择')
            self.assertEqual([a.text() for a in tray.actions.values()], ['谷歌浏览器', '系统声音', '系统麦克风'])
            for key in SOURCE_REGISTRY:
                tray.actions[key].trigger()
                self.assertEqual(selected[-1], key)
                self.assertEqual([k for k, a in tray.actions.items() if a.isChecked()], [key])
            exited = []
            tray.exit_requested.connect(lambda: exited.append(True))
            tray.menu.actions()[-1].trigger()
            self.assertEqual(exited, [True])
        finally:
            tray.shutdown()


class WindowIntegrationTests(unittest.TestCase):
    def test_tray_switches_live_window_and_exit_stops_worker(self):
        from PySide6.QtCore import QTimer
        from ui.launcher import run
        app = QApplication.instance() or QApplication([])
        trays, calls, active, failures = [], [], [], []
        def make_tray(*args, **kwargs):
            tray = SubtitleTray(*args, **kwargs)
            trays.append(tray)
            return tray
        def translate(argv, stop_event, on_event, on_state):
            if active:
                failures.append('overlapping workers')
            key = argv[-1]
            active.append(key)
            calls.append(key)
            on_state('connected', '测试会话')
            try:
                if not stop_event.wait(3):
                    failures.append('worker failed to stop')
            finally:
                active.remove(key)
            return 0
        timer = QTimer()
        stage = [0]
        def advance():
            if not trays:
                return
            tray = trays[0]
            if stage[0] == 0 and calls == ['chrome']:
                stage[0] = 1
                tray.actions['system'].trigger()
            elif stage[0] == 1 and calls == ['chrome', 'system']:
                stage[0] = 2
                tray.actions['microphone'].trigger()
            elif stage[0] == 2 and calls == ['chrome', 'system', 'microphone']:
                stage[0] = 3
                tray.menu.actions()[-1].trigger()
        timer.timeout.connect(advance)
        timer.start(10)
        watchdog = QTimer()
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(app.quit)
        watchdog.start(4000)
        try:
            with patch('tools.chrome_translate.main', translate), \
                 patch('ui.tray.SubtitleTray', side_effect=make_tray), \
                 patch('app.preferences.read_window', return_value={}), \
                 patch('app.preferences.save_window'):
                self.assertEqual(run([]), 0)
            self.assertEqual(stage[0], 3)
            self.assertEqual(calls, ['chrome', 'system', 'microphone'])
            self.assertFalse(active)
            self.assertFalse(failures)
        finally:
            timer.stop()
            watchdog.stop()


class TrayLockTests(unittest.TestCase):
    def test_tray_lock_tracks_window_and_recovers_after_native_failure(self):
        from PySide6.QtCore import QTimer
        from ui.launcher import run
        app = QApplication.instance() or QApplication([])
        trays, failures = [], []
        def make_tray(*args, **kwargs):
            tray = SubtitleTray(*args, **kwargs)
            trays.append(tray)
            return tray
        def exercise():
            try:
                tray = trays[0]
                window = tray.parent()
                self.assertFalse(tray.lock_action.isEnabled())
                window.lock_available = True
                window.shortcut_prefix = 'Ctrl+Alt+Shift'
                tray.menu.aboutToShow.emit()
                self.assertIn('Ctrl+Alt+Shift+L', tray.lock_action.text())
                tray.lock_action.trigger()
                self.assertTrue(window.locked)
                self.assertTrue(tray.lock_action.isChecked())
                native.assert_called_with(int(window.winId()), True)
                tray.lock_action.trigger()
                self.assertFalse(window.locked)
                self.assertFalse(tray.lock_action.isChecked())
                native.assert_called_with(int(window.winId()), False)
                # Changes through the existing window/shortcut path are reflected on menu opening.
                window.toggle_lock()
                tray.menu.aboutToShow.emit()
                self.assertTrue(tray.lock_action.isChecked())
                window.toggle_lock()
                native.side_effect = OSError('simulated failure')
                tray.lock_action.trigger()
                self.assertFalse(window.locked)
                self.assertFalse(tray.lock_action.isChecked())
                window.stopping = True
                tray.menu.aboutToShow.emit()
                self.assertFalse(tray.lock_action.isEnabled())
            except Exception as exc:
                failures.append(exc)
            finally:
                app.quit()
        QTimer.singleShot(100, exercise)
        with patch('ui.tray.SubtitleTray', side_effect=make_tray), patch('ui.hotkeys.click_through') as native, patch('app.preferences.read_window', return_value={}), patch('app.preferences.save_window'):
            self.assertEqual(run([], demo=True), 0)
        if failures:
            raise failures[0]
