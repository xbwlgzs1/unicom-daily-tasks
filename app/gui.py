# -*- coding: utf-8 -*-
"""tkinter 图形界面: 账号 / 功能开关 / 运行日志 / 运行结果 / 中奖记录 / 设置 + 定时运行"""
import os
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import logstream, paths, records, runner, scheduler, sms_login
from .settings import MODULE_SWITCHES, AccountStore, Settings

APP_TITLE = "中国联通 · 日常任务合集"

FONT = ("Microsoft YaHei UI", 10)
FONT_B = ("Microsoft YaHei UI", 10, "bold")
FONT_T = ("Microsoft YaHei UI", 15, "bold")
FONT_S = ("Microsoft YaHei UI", 9)

COLORS = {"error": "#C0392B", "warn": "#D35400", "ok": "#1E8449",
          "sys": "#2471A3", "info": "#2C3E50"}


# ============================================================
# 账号编辑对话框
# ============================================================
class AccountDialog(tk.Toplevel):
    def __init__(self, master, title, config="", note="", multi=False):
        super(AccountDialog, self).__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.transient(master)
        self.result = None
        self.configure(bg="#F7F9FB")

        body = tk.Frame(self, padx=16, pady=14, bg="#F7F9FB")
        body.pack(fill="both", expand=True)

        tk.Label(body, text=("每行一个账号，支持 & 分隔\n"
                             "格式:  账号#密码  或  Token#AppId  或  仅Token  或  纯手机号"),
                 justify="left", font=FONT_S, fg="#5D6D7E", bg="#F7F9FB"
                 ).grid(row=0, column=0, columnspan=2, sticky="w")

        if multi:
            self.txt = ScrolledText(body, width=76, height=13, font=FONT, wrap="none")
            self.txt.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(8, 8))
            self.txt.insert("1.0", config)
        else:
            tk.Label(body, text="账号配置:", font=FONT, bg="#F7F9FB").grid(
                row=1, column=0, sticky="w", pady=(8, 4))
            self.var_cfg = tk.StringVar(value=config)
            ent = tk.Entry(body, textvariable=self.var_cfg, width=68, font=FONT)
            ent.grid(row=1, column=1, sticky="ew", pady=(8, 4), padx=(6, 0))
            ent.focus_set()

        tk.Label(body, text="备注名称:", font=FONT, bg="#F7F9FB").grid(
            row=2, column=0, sticky="w", pady=(6, 0))
        self.var_note = tk.StringVar(value=note)
        tk.Entry(body, textvariable=self.var_note, width=42, font=FONT).grid(
            row=2, column=1, sticky="w", pady=(6, 0), padx=(6, 0))

        btns = tk.Frame(body, bg="#F7F9FB")
        btns.grid(row=3, column=0, columnspan=2, sticky="e", pady=(14, 0))
        tk.Button(btns, text="取消", width=9, font=FONT, command=self.destroy
                  ).pack(side="right", padx=(8, 0))
        tk.Button(btns, text="确定", width=9, font=FONT, bg="#2471A3", fg="white",
                  activebackground="#1F6391", command=self._ok).pack(side="right")

        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()

    def _ok(self):
        cfg = self.txt.get("1.0", "end").strip() if hasattr(self, "txt") \
            else self.var_cfg.get().strip()
        if not cfg:
            messagebox.showwarning(APP_TITLE, "账号配置不能为空", parent=self)
            return
        self.result = (cfg, self.var_note.get().strip())
        self.destroy()


