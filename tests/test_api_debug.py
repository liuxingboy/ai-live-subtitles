import json
import threading
import unittest

from tools.api_debug import Session, configure_console, connection_config, safe_error, session_config, subtitle_line

configure_console()


class ProtocolTests(unittest.TestCase):
    def test_configuration_and_host_override(self):
        key, url = connection_config({"DASHSCOPE_API_KEY": "test-key", "DASHSCOPE_WORKSPACE_ID": "workspace"})
        self.assertEqual(key, "test-key")
        self.assertIn("wss://workspace.cn-beijing.maas.aliyuncs.com/", url)
        _, url = connection_config({"DASHSCOPE_API_KEY": key, "DASHSCOPE_WS_HOST": "example.com"})
        self.assertTrue(url.startswith("wss://example.com/"))
        for host in ("https://example.com", "example.com/path", "user@example.com"):
            with self.assertRaises(ValueError):
                connection_config({"DASHSCOPE_API_KEY": key, "DASHSCOPE_WS_HOST": host})
        with self.assertRaises(ValueError):
            connection_config({})

    def test_text_only_with_asr_and_server_vad(self):
        config = session_config()
        self.assertEqual(config["modalities"], ["text"])
        self.assertEqual(config["input_audio_transcription"]["language"], "en")
        self.assertEqual(config["translation"]["language"], "zh")
        self.assertEqual(config["turn_detection"]["type"], "server_vad")

    def test_all_four_subtitle_events(self):
        cases = [
            ({"type": "conversation.item.input_audio_transcription.text", "text": "Hello", "stash": " world"}, "[EN partial] Hello world"),
            ({"type": "conversation.item.input_audio_transcription.completed", "transcript": "Hello."}, "[EN] Hello."),
            ({"type": "response.text.text", "text": "你好", "stash": "世界"}, "[ZH partial] 你好世界"),
            ({"type": "response.text.done", "text": "你好。"}, "[ZH] 你好。"),
        ]
        for event, expected in cases:
            self.assertEqual(subtitle_line(event), expected)
        self.assertIsNone(subtitle_line({"type": "session.created"}))

    def test_secrets_are_redacted(self):
        self.assertEqual(safe_error("secret sk-example", "secret"), "<redacted> <redacted>")

    def test_finish_waits_for_ack(self):
        class FakeSocket:
            sent = []

            def send(self, value):
                self.sent.append(json.loads(value))

        ws = FakeSocket()
        session = Session(ws, "")
        timer = threading.Timer(0.05, session.finished.set)
        timer.start()
        try:
            session.finish(timeout=1)
        finally:
            timer.join()
        self.assertEqual(ws.sent[0]["type"], "session.finish")
        self.assertTrue(session.finished.is_set())

    def test_finish_timeout_is_not_success(self):
        class FakeSocket:
            def send(self, value):
                pass

        with self.assertRaises(TimeoutError):
            Session(FakeSocket(), "").finish(timeout=0.01)


if __name__ == "__main__":
    unittest.main()
