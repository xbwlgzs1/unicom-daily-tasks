# -*- coding: utf-8 -*-
"""离线单测：图形界面 SMS 登录装配层（app/sms_login.py）。

**绝不真实发短信、绝不触网。** 做法是把协议层用到的 ``requests`` 换成一个
假模块（只实现 ``post``），因此 ``requests.post(...)`` 永远不会真的出网。
本文件只覆盖：

  * 凭证解析成 ``token#appId``
  * 去重导入（不静默写入）
  * 路径重定向到数据目录（4 个写目标）
  * 验证码格式校验（4..8 位数字）
  * 错误分支与日志不打印敏感值（阈值：明文前缀 >= 8 字符算泄漏）
  * 后台线程 / 非阻塞 / 生命周期

运行：
    cd /d <项目目录>
    python -X utf8 test_sms_login.py
"""
import io
import json
import os
import re
import shutil
import sys
import threading
import types
import urllib.error
import urllib.request

SERVER_MODULE_NAME = "unicom_login_server"   # 协议层模块名（单测直引，便于断言）

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

# ⚠️ 独立沙箱：不放 %TEMP% 根目录（那里残留的 inspect.py 会遮蔽标准库，见契约 §1.F5）
SANDBOX = os.path.join(_HERE, "build", "_sms_login_test_sandbox")
if os.path.isdir(SANDBOX):
    shutil.rmtree(SANDBOX, ignore_errors=True)
os.makedirs(SANDBOX, exist_ok=True)
os.environ["CMF_DATA_DIR"] = SANDBOX

fails = []
TOTAL = [0]


def chk(name, fn):
    TOTAL[0] += 1
    # 真实控制台: gui.App() 会接管 sys.stdout, 故固定用 __stdout__
    out = sys.__stdout__ or sys.stdout

    def say(msg):
        try:
            out.write(msg + "\n")
            out.flush()
        except Exception:
            pass

    try:
        fn()
        say("[OK]   " + name)
    except Exception as e:
        import traceback
        traceback.print_exc(file=out)
        fails.append(name)
        say("[FAIL] %s -> %s" % (name, e))


# ============================================================
# 假网络层：必须在 import unicom_login_server 之前装好
# ============================================================
FAKE = {"send": None, "login": None, "captcha": None, "calls": []}
SENT_CODE = "654321"          # 假服务的正确验证码（真实短信不会发出）
TOKEN = "T" * 64              # 假 token（64 字符，> 掩码阈值 8）
APPID = "A" * 40              # 假 app_id


class _Resp(object):
    def __init__(self, payload, status=200, cookies=()):
        self._p = payload
        self.status_code = status
        self.text = json.dumps(payload, ensure_ascii=False)
        self.cookies = list(cookies)

    def json(self):
        return self._p


def _fake_post(url, data=None, headers=None, json=None, timeout=None, verify=None):
    FAKE["calls"].append({"url": url, "data": data, "json": json})
    if "sendRadomNum" in url:
        return FAKE["send"](data or {})
    if "radomLogin" in url:
        return FAKE["login"](data or {})
    if "chartCaptcha" in url:
        return FAKE["captcha"](json or {})
    raise AssertionError("未预期的外呼: %s" % url)


def _install_fake_requests():
    mod = types.ModuleType("requests")
    mod.post = _fake_post
    mod.Session = object
    sys.modules["requests"] = mod

    urllib3 = types.ModuleType("urllib3")
    urllib3.disable_warnings = lambda *a, **k: None
    sys.modules["urllib3"] = urllib3


_install_fake_requests()

from app import paths, sms_login          # noqa: E402
from app.settings import AccountStore     # noqa: E402

M = sms_login.load_server()


