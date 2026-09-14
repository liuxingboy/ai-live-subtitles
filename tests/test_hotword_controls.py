import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from app.preferences import DEFAULT_HOTWORDS, discover_hotwords, load_hotwords
from app.translation_controller import TranslationController
from tools.api_debug import configure_console, session_config
from ui.tray import SubtitleTray


def setUpModule():
    configure_console()


class HotwordTests(unittest.TestCase):
    def test_discovery_includes_new_json_files_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('python.json', 'cs2.json', 'biology.json', 'notes.txt'):
                (root/name).write_text('{}', encoding='utf-8')
            (root/'directory.json').mkdir()
            choices = discover_hotwords(root)
            self.assertEqual(list(choices.values()), ['Python 教学', 'CS2 电竞', 'biology'])
            self.assertEqual(discover_hotwords(root/'missing'), {})

    def test_default_off_and_explicit_cli_enable(self):
        from tools.chrome_translate import main
        for argv, expected in (([], False), (['--hotwords', str(DEFAULT_HOTWORDS)], True), (['--hotwords', str(DEFAULT_HOTWORDS), '--no-hotwords'], False)):
            with self.subTest(argv=argv), patch('tools.chrome_translate.connection_config', side_effect=ValueError('test ends before cloud')), patch('app.preferences.load_hotwords', return_value={}) as loader, patch('pathlib.Path.write_text'):
                self.assertEqual(main(argv), 1)
                self.assertEqual(loader.call_args.args[0], DEFAULT_HOTWORDS if expected else None)
            controller = TranslationController(Mock(return_value=0), argv, Mock(), Mock())
            self.assertEqual(controller.hotwords_enabled, expected)

    def test_invalid_library_preserves_active_session_and_state(self):
        entered = threading.Event()
        def translate(argv, stop_event, **kwargs):
            entered.set();stop_event.wait(2);return 0
        controller = TranslationController(translate, [], Mock(), Mock())
        try:
            controller.select('system')
            self.assertTrue(entered.wait(1))
            with tempfile.TemporaryDirectory() as folder:
                for text in ('broken JSON', '[]', '{"term": 5}'):
                    path = Path(folder)/'bad.json';path.write_text(text, encoding='utf-8')
                    with self.assertRaises(ValueError):
                        controller.set_hotwords(enabled=True, path=path)
                    self.assertFalse(controller.hotwords_enabled)
                    self.assertEqual(controller.hotwords_path, DEFAULT_HOTWORDS)
                    self.assertFalse(controller.stop.is_set())
            with self.assertRaises(OSError):
                controller.set_hotwords(enabled=True, path=Path(folder)/'missing.json')
            self.assertFalse(controller.stop.is_set())
        finally:
            controller.close();controller.join(2)

    def test_tray_flow_retains_library_on_disable_and_language_change(self):
        from ui.launcher import run
        app = QApplication.instance() or QApplication([])
        trays, calls, active, failures = [], [], [], []
        cs2 = str((DEFAULT_HOTWORDS.parent/'cs2.json').resolve())
        def make_tray(*args, **kwargs):
            tray = SubtitleTray(*args, **kwargs);trays.append(tray);return tray
        def translate(argv, stop_event, **kwargs):
            language = argv[argv.index('--target-language')+1]
            path = argv[argv.index('--hotwords')+1] if '--hotwords' in argv else None
            if active: failures.append('overlap')
            config = session_config(load_hotwords(path), target_language=language)
            selection = (path, language, 'corpus' in config['translation'])
            active.append(selection);calls.append(selection)
            if not stop_event.wait(3):failures.append('stop timeout')
            active.remove(selection);return 0
        stage = [0]
        def advance():
            if not trays or len(calls) != stage[0]+1:return
            tray = trays[0]
            try:
                if stage[0] == 0:
                    self.assertFalse(tray.hotword_enable_action.isChecked())
                    tray.hotword_actions[cs2].trigger()
                    self.assertEqual(len(calls), 1)
                    self.assertTrue(tray.hotword_actions[cs2].isChecked())
                    tray.hotword_enable_action.trigger()
                elif stage[0] == 1:
                    tray.hotword_enable_action.trigger()
                    self.assertTrue(tray.hotword_actions[cs2].isChecked())
                elif stage[0] == 2:tray.hotword_enable_action.trigger()
                elif stage[0] == 3:
                    tray.language_actions['ja'].trigger()
                    self.assertFalse(tray.hotword_enable_action.isEnabled())
                    self.assertTrue(tray.hotword_enable_action.isChecked())
                    self.assertTrue(tray.hotword_note.isVisible())
                elif stage[0] == 4:
                    tray.language_actions['zh'].trigger()
                    self.assertTrue(tray.hotword_enable_action.isEnabled())
                elif stage[0] == 5:tray.menu.actions()[-1].trigger()
                stage[0] += 1
            except Exception as exc:
                failures.append(exc);app.quit()
        timer=QTimer();timer.timeout.connect(advance);timer.start(10)
        watchdog=QTimer();watchdog.setSingleShot(True);watchdog.timeout.connect(app.quit);watchdog.start(5000)
        try:
            with patch('tools.chrome_translate.main', translate), patch('ui.tray.SubtitleTray', side_effect=make_tray), patch('app.preferences.read_window', return_value={}), patch('app.preferences.save_window'):
                self.assertEqual(run(['--source', 'system']), 0)
            self.assertEqual(calls, [(None,'zh',False), (cs2,'zh',True), (None,'zh',False), (cs2,'zh',True), (cs2,'ja',False), (cs2,'zh',True)])
            self.assertEqual(stage[0], 6)
            self.assertFalse(active)
            self.assertFalse(failures)
        finally:
            timer.stop();watchdog.stop()
