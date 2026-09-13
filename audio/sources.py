"""Audio source registry shared by CLI, tray and streaming sessions.

To add a source, register its label and resolver. A resolved source supplies
create(seconds, audio_queue) and alive(); streaming code stays source-agnostic.
"""
from dataclasses import dataclass
import threading
from audio.live_source import ChromeAudioSource, PCMQueue


class SourceShutdownError(RuntimeError):
    """A producer is still alive; starting another capture would be unsafe."""


class EndpointAudioSource:
    def __init__(self, kind, seconds=None, audio_queue=None):
        self.kind = kind
        self.seconds = seconds
        self.audio = audio_queue if audio_queue is not None else PCMQueue()
        self.stop = threading.Event()
        self.done = threading.Event()
        self.error = self.result = None
        self.thread = threading.Thread(target=self.run, name=f'{kind}-audio', daemon=True)

    def run(self):
        try:
            from audio.endpoint_capture import capture_endpoint
            self.result = capture_endpoint(self.kind, self.seconds, self.stop, self.audio.put)
            self.audio.flush()
        except Exception as exc:
            self.error = exc
        finally:
            self.done.set()


@dataclass(frozen=True)
class ResolvedSource:
    key: str
    label: str
    factory: object
    alive: object
    pid: int | None = None

    def create(self, seconds=None, audio_queue=None):
        return self.factory(seconds, audio_queue)


def _chrome(pid):
    from audio.chrome_detector import find_chrome_processes, choose_chrome, still_running
    target = choose_chrome(find_chrome_processes(), pid)
    return ResolvedSource('chrome', '谷歌浏览器',
                          lambda seconds, queue: ChromeAudioSource(target, seconds, queue),
                          lambda: still_running(target), target.pid)


def _endpoint(key, label):
    def resolve(pid):
        if pid is not None:
            raise ValueError('--pid 仅适用于谷歌浏览器声源')
        return ResolvedSource(key, label,
                              lambda seconds, queue: EndpointAudioSource(key, seconds, queue),
                              lambda: True)
    return resolve


SOURCE_REGISTRY = {
    'chrome': ('谷歌浏览器', _chrome),
    'system': ('系统声音', _endpoint('system', '系统声音')),
    'microphone': ('系统麦克风', _endpoint('microphone', '系统麦克风')),
}


def resolve_source(key, pid=None):
    if key not in SOURCE_REGISTRY:
        raise ValueError(f'未知声源：{key}')
    return SOURCE_REGISTRY[key][1](pid)
