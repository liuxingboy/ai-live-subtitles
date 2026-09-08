import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from unittest.mock import patch
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication
from ui.overlay import Overlay


class OverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_long_paragraph_is_bounded_and_text_is_plain(self):
        window = Overlay()
        window.resize(650, 320)
        window.show_subtitles('a long source sentence ' * 100, '<b>这不是 HTML</b> ' * 100)
        self.assertLessEqual(len(window.source.text().splitlines()), 3)
        self.assertLessEqual(len(window.translation.text().splitlines()), 3)
        self.assertEqual(window.translation.textFormat(), Qt.TextFormat.PlainText)
        window.running = False
        window.close()

    def test_close_requests_stop_before_destroying_window(self):
        window = Overlay()
        requests = []
        window.stop_requested.connect(lambda: requests.append(True))
        window.show()
        self.app.processEvents()
        window.close()
        self.assertEqual(requests, [True])
        self.assertTrue(window.isVisible())
        self.assertFalse(window.close_button.isEnabled())
        window.running = False
        window.close()
        self.assertFalse(window.isVisible())

    def test_default_window_displays_partial_before_any_final(self):
        from ui.launcher import run
        observed = []
        stopped = []
        def fake_translate(argv, stop_event, on_event, on_state):
            on_state('connected', '已连接')
            on_event({'type': 'conversation.item.input_audio_transcription.text', 'item_id': 's', 'text': 'Hello', 'stash': ' world.'})
            on_event({'type': 'conversation.item.created', 'item': {'id': 't', 'role': 'assistant'}, 'previous_item_id': 's'})
            on_event({'type': 'response.text.text', 'item_id': 't', 'text': '你好，', 'stash': '世界。'})
            stopped.append(stop_event.wait(3))
            return 0
        def inspect_and_close():
            for widget in self.app.topLevelWidgets():
                if isinstance(widget, Overlay) and widget.isVisible():
                    observed.append((widget.source.text(), widget.translation.text()))
                    widget.close()
        QTimer.singleShot(400, inspect_and_close)
        with patch('tools.chrome_translate.main', side_effect=fake_translate), patch('app.preferences.read_window', return_value={}), patch('app.preferences.save_window'):
            self.assertEqual(run([]), 0)
        self.assertEqual(observed, [('Hello world.', '你好，世界。')])
        self.assertEqual(stopped, [True])


if __name__ == '__main__':
    unittest.main()
