"""Serial worker handover. Qt calls select/poll/close on its main thread."""
import threading
from audio.sources import SOURCE_REGISTRY
from app.preferences import SPEED_MODES, TARGET_LANGUAGES


class TranslationController:
    def __init__(self, translate, argv, on_event, on_state, *, speed='normal', target_language='zh'):
        if speed not in SPEED_MODES:
            raise ValueError(f'未知速度模式：{speed}')
        if target_language not in TARGET_LANGUAGES:
            raise ValueError(f'不支持的目标语言：{target_language}')
        self.target_language = target_language
        self.speed = speed
        self.translate = translate
        self.argv = list(argv or [])
        self.on_event, self.on_state = on_event, on_state
        self.thread = None
        self.stop = threading.Event()
        self.done = threading.Event()
        self.result = 0
        self.selected = 'chrome'
        self.pending = None
        self.generation = 0
        self.closing = False
        self.blocked = False

    def select(self, key, *, force=False):
        if key not in SOURCE_REGISTRY or self.closing or self.blocked:
            return False
        if not force and key == self.selected and self.thread and self.thread.is_alive() and self.pending is None:
            return True
        self.selected = self.pending = key
        self.generation += 1  # suppress late callbacks from the old session
        self.stop.set()
        self.on_event({'type': '_session_reset'})
        self.on_state('switching', f'正在切换到{SOURCE_REGISTRY[key][0]} · {SPEED_MODES[self.speed]} · {TARGET_LANGUAGES[self.target_language]}…')
        self.poll()
        return True

    def select_speed(self, speed):
        if speed not in SPEED_MODES or self.closing or self.blocked:
            return False
        if speed == self.speed:
            return self.select(self.selected)
        self.speed = speed
        return self.select(self.selected, force=True)

    def select_language(self, language):
        if language not in TARGET_LANGUAGES or self.closing or self.blocked:
            return False
        if language == self.target_language:
            return self.select(self.selected)
        self.target_language = language
        return self.select(self.selected, force=True)

    def poll(self):
        if self.thread and self.thread.is_alive():
            return
        if self.thread and self.result == 2 and not self.blocked:
            self.blocked = True
            self.pending = None
            self.on_state('error', '旧音频采集未能退出，请退出并重启程序')
        if self.pending is None or self.closing or self.blocked:
            return
        key, self.pending = self.pending, None
        self.stop = threading.Event()
        self.done.clear()
        self.result = 0
        generation = self.generation
        stop = self.stop
        argv = list(self.argv)
        # UI selection overrides --source. PID only belongs to Chrome.
        cleaned = []
        skip = False
        for arg in argv:
            if skip:
                skip = False
                continue
            if arg in ('--source', '--speed', '--target-language') or (key != 'chrome' and arg == '--pid'):
                skip = True
                continue
            if arg.startswith(('--source=', '--speed=', '--target-language=')) or (key != 'chrome' and arg.startswith('--pid=')):
                continue
            cleaned.append(arg)
        cleaned += ['--target-language', self.target_language, '--speed', self.speed, '--source', key]
        def event(value):
            if generation == self.generation and not self.closing:
                self.on_event(value)
        def state(kind, message):
            if generation == self.generation and not self.closing:
                self.on_state(kind, message)
        def worker():
            try:
                self.result = self.translate(cleaned, stop_event=stop, on_event=event, on_state=state)
            except SystemExit as exc:
                self.result = int(exc.code or 0)
                state('error', '启动参数无效，请查看终端帮助')
            except Exception as exc:
                # Unexpected cleanup failures must not allow overlapping captures.
                self.result = 2
                state('error', f'程序异常：{type(exc).__name__}，请重启程序')
            finally:
                self.done.set()
        self.thread = threading.Thread(target=worker, name='translation-worker')
        self.thread.start()

    def close(self):
        self.closing = True
        self.pending = None
        self.generation += 1
        self.stop.set()

    def join(self, timeout=45):
        if self.thread:
            self.thread.join(timeout)