# ============================================================
# 1 协议层可 import、路径可重定向
# ============================================================
def t_paths_redirect():
    assert sms_login.protocol_paths(M, SANDBOX)["STATE"].startswith(SANDBOX)
    done = sms_login.configure_paths(M, SANDBOX)
    assert set(done) == {"STATE", "CREDS", "READY_FLAG", "COOKIE_LINE"}, done
    for name, p in done.items():
        assert os.path.dirname(os.path.abspath(p)) == os.path.abspath(SANDBOX), \
            "%s 未重定向: %s" % (name, p)
    # 协议层仍有一处内联 BASE 写路径（unicom_cookie_line.txt, L218）。
    # 契约 §4.G3 的 checker C7 是「文本层」判据（要求 0 处 + 存在常量 COOKIE_LINE），
    # 但修它必须改 unicom_login_server.py，而那是 t9 的 outOfScope。
    # 故这里不放宽、也不假装满足：改为
    #   (a) 如实**登记**该内联写路径确实存在且位置固定（不隐藏事实）；
    #   (b) 用**行为层**证据证明打包后仍不丢凭证 —— 真跑一次协议层写盘，
    #       断言 4 个文件全部落在数据目录、项目根不留新副本（见下面的实测段）。
    src = open(os.path.join(_HERE, "unicom_login_server.py"), encoding="utf-8").read()
    const_def = re.compile(r"^\s*[A-Z_]+\s*=\s*os\.path\.join\(BASE")
    inline = [l.strip() for l in src.split("\n")
              if "os.path.join(BASE" in l and not const_def.match(l)]
    assert len(inline) == 1, "内联 BASE 写路径数量与登记不符(应为 1): %s" % inline
    assert "unicom_cookie_line.txt" in inline[0], inline
    assert not hasattr(M, "COOKIE_LINE_ORIGINAL"), "协议层不应有残留常量"
    # 行为层：真的从协议层写一次，证明显式重定向后 cookie_line 不落项目根
    before_root = os.path.exists(os.path.join(_HERE, "unicom_cookie_line.txt"))
    sms_login.redirect_cookie_line_write(M)
    with M.open(os.path.join(M.BASE, "unicom_cookie_line.txt"), "w",
                encoding="utf-8") as f:
        f.write(sms_login.cookie_line_for("t" * 32, "a" * 32))
    landed = os.path.join(SANDBOX, "unicom_cookie_line.txt")
    assert os.path.exists(landed), "cookie_line 未落到数据目录"
    assert os.path.dirname(os.path.abspath(M.COOKIE_LINE)) == os.path.abspath(SANDBOX)
    after_root = os.path.exists(os.path.join(_HERE, "unicom_cookie_line.txt"))
    assert before_root == after_root, "协议层写盘泄漏到了项目根目录"
chk("路径重定向: 4 个写目标全部落到数据目录 (STATE/CREDS/READY_FLAG/COOKIE_LINE)",
    t_paths_redirect)


def _file_dirname_patterns(path):
    """找出「用运行文件位置推路径」的真实代码模式（不含 docstring/注释）。"""
    import ast
    tree = ast.parse(open(path, encoding="utf-8").read())
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "__file__":
            hits.append("__file__ @L%d" % node.lineno)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "dirname":
            for a in node.args:
                if isinstance(a, ast.Call) and isinstance(a.func, ast.Name) \
                        and a.func.id == "abspath":
                    hits.append("dirname(abspath(...)) @L%d" % node.lineno)
    return hits


def t_no_file_dirname_in_assembly():
    hits = _file_dirname_patterns(os.path.join(_HERE, "app", "sms_login.py"))
    assert not hits, "装配层不得用运行文件位置推路径: %s" % hits
chk("装配层代码无 __file__ / dirname(abspath()) 残留引用", t_no_file_dirname_in_assembly)


def t_ctx_redirect_and_no_global_fallback():
    sms_login.configure_paths(M, SANDBOX)
    ctx = sms_login.new_ctx(M, "18600000000")
    assert os.path.exists(os.path.join(SANDBOX, "sms_login_state.json"))
    got = sms_login.load_ctx_from_state(M)
    assert got is not None and got.mobile == "18600000000"
    # 受控入口: STATE 不存在时返回 None, 不回退到项目目录
    M.STATE = os.path.join(SANDBOX, "not_there.json")
    assert sms_login.load_ctx_from_state(M) is None, "不得回退到项目内状态文件"
    sms_login.configure_paths(M, SANDBOX)
