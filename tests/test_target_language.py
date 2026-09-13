import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from unittest.mock import patch
from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from app.preferences import TARGET_LANGUAGES
from tools.api_debug import configure_console, session_config, subtitle_line
from ui.tray import SubtitleTray


def setUpModule():
    configure_console()


class LanguageTests(unittest.TestCase):
    def test_all_targets_use_matching_language_and_safe_corpus(self):
        words = {'variable': '变量'}
        self.assertEqual(len(TARGET_LANGUAGES), 18)
        for target in TARGET_LANGUAGES:
            with self.subTest(target=target):
                config = session_config(words, speed='fast', target_language=target)
                self.assertEqual(config['translation']['language'], target)
                self.assertEqual(config['turn_detection']['silence_duration_ms'], 300)
                self.assertEqual(config['modalities'], ['text'])
                if target == 'zh':
                    self.assertEqual(config['translation']['corpus']['phrases'], words)
                else:
                    self.assertNotIn('corpus', config['translation'])
        self.assertEqual(session_config(words)['translation']['corpus']['phrases'], words)
        with self.assertRaises(ValueError):
            session_config(target_language='invalid')

    def test_translated_console_lines_use_selected_language(self):
        for target in TARGET_LANGUAGES:
            self.assertEqual(subtitle_line({'type': 'response.text.done', 'text': 'example'}, target), f'[{target.upper()}] example')
            self.assertEqual(subtitle_line({'type': 'response.text.text', 'text': 'a', 'stash': 'b'}, target), f'[{target.upper()} partial] ab')
        self.assertEqual(subtitle_line({'type': 'conversation.item.input_audio_transcription.completed', 'transcript': 'hello'}, 'ja'), '[EN] hello')

    def test_language_menu_is_exclusive_and_independent(self):
        app = QApplication.instance() or QApplication([])
        tray = SubtitleTray(QIcon())
        try:
            changes = []
            tray.language_selected.connect(changes.append)
            self.assertEqual(tray.language_menu.title(), '目标语言')
            self.assertTrue(tray.language_actions['zh'].isChecked())
            for key in TARGET_LANGUAGES:
                tray.language_actions[key].trigger()
                self.assertEqual(changes[-1], key)
                self.assertEqual([k for k,a in tray.language_actions.items() if a.isChecked()], [key])
                self.assertTrue(tray.actions['chrome'].isChecked())
                self.assertTrue(tray.speed_actions['normal'].isChecked())
        finally:
            tray.shutdown()

    def test_window_preserves_target_across_speed_source_and_switch_back(self):
        from ui.launcher import run
        app = QApplication.instance() or QApplication([])
        trays, calls, active, failures = [], [], [], []
        def make_tray(*args, **kwargs):
            tray = SubtitleTray(*args, **kwargs);trays.append(tray);return tray
        def translate(argv, stop_event, **kwargs):
            selection = tuple(argv[argv.index(flag)+1] for flag in ('--source', '--speed', '--target-language'))
            if active: failures.append('overlap')
            active.append(selection);calls.append(selection)
            if not stop_event.wait(3): failures.append('stop timeout')
            active.remove(selection)
            return 0
        stage = [0]
        def advance():
            if not trays or len(calls) != stage[0]+1: return
            tray = trays[0]
            if stage[0] == 0: tray.language_actions['ja'].trigger()
            elif stage[0] == 1: tray.speed_actions['fast'].trigger()
            elif stage[0] == 2: tray.actions['microphone'].trigger()
            elif stage[0] == 3: tray.language_actions['zh'].trigger()
            elif stage[0] == 4: tray.menu.actions()[-1].trigger()
            stage[0] += 1
        timer=QTimer();timer.timeout.connect(advance);timer.start(10)
        watchdog=QTimer();watchdog.setSingleShot(True);watchdog.timeout.connect(app.quit);watchdog.start(4000)
        try:
            with patch('tools.chrome_translate.main', translate), patch('ui.tray.SubtitleTray', side_effect=make_tray), patch('app.preferences.read_window', return_value={}), patch('app.preferences.save_window'):
                self.assertEqual(run(['--source', 'system', '--target-language=en']), 0)
            self.assertEqual(calls, [('system','normal','en'), ('system','normal','ja'), ('system','fast','ja'), ('microphone','fast','ja'), ('microphone','fast','zh')])
            self.assertEqual(stage[0], 5)
            self.assertFalse(active)
            self.assertFalse(failures)
        finally:
            timer.stop();watchdog.stop()
