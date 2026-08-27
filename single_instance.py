from __future__ import annotations

import os
import tempfile


class SingleInstanceGuard:
    """Cross-platform per-user/process-session guard for the Dunoon Daemon GUI.

    Windows uses a named mutex so separately installed/copied builds still collide.
    POSIX uses a non-blocking advisory lock in the user's temp directory.
    The guard must stay alive for the lifetime of the process.
    """

    def __init__(self, name: str = "DunoonDaemon"):
        self.name = "".join(ch for ch in str(name or "DunoonDaemon") if ch.isalnum() or ch in "-_.") or "DunoonDaemon"
        self._handle = None
        self._file = None
        self._acquired = False

    def acquire(self) -> bool:
        if self._acquired:
            return True
        if os.name == "nt":
            return self._acquire_windows()
        return self._acquire_posix()

    def _acquire_windows(self) -> bool:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_mutex = kernel32.CreateMutexW
        create_mutex.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        create_mutex.restype = wintypes.HANDLE
        handle = create_mutex(None, False, rf"Local\{self.name}_SingleInstance_v1")
        if not handle:
            # If the platform cannot create the mutex, do not brick app startup.
            return True
        ERROR_ALREADY_EXISTS = 183
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        self._handle = handle
        self._acquired = True
        return True

    def _acquire_posix(self) -> bool:
        try:
            import fcntl
        except Exception:
            # Unsupported niche platform: fail open rather than prevent startup.
            return True
        try:
            uid = str(os.getuid()) if hasattr(os, "getuid") else str(os.environ.get("USER") or os.environ.get("USERNAME") or "user")
            path = os.path.join(tempfile.gettempdir(), f"{self.name}-{uid}.lock")
            fh = open(path, "a+", encoding="utf-8")
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, OSError):
                fh.close()
                return False
            try:
                fh.seek(0)
                fh.truncate()
                fh.write(str(os.getpid()))
                fh.flush()
            except Exception:
                pass
            self._file = fh
            self._acquired = True
            return True
        except Exception:
            return True

    def release(self) -> None:
        if not self._acquired:
            return
        if os.name == "nt" and self._handle is not None:
            try:
                import ctypes
                ctypes.WinDLL("kernel32").CloseHandle(self._handle)
            except Exception:
                pass
            self._handle = None
        if self._file is not None:
            try:
                import fcntl
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                self._file.close()
            except Exception:
                pass
            self._file = None
        self._acquired = False

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError("Dunoon Daemon is already running.")
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()


def show_already_running_message() -> None:
    title = "Dunoon Daemon"
    message = "Dunoon Daemon is already running. Close the existing instance before opening another."
    if os.name == "nt":
        try:
            import ctypes
            # MB_OK | MB_ICONWARNING | MB_SETFOREGROUND
            ctypes.windll.user32.MessageBoxW(None, message, title, 0x00000000 | 0x00000030 | 0x00010000)
            return
        except Exception:
            pass
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning(title, message, parent=root)
        root.destroy()
    except Exception:
        print(message)