# ============================================================
# 手机号 + 短信验证码登录对话框
# ============================================================
class SmsLoginDialog(tk.Toplevel):
    """手机号 + 短信验证码登录。

    腾讯 TJCaptcha 是 JS 组件，tkinter 无法承载 → 本对话框只做「手机号校验 +
    调起本地网页 + 轮询凭证」，验证码交互全部在系统浏览器里完成。
    **不在 tkinter 内重画验证码。**

    网络与服务生命周期都在后台线程；UI 只由 ``self.after(0, ...)`` 更新。
    登录成功必须由用户点「添加到账号列表」才写入 —— 不静默写。
    """

    POLL_MS = 900

    def __init__(self, master, store, bus):
        super(SmsLoginDialog, self).__init__(master)
        self.app = master
        self.store = store
        self.bus = bus
        self.title("手机号 + 短信验证码登录")
        self.resizable(False, False)
        self.transient(master)
        self.configure(bg="#F7F9FB")

        self.svc = None
        self.creds = None
        self.imported = False
        self._canceled = False
        self._waiting = False
        self._poll_job = None
        self._poll_error_reported = False

        body = tk.Frame(self, padx=16, pady=14, bg="#F7F9FB")
        body.pack(fill="both", expand=True)

        tk.Label(body, text="手机号 + 短信验证码登录", font=FONT_B, bg="#F7F9FB"
                 ).grid(row=0, column=0, columnspan=3, sticky="w")
        tk.Label(body, text=("步骤：填手机号 → 点「发送验证码」→ 浏览器里完成腾讯安全验证 →\n"
                             "手机收到 6 位码后在网页里填入并登录 → 回到这里点「添加到账号列表」。"),
                 justify="left", font=FONT_S, fg="#5D6D7E", bg="#F7F9FB"
                 ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 10))

        tk.Label(body, text="手机号:", font=FONT, bg="#F7F9FB").grid(
            row=2, column=0, sticky="w", pady=(0, 4))
        self.var_phone = tk.StringVar()
        ent = tk.Entry(body, textvariable=self.var_phone, width=26, font=FONT)
        ent.grid(row=2, column=1, sticky="w", padx=(6, 0), pady=(0, 4))
        ent.focus_set()
        ent.bind("<Return>", lambda e: self._send_code())

        self.btn_send = tk.Button(body, text="发送验证码", font=FONT, bg="#8E44AD",
                                  fg="white", activebackground="#71368A", padx=12,
                                  pady=2, command=self._send_code)
        self.btn_send.grid(row=2, column=2, sticky="w", padx=(8, 0), pady=(0, 4))

        self.var_status = tk.StringVar(value="就绪")
        self.lbl_status = tk.Label(body, textvariable=self.var_status, font=FONT_S,
                                   fg="#2C3E50", bg="#F7F9FB", justify="left",
                                   anchor="w", wraplength=470)
        self.lbl_status.grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 2))

        self.var_creds = tk.StringVar(value="")
        self.lbl_creds = tk.Label(body, textvariable=self.var_creds, font=FONT_S,
                                  fg="#1E8449", bg="#F7F9FB", justify="left",
                                  anchor="w", wraplength=470)
        self.lbl_creds.grid(row=4, column=0, columnspan=3, sticky="w", pady=(2, 6))

        btns = tk.Frame(body, bg="#F7F9FB")
        btns.grid(row=5, column=0, columnspan=3, sticky="e", pady=(6, 0))
        self.btn_add = tk.Button(btns, text="＋ 添加到账号列表", font=FONT_B,
                                 bg="#1E8449", fg="white", activebackground="#196F3D",
                                 padx=14, pady=3, state="disabled",
                                 command=self._add_account)
        self.btn_add.pack(side="right", padx=(8, 0))
        self.btn_open = tk.Button(btns, text="🌐 重新打开登录页", font=FONT,
                                  state="disabled", command=self._open_page)
        self.btn_open.pack(side="right", padx=(8, 0))
        tk.Button(btns, text="关闭", font=FONT, width=8,
                  command=self._on_close).pack(side="right")

        self.bind("<Escape>", lambda e: self._on_close())
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.grab_set()

    # ---------- UI 线程辅助 ----------
    def _set_status(self, text, color="#2C3E50"):
        """只能在主线程调用。"""
        try:
            self.var_status.set(text)
            self.lbl_status.configure(fg=color)
        except Exception:
            pass

    def _ui(self, fn, *a, **kw):
        """后台线程 → 主线程的唯一通道。"""
        try:
            self.after(0, lambda: fn(*a, **kw))
        except Exception:
            pass

    # ---------- 发送验证码 ----------
    def _send_code(self):
        if self._waiting:
            return
        mobile, err = sms_login.validate_mobile(self.var_phone.get())
        if err:
            self._set_status("⚠️ " + err, "#C0392B")
            return
        ok, why = sms_login.available()
        if not ok:
            self._set_status("❌ " + why, "#C0392B")
            return
        self.var_phone.set(mobile)
        self.btn_send.configure(state="disabled", text="启动中…")
        self._set_status("正在启动本地登录页（后台线程）…", "#2471A3")

        def work():
            try:
                svc = sms_login.LoginService(data_dir=paths.data_dir())
                svc.start()                      # 后端起服务，不阻塞界面
                self.svc = svc
                self._ui(self._service_ready, svc)
            except Exception as e:
                self.svc = None
                self._ui(self._service_failed, "%s: %s" % (type(e).__name__, e))

        threading.Thread(target=work, name="uni-sms-start", daemon=True).start()

    def _service_failed(self, reason):
        self.btn_send.configure(state="normal", text="发送验证码")
        self._set_status("❌ 本地登录页启动失败：%s" % reason, "#C0392B")

    def _service_ready(self, svc):
        self.btn_send.configure(state="normal", text="发送验证码")
        self.btn_open.configure(state="normal")
        note = ("；" + svc.port_note) if svc.port_note else ""
        self._set_status("✅ 本地登录页已就绪（仅监听 127.0.0.1）%s\n"
                         "请在浏览器中：填手机号 → 发送验证码 → 完成安全验证 → "
                         "填 6 位码 → 登录。\n"
                         "本窗口会自动检测登录结果（不会为发短信而阻塞界面）。"
                         % svc.url, "#1E8449")
        opened, err = svc.open_browser()
        if not opened:
            self._set_status("⚠️ 浏览器未能自动打开（%s），请手动访问 %s"
                             % (err, svc.url), "#D35400")
        self.bus.emit("📱 短信登录页已启动: %s%s（仅监听本机回环）" % (svc.url, note), "info")
        self._wait_for_credentials()

    def _open_page(self):
        if self.svc:
            self.svc.open_browser()

    # ---------- 轮询（等待登录完成） ----------
    def _wait_for_credentials(self):
        if self._waiting or self._canceled or not self.svc:
            return
        self._waiting = True
        self._started_at = time.time()
        svc = self.svc
        self._poll(svc, time.time())

    def _poll(self, svc, not_before):
        if self._canceled:
            return
        try:
            creds, err = svc.credentials(not_before=not_before)
        except Exception as e:
            creds, err = None, "%s" % type(e).__name__
        if creds is not None:
            self._on_credentials(creds)
            return
        # 超时后不再刷屏，但保持按钮可用，用户可继续在网页里操作
        if not self._poll_error_reported and time.time() - not_before > 300:
            self._poll_error_reported = True
            self._set_status("⏳ 还没检测到登录完成（已等待 5 分钟）。"
                             "如已登录请点「重新打开登录页」确认凭证是否写入。", "#D35400")
        self._poll_job = self.after(self.POLL_MS, lambda: self._poll(svc, not_before))

    def _on_credentials(self, creds):
        self._waiting = False
        self.creds = creds
        config, err = sms_login.credentials_to_config(creds)
        if err:
            self._set_status("⚠️ 拿到凭证但无法解析：%s" % err, "#C0392B")
            return
        token, app_id = config.split("#", 1)
        self.var_creds.set("已获取凭证：token %s · app_id %s\n落盘：%s"
                           % (sms_login.mask(token), sms_login.mask(app_id),
                              os.path.basename(self.svc.creds_path)))
        self.btn_add.configure(state="normal")
        self._set_status("✅ 检测到登录成功，凭证已写入数据目录。"
                         "点「添加到账号列表」完成导入（不会自动写入）。", "#1E8449")
        self.bus.emit("📱 短信登录成功：token %s / app_id %s（等待用户确认导入）"
                      % (sms_login.mask(token), sms_login.mask(app_id)), "ok")

    # ---------- 导入 ----------
    def _add_account(self):
        if not self.creds:
            return
        try:
            added, config = sms_login.import_credentials(self.store, self.creds)
        except Exception as e:
            self._set_status("❌ 写入账号失败：%s" % e, "#C0392B")
            return
        if not added:
            self._set_status("ℹ️ 该账号已存在，未重复添加（列表里已有同一条 token#appId）",
                             "#D35400")
            self.bus.emit("📱 短信登录：账号已存在，跳过重复添加", "warn")
            self.imported = True
            return
        ok, err = self.store.save()
        if not ok:
            self._set_status("❌ 账号保存失败：%s" % err, "#C0392B")
            return
        self.imported = True
        self.btn_add.configure(state="disabled", text="✔ 已添加")
        self._set_status("✅ 已添加到账号列表（默认启用）。可直接在「账号管理」看到它。",
                         "#1E8449")
        self.bus.emit("📱 短信登录账号已导入账号列表（token %s / app_id %s）"
                      % (sms_login.mask(config.split("#", 1)[0]),
                         sms_login.mask(config.split("#", 1)[1])), "ok")
        try:
            if hasattr(self.app, "_refresh_accounts"):
                self.app._refresh_accounts()
        except Exception:
            pass

    # ---------- 收尾 ----------
    def _on_close(self):
        self._canceled = True
        self._waiting = False
        if self._poll_job:
            try:
                self.after_cancel(self._poll_job)
            except Exception:
                pass
            self._poll_job = None
        if self.svc is not None:
            self.svc.shutdown()          # 停服务、释放端口
            self.bus.emit("📱 短信登录页已关闭（端口已释放）", "info")
        self.destroy()


