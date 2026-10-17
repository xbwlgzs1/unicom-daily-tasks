# -*- coding: utf-8 -*-
"""手机号 + 短信验证码登录 —— 图形界面装配层.

本模块**不重新实现**登录协议。协议层（逆向自官方 App 接口）已存在于
``unicom_login_server.py``，其 ``api_send_sms`` / ``api_validate_captcha`` /
``api_login`` / ``Ctx`` / ``PAGE`` / ``Handler`` 均为模块级符号，文件底部有
``if __name__ == "__main__"`` 守卫，import 不会启动服务。

本装配层只做四件事（协议层源码零改动）：

1. **路径重定向（打包关键）**：协议层用 ``BASE = dirname(abspath(__file__))``
   决定写目标 —— ``STATE`` / ``CREDS`` / ``READY_FLAG`` 是模块级常量，另有
   **一处内联**写路径（``unicom_cookie_line.txt``，协议层 L218 直接
   ``os.path.join(BASE, …)``）。onefile 打包后 ``__file__`` 落在
   ``sys._MEIPASS``（进程退出即删），凭证会丢。
   ``STATE`` / ``CREDS`` / ``READY_FLAG`` 直接改指 :func:`app.paths.data_dir`，
   做法与 ``app/runner.py::apply_config`` 对 ``legacy.UNICOM_TOKEN_CACHE_PATH``
   的既有做法一致：**装配层赋值，不改协议实现本身**。内联那处没有可赋值的常量，
   改由 :func:`redirect_cookie_line_write` 在**协议模块自己的命名空间**里包装
   ``open`` 拦截 —— 同样**协议源码零改动**
   （``unicom_login_server.py`` 本轮 sha256
   ``EB28645C86CFB25B7585A20C3FB6A4F6464AF67571C58A59C8EC7D0A352BDA8C``）。

   注意纪律冲突（如实登记）：契约 ``REQ-UNICOM-SMSLOGIN`` §4.G3 的 checker C7
   是**文本层**判据（要求协议源码「无内联 BASE 写路径」且「存在模块级常量
   ``COOKIE_LINE``」）。这与 t9 的 outOfScope（禁止改 ``unicom_login_server.py``）
   不能同时满足，故本轮**不改协议源码**，改用**行为层**证据证明打包后不丢凭证
   （见 ``test_sms_login.py`` 的「路径重定向」项）。

2. **本地网页承载腾讯验证码**：腾讯 TJCaptcha 是 JS 组件，tkinter 无法承载。
   这里在**后台守护线程**里起 ``HTTPServer`` 绑 ``127.0.0.1``，用 ``webbrowser``
   打开协议层现成的网页；用户在网页里完成「发码 → 过验证码 → 填码登录」，
   本模块轮询凭证文件检测结果。**不在 tkinter 内重画验证码。**

3. **脱敏封装**：协议层在成功分支会 ``print`` 64 字符 ``token_online`` 与 40 字符
   ``app_id`` 的 **32 字符前缀**（协议层 L222–L225）。GUI 模式下 ``sys.stdout``
   已被 ``logstream`` 接管并落盘到用户日志 + 日志面板，故这些行**会**进用户日志。
   本层在**协议模块自己的命名空间**里装一个掩码 ``print``
   （:func:`redirect_protocol_print`）——模块全局名优先于内建名，因此只影响该模块
   的 print，不动全局 ``sys.stdout``（避免并发请求期间丢掉 GUI 自己的日志）。
   :class:`quiet_protocol` 另作为可选的「整段静音」工具保留。
   本层自己的输出一律经过 :func:`mask` 掩码（只留首 3 位）。

4. **离线可测的纯逻辑**：手机号/验证码格式校验、凭证解析、去重导入、
   错误分支文案 —— 全部是不触网的纯函数，``test_sms_login.py`` 直接覆盖。

诚实性：本模块只能证明「代码路径 + 离线单测 + UI 可构建 + exe 可启动」。
**真实联通侧端到端未验证 —— 需要真手机收码 + 人工完成腾讯验证码。**
"""
import json
import os
import re
import threading
import time
import webbrowser

