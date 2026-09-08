"""Console-free entry used by the native Windows launcher."""
import ctypes
import os
from pathlib import Path
import runpy
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    sys.path.insert(0, str(root))
    # pythonw has no console streams. Do not persist spoken content in a log.
    with open(os.devnull, 'w', encoding='utf-8') as output:
        sys.stdout = sys.stderr = output
        try:
            if '--launcher-check' in sys.argv:
                import PySide6.QtWidgets
                import ui.launcher
                import tools.chrome_translate
                return 0
            sys.argv[0] = str(root / 'main.py')
            runpy.run_path(sys.argv[0], run_name='__main__')
        except SystemExit as exc:
            return exc.code or 0
        except Exception as exc:
            ctypes.windll.user32.MessageBoxW(
                None,
                f'字幕程序启动失败（{type(exc).__name__}）。\n'
                '请在项目目录的终端运行 .\\.venv\\Scripts\\python.exe main.py 查看详情。',
                '实时双语字幕', 0x10)
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