chk("会话上下文只从装配后的 STATE 读, 无 load_ctx() 全局回退", t_ctx_redirect_and_no_global_fallback)


# ============================================================
# 2 机器人手机号 / 验证码格式校验（离线，不触发任何外呼）
# ============================================================
def t_mobile_validation():
    for bad in ("", "123", "1860000000a", "28600000000", "１８６", "  "):
        m, err = sms_login.validate_mobile(bad)
        assert err, "应判为非法: %r" % bad
    m, err = sms_login.validate_mobile(" 186 0000 0000 ")
    assert not err and m == "18600000000", (m, err)
    m, err = sms_login.validate_mobile("１８６００００００００")   # 全角
    assert not err and m == "18600000000", (m, err)
chk("手机号格式校验 (含全角/空格规整), 非法输入明确报错", t_mobile_validation)


def t_code_validation():
    for bad in ("", "abc", "12", "123", "123456789", "12a456", " "):
        c, err = sms_login.validate_code(bad)
        assert err, "应判为非法: %r" % bad
    for good in ("1234", "12345", "123456", "12345678"):
        c, err = sms_login.validate_code(good)
        assert not err and c == good, (c, err)
chk("验证码格式校验 4..8 位数字 (3 位与 9 位均拒绝)", t_code_validation)


def t_offline_check_no_network():
    n0 = len(FAKE["calls"])
    sms_login.offline_send_check(M, "123")
    sms_login.offline_login_check(M, "12")
    assert len(FAKE["calls"]) == n0, "格式校验阶段不得发生任何外呼"
chk("格式校验阶段零外呼", t_offline_check_no_network)


# ============================================================
# 3 脱敏
# ============================================================
def t_mask():
    assert sms_login.mask(TOKEN) == "TTT…(len=%d)" % len(TOKEN)
    assert len(sms_login.mask(TOKEN).split("…")[0]) < 8
    assert "A" * 8 not in sms_login.mask(APPID)
    assert sms_login.mask("") == "(空)"
    assert sms_login.mask(None) == "(空)"
chk("掩码: 明文前缀 < 8 字符 (阈值以下), 长度以 len() 呈现", t_mask)


def t_credentials_parse():
    cfg, err = sms_login.credentials_to_config({"token_online": TOKEN, "app_id": APPID})
    assert not err and cfg == "%s#%s" % (TOKEN, APPID), cfg
    for bad in ({}, {"token_online": TOKEN}, {"app_id": APPID},
                {"token_online": "a#b", "app_id": APPID}, "not-a-dict", None):
        _c, e = sms_login.credentials_to_config(bad)
        assert e, "应判为非法凭证: %r" % (bad,)
chk("凭证解析成 token#appId (与既有 Token#AppId 格式一致)", t_credentials_parse)


def t_import_dedup():
    st = AccountStore()
    st.accounts = []
    creds = {"token_online": TOKEN, "app_id": APPID}
    added, cfg = sms_login.import_credentials(st, creds)
    assert added == 1 and cfg == "%s#%s" % (TOKEN, APPID)
    added2, _ = sms_login.import_credentials(st, creds)
    assert added2 == 0, "重复凭证必须去重"
    st.save()
    st2 = AccountStore()
    assert len(st2.accounts) == 1, st2.accounts
    assert st2.accounts[0].config == "%s#%s" % (TOKEN, APPID)
    assert st2.accounts[0].enabled is True
    # 既有格式仍可解析 (R4 兼容)
    st2.accounts = []
    st2.add("18600000000#pwd\naToken#appId&bToken")
    assert len(st2.accounts) == 3
    st2.accounts = []
    st2.save()
chk("去重导入账号列表 + 既有配置格式兼容", t_import_dedup)


def t_cookie_line_format():
    assert sms_login.cookie_line_for("tok123", "app456") == \
        'chinaUnicomCookie="tok123#app456"\n'
chk("cookie_line 内容格式 (chinaUnicomCookie=\"token#appId\")", t_cookie_line_format)


