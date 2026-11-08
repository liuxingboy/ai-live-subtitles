import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import threading
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from app.translation_controller import TranslationController
from ui.overlay import Overlay


class PauseTests(unittest.TestCase):
    def test_pause_stops_worker_suppresses_late_events_and_defers_setting_changes(self):
        started = threading.Event()
        events, states, calls = [], [], []
        def translate(argv, stop_event, on_event, on_state):
            calls.append(argv)
            started.set()
            stop_event.wait(2)
            on_event({'type': 'late'})
            on_state('connected', 'late')
            return 0
        controller = TranslationController(translate, [], events.append, lambda *args: states.append(args))
        try:
            controller.select('system')
            self.assertTrue(started.wait(1))
            self.assertTrue(controller.set_suspended(True))
            controller.join(1)
            self.assertFalse(controller.thread.is_alive())
            self.assertNotIn({'type': 'late'}, events)
            self.assertEqual(states[-1][0], 'paused')
            controller.select('microphone')
            controller.select_speed('fast')
            controller.select_language('ja')
            controller.poll()
            self.assertEqual(len(calls), 1)
            started.clear()
            self.assertTrue(controller.set_suspended(False))
            self.assertTrue(started.wait(1))
            self.assertEqual(len(calls), 2)
            self.assertIn('microphone', calls[-1])
            self.assertIn('ja', calls[-1])
            self.assertIn('fast', calls[-1])
        finally:
            controller.close()
            controller.join(2)

    def test_quick_restore_waits_for_old_worker_and_close_prevents_resume(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def translate(argv, **kwargs):
            calls.append(argv)
            entered.set()
            release.wait(2)
            return 0
        controller = TranslationController(translate, [], Mock(), Mock())
        try:
            controller.select('system')
            self.assertTrue(entered.wait(1))
            controller.set_suspended(True)
            controller.set_suspended(False)
            controller.poll()
            self.assertEqual(len(calls), 1)
            controller.close()
            release.set()
            controller.join(1)
            self.assertFalse(controller.set_suspended(False))
            controller.poll()
            self.assertEqual(len(calls), 1)
        finally:
            release.set()
            controller.close()
            controller.join(2)


class MinimizeUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_button_emits_only_real_minimize_changes_and_preserves_geometry(self):
        window = Overlay()
        window.running = False
        changes = []
        window.minimized_changed.connect(changes.append)
        window.show()
        self.app.processEvents()
        expected = window.preferences()
        window.minimize_button.click()
        self.app.processEvents()
        self.assertTrue(window.isMinimized())
        self.assertEqual(window.preferences(), expected)
        window.showNormal()
        self.app.processEvents()
        self.assertEqual(changes, [True, False])
        window.hide()
        window.show()
        self.assertEqual(changes, [True, False])
        window.close()
        window.deleteLater()

    def test_launcher_pauses_and_resumes_without_shutting_down_screenshots(self):
        from ui.launcher import run
        from app.screenshot_controller import ScreenshotController
        calls, observations, screenshots = [], [], []
        def translate(argv, stop_event, **kwargs):
            calls.append(stop_event)
            stop_event.wait(3)
            return 0
        def create_screenshots(*args):
            value = ScreenshotController(*args)
            screenshots.append(value)
            return value
        def window():
            return next(w for w in self.app.topLevelWidgets() if isinstance(w, Overlay) and w.isVisible())
        QTimer.singleShot(150, lambda: window().minimize_button.click())
        def inspect_paused():
            observations.append((len(calls), calls[0].is_set(), screenshots[0].closed))
            window().showNormal()
        QTimer.singleShot(450, inspect_paused)
        def finish():
            observations.append((len(calls), calls[-1].is_set(), screenshots[0].closed))
            window().close()
        QTimer.singleShot(750, finish)
        with patch('tools.chrome_translate.main', side_effect=translate), \
                patch('app.screenshot_controller.ScreenshotController', side_effect=create_screenshots), \
                patch('app.preferences.read_window', return_value={}), patch('app.preferences.save_window'):
            self.assertEqual(run(['--source', 'system']), 0)
        self.assertEqual(observations, [(1, True, False), (2, False, False)])

    def test_screenshot_does_not_restore_minimized_subtitle_window(self):
        from app.screenshot_controller import ScreenshotController
        from ui.tray import SubtitleTray
        from PySide6.QtGui import QIcon
        window, tray = Overlay(), SubtitleTray(QIcon())
        window.running = False
        controller = ScreenshotController(self.app, tray, window, lambda: 'zh')
        try:
            window.showMinimized()
            self.app.processEvents()
            controller.begin('region')
            self.assertNotIn(window, controller.hidden)
            controller.finish_capture()
            self.assertTrue(window.isMinimized())
            self.assertFalse(controller.closed)
        finally:
            controller.shutdown()
            window.close()
            tray.shutdown()
