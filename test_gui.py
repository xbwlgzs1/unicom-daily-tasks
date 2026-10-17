# -*- coding: utf-8 -*-
"""GUI 冒烟测试: 6 个选项卡、日志、账号、开关、记录表、定时器、运行保护"""
import os
import sys
import threading

# 必须在导入 app.* 之前设置独立数据目录 (paths 在模块级就解析好了路径)
_BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _BASE)
_TMP = os.path.join(os.environ.get("APPDATA") or _BASE, "UnicomAllIn1", "_guitest")
os.environ["CMF_DATA_DIR"] = _TMP
os.makedirs(_TMP, exist_ok=True)

from app import records
from app import gui

# gui.App() 内部会把 sys.stdout 重定向进日志总线, 测试输出必须走原始 stdout
_REAL_OUT = sys.__stdout__
try:
    _REAL_OUT.reconfigure(encoding="utf-8")
except Exception:
    pass


def say(msg):
    try:
        _REAL_OUT.write(msg + "\n")
        _REAL_OUT.flush()
    except Exception:
        pass


fails = []
TOTAL = [0]


def chk(name, fn):
    TOTAL[0] += 1
    try:
        fn()
        say("[OK]   " + name)
    except Exception as e:
        import traceback
        traceback.print_exc(file=_REAL_OUT)
        fails.append(name)
        say("[FAIL] %s -> %s" % (name, e))


app = gui.App()
app.update()


# ---- 1 选项卡 ----
def t_tabs():
    assert len(app.nb.tabs()) == 6, "期望6个选项卡, 实际 %d" % len(app.nb.tabs())
    for i in range(6):
        app.nb.select(i)
        app.update()
chk("六个选项卡全部可构建并切换", t_tabs)


# ---- 2 日志 ----
def t_log():
    app.bus.emit("✅ 测试成功日志", "ok")
    app.bus.emit("❌ 测试错误日志", "error")
    app.bus.emit("⚠️ 测试警告日志", "warn")
    app.bus.emit("普通INFO日志", "info")
    app._poll_logs()
    txt = app.log_text.get("1.0", "end")
    for s in ("测试成功日志", "测试错误日志", "测试警告日志", "普通INFO日志"):
        assert s in txt, "缺少 %s" % s
chk("日志写入与颜色标签", t_log)


# ---- 3 日志筛选 ----
def t_filter():
    app.var_filter.set("仅错误")
    app._rebuild_log()
    txt = app.log_text.get("1.0", "end")
    assert "测试错误日志" in txt and "普通INFO日志" not in txt, txt[:300]
    app.var_filter.set("全部")
    app._rebuild_log()
    assert "普通INFO日志" in app.log_text.get("1.0", "end")
chk("日志筛选", t_filter)


# ---- 4 账号管理 ----
def t_acc():
    st = app.store
    st.accounts = []
    st.add("tokAAA#app1", note="账号甲")
    st.add("tokBBB#app2")
    st.save()
    app._refresh_accounts()
    ids = list(app.acc_tree.get_children(""))
    assert len(ids) == 2, ids
    st.remove([ids[0]])
    app._refresh_accounts()
    assert len(app.acc_tree.get_children("")) == 1
    st.toggle([st.accounts[0].id], False)
    assert st.enabled_configs() == []
    st.toggle([st.accounts[0].id], True)
    assert len(st.enabled_configs()) == 1
    st.accounts = []
    st.save()
    app._refresh_accounts()
chk("账号表格刷新 / 删除 / 启停", t_acc)


