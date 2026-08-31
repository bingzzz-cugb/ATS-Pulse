import ctypes
import json
import os
import signal
import sys
from datetime import datetime
from pathlib import Path


def pid_is_alive(pid: int) -> bool:
    """Return True if a process with the given PID is still running."""
    if sys.platform == "win32":
        # os.kill(pid, 0) raises WinError 87/11 on Windows, so probe via Win32 API
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def terminate_process(pid: int, force: bool = False) -> bool:
    """Terminate a process by PID. Returns False if the process is already gone.

    On Windows os.kill only accepts SIGTERM/SIGINT (SIGKILL raises WinError 87),
    so both graceful and forced termination go through the Win32 API.
    """
    if sys.platform == "win32":
        PROCESS_TERMINATE = 0x0001
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
        if not handle:
            return False
        try:
            return bool(kernel32.TerminateProcess(handle, 1))
        finally:
            kernel32.CloseHandle(handle)

    os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
    return True


class ServiceLock:
    def __init__(self, data_dir: Path | str):
        self.lock_file = Path(data_dir) / ".pulse.lock"

    def is_locked(self) -> tuple[bool, dict | None]:
        if not self.lock_file.exists():
            return False, None

        try:
            with open(self.lock_file, "r") as f:
                content = f.read().strip()
                if not content:
                    return False, None
                info = json.loads(content)
        except (json.JSONDecodeError, KeyError, FileNotFoundError):
            return False, None

        # release() must run after the file handle is closed (Windows can't
        # unlink an open file), so any stale-lock cleanup happens below.
        if not info.get("pid"):
            return True, info
        if not pid_is_alive(info["pid"]):
            self.release()
            return False, None
        return True, info

    def acquire(self, host: str, port: int, pid: int | None = None, allow_non_localhost: bool = False) -> bool:
        try:
            info = {
                "pid": pid or os.getpid(),
                "host": host,
                "port": port,
                "allow_non_localhost": allow_non_localhost,
                "started_at": datetime.now().isoformat(),
            }
            with open(self.lock_file, "w") as f:
                json.dump(info, f, indent=2)
            return True
        except Exception:
            return False

    def release(self):
        try:
            if self.lock_file.exists():
                self.lock_file.unlink()
        except Exception:
            pass

    def get_status_message(self, info: dict | None) -> str:
        if not info:
            return "服务状态未知"

        host = info.get("host", "unknown")
        port = info.get("port", "unknown")
        pid = info.get("pid", "unknown")
        started_at = info.get("started_at", "unknown")

        lines = [
            f"🌐 访问地址: http://{host}:{port}",
            f"🔢 进程 PID: {pid}",
            f"⏰ 启动时间: {started_at}",
        ]

        if info.get("allow_non_localhost"):
            lines.append("⚠️  非本地访问模式 (已启用)")

        return "\n".join(lines)


def check_and_acquire_lock(data_dir: str) -> ServiceLock | None:
    lock = ServiceLock(data_dir)
    is_locked, _ = lock.is_locked()
    if not is_locked:
        return lock
    return None
