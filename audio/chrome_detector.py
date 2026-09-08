"""Find browser roots without exposing command lines or browsing data."""
from dataclasses import dataclass
import psutil


@dataclass(frozen=True)
class ChromeProcess:
    pid: int
    parent_pid: int
    created_at: float
    is_browser: bool


def find_chrome_processes():
    found = []
    for process in psutil.process_iter():
        try:
            if process.name().lower() != "chrome.exe":
                continue
            args = process.cmdline()
            # Browser roots have no --type=renderer / utility / gpu-process.
            browser = bool(args) and not any(
                arg == "--type" or arg.startswith("--type=") for arg in args[1:]
            )
            found.append(ChromeProcess(process.pid, process.ppid(), process.create_time(), browser))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return sorted(found, key=lambda p: (p.created_at, p.pid))


def choose_chrome(processes, pid=None):
    candidates = [p for p in processes if p.is_browser]
    if pid is not None:
        candidates = [p for p in processes if p.pid == pid]
    if not candidates:
        raise RuntimeError("未检测到可用 Chrome 进程。请启动 Chrome 并播放视频，再重新运行。")
    if len(candidates) > 1:
        ids = ", ".join(str(p.pid) for p in candidates)
        raise RuntimeError(f"检测到多个 Chrome 主进程：{ids}。请用 --pid 指定一个。")
    return candidates[0]


def still_running(target):
    try:
        process = psutil.Process(target.pid)
        return process.name().lower() == "chrome.exe" and process.create_time() == target.created_at
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