# 协议层模块名（供测试替换/预加载）
SERVER_MODULE = "unicom_login_server"

# ⚠️ 打包关键：这一行是**故意**存在的静态导入，唯一目的是让 PyInstaller 的静态
# 分析把协议层收进 exe 的 PYZ。PyInstaller 看不见 importlib.import_module(变量)，
# 只用动态导入时打包产物里不会有 unicom_login_server，打包后短信登录入口即不可用
# （本轮实测：旧 exe 的 PYZ 1084 个模块中不含 unicom_login_server）。
# 用 try/except 包住，使 requests / pycryptodome 缺失时仍能优雅降级（available()
# 返回 False 并给出可读原因），而不是让 app.sms_login 整个 import 失败。
try:
    import unicom_login_server as _STATIC_SERVER_MODULE     # noqa: F401
except Exception:                                            # pragma: no cover
    _STATIC_SERVER_MODULE = None

DEFAULT_PORT = 8787
PORT_ENV = "UNICOM_SMS_LOGIN_PORT"
PREFERRED_PORTS = (8787, 8788, 8789, 8790, 8791)

MASK_PREFIX = 3          # 掩码保留的首部字符数（< 契约阈值 8）
CODE_MIN, CODE_MAX = 4, 8


# ============================================================
# 脱敏
# ============================================================
def mask(secret, prefix=MASK_PREFIX):
    """把密钥类值压成 ``abc…(len=N)``；长度不足以复用，可安全入日志。

    绝不返回 >= 8 字符的明文——这正是契约 §5.S2/S3 的阈值。
    """
    s = "" if secret is None else str(secret)
    if not s:
        return "(空)"
    head = s[:max(0, int(prefix))]
    return "%s…(len=%d)" % (head, len(s))


def safe_message(exc):
    """把任意异常压成一行可读中文，且不带任何请求体/响应体内容。"""
    name = type(exc).__name__
    text = str(exc)
    for bad in ("token", "appId", "app_id", "cookie", "password", "验证码"):
        # 异常文本里若夹带敏感键名，只保留异常类型
        if bad.lower() in text.lower():
            return "网络/协议异常：%s（详情已省略，避免泄漏凭证）" % name
    text = text[:60]
    return "网络/协议异常：%s %s" % (name, text) if text else "网络/协议异常：%s" % name


# ============================================================
# 纯逻辑（离线可单测）
# ============================================================
def normalize_mobile(raw):
    """手机号输入规整；顺带把全角数字转半角（用户从别处粘贴很常见）。"""
    s = "" if raw is None else str(raw).strip()
    out = []
    for ch in s:
        if "\uff10" <= ch <= "\uff19":          # 全角 ０-９
            out.append(chr(ord(ch) - 0xFEE0))
        elif ch in " \t-()":
            continue
        else:
            out.append(ch)
    return "".join(out)


def validate_mobile(raw):
    """返回 ``(mobile, err)``；``err`` 非空表示不得发起任何网络请求。"""
    m = normalize_mobile(raw)
    if not m:
        return m, "请输入手机号"
    if len(m) != 11 or not m.isdigit():
        return m, "手机号必须是 11 位数字"
    if not m.startswith("1"):
        return m, "手机号必须以 1 开头"
    return m, ""


def validate_code(raw):
    """验证码格式校验（4–8 位数字）。返回 ``(code, err)``。"""
    c = "" if raw is None else str(raw).strip()
    if not c:
        return c, "请输入短信验证码"
    if not c.isdigit():
        return c, "验证码只能是数字"
    if not (CODE_MIN <= len(c) <= CODE_MAX):
        return c, "验证码格式错误：应为 %d–%d 位数字" % (CODE_MIN, CODE_MAX)
    return c, ""


