"""Peak working-set sampling for the executor (Windows, ctypes only).

Important environment fact: a uv-managed virtualenv ``python.exe`` is a small
launcher that spawns the real interpreter as a child process.  Sampling only the
``Popen`` pid therefore measures a ~3 MB launcher and makes memory limits
useless.  :class:`ProcessTreeSampler` enumerates the process tree (Toolhelp32)
and reports the peak working set across the root and all descendants, together
with the pids it actually measured.

On non-Windows platforms both samplers return ``None`` instead of inventing a
value.
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time

__all__ = ["ProcessMemorySampler", "ProcessTreeSampler", "descendant_pids"]


class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


class _PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_ulong),
        ("cntUsage", ctypes.c_ulong),
        ("th32ProcessID", ctypes.c_ulong),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", ctypes.c_ulong),
        ("cntThreads", ctypes.c_ulong),
        ("th32ParentProcessID", ctypes.c_ulong),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_ulong),
        ("szExeFile", ctypes.c_char * 260),
    ]


_TH32CS_SNAPPROCESS = 0x00000002


def _kernel32():
    return ctypes.WinDLL("kernel32", use_last_error=True)


def _psapi():
    return ctypes.WinDLL("psapi", use_last_error=True)


def _process_table() -> list[tuple[int, int]]:
    """Return ``(pid, parent_pid)`` for every process."""

    kernel32 = _kernel32()
    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel32.CreateToolhelp32Snapshot.argtypes = [ctypes.c_uint, ctypes.c_uint]
    kernel32.Process32First.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PROCESSENTRY32)]
    kernel32.Process32Next.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PROCESSENTRY32)]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    snapshot = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not snapshot:
        return []
    entry = _PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(_PROCESSENTRY32)
    rows: list[tuple[int, int]] = []
    try:
        ok = kernel32.Process32First(snapshot, ctypes.byref(entry))
        while ok:
            rows.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID)))
            ok = kernel32.Process32Next(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return rows


def descendant_pids(root_pid: int) -> list[int]:
    """All live descendants of ``root_pid`` (breadth first, root excluded)."""

    if sys.platform != "win32":
        return []
    table = _process_table()
    children: dict[int, list[int]] = {}
    for pid, parent in table:
        children.setdefault(parent, []).append(pid)
    found: list[int] = []
    frontier = [int(root_pid)]
    while frontier:
        current = frontier.pop()
        for child in children.get(current, []):
            if child not in found:
                found.append(child)
                frontier.append(child)
    return found


def _working_set_bytes(pid: int) -> int | None:
    if sys.platform != "win32":
        return None
    kernel32 = _kernel32()
    psapi = _psapi()
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [ctypes.c_uint, ctypes.c_bool, ctypes.c_uint]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_PROCESS_MEMORY_COUNTERS),
        ctypes.c_uint,
    ]
    psapi.GetProcessMemoryInfo.restype = ctypes.c_bool
    process = kernel32.OpenProcess(0x0400 | 0x0010, False, int(pid))
    if not process:
        return None
    try:
        counters = _PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
            return None
        return int(counters.WorkingSetSize)
    finally:
        kernel32.CloseHandle(process)


class ProcessMemorySampler:
    """Sample a single pid (kept for compatibility and calibration tests)."""

    def __init__(self, pid: int, *, interval_sec: float = 0.05) -> None:
        self._pid = pid
        self._interval = interval_sec
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._peak_bytes: int | None = None
        self._supported = sys.platform == "win32"

    def _sample(self) -> int | None:
        if not self._supported:
            return None
        return _working_set_bytes(self._pid)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            value = self._sample()
            if value is not None and (self._peak_bytes is None or value > self._peak_bytes):
                self._peak_bytes = value

    def start(self) -> None:
        if not self._supported:
            return
        self._thread = threading.Thread(target=self._run, name="rf-memory-sampler", daemon=True)
        self._thread.start()

    def current_mb(self) -> float | None:
        value = self._sample()
        if value is None:
            return None
        if self._peak_bytes is None or value > self._peak_bytes:
            self._peak_bytes = value
        return round(value / (1024 * 1024), 3)

    def peak_mb(self) -> float | None:
        if self._peak_bytes is None:
            return None
        return round(self._peak_bytes / (1024 * 1024), 3)

    def stop(self) -> float | None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        last = self._sample()
        if last is not None and (self._peak_bytes is None or last > self._peak_bytes):
            self._peak_bytes = last
        return self.peak_mb()


class ProcessTreeSampler:
    """Sample the peak working set of a launcher pid and all its descendants."""

    def __init__(self, root_pid: int, *, interval_sec: float = 0.05) -> None:
        self._root_pid = int(root_pid)
        self._interval = interval_sec
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._peak_bytes: int | None = None
        self._measured: set[int] = set()
        self._supported = sys.platform == "win32"

    def _sample(self) -> tuple[int | None, list[int]]:
        if not self._supported:
            return None, []
        pids = [self._root_pid] + descendant_pids(self._root_pid)
        peak: int | None = None
        measured: list[int] = []
        for pid in pids:
            value = _working_set_bytes(pid)
            if value is None:
                continue
            measured.append(pid)
            if peak is None or value > peak:
                peak = value
        return peak, measured

    def _record(self, peak: int | None, measured: list[int]) -> None:
        if peak is None:
            return
        self._measured.update(measured)
        if self._peak_bytes is None or peak > self._peak_bytes:
            self._peak_bytes = peak

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            self._record(*self._sample())

    def start(self) -> None:
        if not self._supported:
            return
        self._thread = threading.Thread(target=self._run, name="rf-tree-sampler", daemon=True)
        self._thread.start()

    def current_mb(self) -> float | None:
        peak, measured = self._sample()
        self._record(peak, measured)
        return None if peak is None else round(peak / (1024 * 1024), 3)

    def peak_mb(self) -> float | None:
        if self._peak_bytes is None:
            return None
        return round(self._peak_bytes / (1024 * 1024), 3)

    def measured_pids(self) -> list[int]:
        return sorted(self._measured)

    def stop(self) -> float | None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._record(*self._sample())
        return self.peak_mb()