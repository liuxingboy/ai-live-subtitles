import json
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]
WINDOW_PATH = ROOT / '.local' / 'window.json'


def read_window(path=WINDOW_PATH):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            return {}
        return {key: value[key] for key in ('x', 'y', 'width', 'source_font', 'translation_font')
                if type(value.get(key)) is int}
    except (OSError, ValueError):
        return {}


def save_window(values, path=WINDOW_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def load_hotwords(path):
    if path is None:
        return {}
    value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict) or not all(isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip() for k, v in value.items()):
        raise ValueError('术语词库必须是非空字符串到非空字符串的 JSON 映射。')
    return value