# ---- 5 功能开关 ----
def t_switches():
    from app.settings import MODULE_SWITCHES, Settings
    assert len(app.switch_vars) >= len(MODULE_SWITCHES), len(app.switch_vars)
    # 全关再全开
    for _key, _l, _h in MODULE_SWITCHES:
        app.switch_vars[_key].set(False)
    app.switch_vars["enable_woread"].set(True)
    app.switch_vars["run_grab_coupon"].set(True)
    app.switch_vars["market_run_draw"].set(False)
    app.save_settings()
    s = Settings()
    cfg = s.as_global_config()
    assert cfg["enable_woread"] is True
    assert cfg["enable_sign"] is False
    assert cfg["sign_config"]["run_grab_coupon"] is True
    assert cfg["market_config"]["run_draw"] is False
    # 还原为全部默认
    for _key, _l, _h in MODULE_SWITCHES:
        app.switch_vars[_key].set(True)
    app.switch_vars["enable_woread"].set(False)
    app.switch_vars["run_grab_coupon"].set(False)
    app.switch_vars["market_run_draw"].set(True)
    app.save_settings()
    assert Settings().as_global_config()["enable_sign"] is True
chk("功能开关 → globalConfig 映射", t_switches)


# ---- 6 记录表 ----
def t_records():
    records.clear()
    records.ingest_wins([{"时间": "08:01:02", "账号": 1, "手机号": "186****0000",
                          "来源": "权益超市", "类型": "奖品", "内容": "5元话费",
                          "账号ID": "a1"}])
    records.append_results([{"时间": "2026-10-05 08:00", "账号": 1,
                             "手机号": "186****0000", "状态": "完成",
                             "话费余额": "¥23.50", "本次收益": "5元话费"}])
    app._refresh_wins()
    app._refresh_results()
    w = app.win_tree.get_children("")
    r = app.res_tree.get_children("")
    assert len(w) == 1 and len(r) == 1, (w, r)
    assert app.win_tree.item(w[0], "values")[5] == "5元话费"
    assert app.res_tree.item(r[0], "values")[4] == "¥23.50"
    records.clear()
    app._refresh_wins()
    app._refresh_results()
chk("中奖记录表 / 运行结果表刷新", t_records)


# ---- 7 设置持久化 ----
def t_settings():
    app.vars["pushplus_token"].set("TESTTOK")
    app.var_sched_times.set("06:30,19:45")
    app.save_settings()
    from app.settings import Settings
    s = Settings()
    assert s.pushplus_token == "TESTTOK", s.pushplus_token
    assert s.schedule_times == "06:30,19:45", s.schedule_times
    assert app.sched.status().startswith("下次自动运行"), app.sched.status()
    app.vars["pushplus_token"].set("")
    app.var_sched_times.set("07:00,20:00")
    app.save_settings()
    s2 = Settings()
    assert s2.pushplus_token == "" and s2.schedule_times == "07:00,20:00"
chk("设置保存 / 定时状态显示", t_settings)


# ---- 8 定时器 ----
def t_sched():
    from datetime import datetime
    from app.scheduler import DailyScheduler
    logs = []
    s = DailyScheduler(get_times=lambda: "07:00,20:00", is_enabled=lambda: True,
                       trigger=lambda: None,
                       on_log=lambda m, lv="info": logs.append(m))
    s._tick()
    assert s.next_run, "未计算出下次运行时间"
    now = datetime.now().strftime("%H:%M")
    s._fired["%s|%s" % (datetime.now().strftime("%Y-%m-%d"), now)] = True
    before = len(logs)
    s._tick()
    assert len(logs) == before, "同一时刻不应重复触发"
    s2 = DailyScheduler(get_times=lambda: "07:00", is_enabled=lambda: False,
                        trigger=lambda: None, on_log=lambda *a, **k: None)
    s2._tick()
    assert s2.next_run == "" and "关闭" in s2.status()
chk("定时器到点计算 / 去重 / 开关", t_sched)


# ---- 9 空账号运行保护 ----
def t_guard():
    from app import runner
    from app.settings import Settings
    app.store.accounts = []
    out = runner.run_batch(Settings(), app.store, app.bus, threading.Event())
    assert out["results"] == [] and out["aborted"] is True, out
chk("无账号时运行保护", t_guard)


