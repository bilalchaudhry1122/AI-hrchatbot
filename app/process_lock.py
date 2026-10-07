import os
from pathlib import Path

_LOCK_FD = None


def lock_path_for(root_dir):
    return Path(root_dir) / ".bot.instance.lock"


def is_pid_running(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError as error:
        return getattr(error, "errno", None) == 13


def _try_lock(fd):
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(fd):
    if os.name == "nt":
        import msvcrt

        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return
    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass


def acquire_instance_lock(root_dir, pid=None):
    """One live bot per repo. The lock file stays open until release."""
    global _LOCK_FD
    pid = os.getpid() if pid is None else pid
    lock_path = lock_path_for(root_dir)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    try:
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"0")
        os.lseek(fd, 0, os.SEEK_SET)
        _try_lock(fd)
    except OSError:
        os.close(fd)
        raise RuntimeError(
            "Another bot instance is already running. "
            "Stop that process, then start again so Discord does not get double replies."
        )
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    os.write(fd, str(pid).encode("utf-8"))
    os.fsync(fd)
    _LOCK_FD = fd
    return lock_path


def release_instance_lock(root_dir, pid=None):
    global _LOCK_FD
    del pid
    lock_path = lock_path_for(root_dir)
    fd = _LOCK_FD
    _LOCK_FD = None
    if fd is not None:
        _unlock(fd)
        try:
            os.close(fd)
        except OSError:
            pass
    try:
        lock_path.unlink()
    except OSError:
        pass