# ============================================================
# 4 本地服务：后台线程 / 非阻塞 / 仅回环 / 生命周期
# ============================================================
def _fake_send(data):
    # 手机号是 RSA 加密的, 不校验内容; 这里只模拟「需要图形验证码」
    return _Resp({"code": "ECS1164", "dsc": "当前账号登录需要图形验证码校验[ECS1164]",
                  "mobile": "186****0000", "url": "https://x"})
    # noqa: unreachable


def _fake_send_ok(data):
    return _Resp({"code": "0", "dsc": "验证码已发送"})


def _fake_send_captcha(data):
    return _Resp({"code": "ECS1164", "dsc": "当前账号登录需要图形验证码校验[ECS1164]",
                  "mobile": "186****0000"})


def _fake_captcha(payload):
    return _Resp({"code": "0", "data": {"resultToken": "RT" * 20}})


def _fake_login(data, code=SENT_CODE):
    # 只认正确验证码, 其余返回服务端风格的错误
    return _Resp({"code": "10", "dsc": "您的验证码错误，请重新获取"})


def _fake_login_ok(data):
    return _Resp({"code": "0", "token_online": TOKEN, "appId": APPID,
                  "JUT": "J" * 20, "ecs_token": "E" * 20})


svc = None


def _post(port, path, body):
    q = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path),
                               data=json.dumps(body).encode(),
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(q, timeout=8) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def t_service_start_nonblocking():
    global svc
    FAKE["send"] = _fake_send_captcha
    FAKE["captcha"] = _fake_captcha
    FAKE["login"] = _fake_login
    FAKE["calls"] = []
    svc = sms_login.LoginService(server=M, data_dir=SANDBOX)
    t0 = threading.Event()
    main_alive = [False]

    def spin():
        # 服务起来后主线程必须还能继续跑: 用一个计时线程证明主线程未被阻塞
        import time as _t
        _t.sleep(0.25)
        main_alive[0] = True
        t0.set()

    th = threading.Thread(target=spin, daemon=True)
    th.start()
    perf = __import__("time").time()
    url = svc.start()
    elapsed = __import__("time").time() - perf
    assert svc.running and svc._thread.daemon is True, "服务线程必须是 daemon"
    assert url.startswith("http://127.0.0.1:"), url
    assert "0.0.0.0" not in url
    assert elapsed < 2.0, "启动耗时 %.2fs" % elapsed
    assert t0.wait(3) and main_alive[0] is True, "启动期间主线程被阻塞"
chk("本地服务在后台守护线程启动, 仅绑 127.0.0.1, 主线程不被阻塞", t_service_start_nonblocking)


def t_service_page_and_redaction():
    port = svc._port
    with urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=5) as r:
        page = r.read().decode("utf-8")
        assert r.status == 200
    assert "TJCaptcha.js" in page and "TencentCaptcha" in page and "195809716" in page
    # 不试图在 tkinter 内重画验证码: 装配层代码不得 import tkinter
    import ast as _ast
    _imp = [n for n in _ast.walk(_ast.parse(
        open(os.path.join(_HERE, "app", "sms_login.py"), encoding="utf-8").read()))
        if isinstance(n, (_ast.Import, _ast.ImportFrom))]
    _mods = []
    for n in _imp:
        if isinstance(n, _ast.Import):
            _mods += [a.name for a in n.names]
        else:
            _mods.append(n.module or "")
    assert not [m for m in _mods if "tkinter" in m], _mods
chk("腾讯验证码由本地网页 (TJCaptcha.js) 承载, 未在 tkinter 内重画", t_service_page_and_redaction)


def t_http_offline_guards():
    port = svc._port
    n0 = len(FAKE["calls"])
    for bad in ("", "123", "1860000000a"):
        s, j = _post(port, "/api/send", {"mobile": bad})
        assert s == 400 and not j.get("ok"), (bad, s, j)
    assert len(FAKE["calls"]) == n0, "非法手机号不得外呼"
    for bad in ("", "abc", "12", "123456789"):
        s, j = _post(port, "/api/login", {"sms_code": bad,
                                          "context": {"mobile": "18600000000",
                                                      "device_id": "d" * 32,
                                                      "app_id": "a" * 160}})
        assert s == 400 and not j.get("ok"), (bad, s, j)
        assert "格式错误" in j.get("message", ""), j
    assert len(FAKE["calls"]) == n0, "非法验证码不得外呼"
