import base64
from types import SimpleNamespace
import threading
import unittest

from audio.live_source import PCMQueue
from tools.chrome_translate import stream_audio


class StreamingTests(unittest.TestCase):
    def test_packets_preserve_pcm_and_flush_tail(self):
        queue = PCMQueue()
        audio = bytes(range(256)) * 31
        for start in range(0, len(audio), 320):
            queue.put(audio[start:start + 320])
        queue.flush()
        blocks = [queue.get(0), queue.get(0), queue.get(0)]
        self.assertEqual([len(b) for b in blocks], [3200, 3200, 1536])
        self.assertEqual(b''.join(blocks), audio)
        self.assertIsNone(queue.get(0))

    def test_queue_is_bounded(self):
        queue = PCMQueue(max_blocks=2)
        queue.put(bytes(6400))
        with self.assertRaisesRegex(RuntimeError, '队列'):
            queue.put(bytes(3200))
        self.assertEqual(queue.queue.qsize(), 2)

    def test_shutdown_drains_audio_before_return(self):
        queue = PCMQueue()
        queue.put(bytes(3200))
        queue.put(b'\x01\x02')
        queue.flush()
        source = SimpleNamespace(audio=queue, stop=threading.Event(), done=threading.Event(),
                                 error=None, thread=SimpleNamespace(start=lambda: None))
        source.done.set()
        sent = []
        session = SimpleNamespace(failed=threading.Event(), finished=threading.Event(),
                                  heartbeat=lambda: None,
                                  send=lambda kind, **fields: sent.append((kind, fields)))
        stop = threading.Event()
        stop.set()
        report = {}
        stream_audio(session, source, stop, report)
        self.assertTrue(source.stop.is_set())
        self.assertEqual(len(sent), 2)
        self.assertEqual(base64.b64decode(sent[-1][1]['audio']), b'\x01\x02')
        self.assertEqual(report['uploaded_seconds'], round(3202 / 32000, 3))

    def test_network_failure_stops_sender(self):
        source = SimpleNamespace(thread=SimpleNamespace(start=lambda: None))
        session = SimpleNamespace(failed=threading.Event(), finished=threading.Event())
        session.failed.set()
        def fail():
            raise RuntimeError('connection failed')
        session.raise_failure = fail
        with self.assertRaises(RuntimeError):
            stream_audio(session, source, threading.Event(), {})


if __name__ == '__main__':
    unittest.main()