# ---- 10 停止信号 ----
def t_stop():
    from core import legacy
    ev = threading.Event()
    legacy.STOP_EVENT = ev
    assert legacy._stopped() is False
    ev.set()
    assert legacy._stopped() is True
    assert legacy._sleep(10) is True, "停止信号应立即打断等待"
    legacy.STOP_EVENT = None
    assert legacy._stopped() is False
chk("核心模块停止控制 / 可中断等待", t_stop)


# ---- 11 推送模块 ----
def t_notify():
    import notify
    assert callable(notify.send)
    # 未配置 Token → 不外发, 返回 False
    from app.settings import Settings
    Settings().pushplus_token = ""
    assert notify.send("标题", "内容") is False
chk("notify 模块 / 未配置 Token 不外发", t_notify)


# ---- 12 事件泵 ----
def t_pump():
    app.update_idletasks()
    app.update()
    assert app.winfo_exists()
chk("界面事件泵", t_pump)


# ---- 13 内核版本必须真读, 不得硬编码 (t5 独立验证发现的缺陷) ----
def t_core_version():
    from core import legacy
    real = legacy.SCRIPT_VERSION
    assert app._core_version() == real, (app._core_version(), real)
    # 关键: 篡改内核版本, 界面取值必须跟着变 —— 硬编码则不会变
    legacy.SCRIPT_VERSION = "v9.9.9-FAKE"
    try:
        assert app._core_version() == "v9.9.9-FAKE", \
            "版本号疑似硬编码(篡改内核后未跟随变化): %s" % app._core_version()
    finally:
        legacy.SCRIPT_VERSION = real
    assert app._core_version() == real
chk("内核版本动态读取 (非硬编码)", t_core_version)


# ---- 14 人脸图选择入口 (v1.2.1 新增) ----
def t_face():
    from app.settings import Settings
    app.nb.select(5)          # 设置页
    app.update()
    # 清单控件必须已构建
    assert hasattr(app, "face_list") and hasattr(app, "var_face")
    app.settings.face_images = []
    app.settings.save()
    app._face_refresh()
    assert "未选" in app.var_face.get(), app.var_face.get()
    assert app.face_list.size() == 0
    # 模拟"添加图片"选中两个文件 (绕过文件对话框)
    import tempfile
    tmp = tempfile.gettempdir()
    p1 = os.path.join(tmp, "_uni_face1.jpg")
    p2 = os.path.join(tmp, "_uni_face2.png")
    for p in (p1, p2):
        with open(p, "wb") as f:
            f.write(b"\xff\xd8\xff\xe0" + b"0" * 64)
    picked = [p1, p2]
    import app.gui as _g
    _orig = _g.filedialog.askopenfilenames
    _g.filedialog.askopenfilenames = lambda **kw: tuple(picked)
    try:
        app._face_add()
    finally:
        _g.filedialog.askopenfilenames = _orig
    assert app.face_list.size() == 2, app.face_list.size()
    assert "已选 2 张" in app.var_face.get(), app.var_face.get()
    # 持久化 + 去重 (重复添加不应翻倍)
    assert Settings().face_images == picked, Settings().face_images
    _g.filedialog.askopenfilenames = lambda **kw: tuple(picked)
    try:
        app._face_add()
    finally:
        _g.filedialog.askopenfilenames = _orig
    assert app.face_list.size() == 2, "重复添加应去重"
    # 清空
    _g.messagebox.askyesno = lambda *a, **k: True
    app._face_clear()
    assert app.face_list.size() == 0
    assert Settings().face_images == []
    for p in (p1, p2):
        try:
            os.unlink(p)
        except Exception:
            pass
chk("人脸图选择入口 / 去重 / 持久化 / 清空", t_face)

app.destroy()

say("")
say("=" * 50)
say("GUI 冒烟测试: 通过 %d / 失败 %d" % (TOTAL[0] - len(fails), len(fails)))
if fails:
    say("失败项: " + ", ".join(fails))
say("=" * 50)
sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__
sys.exit(1 if fails else 0)