def credentials_to_config(creds):
    """把凭证字典解析成账号列表用的 ``token#appId``。

    返回 ``(config, err)``。``config`` 与既有 ``Token#AppId`` 条目格式完全一致
    （见 ``app/settings.py::AccountStore.add`` 与契约 §7.R4）。
    """
    if not isinstance(creds, dict):
        return "", "凭证内容不是对象"
    token = str(creds.get("token_online") or "").strip()
    app_id = str(creds.get("app_id") or "").strip()
    if not token:
        return "", "凭证里没有 token_online"
    if not app_id:
        return "", "凭证里没有 app_id"
    if "#" in token:
        return "", "token_online 含 '#'，无法安全拼接"
    return "%s#%s" % (token, app_id), ""


def import_credentials(store, creds, note="短信验证码登录"):
    """把凭证去重写入账号库。返回 ``(added, config)``。

    ``added`` 为 0 表示该账号已存在（去重命中），调用方须如实提示用户，
    不得静默写入。
    """
    config, err = credentials_to_config(creds)
    if err:
        raise ValueError(err)
    added = store.add(config, note=note)
    return added, config


# ============================================================
# 协议层装配：路径重定向
# ============================================================
def protocol_paths(server, data_dir):
    """协议层会写盘的**全部**目标在本轮数据目录下的落点（纯函数，便于断言）。"""
    d = os.path.abspath(data_dir)
    return {
        "STATE": os.path.join(d, "sms_login_state.json"),
        "CREDS": os.path.join(d, "unicom_sms_creds.json"),
        "READY_FLAG": os.path.join(d, "unicom_sms_ready.flag"),
        "COOKIE_LINE": os.path.join(d, "unicom_cookie_line.txt"),
    }


def configure_paths(server, data_dir):
    """把协议层的写盘目标改指 ``data_dir``。

    ``STATE`` / ``CREDS`` / ``READY_FLAG`` 是模块级常量，直接赋值即可（与
    ``app/runner.py::apply_config`` 改 ``legacy.UNICOM_TOKEN_CACHE_PATH`` 同法）。
    ``unicom_cookie_line.txt`` 的路径在协议层是**内联** ``os.path.join(BASE, …)``，
    没有对应常量，故交由 :func:`redirect_cookie_line_write` 在 ``open`` 层拦截。

    返回 ``{名称: 实际路径}``，供测试与日志断言。
    """
    targets = protocol_paths(server, data_dir)
    done = {}
    for name in ("STATE", "CREDS", "READY_FLAG"):
        setattr(server, name, targets[name])
        done[name] = getattr(server, name)
    done["COOKIE_LINE"] = redirect_cookie_line_write(server)
    redirect_protocol_print(server)          # 协议层 print 的凭证前缀不得进 GUI 日志
    return done


def cookie_line_for(token, app_id):
    """协议层 ``unicom_cookie_line.txt`` 的内容格式（桌面脚本现成配置行）。"""
    return 'chinaUnicomCookie="%s#%s"\n' % (token, app_id)


def redirect_cookie_line_write(server, data_dir=None):
    """把协议层对 ``unicom_cookie_line.txt`` 的写入改到数据目录。**协议源码零改动。**

    背景：协议层 ``api_login`` 里这一处写路径是内联的
    ``open(os.path.join(BASE, "unicom_cookie_line.txt"), "w", …)``，没有可赋值的模块级
    常量。onefile 打包下 ``BASE`` 指向 ``sys._MEIPASS``（进程退出即删）→ 该文件会丢。

    做法：在**协议模块自己的命名空间**里把内建 ``open`` 包一层，只对
    「以 ``unicom_cookie_line.txt`` 结尾」的路径改写目标目录（改到 ``CREDS`` 所在目录，
    即 :func:`app.paths.data_dir`），其余读写全部原样透传。不改协议源码、不改全局内建。

    返回 cookie_line 的实际落点（供断言）。
    """
    dest_dir = os.path.dirname(os.path.abspath(data_dir or server.CREDS))
    target = os.path.join(dest_dir, "unicom_cookie_line.txt")
    server.__dict__["COOKIE_LINE"] = target      # 便于断言/诊断，不参与协议逻辑
    if server.__dict__.get("_cookie_line_open_patched"):
        return target

    import builtins
    original_open = server.__dict__.get("_original_open") or builtins.open

    def patched_open(file, *a, **kw):
        try:
            if isinstance(file, (str, bytes)) and str(file).endswith(
                    "unicom_cookie_line.txt"):
                return original_open(target, *a, **kw)
        except Exception:
            pass
        return original_open(file, *a, **kw)

    server.__dict__["_original_open"] = original_open
    server.__dict__["open"] = patched_open     # 只影响该模块的对象命名空间
    server.__dict__["_cookie_line_open_patched"] = True
    return target


