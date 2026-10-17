# -*- coding: utf-8 -*-
"""内置定时器: 每天在指定时刻自动运行 (默认 07:00 / 20:00)"""
import threading
from datetime import datetime, timedelta


def parse_times(text):
    """"07:00,20:00" -> ['07:00','20:00'] (过滤非法值, 归一化, 去重排序)"""
    out = set()
    for part in str(text or "").replace("，", ",").replace(";", ",").split(","):
        p = part.strip()
        if not p:
            continue
        try:
            h, m = [int(x) for x in p.split(":")]
        except Exception:
            continue
        if 0 <= h <= 23 and 0 <= m <= 59:
            out.add("%02d:%02d" % (h, m))
    return sorted(out)


class DailyScheduler(threading.Thread):
    def __init__(self, get_times, is_enabled, trigger, on_log=None):
        super(DailyScheduler, self).__init__(daemon=True, name="uni-scheduler")
        self._get_times = get_times
        self._enabled = is_enabled
        self._trigger = trigger
        self._log = on_log or (lambda *a, **k: None)
        self._stop = threading.Event()
        self._fired = {}
        self.next_run = ""
        self._recompute_next()

    def stop(self):
        self._stop.set()

    def status(self):
        try:
            en = bool(self._enabled())
        except Exception:
            en = False
        if not en:
            return "定时已关闭"
        return "下次自动运行: %s" % (self.next_run or "—")

    def _recompute_next(self):
        try:
            times = parse_times(self._get_times())
        except Exception:
            times = []
        if not times:
            self.next_run = ""
            return
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        for t in times:
            cand = datetime.strptime("%s %s" % (today, t), "%Y-%m-%d %H:%M")
            if cand > now and "%s|%s" % (today, t) not in self._fired:
                self.next_run = cand.strftime("%m-%d %H:%M")
                return
        nxt = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        cand = datetime.strptime("%s %s" % (nxt, times[0]), "%Y-%m-%d %H:%M")
        self.next_run = cand.strftime("%m-%d %H:%M")

    def _tick(self):
        try:
            enabled = bool(self._enabled())
        except Exception:
            enabled = False
        if not enabled:
            self.next_run = ""
            return
        times = parse_times(self._get_times())
        if not times:
            self.next_run = ""
            return
        now = datetime.now()
        slot = now.strftime("%H:%M")
        key = "%s|%s" % (now.strftime("%Y-%m-%d"), slot)
        if slot in times and key not in self._fired:
            self._fired[key] = True
            limit = (now - timedelta(days=7)).strftime("%Y-%m-%d")
            self._fired = {k: v for k, v in self._fired.items() if k[:10] >= limit}
            self._log("⏰ 定时触发: %s, 开始自动运行" % slot, "sys")
            try:
                self._trigger()
            except Exception as e:
                self._log("❌ 定时任务启动失败: %s" % e, "error")
        self._recompute_next()

    def run(self):
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                self._log("⚠️ 定时器异常: %s" % e, "warn")
            self._stop.wait(20)