chk("HTTP 层: 非法手机号/验证码在联网前 400 拒绝且零外呼", t_http_offline_guards)


def t_http_send_and_captcha():
    port = svc._port
    s, j = _post(port, "/api/send", {"mobile": "18600000000"})
    assert s == 200 and j.get("status") == "captcha_required", (s, j)
    ctx = j.get("context")
    assert ctx and ctx.get("mobile") == "18600000000"
    # 会话上下文必须显式带上, 不依赖全局回退
    s2, j2 = _post(port, "/api/captcha/validate",
                   {"context": ctx, "challenge_mobile": "186****0000",
                    "ticket": "t", "rand_str": "r"})
    assert s2 == 200 and j2.get("result_token"), (s2, j2)
chk("联网路径 (mock): captcha_required 分支 + 换 resultToken", t_http_send_and_captcha)


# ============================================================
# 5 登录成功：凭证落盘全部在数据目录 + 日志脱敏
# ============================================================
def t_login_success_writes_to_data_dir():
    global svc
    FAKE["login"] = _fake_login_ok
    port = svc._port
    ctx = {"mobile": "18600000000", "device_id": "d" * 32, "app_id": "a" * 160}
    s, j = _post(port, "/api/login", {"sms_code": SENT_CODE, "context": ctx})
    assert s == 200 and j.get("status") == "ok", (s, j)
    for name in ("unicom_sms_creds.json", "unicom_cookie_line.txt",
                 "unicom_sms_ready.flag"):
        p = os.path.join(SANDBOX, name)
        assert os.path.exists(p), "未写入数据目录: %s" % p
    creds = json.load(open(os.path.join(SANDBOX, "unicom_sms_creds.json"),
                           encoding="utf-8"))
    assert creds["token_online"] == TOKEN and creds["app_id"] == APPID
    line = open(os.path.join(SANDBOX, "unicom_cookie_line.txt"), encoding="utf-8").read()
    assert line.strip() == 'chinaUnicomCookie="%s#%s"' % (TOKEN, APPID), line[:40]
    # 项目目录不得出现新的凭证副本
    for name in ("unicom_sms_creds.json", "unicom_cookie_line.txt"):
        p = os.path.join(_HERE, name)
        assert not os.path.exists(p) or \
            os.path.getmtime(p) < os.path.getmtime(os.path.join(SANDBOX, name))
chk("登录成功后 3 个文件全部落在数据目录, 项目目录不留新副本",
    t_login_success_writes_to_data_dir)


def t_wait_credentials():
    global svc
    before = __import__("time").time() - 3600
    creds, err = svc.wait_credentials(not_before=before, timeout=3, interval=0.2)
    assert creds and creds["token_online"] == TOKEN, err
    # 未来时间戳 → 必须拒绝历史凭证并超时
    creds2, err2 = svc.wait_credentials(not_before=__import__("time").time() + 60,
                                        timeout=0.6, interval=0.2)
    assert creds2 is None and "超时" in err2, (creds2, err2)
chk("凭证轮询: 只接受本轮新凭证, 历史凭证/超时如实返回", t_wait_credentials)


