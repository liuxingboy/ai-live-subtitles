from pathlib import Path
import struct
import tempfile
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest
from app.preferences import read_window, save_window, load_hotwords
from audio.live_source import PCMQueue
from audio.silence import ActivityDetector
from tools.idle_translate import run_idle_attempt
from tools.api_debug import session_config

TONE = struct.pack('<h', 2000) * 1600
QUIET = bytes(3200)


class PreferencesTests(unittest.TestCase):
    def test_window_settings_roundtrip_and_invalid(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'window.json'
            data = dict(x=-1400, y=500, width=900, source_font=20, translation_font=26)
            save_window(data, path)
            self.assertEqual(read_window(path), data)
            path.write_text('not json')
            self.assertEqual(read_window(path), {})

    def test_hotwords_are_in_each_session_config(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'words.json'
            path.write_text('{"retake": "回防"}', encoding='utf-8')
            words = load_hotwords(path)
            self.assertEqual(session_config(words)['translation']['corpus']['phrases'], {'retake': '回防'})
            self.assertNotIn('corpus', session_config()['translation'])
            path.write_text('{"bad": 1}')
            with self.assertRaises(ValueError):
                load_hotwords(path)

    def test_activity_threshold_and_quiet_reset(self):
        detector = ActivityDetector()
        for _ in range(300):
            detector.feed(QUIET)
        self.assertAlmostEqual(detector.quiet_seconds, 30)
        detector.feed(TONE)
        self.assertEqual(detector.quiet_seconds, 0)
        self.assertAlmostEqual(detector.active_seconds, .1)

    def test_bounded_buffer_keeps_recent_audio(self):
        queue = PCMQueue(2, drop_oldest=True)
        queue.put(QUIET)
        queue.put(TONE)
        queue.put(TONE)
        self.assertEqual(queue.dropped_bytes, 3200)
        self.assertEqual(queue.get(0), TONE)

    def test_pause_resume_keeps_onset_and_reapplies_hotwords(self):
        self._exercise([QUIET] * 4 + [TONE] * 3 + [QUIET] * 4 + [TONE] * 4, expected_connections=2)

    def test_all_silence_never_opens_cloud(self):
        self._exercise([QUIET] * 20, expected_connections=0)

    def test_fast_mode_survives_idle_resume(self):
        self._exercise([TONE] * 3 + [QUIET] * 4 + [TONE] * 4, expected_connections=2, speed='fast')

    def test_target_language_survives_idle_resume(self):
        self._exercise([TONE] * 3 + [QUIET] * 4 + [TONE] * 4, expected_connections=2, speed='fast', target_language='ja')

    def _exercise(self, blocks, expected_connections, speed='normal', target_language='zh'):
        queue = PCMQueue(200, drop_oldest=True)
        for block in blocks:
            queue.put(block)
        source = SimpleNamespace(audio=queue, thread=Mock(), stop=threading.Event(), done=threading.Event(), error=None, result=None)
        source.done.set()
        source.thread.is_alive.return_value = False
        sessions = []
        class FakeSession:
            def __init__(self, *args, **kwargs):
                self.ready = threading.Event()
                self.ready.set()
                self.failed = threading.Event()
                self.finished = threading.Event()
                self.closing = threading.Event()
                self.reader = Mock()
                self.english_finals = self.chinese_finals = 0
                self.close_code = None
                self.sent = []
                self.finish_calls = 0
                sessions.append(self)
            def wait(self, *args): return True
            def heartbeat(self): pass
            def send(self, kind, **fields): self.sent.append((kind, fields))
            def finish(self):
                self.finish_calls += 1
                self.finished.set()
        args = SimpleNamespace(silence_seconds=.3, silence_db=-55, on_state=None, on_event=None, partial=False, hotwords={'retake': '回防'}, speed=speed, target_language=target_language)
        report = {}
        target = SimpleNamespace(label='测试声源', create=Mock(return_value=source))
        with patch('tools.idle_translate.Session', FakeSession), patch('tools.idle_translate.websocket.create_connection') as connect:
            run_idle_attempt(target, 'fake-key', 'wss://example.invalid', args, 3, threading.Event(), report)
        self.assertEqual(connect.call_count, expected_connections)
        self.assertTrue(report['normal_finish'])
        for session in sessions:
            self.assertEqual(session.finish_calls, 1)
            expected_vad = {'type': 'server_vad', **({'silence_duration_ms': 300} if speed == 'fast' else {})}
            self.assertEqual(session.sent[0][1]['session']['turn_detection'], expected_vad)
            translation = session.sent[0][1]['session']['translation']
            self.assertEqual(translation['language'], target_language)
            if target_language == 'zh':
                self.assertEqual(translation['corpus']['phrases'], args.hotwords)
            else:
                self.assertNotIn('corpus', translation)
        if sessions:
            import base64
            uploaded = b''.join(base64.b64decode(fields['audio']) for session in sessions for kind, fields in session.sent if kind == 'input_audio_buffer.append')
            self.assertEqual(uploaded.count(TONE), blocks.count(TONE))


if __name__ == '__main__':
    unittest.main()