def redirect_protocol_print(server):
    """把协议模块命名空间里的 ``print`` 换成掩码版。**协议源码零改动。**

    背景：协议层成功分支（L222–L225）会 print 64 字符 ``token_online`` 与 40 字符
    ``app_id`` 的 **32 字符前缀**。GUI 模式下 ``sys.stdout`` 已被 ``app/logstream``
    接管并落盘到用户日志文件 + 日志面板，所以这些行在真实使用中**会**进日志 ——
    ``quiet_protocol`` 那段「丢弃 sys.stdout」的旧注释是不成立的：它只有在有人显式
    用 ``with quiet_protocol()`` 包住调用时才生效，而 GUI 路径并没有包。

    做法：Python 的模块全局名解析优先于内建名，故在**协议模块自己的 ``__dict__``**
    里放一个 ``print`` 覆盖内建 ``print``：只影响该模块内部的 print 调用，不动
    ``sys.stdout``（避免并发请求时把 GUI 自己的日志一起吞掉）。

    掩码规则：任何 ``键: 值`` 形态的行，若值长度 >= :data:`MASK_PREFIX` 阈值
    （8，与契约 §5.S2/S3 一致）则把值压成 ``mask()`` 形态；非敏感行原样透传。
    """
    if server.__dict__.get("_print_patched"):
        return server.__dict__.get("_original_print")
    import builtins
    original_print = server.__dict__.get("_original_print") or builtins.print

    # 只针对协议层实际会打的两类行：token_online / app_id（含 cookies 行不敏感）
    key_re = re.compile(r"(token_online|app_id)\s*[:=]\s*(\S+)")

    def masked_print(*args, **kw):
        try:
            text = " ".join("" if a is None else str(a) for a in args)
            text = key_re.sub(
                lambda m: "%s: %s" % (m.group(1), mask(m.group(2))), text)
            original_print(text, **kw)
        except Exception:
            pass
        return None

    server.__dict__["_original_print"] = original_print
    server.__dict__["print"] = masked_print   # 只影响该模块的对象命名空间
    server.__dict__["_print_patched"] = True
    return original_print


def load_ctx_from_state(server):
    """只从装配后的 ``STATE`` 读会话上下文；**不**触网、不读项目目录。

    协议层原有的 ``load_ctx()`` 在 STATE 缺失时会回退到项目内文件，若该文件
    是上一轮别的号码留下的，就会用错上下文登录（契约 §10.0 第 3 条）。
    装配层一律走这个受控入口。
    """
    path = getattr(server, "STATE", "")
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return server.Ctx.from_dict(json.load(f))
    except Exception:
        return None


def new_ctx(server, mobile):
    """为一轮会话新建上下文（含随机 device_id 与 app_id）。"""
    import uuid
    ctx = server.Ctx(mobile, uuid.uuid4().hex, server.generate_app_id())
    with open(server.STATE, "w", encoding="utf-8") as f:
        json.dump(ctx.to_dict(), f, ensure_ascii=False, indent=2)
    return ctx


# ============================================================
# 静音协议层的凭证打印
# ============================================================
class _NullStream(object):
    """丢弃流：协议层成功分支的 print（含 32 字符 token/app_id 前缀）不进日志。"""

    encoding = "utf-8"

    def write(self, _s):
        return len(_s or "")

    def flush(self):
        pass

    def isatty(self):
        return False


