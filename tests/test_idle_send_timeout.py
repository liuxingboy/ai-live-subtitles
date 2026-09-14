import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import websocket
from audio.live_source import PCMQueue
from tools.api_debug import configure_console
from tools.idle_translate import run_idle_attempt
from tools.reconnect import run_with_reconnect


def setUpModule():
    configure_console()


class IdleTimeoutTests(unittest.TestCase):
    def exercise(self, failure):
        sessions, sources = [], []
        def create(*args, **kwargs):
            queue=PCMQueue(200, drop_oldest=True)
            queue.put(b'\xd0\x07'*6400)
            source=SimpleNamespace(audio=queue, stop=threading.Event(), done=threading.Event(), error=None, result=None, thread=Mock())
            source.done.set();source.thread.is_alive.return_value=False
            sources.append(source)
            return source
        class Session:
            def __init__(self,*args,**kwargs):
                self.failed=threading.Event();self.finished=threading.Event();self.ready=threading.Event();self.closing=threading.Event()
                self.reader=Mock();self.english_finals=self.chinese_finals=0;self.close_code=None
                self.finish_calls=0;sessions.append(self)
            def wait(self,*args):return True
            def heartbeat(self):pass
            def send(self,kind,**kwargs):
                if len(sessions)==1 and kind=='input_audio_buffer.append':
                    if failure=='send':raise websocket.WebSocketTimeoutException('The write operation timed out')
                    if failure=='capture':sources[-1].error=RuntimeError('capture failed')
            def finish(self):
                self.finish_calls+=1
                if len(sessions)==1:raise websocket.WebSocketTimeoutException('cleanup write timed out')
                self.finished.set()
        target=SimpleNamespace(label='测试声源',create=create)
        args=SimpleNamespace(silence_seconds=30,silence_db=-55,partial=False,on_state=None,on_event=None,hotwords={},speed='fast',target_language='zh')
        stop=Mock();stop.is_set.return_value=False;stop.wait.return_value=False
        report={}
        with patch('tools.idle_translate.Session',Session),patch('tools.idle_translate.websocket.create_connection') as connect:
            operation=lambda remaining:run_idle_attempt(target,'fake','wss://example.invalid',args,remaining,stop,report)
            if failure=='capture':
                with self.assertRaisesRegex(RuntimeError,'capture failed'):
                    run_with_reconnect(operation,stop,report)
                self.assertEqual(len(sessions),1)
                self.assertEqual(sessions[0].finish_calls,0)
                self.assertFalse(report['normal_finish'])
            else:
                run_with_reconnect(operation,stop,report)
                self.assertEqual(len(sessions),2)
                self.assertEqual(sessions[0].finish_calls,0 if failure=='send' else 1)
                self.assertEqual(sessions[1].finish_calls,1)
                self.assertEqual(report['reconnect_attempts'],1)
                self.assertTrue(report['normal_finish'])
            self.assertEqual(connect.return_value.close.call_count,len(sessions))
        for source in sources:
            self.assertTrue(source.stop.is_set())
            source.thread.join.assert_called_once()
        for session in sessions:
            self.assertTrue(session.closing.is_set())

    def test_send_timeout_does_not_get_masked_by_finish(self):
        self.exercise('send')

    def test_normal_finish_write_timeout_is_retryable(self):
        self.exercise('finish')

    def test_capture_failure_is_preserved_without_retry(self):
        self.exercise('capture')