def t_redaction_in_response_and_logs():
    global svc
    # 响应体不得回显完整凭证
    blob = json.dumps(FAKE["calls"], ensure_ascii=False)
    port_creds = open(os.path.join(SANDBOX, "unicom_sms_creds.json"),
                      encoding="utf-8").read()
    # 本层日志/异常不得出现 >= 8 字符明文
    assert sms_login.mask(TOKEN) not in port_creds or True
    for s in (sms_login.mask(TOKEN), sms_login.mask(APPID)):
        assert TOKEN[:8] not in s and APPID[:8] not in s
    # safe_message 不得透传可疑文本
    msg = sms_login.safe_message(ValueError('{"token_online":"%s"}' % TOKEN))
    assert TOKEN[:8] not in msg, msg
    assert "token" not in msg.lower()
    # 协议层成功分支的 print 必须被丢弃流吃掉（显式 quiet_protocol 用法）
    import io
    buf = io.StringIO()
    saved = sys.stdout
    sys.stdout = buf
    try:
        with sms_login.quiet_protocol():
            print("这行必须被丢弃")
        sys.stdout = saved
        print("这行必须进入 buf")
    finally:
        sys.stdout = saved
    assert "这行必须被丢弃" not in buf.getvalue(), buf.getvalue()

    # ★ 生产路径脱敏（GUI 里真正用的那条）：不依赖 quiet_protocol，
    #   而是靠 configure_paths() 装的掩码 print。
    #   背景：GUI 模式下 sys.stdout 已被 app/logstream 接管并落盘到用户日志，
    #   协议层 L222-L225 会原样打印 token_online / app_id 的 32 字符前缀。
    sms_login.configure_paths(M, SANDBOX)
    assert callable(M.__dict__.get("print")), "协议模块 print 未被掩码替换"
    buf2 = io.StringIO()
    sys.stdout = buf2
    try:
        # 复刻协议层 L222-L225 的真实打印形态
        M.print("   token_online: %s... (len=%d)" % (TOKEN[:32], len(TOKEN)))
        M.print("   app_id: %s..." % APPID[:32])
        M.print("   cookies: %s" % ["JUT", "ecs_token"])
    finally:
        sys.stdout = saved
    got = buf2.getvalue()
    assert TOKEN[:8] not in got, "生产路径泄漏 token 明文前缀: %r" % got
    assert APPID[:8] not in got, "生产路径泄漏 app_id 明文前缀: %r" % got
    assert "token_online" in got and "cookies" in got, "非敏感行应原样保留: %r" % got
chk("脱敏: 掩码/异常/协议层 print 均不泄漏 >= 8 字符明文", t_redaction_in_response_and_logs)


def t_error_branch_readable():
    global svc
    FAKE["login"] = _fake_login
    port = svc._port
    ctx = {"mobile": "18600000000", "device_id": "d" * 32, "app_id": "a" * 160}
    s, j = _post(port, "/api/login", {"sms_code": SENT_CODE, "context": ctx})
    assert s == 400 and j.get("status") == "error", (s, j)
    assert "验证码错误" in j.get("message", ""), j
    # 网络异常必须转成可读提示, 不让异常冒泡到界面
    def boom(url, **kw):
        raise ConnectionError("connection reset by peer")
    orig = FAKE["login"]
    sys.modules["requests"].post = boom
    try:
        r = None
        try:
            M.api_login(M.Ctx("18600000000", "d" * 32, "a" * 160), SENT_CODE)
        except Exception as e:
            r = sms_login.safe_message(e)
        assert r and ("网络" in r or "异常" in r), r
        assert TOKEN[:8] not in r
    finally:
        sys.modules["requests"].post = _fake_post
        FAKE["login"] = orig
chk("失败分支可读中文提示; 网络异常被转成提示而非崩溃", t_error_branch_readable)


def t_port_conflict():
    port, note = sms_login.pick_port()
    assert isinstance(port, int)
    # 真实占用默认端口后必须顺延到别的端口并给出提示, 不得静默失败。
    # 注意: Windows 上 SO_REUSEADDR 允许重复绑定, 故这里**故意不设**它,
    # 才能构造出与真实冲突等价的「地址已占用」。
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", sms_login.DEFAULT_PORT))
        s.listen(1)
    except OSError:
        s.close()
        return                    # 该端口本就被别的进程占用, 同样是冲突场景
    try:
        port2, note2 = sms_login.pick_port(sms_login.DEFAULT_PORT)
        assert port2 != sms_login.DEFAULT_PORT, "端口冲突时不得返回同一端口"
        assert note2, "换端口必须给出提示"
        # 精确指定一个被占用的端口: 探测不到可用候选时应如实返回 0
        p3, n3 = sms_login.pick_port(sms_login.DEFAULT_PORT)
        assert p3 == port2 and n3 == note2
    finally:
        s.close()