# ============================================================
# 主窗口
# ============================================================
class App(tk.Tk):
    def __init__(self):
        super(App, self).__init__()
        self.title(APP_TITLE)
        self.geometry("1120x740")
        self.minsize(940, 620)
        self.configure(bg="#EEF2F6")

        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

        self.settings = Settings()
        self.store = AccountStore()
        self.bus = logstream.LogBus()
        logstream.install(self.bus)

        self.stop_event = threading.Event()
        self.worker = None
        self.running = False
        self._log_filter = "全部"
        self.switch_vars = {}

        self._build_style()
        self._build_ui()

        self.sched = scheduler.DailyScheduler(
            get_times=lambda: self.settings.schedule_times,
            is_enabled=lambda: self.settings.schedule_enabled,
            trigger=lambda: self.after(0, self.start_run),
            on_log=lambda m, lv="info": self.bus.emit(m, lv),
        )
        self.sched.start()

        self.after(150, self._poll_logs)
        self.after(1000, self._poll_status)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.bus.emit("✅ 程序已启动 · %s" % APP_TITLE, "sys")
        self.bus.emit("ℹ️ 核心脚本: 中国联通 %s · 共 %d 个功能模块"
                      % (self._core_version(), len(MODULE_SWITCHES)), "info")
        self._refresh_accounts()
        self._refresh_results()
        self._refresh_wins()
        self._face_refresh()

        if self.settings.run_on_start:
            self.after(800, self.start_run)

    # --------------------------------------------------------
    # 内核版本 (必须从内核真读, 不得硬编码)
    # --------------------------------------------------------
    @staticmethod
    def _core_version():
        """从实际加载的 core.legacy 读取 SCRIPT_VERSION.

        早先这里是硬编码字面量 "v1.2.1", 导致即使误装了别的内核,
        启动横幅也照样宣称 v1.2.1 —— 会给版本核验制造虚假信心
        (由 t5 独立验证发现)。改为真读, 读不到就如实显示"未知"。
        """
        try:
            from core import legacy
            v = str(getattr(legacy, "SCRIPT_VERSION", "") or "").strip()
            return v or "(未知: 内核未声明 SCRIPT_VERSION)"
        except Exception as e:
            return "(未知: 内核载入失败 %s)" % type(e).__name__

    # --------------------------------------------------------
    # 样式
    # --------------------------------------------------------
    def _build_style(self):
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure(".", font=FONT, background="#EEF2F6", foreground="#2C3E50")
        st.configure("TNotebook", background="#EEF2F6", borderwidth=0)
        st.configure("TNotebook.Tab", font=FONT_B, padding=(13, 7))
        st.configure("TFrame", background="#EEF2F6")
        st.configure("TLabelframe", background="#EEF2F6")
        st.configure("TLabelframe.Label", font=FONT_B, background="#EEF2F6")
        st.configure("TLabel", background="#EEF2F6")
        st.configure("Treeview", font=FONT, rowheight=28, background="white",
                     fieldbackground="white")
        st.configure("Treeview.Heading", font=FONT_B, background="#DCE6F1", foreground="#1B3A57")
        st.map("Treeview", background=[("selected", "#BBD7EE")])
        st.configure("TButton", font=FONT, padding=(12, 5))
        st.configure("TCheckbutton", font=FONT, background="#EEF2F6")

    # --------------------------------------------------------
    # 界面骨架
    # --------------------------------------------------------
    def _build_ui(self):
        top = tk.Frame(self, bg="#2471A3", height=64)
        top.pack(fill="x")
        top.pack_propagate(False)
        tk.Label(top, text="⛵ " + APP_TITLE, font=FONT_T, fg="white",
                 bg="#2471A3").pack(side="left", padx=16)
        self.var_run = tk.StringVar(value="就绪")
        tk.Label(top, textvariable=self.var_run, font=FONT_B, fg="#FFF3CD",
                 bg="#2471A3").pack(side="right", padx=18)

        bar = tk.Frame(self, bg="#EEF2F6", pady=10, padx=12)
        bar.pack(fill="x")
        self.btn_run = tk.Button(bar, text="▶  立即运行", font=FONT_B, bg="#1E8449",
                                 fg="white", activebackground="#196F3D", width=14,
                                 height=1, command=self.start_run)
        self.btn_run.pack(side="left")
        self.btn_stop = tk.Button(bar, text="■  停止", font=FONT_B, bg="#C0392B",
                                  fg="white", activebackground="#922B21", width=12,
                                  height=1, state="disabled", command=self.stop_run)
        self.btn_stop.pack(side="left", padx=(8, 0))

        tk.Frame(bar, width=1, bg="#C5D0DC").pack(side="left", fill="y", padx=14)
        self.var_sched_on = tk.BooleanVar(value=self.settings.schedule_enabled)
        tk.Checkbutton(bar, text="定时自动运行", variable=self.var_sched_on,
                       command=self._save_schedule).pack(side="left")
        tk.Label(bar, text="时刻:", font=FONT).pack(side="left", padx=(4, 2))
        self.var_sched_times = tk.StringVar(value=self.settings.schedule_times)
        ent = tk.Entry(bar, textvariable=self.var_sched_times, width=18, font=FONT)
        ent.pack(side="left")
        ent.bind("<FocusOut>", lambda e: self._save_schedule())
        ent.bind("<Return>", lambda e: self._save_schedule())
        tk.Label(bar, text="(逗号分隔)", font=FONT_S, fg="#7F8C8D").pack(side="left", padx=(4, 0))

        tk.Button(bar, text="💾 保存全部设置", font=FONT, command=self.save_settings
                  ).pack(side="right")
        self.var_next = tk.StringVar(value="")
        tk.Label(bar, textvariable=self.var_next, font=FONT_S, fg="#2471A3"
                 ).pack(side="right", padx=14)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        self.nb = nb
        self._tab_accounts(nb)
        self._tab_switches(nb)
        self._tab_log(nb)
        self._tab_results(nb)
        self._tab_wins(nb)
        self._tab_settings(nb)

        st = tk.Frame(self, bg="#DCE6F1", height=26)
        st.pack(fill="x", side="bottom")
        st.pack_propagate(False)
        self.var_status = tk.StringVar(value="就绪")
        tk.Label(st, textvariable=self.var_status, font=FONT_S, bg="#DCE6F1",
                 fg="#1B3A57").pack(side="left", padx=12)
        self.var_progress = tk.StringVar(value="")
        tk.Label(st, textvariable=self.var_progress, font=FONT_S, bg="#DCE6F1",
                 fg="#1B3A57").pack(side="right", padx=12)

    # ---------- 1 账号管理 ----------
    def _tab_accounts(self, nb):
        f = tk.Frame(nb, bg="#EEF2F6")
        nb.add(f, text="  账号管理  ")
        bar = tk.Frame(f, bg="#EEF2F6")
        bar.pack(fill="x", padx=8, pady=(8, 4))

        def mk(text, cmd, bg="#2471A3"):
            return tk.Button(bar, text=text, font=FONT, bg=bg, fg="white",
                             activebackground="#1F6391", padx=10, pady=2, command=cmd)

        mk("＋ 添加账号", self._acc_add).pack(side="left")
        mk("＋ 批量导入", self._acc_import, "#16A085").pack(side="left", padx=(6, 0))
        mk("✎ 修改", self._acc_edit, "#7F8C8D").pack(side="left", padx=(6, 0))
        mk("－ 删除", self._acc_del, "#C0392B").pack(side="left", padx=(6, 0))
        tk.Frame(bar, width=1, bg="#C5D0DC").pack(side="left", fill="y", padx=10)
        mk("✔ 启用", lambda: self._acc_toggle(True), "#1E8449").pack(side="left")
        mk("✖ 禁用", lambda: self._acc_toggle(False), "#D35400").pack(side="left", padx=(6, 0))
        tk.Frame(bar, width=1, bg="#C5D0DC").pack(side="left", fill="y", padx=10)
        self.btn_sms_login = tk.Button(
            bar, text="📱 手机号验证码登录…", font=FONT, bg="#8E44AD", fg="white",
            activebackground="#71368A", padx=10, pady=2, command=self._sms_login)
        self.btn_sms_login.pack(side="left")

        cols = ("no", "name", "cfg", "on", "time", "status", "bal")
        heads = ("序号", "账号/备注", "配置摘要", "启用", "上次运行", "上次状态", "话费余额")
        widths = (52, 150, 250, 52, 130, 130, 110)
        self.acc_tree = ttk.Treeview(f, columns=cols, show="headings", selectmode="extended")
        for c, h, w in zip(cols, heads, widths):
            self.acc_tree.heading(c, text=h)
            self.acc_tree.column(c, width=w,
                                 anchor="w" if c in ("name", "cfg") else "center",
                                 stretch=(c == "cfg"))
        vsb = ttk.Scrollbar(f, orient="vertical", command=self.acc_tree.yview)
        self.acc_tree.configure(yscrollcommand=vsb.set)
        self.acc_tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=(0, 8))
        vsb.pack(side="right", fill="y", pady=(0, 8), padx=(0, 8))
        self.acc_tree.bind("<Double-1>", lambda e: self._acc_edit())
        tk.Label(f, text="账号只保存在本机 %s，不会上传到任何第三方" % paths.data_dir(),
                 font=FONT_S, fg="#7F8C8D", bg="#EEF2F6").pack(side="bottom",
                                                               fill="x", padx=10, pady=(0, 4))

    # ---------- 2 功能开关 ----------
    def _tab_switches(self, nb):
        f = tk.Frame(nb, bg="#EEF2F6")
        nb.add(f, text="  功能开关  ")

        head = tk.Frame(f, bg="#EEF2F6")
        head.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(head, text="选择本次运行要执行的模块（对应原脚本 globalConfig）",
                 font=FONT, fg="#5D6D7E").pack(side="left")

        wrap = tk.Frame(f, bg="#EEF2F6")
        wrap.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        # 11 个模块总开关
        left = tk.Frame(wrap, bg="#EEF2F6")
        left.pack(side="left", fill="both", expand=True, anchor="n")
        for i, (key, label, hint) in enumerate(MODULE_SWITCHES):
            v = tk.BooleanVar(value=bool(self.settings._d.get(key, True)))
            self.switch_vars[key] = v
            rowf = tk.Frame(left, bg="#EEF2F6")
            rowf.pack(fill="x", pady=2, anchor="w")
            tk.Checkbutton(rowf, text="  %-8s" % label, variable=v, font=FONT_B,
                           bg="#EEF2F6", width=12, anchor="w").pack(side="left")
            tk.Label(rowf, text=hint, font=FONT_S, fg="#7F8C8D", bg="#EEF2F6"
                     ).pack(side="left", padx=6)
        tk.Checkbutton(left, text="  推送通知", variable=self.switch_vars.setdefault(
            "enable_notify", tk.BooleanVar(value=bool(self.settings.enable_notify))),
            font=FONT_B, bg="#EEF2F6").pack(anchor="w", pady=(8, 0))

        # 子开关
        right = tk.Frame(wrap, bg="#EEF2F6")
        right.pack(side="right", fill="both", expand=True, anchor="n", padx=(20, 0))

        def group(title, items):
            fr = tk.LabelFrame(right, text=" " + title + " ", font=FONT_B)
            fr.pack(fill="x", pady=(0, 8), anchor="w")
            for key, label in items:
                v = tk.BooleanVar(value=bool(self.settings._d.get(key, True)))
                self.switch_vars[key] = v
                tk.Checkbutton(fr, text=label, variable=v, font=FONT, bg="#EEF2F6"
                               ).pack(anchor="w", padx=10, pady=2)
            return fr

        group("首页签到", [("run_grab_coupon", "抢话费券 (需 9点/17点58分 运行)")])
        # 注: v1.2.1 已下线「权益超市-会员中心积分任务」, 原开关随之移除
        group("权益超市", [("market_run_task", "做任务(浏览/分享)"),
                        ("market_run_draw", "抽奖"),
                        ("market_run_claim", "自动领奖")])
        group("区域专区", [("run_ah_friday", "安徽超级星期五抢红包")])
        g = tk.LabelFrame(right, text=" 其他 ", font=FONT_B)
        g.pack(fill="x", pady=(0, 8), anchor="w")
        tk.Checkbutton(g, text="强制刷新设备ID", variable=self.switch_vars.setdefault(
            "refresh_device_id", tk.BooleanVar(value=bool(self.settings.refresh_device_id))),
            font=FONT, bg="#EEF2F6").pack(anchor="w", padx=10, pady=2)
        tk.Checkbutton(g, text="查询模式 (只查资产不执行任务)",
                       variable=self.switch_vars.setdefault(
                           "query_only", tk.BooleanVar(value=bool(self.settings.query_only))),
                       font=FONT, bg="#EEF2F6").pack(anchor="w", padx=10, pady=2)

        tk.Button(f, text="💾 保存开关设置", font=FONT_B, bg="#2471A3", fg="white",
                  padx=18, pady=6, command=self.save_settings).pack(pady=(0, 10))

    # ---------- 3 运行日志 ----------
    def _tab_log(self, nb):
        f = tk.Frame(nb, bg="#EEF2F6")
        nb.add(f, text="  运行日志  ")
        bar = tk.Frame(f, bg="#EEF2F6")
        bar.pack(fill="x", padx=8, pady=(8, 4))
        tk.Label(bar, text="筛选:", font=FONT).pack(side="left")
        self.var_filter = tk.StringVar(value="全部")
        cb = ttk.Combobox(bar, textvariable=self.var_filter,
                          values=["全部", "仅错误", "仅警告", "仅成功"], state="readonly",
                          width=10, font=FONT)
        cb.pack(side="left", padx=(4, 0))
        cb.bind("<<ComboboxSelected>>", lambda e: self._rebuild_log())
        self.var_scroll = tk.BooleanVar(value=True)
        tk.Checkbutton(bar, text="自动滚动", variable=self.var_scroll, font=FONT
                       ).pack(side="left", padx=14)
        tk.Button(bar, text="清空", font=FONT, command=self._clear_log).pack(side="right")
        tk.Button(bar, text="保存日志", font=FONT, command=self._save_log
                  ).pack(side="right", padx=6)

        self.log_text = ScrolledText(f, font=("Consolas", 10), wrap="word",
                                     state="disabled", bg="white", fg=COLORS["info"],
                                     insertbackground="#2C3E50", relief="flat",
                                     padx=8, pady=6)
        for k, v in COLORS.items():
            self.log_text.tag_configure(k, foreground=v)
        self.log_text.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    # ---------- 4 运行结果 ----------
    def _tab_results(self, nb):
        f = tk.Frame(nb, bg="#EEF2F6")
        nb.add(f, text="  运行结果  ")
        bar = tk.Frame(f, bg="#EEF2F6")
        bar.pack(fill="x", padx=8, pady=(8, 4))
        tk.Button(bar, text="⬇ 导出 Excel", font=FONT, bg="#1E8449", fg="white",
                  padx=10, pady=2, command=self._export_results).pack(side="left")
        tk.Button(bar, text="🔄 刷新", font=FONT, command=self._refresh_results
                  ).pack(side="left", padx=(6, 0))
        tk.Button(bar, text="🗑 清空", font=FONT, bg="#C0392B", fg="white", padx=10,
                  pady=2, command=lambda: self._clear_rec("results")
                  ).pack(side="left", padx=(6, 0))
        self.var_res_cnt = tk.StringVar(value="")
        tk.Label(bar, textvariable=self.var_res_cnt, font=FONT_S, fg="#7F8C8D"
                 ).pack(side="right")

        cols = ("time", "acc", "phone", "status", "bal", "gain")
        heads = ("时间", "账号", "手机号", "状态", "话费余额", "本次收益")
        widths = (140, 60, 120, 110, 110, 320)
        self.res_tree = ttk.Treeview(f, columns=cols, show="headings", selectmode="browse")
        for c, h, w in zip(cols, heads, widths):
            self.res_tree.heading(c, text=h)
            self.res_tree.column(c, width=w, anchor="w", stretch=(c == "gain"))
        vsb = ttk.Scrollbar(f, orient="vertical", command=self.res_tree.yview)
        self.res_tree.configure(yscrollcommand=vsb.set)
        self.res_tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=(0, 8))
        vsb.pack(side="right", fill="y", pady=(0, 8), padx=(0, 8))

    # ---------- 5 中奖记录 ----------
    def _tab_wins(self, nb):
        f = tk.Frame(nb, bg="#EEF2F6")
        nb.add(f, text="  中奖记录  ")
        bar = tk.Frame(f, bg="#EEF2F6")
        bar.pack(fill="x", padx=8, pady=(8, 4))
        tk.Button(bar, text="⬇ 导出 Excel", font=FONT, bg="#1E8449", fg="white",
                  padx=10, pady=2, command=self._export_wins).pack(side="left")
        tk.Button(bar, text="🔄 刷新", font=FONT, command=self._refresh_wins
                  ).pack(side="left", padx=(6, 0))
        tk.Button(bar, text="🗑 清空记录", font=FONT, bg="#C0392B", fg="white", padx=10,
                  pady=2, command=lambda: self._clear_rec("wins")).pack(side="left", padx=(6, 0))
        self.var_win_cnt = tk.StringVar(value="")
        tk.Label(bar, textvariable=self.var_win_cnt, font=FONT_S, fg="#7F8C8D"
                 ).pack(side="right")

        cols = ("time", "acc", "phone", "src", "kind", "content")
        heads = ("时间", "账号", "手机号", "来源", "类型", "内容")
        widths = (90, 55, 115, 130, 60, 400)
        self.win_tree = ttk.Treeview(f, columns=cols, show="headings", selectmode="browse")
        for c, h, w in zip(cols, heads, widths):
            self.win_tree.heading(c, text=h)
            self.win_tree.column(c, width=w, anchor="w", stretch=(c == "content"))
        vsb = ttk.Scrollbar(f, orient="vertical", command=self.win_tree.yview)
        self.win_tree.configure(yscrollcommand=vsb.set)
        self.win_tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=(0, 8))
        vsb.pack(side="right", fill="y", pady=(0, 8), padx=(0, 8))

    # ---------- 6 设置 ----------
    def _tab_settings(self, nb):
        f = tk.Frame(nb, bg="#EEF2F6")
        nb.add(f, text="  设置  ")
        wrap = tk.Frame(f, bg="#EEF2F6")
        wrap.pack(fill="both", expand=True, padx=10, pady=10)
        self.vars = {}

        def entry(parent, key, label, width=52, hint="", browse=None):
            r = entry.r
            tk.Label(parent, text=label, font=FONT, bg="#EEF2F6").grid(
                row=r, column=0, sticky="w", pady=4, padx=(0, 10))
            v = tk.StringVar(value=str(self.settings._d.get(key, "")))
            self.vars[key] = v
            tk.Entry(parent, textvariable=v, width=width, font=FONT).grid(
                row=r, column=1, sticky="w", pady=4)
            if hint:
                tk.Label(parent, text=hint, font=FONT_S, fg="#909497", bg="#EEF2F6"
                         ).grid(row=r, column=2, sticky="w", padx=8)
            if browse:
                tk.Button(parent, text="浏览…", font=FONT_S, command=browse
                          ).grid(row=r, column=3, sticky="w", padx=6)
            entry.r += 1
            return v
        entry.r = 0

        p1 = ttk.LabelFrame(wrap, text=" 推送通知（pushplus） ")
        p1.pack(fill="x", pady=(0, 8))
        entry(p1, "pushplus_token", "推送 Token:", 50, "留空则不推送，仅在本窗口看日志")
        entry(p1, "pushplus_topic", "群组编码:", 50, "可选，一对多推送")

        p2 = ttk.LabelFrame(wrap, text=" 运行参数 ")
        p2.pack(fill="x", pady=(0, 8))
        entry(p2, "grab_amount", "抢兑面额:", 12, "默认 5（匹配含「5元/5话费」的奖品）")
        entry(p2, "ah_friday_amount", "安徽周五红包:", 12, "如 50；留空=不执行")
        entry(p2, "attempt_count", "新疆抽奖次数:", 12, "默认 1")
        entry(p2, "ttxc_garbage_wait", "通通乡村等待秒:", 12, "默认 28")

        # ---- 海岛逐浪 / 芒果 AI入戏 (v1.2.1 新增) ----
        p2b = ttk.LabelFrame(wrap, text=" 联通云盘 · 海岛逐浪 / AI入戏（v1.2.1 新增） ")
        p2b.pack(fill="x", pady=(0, 8))

        r0 = tk.Frame(p2b, bg="#EEF2F6")
        r0.pack(fill="x", padx=10, pady=(6, 2))
        tk.Label(r0, text="本地人脸图:", font=FONT, bg="#EEF2F6").pack(side="left")
        self.var_face = tk.StringVar(value="")
        tk.Label(r0, textvariable=self.var_face, font=FONT_S, fg="#7F8C8D",
                 bg="#EEF2F6", anchor="w", width=46).pack(side="left", padx=(8, 0))
        tk.Button(r0, text="添加图片…", font=FONT_S, command=self._face_add).pack(side="left")
        tk.Button(r0, text="清空", font=FONT_S, command=self._face_clear).pack(side="left", padx=6)

        self.face_list = tk.Listbox(p2b, height=4, font=FONT_S, activestyle="none")
        self.face_list.pack(fill="x", padx=10, pady=(2, 2))
        tk.Label(p2b, text="不选则自动读取数据目录下的 face_images\\ ；支持 jpg/jpeg/png，"
                           "多个文件会按随机顺序逐个尝试直到通过。",
                 font=FONT_S, fg="#909497", bg="#EEF2F6", justify="left", anchor="w",
                 wraplength=760).pack(fill="x", padx=10, pady=(0, 7))

        p2c = ttk.LabelFrame(wrap, text=" 云盘 AI入戏 · 高级（可留空） ")
        p2c.pack(fill="x", pady=(0, 8))
        entry(p2c, "cmf_img_fid", "云盘人脸图 FID:", 34, "指定已上传云盘的图片 FID")
        entry(p2c, "cmf_template_id", "模板 ID:", 34, "留空用内置默认")
        entry(p2c, "cmf_target_id", "选角 targetId:", 34, "留空自动选第一个")
        entry(p2c, "cmf_source", "活动入口:", 34, "留空用内置默认")

        p3 = ttk.LabelFrame(wrap, text=" 代理（可选） ")
        p3.pack(fill="x", pady=(0, 8))
        entry(p3, "proxy_api", "代理提取接口:", 52, "http/socks5 提取链接")
        entry(p3, "proxy_type", "代理类型:", 20, "socks5 / http")

        # 复选框
        p4 = ttk.LabelFrame(wrap, text=" 其他 ")
        p4.pack(fill="x", pady=(0, 8))
        self.check_vars = {}
        for key, label in (("hometown_enable", "云盘家乡打卡（内置素材，无需外链）"),
                           ("cmf_del_cloud_photos", "AI入戏后清理网盘临时照片"),
                           ("query_only", "查询模式（只查资产不执行任务）"),
                           ("run_on_start", "启动程序后自动运行一次")):
            v = tk.BooleanVar(value=bool(self.settings._d.get(key, True)))
            self.check_vars[key] = v
            tk.Checkbutton(p4, text=label, variable=v, font=FONT, bg="#EEF2F6"
                           ).pack(anchor="w", padx=10, pady=3)

        tk.Button(wrap, text="💾 保存全部设置", font=FONT_B, bg="#2471A3", fg="white",
                  padx=18, pady=6, command=self.save_settings).pack(pady=(4, 0))

    # --------------------------------------------------------
    # 账号操作
    # --------------------------------------------------------
    def _refresh_accounts(self):
        t = self.acc_tree
        t.delete(*t.get_children())
        for i, a in enumerate(self.store.accounts, 1):
            cfg = a.config.replace("\n", " ")
            if len(cfg) > 46:
                cfg = cfg[:44] + "…"
            t.insert("", "end", iid=a.id, values=(
                i, a.label(), cfg, "✔" if a.enabled else "✖",
                a.last_time or "—", a.last_status or "—", a.last_balance or "—"))
        self.var_status.set("就绪 · 共 %d 个账号（启用 %d）· 中奖记录 %d 条" % (
            len(self.store.accounts),
            sum(1 for a in self.store.accounts if a.enabled),
            records.count()))

    def _sel(self):
        return list(self.acc_tree.selection())

    def _acc_add(self):
        d = AccountDialog(self, "添加账号", multi=True)
        self.wait_window(d)
        if not d.result:
            return
        n = self.store.add(d.result[0], d.result[1])
        self.store.save()
        self._refresh_accounts()
        self.bus.emit("➕ 新增 %d 个账号" % n, "ok")

    def _acc_import(self):
        self._acc_add()

    def _acc_edit(self):
        ids = self._sel()
        if len(ids) != 1:
            messagebox.showinfo(APP_TITLE, "请先在列表中选中一个账号", parent=self)
            return
        a = self.store.get(ids[0])
        if not a:
            return
        d = AccountDialog(self, "修改账号", config=a.config, note=a.note)
        self.wait_window(d)
        if not d.result:
            return
        a.config, a.note = d.result
        self.store.save()
        self._refresh_accounts()
        self.bus.emit("✏️ 账号已更新: %s" % a.label(), "ok")

    def _acc_del(self):
        ids = self._sel()
        if not ids:
            messagebox.showinfo(APP_TITLE, "请先选中要删除的账号", parent=self)
            return
        if not messagebox.askyesno(
                APP_TITLE, "确定删除选中的 %d 个账号？\n（只删本程序记录，不影响联通侧数据）"
                % len(ids), parent=self):
            return
        self.store.remove(ids)
        self.store.save()
        self._refresh_accounts()
        self.bus.emit("🗑 已删除 %d 个账号" % len(ids), "warn")

    def _acc_toggle(self, on):
        ids = self._sel()
        if not ids:
            messagebox.showinfo(APP_TITLE, "请先选中账号", parent=self)
            return
        self.store.toggle(ids, on)
        self.store.save()
        self._refresh_accounts()

    # --------------------------------------------------------
    # 手机号 + 短信验证码登录
    # --------------------------------------------------------
    def _sms_login(self):
        """调起短信验证码登录对话框。

        协议层来自 unicom_login_server.py（逆向官方 App 接口）；本界面只负责
        入口、后台线程调度与凭证导入。腾讯 JS 验证码在系统浏览器里完成。
        """
        ok, why = sms_login.available()
        if not ok:
            messagebox.showerror(APP_TITLE, why, parent=self)
            return
        self.bus.emit("📱 打开手机号验证码登录（协议层复用 unicom_login_server.py）", "sys")
        d = SmsLoginDialog(self, self.store, self.bus)
        self.wait_window(d)
        self._refresh_accounts()

    # --------------------------------------------------------
    # 人脸图 (海岛逐浪 / AI入戏, v1.2.1)
    # --------------------------------------------------------
    def _face_refresh(self):
        """把当前人脸图清单画到列表和摘要标签上"""
        paths_list = list(getattr(self.settings, "face_images", None) or [])
        self.face_list.delete(0, "end")
        for p in paths_list:
            self.face_list.insert("end", p)
        if paths_list:
            self.var_face.set("已选 %d 张" % len(paths_list))
        else:
            self.var_face.set("未选（自动用 face_images 目录）")

    def _face_add(self):
        files = filedialog.askopenfilenames(
            parent=self, title="选择人脸图片",
            filetypes=[("图片", "*.jpg *.jpeg *.png"), ("所有文件", "*.*")])
        if not files:
            return
        cur = list(getattr(self.settings, "face_images", None) or [])
        added = 0
        for f in files:
            f = os.path.abspath(f)
            if f not in cur:
                cur.append(f)
                added += 1
        self.settings.face_images = cur
        if self.settings.save()[0]:
            self._face_refresh()
            self.bus.emit("🖼 已添加 %d 张人脸图（共 %d 张）" % (added, len(cur)), "ok")
        else:
            self.bus.emit("❌ 人脸图保存失败", "error")

    def _face_clear(self):
        if not (getattr(self.settings, "face_images", None) or []):
            return
        if not messagebox.askyesno(APP_TITLE, "清空人脸图清单？\n（只清本程序记录，不删除图片文件）",
                                   parent=self):
            return
        self.settings.face_images = []
        self.settings.save()
        self._face_refresh()
        self.bus.emit("🖼 人脸图清单已清空，运行时将回退到 face_images 目录", "warn")

    # --------------------------------------------------------
    # 设置保存
    # --------------------------------------------------------
    def save_settings(self):
        # 功能开关页
        for key, var in list(self.switch_vars.items()):
            try:
                setattr(self.settings, key, var.get())
            except Exception as e:
                self.bus.emit("⚠️ 开关 %s 保存失败: %s" % (key, e), "warn")
        # 设置页 (字符串)
        for key, var in getattr(self, "vars", {}).items():
            try:
                setattr(self.settings, key, var.get())
            except Exception as e:
                self.bus.emit("⚠️ 设置 %s 保存失败: %s" % (key, e), "warn")
        # 设置页 (复选框)
        for key, var in getattr(self, "check_vars", {}).items():
            try:
                setattr(self.settings, key, var.get())
            except Exception:
                pass
        ok, err = self.settings.save()
        self._save_schedule()
        if ok:
            enabled = [l for k, l, _h in MODULE_SWITCHES
                       if getattr(self.settings, k, True)]
            self.bus.emit("💾 设置已保存 · 启用 %d/%d 个模块: %s"
                          % (len(enabled), len(MODULE_SWITCHES), "、".join(enabled)), "ok")
        else:
            self.bus.emit("❌ 设置保存失败: %s" % err, "error")

    def _save_schedule(self):
        try:
            self.settings.schedule_enabled = bool(self.var_sched_on.get())
            self.settings.schedule_times = self.var_sched_times.get()
            self.settings.save()
            times = scheduler.parse_times(self.settings.schedule_times)
            if self.settings.schedule_enabled and times:
                self.bus.emit("⏰ 定时已开启: 每天 %s 自动运行" % "、".join(times), "sys")
            else:
                self.bus.emit("⏰ 定时已关闭", "sys")
            self._poll_status()
        except Exception as e:
            self.bus.emit("⚠️ 定时设置保存失败: %s" % e, "warn")

    # --------------------------------------------------------
    # 日志
    # --------------------------------------------------------
    def _match(self, level):
        f = self._log_filter
        if f == "全部":
            return True
        if f == "仅错误":
            return level == "error"
        if f == "仅警告":
            return level in ("warn", "error")
        if f == "仅成功":
            return level == "ok"
        return True

    def _append_log(self, rec):
        if not self._match(rec["level"]):
            return
        tx = self.log_text
        tx.configure(state="normal")
        tx.insert("end", rec["text"] + "\n", (rec["level"],))
        if int(tx.index("end-1c").split(".")[0]) > 6000:
            tx.delete("1.0", "2000.0")
        if self.var_scroll.get():
            tx.see("end")
        tx.configure(state="disabled")

    def _rebuild_log(self):
        self._log_filter = self.var_filter.get()
        tx = self.log_text
        tx.configure(state="normal")
        tx.delete("1.0", "end")
        for rec in self.bus.lines[-3000:]:
            if self._match(rec["level"]):
                tx.insert("end", rec["text"] + "\n", (rec["level"],))
        if self.var_scroll.get():
            tx.see("end")
        tx.configure(state="disabled")

    def _clear_log(self):
        self.bus.clear()
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _save_log(self):
        if not self.bus.lines:
            messagebox.showinfo(APP_TITLE, "暂无日志", parent=self)
            return
        p = filedialog.asksaveasfilename(
            parent=self, title="保存日志", defaultextension=".txt",
            initialfile="运行日志_%s.txt" % time.strftime("%Y%m%d_%H%M%S"),
            filetypes=[("文本文件", "*.txt")])
        if not p:
            return
        try:
            n = self.bus.save_to(p)
            self.bus.emit("💾 已保存 %d 条日志到 %s" % (n, p), "ok")
        except Exception as e:
            self.bus.emit("❌ 保存日志失败: %s" % e, "error")

    def _poll_logs(self):
        for rec in self.bus.drain(400):
            self._append_log(rec)
        self.after(150, self._poll_logs)

    # --------------------------------------------------------
    # 记录表
    # --------------------------------------------------------
    def _refresh_results(self):
        t = self.res_tree
        t.delete(*t.get_children())
        rows = records.all_results()
        for r in rows:
            t.insert("", "end", values=(r.get("时间", ""), r.get("账号", ""),
                                        r.get("手机号", ""), r.get("状态", ""),
                                        r.get("话费余额", ""), r.get("本次收益", "")))
        self.var_res_cnt.set("共 %d 条运行记录" % len(rows))

    def _refresh_wins(self):
        t = self.win_tree
        t.delete(*t.get_children())
        rows = records.all_wins()
        for r in rows:
            t.insert("", "end", values=(r.get("时间", ""), r.get("账号", ""),
                                        r.get("手机号", ""), r.get("来源", ""),
                                        r.get("类型", ""), r.get("内容", "")))
        self.var_win_cnt.set("共 %d 条中奖/获取记录" % len(rows))
        self.var_status.set("就绪 · 共 %d 个账号（启用 %d）· 中奖记录 %d 条" % (
            len(self.store.accounts),
            sum(1 for a in self.store.accounts if a.enabled), len(rows)))

    def _clear_rec(self, kind):
        label = "中奖记录" if kind == "wins" else "运行结果"
        if not messagebox.askyesno(APP_TITLE, "确定清空全部%s？" % label, parent=self):
            return
        records.clear(kind)
        self._refresh_wins()
        self._refresh_results()
        self.bus.emit("🗑 %s已清空" % label, "warn")

    def _export_wins(self):
        rows = records.all_wins()
        if not rows:
            messagebox.showinfo(APP_TITLE, "暂无中奖记录可导出", parent=self)
            return
        p = filedialog.asksaveasfilename(
            parent=self, title="导出中奖记录", defaultextension=".xlsx",
            initialfile="中奖记录_%s.xlsx" % time.strftime("%Y%m%d_%H%M%S"),
            filetypes=[("Excel 工作簿", "*.xlsx"), ("CSV 文件", "*.csv")])
        if not p:
            return
        try:
            n = records.export_wins(p, rows)
            self.bus.emit("✅ 已导出 %d 条中奖记录到 %s" % (n, p), "ok")
        except Exception as e:
            self.bus.emit("❌ 导出失败: %s" % e, "error")

    def _export_results(self):
        rows = records.all_results()
        if not rows:
            messagebox.showinfo(APP_TITLE, "暂无运行记录可导出", parent=self)
            return
        p = filedialog.asksaveasfilename(
            parent=self, title="导出运行结果", defaultextension=".xlsx",
            initialfile="运行结果_%s.xlsx" % time.strftime("%Y%m%d_%H%M%S"),
            filetypes=[("Excel 工作簿", "*.xlsx"), ("CSV 文件", "*.csv")])
        if not p:
            return
        try:
            n = records.export_results(p, rows)
            self.bus.emit("✅ 已导出 %d 条运行记录到 %s" % (n, p), "ok")
        except Exception as e:
            self.bus.emit("❌ 导出失败: %s" % e, "error")

    # --------------------------------------------------------
    # 运行控制
    # --------------------------------------------------------
    def start_run(self):
        if self.running:
            messagebox.showinfo(APP_TITLE, "已有任务正在运行", parent=self)
            return
        if not self.store.enabled_configs():
            messagebox.showwarning(APP_TITLE, "还没有启用的账号，请先在「账号管理」中添加。",
                                   parent=self)
            self.nb.select(0)
            return
        self.save_settings()

        self.stop_event = threading.Event()
        self.running = True
        self.btn_run.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.var_run.set("⏳ 运行中…")
        self.var_progress.set("")

        settings, store, bus, ev = self.settings, self.store, self.bus, self.stop_event

        def work():
            try:
                r = runner.run_batch(settings, store, bus, ev, on_account=self._on_account)
                self.after(0, lambda: self._run_done(r))
            except Exception as e:
                import traceback as tb
                tb.print_exc()
                bus.emit("❌ 运行异常: %s" % e, "error")
                self.after(0, lambda: self._run_done(None))

        self.worker = threading.Thread(target=work, name="uni-runner", daemon=True)
        self.worker.start()

    def _on_account(self, idx, total, label):
        try:
            self.after(0, lambda: self.var_progress.set("账号 %d/%d  %s" % (idx, total, label)))
        except Exception:
            pass

    def _run_done(self, result):
        self.running = False
        self.worker = None
        self.btn_run.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.var_run.set("🛑 已停止" if (result or {}).get("aborted") else "✅ 完成")
        self.var_progress.set("")
        self._refresh_accounts()
        self._refresh_results()
        self._refresh_wins()

    def stop_run(self):
        if not self.running:
            return
        self.stop_event.set()
        self.var_run.set("⏹ 正在停止…")
        self.bus.emit("⏹ 已发送停止指令, 将在当前模块结束后中断", "warn")

    # --------------------------------------------------------
    # 状态 / 关闭
    # --------------------------------------------------------
    def _poll_status(self):
        try:
            self.var_next.set(self.sched.status())
        except Exception:
            pass
        self.after(1000, self._poll_status)

    def _on_close(self):
        if self.running:
            if not messagebox.askyesno(
                    APP_TITLE, "任务正在运行，确定退出吗？\n（未完成的账号将不会执行）", parent=self):
                return
            self.stop_event.set()
        try:
            self.sched.stop()
        except Exception:
            pass
        try:
            self.settings.schedule_enabled = bool(self.var_sched_on.get())
            self.settings.schedule_times = self.var_sched_times.get()
            self.settings.save()
        except Exception:
            pass
        self.destroy()


def run():
    App().mainloop()
