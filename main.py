"""Phase 3 overlay, with a preserved terminal-only entry point."""
import sys
from tools.api_debug import configure_console

if __name__ == "__main__":
    configure_console()
    args = sys.argv[1:]
    if '--help' in args or '-h' in args:
        print('窗口模式（默认）；--console 使用终端；--demo 离线预览窗口。其余选项：')
    if '--console' in args or '--help' in args or '-h' in args:
        from tools.chrome_translate import main
        sys.exit(main([arg for arg in args if arg != '--console']))
    from ui.launcher import run
    demo = '--demo' in args
    sys.exit(run([arg for arg in args if arg != '--demo'], demo=demo))
