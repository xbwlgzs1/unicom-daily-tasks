# -*- coding: utf-8 -*-
"""日志流: 把原脚本的 print 输出捕获到队列(GUI)与日志文件.

原脚本 7000+ 行全部用 print 输出, 图形版不重写其逻辑,
而是重定向 sys.stdout/sys.stderr — 输出格式与命令行版完全一致.
"""
import io
import queue
import re
import sys
import threading
import time

_RE_ACCOUNT = re.compile(r"^\[\d{2}:\d{2}:\d{2}\]\s*账号\[(\d+)\]")


def classify(text):
    if "❌" in text or "失败" in text or "异常" in text or "错误" in text:
        return "error"
    if "⚠️" in text or "警告" in text or "💨" in text:
        return "warn"
    if "✅" in text or "🎉" in text or "成功" in text or "💰" in text or "🎁" in text:
        return "ok"
    if "====" in text:
        return "sys"
    return "info"


class LogBus(object):
    """线程安全日志总线: 写入 -> 队列(GUI轮询) + 文件(落盘)"""

    def __init__(self):
        self.queue = queue.Queue()
        self._lock = threading.Lock()
        self._fp = None
        self._fp_path = ""
        self._buf = ""
        self.lines = []
        self.on_line = None

    # ---------- 文件 ----------
    def _file(self):
        from . import paths
        p = paths.log_file()
        if p != self._fp_path:
            try:
                if self._fp:
                    self._fp.close()
                paths.ensure_dirs()
                self._fp = open(p, "a", encoding="utf-8")
                self._fp_path = p
            except Exception:
                self._fp = None
        return self._fp

    # ---------- 写入 ----------
    def emit(self, text, level=None, account=None):
        text = str(text).rstrip("\n")
        if not text:
            return
        level = level or classify(text)
        if account is None:
            m = _RE_ACCOUNT.match(text)
            account = int(m.group(1)) if m else 0
        rec = {"t": time.strftime("%H:%M:%S"), "text": text, "level": level, "account": account}
        with self._lock:
            self.lines.append(rec)
            try:
                self.queue.put_nowait(rec)
            except Exception:
                pass
            fp = self._file()
            if fp:
                try:
                    fp.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
                    fp.flush()
                except Exception:
                    pass
        if self.on_line:
            try:
                self.on_line(rec)
            except Exception:
                pass

    def write(self, s):
        if not s:
            return 0
        self._buf += s
        while "\n" in self._buf:
            i = self._buf.index("\n")
            line, self._buf = self._buf[:i], self._buf[i + 1:]
            if line.strip():
                self.emit(line)
        return len(s)

    def flush(self):
        if self._buf.strip():
            line, self._buf = self._buf, ""
            self.emit(line)

    def drain(self, limit=400):
        out = []
        for _ in range(limit):
            try:
                out.append(self.queue.get_nowait())
            except Exception:
                break
        return out

    def snapshot(self):
        with self._lock:
            return list(self.lines)

    def clear(self):
        with self._lock:
            self.lines = []
        self.queue = queue.Queue()

    def save_to(self, path):
        with self._lock:
            data = "".join("[%s] %s\n" % (r["t"], r["text"]) for r in self.lines)
        with open(path, "w", encoding="utf-8") as f:
            f.write(data)
        return len(self.lines)


class StreamProxy(io.TextIOBase):
    def __init__(self, bus, original=None):
        self._bus = bus
        self._orig = original

    @property
    def encoding(self):
        return "utf-8"

    def writable(self):
        return True

    def write(self, s):
        try:
            self._bus.write(s)
        except Exception:
            pass
        return len(s)

    def flush(self):
        try:
            self._bus.flush()
        except Exception:
            pass

    def isatty(self):
        return False

    def reconfigure(self, **kwargs):
        return None


_CURRENT_BUS = None


def install(bus):
    global _CURRENT_BUS
    _CURRENT_BUS = bus
    sys.stdout = StreamProxy(bus, sys.stdout)
    sys.stderr = StreamProxy(bus, sys.stderr)
    return sys.stdout