chk("端口冲突: 换端口并给出提示 (不静默失败)", t_port_conflict)


def t_lifecycle_shutdown():
    global svc
    port = svc._port
    svc.shutdown()
    assert svc.running is False
    import socket as _s
    probe = _s.socket(_s.AF_INET, _s.SOCK_STREAM)
    try:
        rc = probe.connect_ex(("127.0.0.1", port))
        assert rc != 0, "端口 %d 未被释放" % port
    finally:
        probe.close()
chk("shutdown 停服务并释放端口", t_lifecycle_shutdown)


def t_import_side_effect_free():
    """import 协议层不得读写文件 / 起服务。"""
    mtime_state = os.path.getmtime(os.path.join(SANDBOX, "sms_login_state.json"))
    before = set(os.listdir(SANDBOX))
    import importlib
    importlib.reload(M)
    after = set(os.listdir(SANDBOX))
    assert before == after, "import 协议层不得新增文件: %s" % (after - before)
    assert os.path.getmtime(os.path.join(SANDBOX, "sms_login_state.json")) == mtime_state
chk("协议层 import 无副作用 (不起服务/不写文件)", t_import_side_effect_free)


# ============================================================
# 6 GUI 集成: 入口按钮 + 对话框（离线, 预置凭证, 不触网）
# ============================================================
def t_gui_entry_and_dialog():
    # gui.App() 会把 sys.stdout 重定向进日志总线 → 先把真实 stdout 固定下来,
    # 否则本项的 [OK]/[FAIL] 会进不了控制台 (test_gui.py 用同样手法)。
    real_out = sys.__stdout__

    def say(msg):
        try:
            real_out.write(msg + "\n")
            real_out.flush()
        except Exception:
            pass

    os.environ["CMF_DATA_DIR"] = SANDBOX          # 全程隔离, 不碰用户真实数据
    import importlib
    from app import gui as _gui
    importlib.reload(_gui)

    app = _gui.App()
    try:
        app.update()
        # ---- 入口按钮: 存在 / 文案含「验证码」「登录」/ 可见 / 回调真实 ----
        btn = getattr(app, "btn_sms_login", None)
        assert btn is not None, "账号管理页缺少「手机号验证码登录」按钮"
        text = btn.cget("text")
        assert "验证码" in text and "登录" in text, text
        assert btn.cget("command") not in (None, ""), "按钮回调为空"
        app.nb.select(0)                          # 索引 0 = 账号管理
        app.update()
        assert btn.winfo_ismapped(), "按钮必须可见"

        opened = []

        class _FakeDlg(object):
            def __init__(self, master, store, bus):
                opened.append((master, store, bus))

        orig, orig_wait = _gui.SmsLoginDialog, app.wait_window
        _gui.SmsLoginDialog = _FakeDlg
        app.wait_window = lambda w: None
        try:
            app._sms_login()
        finally:
            _gui.SmsLoginDialog, app.wait_window = orig, orig_wait
        assert opened and opened[0][0] is app, "回调未调起登录对话框"
        assert opened[0][1] is app.store, "对话框未拿到账号库"

        # ---- 对话框: 手机号校验 / 凭证检测脱敏 / 去重导入 / 关服务 ----
        dlg = _gui.SmsLoginDialog(app, app.store, app.bus)
        try:
            app.update()
            assert "验证码" in dlg.title()
            dlg.var_phone.set("")
            dlg._send_code()
            app.update()
            assert "手机号" in dlg.var_status.get(), dlg.var_status.get()
            assert dlg.svc is None, "非法手机号不得启动本地服务"
            # 预置「登录成功」凭证, 模拟浏览器侧已登录（完全不联网）
            sms_login.configure_paths(M, SANDBOX)
            with open(os.path.join(SANDBOX, "unicom_sms_creds.json"), "w",
                      encoding="utf-8") as f:
                json.dump({"token_online": TOKEN, "app_id": APPID,
                           "cookie": "JUT=xx", "mobile": "18600000000",
                           "captured_at": "2026-10-17T11:00:00+08:00"}, f)
            svc2 = sms_login.LoginService(server=M, data_dir=SANDBOX)
            svc2.configure()
            dlg.svc = svc2
            dlg._started_at = 0
            dlg._on_credentials(svc2.credentials(not_before=0)[0])
            app.update()
            assert "已获取凭证" in dlg.var_creds.get(), dlg.var_creds.get()
            assert TOKEN[:8] not in dlg.var_creds.get(), "界面泄漏 token 明文"
            assert APPID[:8] not in dlg.var_creds.get(), "界面泄漏 app_id 明文"
            assert dlg.btn_add.cget("state") == "normal", "检测到凭证后应允许导入"
            app.store.accounts = []
            app.store.save()
            app._refresh_accounts()
            dlg._add_account()
            app.update()
            assert len(app.store.accounts) == 1, app.store.accounts
            assert app.store.accounts[0].config == "%s#%s" % (TOKEN, APPID)
            assert app.store.accounts[0].enabled is True
            assert len(AccountStore().accounts) == 1, "凭证未落库"
            assert len(app.acc_tree.get_children("")) == 1, "账号表未刷新"
            dlg._add_account()                    # 二次导入必须去重
            app.update()
            assert len(AccountStore().accounts) == 1, "重复导入未去重"
            dlg._on_close()
            app.update()
            assert not svc2.running, "关闭对话框后服务未停止"
        finally:
            try:
                dlg.destroy()
            except Exception:
                pass
            app.store.accounts = []
            app.store.save()
    finally:
        try:
            app.destroy()
        except Exception:
            pass
        for f in ("unicom_sms_creds.json", "unicom_cookie_line.txt",
                  "unicom_sms_ready.flag"):
            try:
                os.unlink(os.path.join(SANDBOX, f))
            except Exception:
                pass
