import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from audio.live_source import PCMQueue
from app.translation_controller import TranslationController
from tools.api_debug import configure_console, session_config
from tools.chrome_translate import run_attempt
from tools.reconnect import ConnectionLost, run_with_reconnect
from ui.tray import SubtitleTray


def setUpModule():
    configure_console()


class SpeedTests(unittest.TestCase):
    def test_fast_only_changes_vad_and_normal_restores_default(self):
        normal = session_config({'Python': 'Python'})
        self.assertEqual(normal['turn_detection'], {'type': 'server_vad'})
        fast = session_config({'Python': 'Python'}, speed='fast')
        expected = {**normal, 'turn_detection': {'type': 'server_vad', 'silence_duration_ms': 300}}
        self.assertEqual(fast, expected)
        self.assertEqual(session_config({'Python': 'Python'}, speed='normal'), normal)
        with self.assertRaises(ValueError):
            session_config(speed='unknown')

    def test_reconnect_reapplies_fast_mode_and_hotwords(self):
        for target_language in ('zh', 'ja'):
            with self.subTest(target_language=target_language):
                self._exercise_reconnect(target_language)

    def _exercise_reconnect(self, target_language):
        configs = []
        class Session:
            def __init__(self, *args, **kwargs):
                self.ready = threading.Event()
                self.failed = threading.Event()
                self.finished = threading.Event()
                self.closing = threading.Event()
                self.reader = Mock()
                self.english_finals = self.chinese_finals = 0
                self.close_code = None
            def send(self, kind, **fields):
                if kind == 'session.update': configs.append(fields['session'])
            def wait(self, *args):
                if len(configs) == 1:
                    self.failed.set()
                    raise ConnectionLost('simulated disconnect')
                return True
            def finish(self, **kwargs): self.finished.set()
        source = SimpleNamespace(audio=PCMQueue(), stop=threading.Event(), done=threading.Event(), error=None, result=None, thread=Mock())
        source.done.set()
        source.thread.is_alive.return_value = False
        target = SimpleNamespace(label='系统声音', create=Mock(return_value=source))
        args = SimpleNamespace(hotwords={'Python': 'Python'}, speed='fast', partial=False, on_state=None, on_event=None, target_language=target_language)
        stop = Mock()
        stop.is_set.return_value = False
        stop.wait.return_value = False
        with patch('tools.chrome_translate.Session', Session), patch('websocket.create_connection'):
            run_with_reconnect(lambda remaining: run_attempt(target, 'fake', 'wss://example.invalid', args, remaining, stop, {}), stop, {})
        self.assertEqual(len(configs), 2)
        self.assertEqual(configs[0], configs[1])
        self.assertEqual(configs[1]['turn_detection']['silence_duration_ms'], 300)
        self.assertEqual(configs[1]['translation']['language'], target_language)
        if target_language == 'zh':
            self.assertEqual(configs[1]['translation']['corpus']['phrases'], args.hotwords)
        else:
            self.assertNotIn('corpus', configs[1]['translation'])

    def test_asr_recovery_budget_survives_main_error_redaction(self):
        from tools.chrome_translate import main
        from tools.reconnect import UnspecifiedASRError
        stop = Mock()
        stop.is_set.return_value = False
        stop.wait.return_value = False
        target = SimpleNamespace(key='system', label='系统声音', pid=None, alive=lambda: True)
        with patch('tools.chrome_translate.connection_config', return_value=('fake', 'wss://example.invalid')), patch('tools.chrome_translate.resolve_source', return_value=target), patch('tools.idle_translate.run_idle_attempt', side_effect=UnspecifiedASRError('fake')) as attempt, patch('pathlib.Path.write_text'):
            self.assertEqual(main(['--source', 'system', '--speed', 'fast', '--no-hotwords'], stop_event=stop), 1)
        self.assertEqual(attempt.call_count, 3)
        self.assertEqual(attempt.call_args.args[3].speed, 'fast')

    def test_rapid_mode_change_waits_for_old_worker_and_latest_choice_wins(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def translate(argv, stop_event, **kwargs):
            calls.append(argv)
            if len(calls) == 1:
                entered.set()
                stop_event.wait(2)
                release.wait(2)
            return 0
        controller = TranslationController(translate, ['--speed=fast', '--hotwords', 'custom.json'], Mock(), Mock())
        try:
            controller.select('system')
            self.assertTrue(entered.wait(1))
            controller.select_speed('fast')
            controller.select('microphone')
            controller.select_speed('normal')
            self.assertEqual(len(calls), 1)
            release.set()
            controller.join(2)
            controller.poll()
            controller.join(2)
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[-1], ['--hotwords', 'custom.json', '--target-language', 'zh', '--speed', 'normal', '--source', 'microphone'])
            controller.close()
            self.assertFalse(controller.select_speed('fast'))
        finally:
            release.set()
            controller.close()
            controller.join(2)

    def test_tray_modes_are_exclusive_independent_of_source(self):
        app = QApplication.instance() or QApplication([])
        tray = SubtitleTray(QIcon())
        try:
            selected = []
            tray.speed_selected.connect(selected.append)
            self.assertEqual(tray.speed_menu.title(), '速度与准度')
            self.assertEqual([a.text() for a in tray.speed_actions.values()], ['正常', '速度优先'])
            self.assertTrue(tray.speed_actions['normal'].isChecked())
            for key in ('fast', 'normal'):
                tray.speed_actions[key].trigger()
                self.assertEqual(selected[-1], key)
                self.assertEqual([k for k,a in tray.speed_actions.items() if a.isChecked()], [key])
                self.assertTrue(tray.actions['chrome'].isChecked())
        finally:
            tray.shutdown()

    def test_window_switches_mode_then_source_without_losing_mode(self):
        from ui.launcher import run
        app = QApplication.instance() or QApplication([])
        trays, calls, active, failures = [], [], [], []
        def make_tray(*args, **kwargs):
            tray = SubtitleTray(*args, **kwargs)
            trays.append(tray)
            return tray
        def translate(argv, stop_event, on_event, on_state):
            selection = (argv[argv.index('--source')+1], argv[argv.index('--speed')+1])
            if active: failures.append('overlap')
            active.append(selection)
            calls.append(selection)
            if not stop_event.wait(3): failures.append('stop timeout')
            active.remove(selection)
            return 0
        stage = [0]
        expected = [('system', 'normal'), ('system', 'fast'), ('microphone', 'fast'), ('microphone', 'normal')]
        def advance():
            if not trays or len(calls) != stage[0]+1: return
            tray = trays[0]
            if stage[0] == 0: tray.speed_actions['fast'].trigger()
            elif stage[0] == 1: tray.actions['microphone'].trigger()
            elif stage[0] == 2: tray.speed_actions['normal'].trigger()
            elif stage[0] == 3: tray.menu.actions()[-1].trigger()
            stage[0] += 1
        timer = QTimer();timer.timeout.connect(advance);timer.start(10)
        watchdog = QTimer();watchdog.setSingleShot(True);watchdog.timeout.connect(app.quit);watchdog.start(4000)
        try:
            with patch('tools.chrome_translate.main', translate), patch('ui.tray.SubtitleTray', side_effect=make_tray), patch('app.preferences.read_window', return_value={}), patch('app.preferences.save_window'):
                self.assertEqual(run(['--source', 'system']), 0)
            self.assertEqual(calls, expected)
            self.assertEqual(stage[0], 4)
            self.assertFalse(active)
            self.assertFalse(failures)
        finally:
            timer.stop();watchdog.stop()