class quiet_protocol(object):
    """把 ``sys.stdout`` 临时换成丢弃流，使协议层内部的 print 不出现在程序日志里。

    用法::

        with quiet_protocol():
            res = api_login(ctx, code)

    仅覆盖 ``sys.stdout``；``sys.stderr`` 不动（真实异常仍可见，便于排障）。
    """

    def __enter__(self):
        import sys
        self._sys = sys
        self._saved = sys.stdout
        sys.stdout = _NullStream()
        return self

    def __exit__(self, *exc):
        try:
            self._sys.stdout = self._saved
        except Exception:
            pass
        return False


# ============================================================
# 离线校验（调用协议层，但失败时绝不触网）
# ============================================================
def offline_send_check(server, raw_mobile):
    """手机号格式校验：不合法时**不得**发起网络请求。返回 ``(mobile, err)``。"""
    return validate_mobile(raw_mobile)


def offline_login_check(server, raw_code):
    """验证码格式校验：不合法时**不得**发起网络请求。返回 ``(code, err)``。"""
    return validate_code(raw_code)


# ============================================================
# 本地登录服务（后台线程 + 可管理生命周期）
# ============================================================
def port_in_use(port, timeout=0.35):
    """``port`` 是否真的被占用。

    ⚠️ Windows 上只靠 ``bind`` 判断**不可靠**：``SO_REUSEADDR`` 允许重复绑定
    已占用的地址，会给出假可用。故先用「连得上 = 有人在听」判定，再用不带
    ``SO_REUSEADDR`` 的 bind 兜底（能连上但不 accept 的半开端口也能拦住）。
    """
    import socket
    c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        c.settimeout(timeout)
        return c.connect_ex(("127.0.0.1", int(port))) == 0
    except Exception:
        return False
    finally:
        c.close()


def pick_port(preferred=None):
    """选一个可用端口：优先 ``preferred``/环境变量，被占用则顺延。

    返回 ``(port, note)``；``note`` 非空说明发生了换端口，必须提示用户。
    全部候选都不可用时返回 ``(0, …)``，由调用方交系统随机分配（不静默失败）。
    """
    import socket
    env = os.environ.get(PORT_ENV, "").strip()
    want = preferred
    if want is None and env.isdigit():
        want = int(env)
    if want is None:
        want = DEFAULT_PORT
    for cand in [want] + [p for p in PREFERRED_PORTS if p != want]:
        if port_in_use(cand):
            continue
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # 故意不设 SO_REUSEADDR: 否则 Windows 会允许绑到已被占用的地址
            s.bind(("127.0.0.1", cand))
        except OSError:
            continue
        finally:
            s.close()
        return cand, ("" if cand == want else
                      "默认端口 %d 被占用，已改用 %d" % (want, cand))
    return 0, "候选端口 %s 均被占用，交由系统随机分配" % (
        ", ".join(str(p) for p in [want] + list(PREFERRED_PORTS)),)