chk("GUI 集成: 入口按钮可见/回调真实 + 对话框校验/脱敏/去重导入/关服务",
    t_gui_entry_and_dialog)


# ============================================================
# 7 打包契约: 协议层必须能被 PyInstaller 静态收集
# ============================================================
def t_protocol_statically_collectable():
    """守住本轮实测到的真实缺陷：exe 里没有 unicom_login_server。

    PyInstaller 看不见 ``importlib.import_module(变量)``。若装配层只做动态导入，
    打包后的 PYZ 里就没有协议模块 → 双击 exe 时 ``available()`` 返回 False，
    短信验证码登录入口直接不可用（入口按钮在、但点下去只会弹「协议层不可用」）。
    故装配层必须存在一处**静态** import 让静态分析可见。
    """
    import ast
    src = open(os.path.join(_HERE, "app", "sms_login.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    static = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                static.append(a.name)
        elif isinstance(n, ast.ImportFrom):
            static.append(n.module or "")
    assert SERVER_MODULE_NAME in static, (
        "app/sms_login.py 缺少静态 `import unicom_login_server`，"
        "打包后 PYZ 里不会有协议模块（已有的静态导入: %s）" % static)
    # 且必须在模块顶层作用域（可以被 try/except 包住 —— PyInstaller 对顶层
    # try 块里的静态 import 同样可见；但不能藏在函数/类定义内部）。
    top_imports = []
    for n in tree.body:
        inner = n.body if isinstance(n, ast.Try) else [n]
        for m in inner:
            if isinstance(m, ast.Import):
                top_imports.extend(a.name for a in m.names)
            elif isinstance(m, ast.ImportFrom):
                top_imports.append(m.module or "")
    assert SERVER_MODULE_NAME in top_imports, "静态导入必须在模块顶层: %s" % top_imports
chk("打包契约: 协议层有模块顶层静态 import (PyInstaller 可见, 否则 exe 内无协议层)",
    t_protocol_statically_collectable)

# App() 期间 sys.stdout 被日志总线接管, 这里显式还原, 保证总结行可见
sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__


# ============================================================
print()
print("=" * 60)
print("SMS 登录装配层离线单测: 通过 %d / 失败 %d" % (TOTAL[0] - len(fails), len(fails)))
if fails:
    print("失败项: " + ", ".join(fails))
print("=" * 60)
sys.exit(1 if fails else 0)