"""Bounded handoff from the WASAPI thread to the WebSocket sender."""
from queue import Queue, Empty, Full
import threading


class PCMQueue:
    """100 ms PCM16 blocks; fail visibly instead of accumulating latency."""
    block_bytes = 3200

    def __init__(self, max_blocks=20, drop_oldest=False):
        self.queue = Queue(maxsize=max_blocks)
        self.pending = bytearray()
        self.total_bytes = 0
        self.high_water = 0
        self.drop_oldest = drop_oldest
        self.dropped_bytes = 0

    def put(self, data):
        if len(data) % 2:
            raise ValueError("PCM 数据未对齐。")
        self.total_bytes += len(data)
        self.pending.extend(data)
        while len(self.pending) >= self.block_bytes:
            self._enqueue(bytes(self.pending[:self.block_bytes]))
            del self.pending[:self.block_bytes]

    def _enqueue(self, block):
        try:
            self.queue.put_nowait(block)
        except Full:
            if self.drop_oldest:
                try:
                    self.dropped_bytes += len(self.queue.get_nowait())
                except Empty:
                    pass
                self.queue.put_nowait(block)
                return
            raise RuntimeError("音频发送队列超过 2 秒，网络发送跟不上；已停止，避免字幕延迟不断增加。") from None
        self.high_water = max(self.high_water, self.queue.qsize())

    def flush(self):
        if self.pending:
            self._enqueue(bytes(self.pending))
            self.pending.clear()

    def get(self, timeout=0.1):
        try:
            return self.queue.get(timeout=timeout)
        except Empty:
            return None


class ChromeAudioSource:
    def __init__(self, target, seconds=None, audio_queue=None):
        self.target = target
        self.seconds = seconds
        self.audio = audio_queue if audio_queue is not None else PCMQueue()
        self.stop = threading.Event()
        self.done = threading.Event()
        self.error = None
        self.result = None
        self.thread = threading.Thread(target=self.run, name="chrome-audio", daemon=True)

    def run(self):
        from audio.chrome_detector import still_running
        from audio.wasapi_capture import capture_process
        try:
            self.result = capture_process(self.target.pid, self.seconds, self.stop,
                                          alive=lambda: still_running(self.target),
                                          on_audio=self.audio.put, monitor_output=True)
            self.audio.flush()
            if self.result.discontinuities:
                raise RuntimeError(f"捕获出现 {self.result.discontinuities} 次不连续，稳定性验证未通过。")
        except Exception as exc:
            self.error = exc
        finally:
            self.done.set()