class LoginService(object):
    """协议层本地网页服务的生命周期封装（后台守护线程）。

    - ``start()``：装配路径 → 选端口 → 起服务 → 返回 URL（**不自动开浏览器**）
    - ``open_browser()``：用系统浏览器打开页面（腾讯 JS 验证码在此完成）
    - ``shutdown()``：停服务并释放端口
    - ``wait_credentials(timeout)``：**不阻塞 UI** 的轮询等待（供后台线程调用）
    """

    def __init__(self, server=None, data_dir=None, port=None):
        self._server = server or load_server()
        self._data_dir = data_dir or _default_data_dir()
        self._port = port
        self._httpd = None
        self._thread = None
        self.paths = {}
        self.port_note = ""
        self.url = ""

    # ---------- 装配 ----------
    def configure(self):
        self.paths = configure_paths(self._server, self._data_dir)
        redirect_cookie_line_write(self._server)
        return self.paths

    # ---------- 生命周期 ----------
    def start(self):
        if self._httpd is not None:
            return self.url
        self.configure()
        port, note = pick_port(self._port)
        self.port_note = note
        # 绑 127.0.0.1：仅本机回环，禁止 0.0.0.0
        self._httpd = self._server.HTTPServer(("127.0.0.1", port), self._server.Handler)
        self._port = int(self._httpd.server_address[1])
        self.url = "http://127.0.0.1:%d/" % self._port
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        name="uni-sms-login-http", daemon=True)
        self._thread.start()
        return self.url

    def open_browser(self):
        if not self.url:
            self.start()
        try:
            webbrowser.open(self.url)
            return True, ""
        except Exception as e:
            return False, "无法自动打开浏览器：%s" % type(e).__name__

    def shutdown(self):
        if self._httpd is None:
            return
        try:
            self._httpd.shutdown()
            self._httpd.server_close()
        except Exception:
            pass
        finally:
            self._httpd = None
            self._thread = None

    @property
    def running(self):
        return self._httpd is not None

    # ---------- 状态 ----------
    @property
    def creds_path(self):
        return self.paths.get("CREDS") or os.path.join(self._data_dir,
                                                       "unicom_sms_creds.json")

    def credentials(self, not_before=None):
        """读凭证文件；``not_before`` 用于排除上一轮的历史凭证。返回 ``(creds, err)``。"""
        p = self.creds_path
        if not os.path.exists(p):
            return None, "尚未收到凭证"
        if not_before is not None:
            try:
                if os.path.getmtime(p) <= float(not_before):
                    return None, "尚未收到新的凭证"
            except OSError:
                return None, "凭证文件读取失败"
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return None, "凭证文件解析失败：%s" % type(e).__name__
        if not isinstance(data, dict):
            return None, "凭证文件格式异常"
        return data, ""

    def wait_credentials(self, not_before=None, timeout=300.0, interval=1.0,
                         poll_window=None):
        """阻塞等待（**必须在后台线程调用**）。返回 ``(creds, err)``。"""
        t0 = time.time()
        while True:
            if poll_window is not None and poll_window.is_set():
                return None, "已取消"
            creds, err = self.credentials(not_before=not_before)
            if creds is not None:
                return creds, ""
            if time.time() - t0 >= float(timeout):
                return None, "等待超时（未检测到登录完成的凭证）"
            time.sleep(float(interval))


# ============================================================
# 协议层载入 / 默认数据目录
# ============================================================
def _default_data_dir():
    from . import paths
    return paths.data_dir()


def load_server():
    """载入协议层模块。import 无副作用（文件底部有 ``__main__`` 守卫）。

    ⚠️ 打包关键：PyInstaller 的静态分析**看不见** ``importlib.import_module(变量)``，
    所以单靠这里动态导入，``unicom_login_server`` 不会被收进 exe 的 PYZ ——
    那样打包后 ``available()`` 会返回 False，短信登录入口直接不可用（本轮实测过
    该缺陷：旧 exe 的 PYZ 里没有 ``unicom_login_server``）。
    故模块顶部另有一个**静态**导入（:data:`_STATIC_SERVER_MODULE`），它才是让
    PyInstaller 把协议层打进去的原因；``load_server()`` 仍走 importlib 以便测试
    替换/重载。
    """
    import importlib
    return importlib.import_module(SERVER_MODULE)


def available():
    """协议层依赖是否齐备（requests / pycryptodome）。返回 ``(ok, reason)``。"""
    try:
        load_server()
        return True, ""
    except Exception as e:
        return False, "短信登录协议层不可用：%s（需 requests 与 pycryptodome）" % type(e).__name__


def start_service(port=None, data_dir=None):
    """便捷入口：装配 + 启动本地网页服务，返回 :class:`LoginService`。"""
    svc = LoginService(port=port, data_dir=data_dir)
    svc.start()
    return svc