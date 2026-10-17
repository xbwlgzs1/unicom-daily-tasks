# -*- coding: utf-8 -*-
"""
中国联通 短信验证码登录 —— 本地网页工具 (Python 版)
====================================================
移植自 canxin121/china-unicom-rs (2026-07) 的官方 App 接口协议。

流程:
  1. 打开 http://127.0.0.1:8787/
  2. 输入手机号 -> 点"发送验证码"
  3. 如要求安全验证 -> 弹出腾讯验证码 -> 滑动完成
  4. 服务端自动换 resultToken 并重发短信
  5. 手机收到 6 位验证码 -> 填入页面 -> 点"登录"
  6. 凭证 (token_online + app_id + cookie) 自动保存到 unicom_sms_creds.json

启动: python unicom_login_server.py [端口]
"""
import sys, os, json, time, random, base64, uuid, threading, webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse

import requests
import urllib3
from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA

urllib3.disable_warnings()
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(BASE, "sms_login_state.json")
CREDS = os.path.join(BASE, "unicom_sms_creds.json")
READY_FLAG = os.path.join(BASE, "unicom_sms_ready.flag")

# ---- 官方 App 接口 (逆向自 china-unicom-rs) ----
SEND_SMS_URL = "https://m.client.10010.com/mobileService/sendRadomNum.htm"
SMS_LOGIN_URL = "https://m.client.10010.com/mobileService/radomLogin.htm"
CAPTCHA_VALIDATE_URL = "https://loginxhm.10010.com/login-web/v1/chartCaptcha/validateTencentCaptcha"
CAPTCHA_APP_ID = "195809716"
CLIENT_VERSION = "android@11.0800"
DEVICE_MODEL = "M2007J3SC"
DEVICE_BRAND = "Xiaomi"

PUB = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDc+CZK9bBA9IU+gZUOc6FUGu7yO9WpTNB0PzmgFBh96Mg1WrovD1oqZ+eIF4LjvxKXGOdI79JRdve9NPhQo07+uqGQgE4imwNnRx7PFtCRryiIEcUoavuNtuRVoBAm6qdB0SrctgaqGfLgKvZHOnwTjyNqjBUxzMeQlEC2czEMSwIDAQAB
-----END PUBLIC KEY-----"""
_RSA_KEY = RSA.import_key(PUB.encode())


def rsa_encrypt_b64(val: str) -> str:
    text = str(val) + "".join(str(random.randint(0, 9)) for _ in range(6))
    return base64.b64encode(PKCS1_v1_5.new(_RSA_KEY).encrypt(text.encode("utf-8"))).decode()


def generate_app_id() -> str:
    d = lambda: str(random.randint(0, 9))
    return (f"{d()}f{d()}af{d()}{d()}ad{d()}"
            "912d306b5053abf90c7ebbb695887bc"
            "870ae0706d573c348539c26c5c0a878641fcc0d3e90acb9be1e6ef858a"
            "59af546f3c826988332376b7d18c8ea2398ee3a9c3db947e2471d32a49612")


def user_agent(mobile: str) -> str:
    return (f"Mozilla/5.0 (Linux; Android 13; {DEVICE_MODEL} Build/TKQ1.220829.002; wv) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/107.0.5304.141 "
            f"Mobile Safari/537.36; unicom{{version:{CLIENT_VERSION},desmobile:{mobile}}};"
            f"devicetype{{deviceBrand:{DEVICE_BRAND},deviceModel:{DEVICE_MODEL}}};{{yw_code:}}")


def ts_now() -> str:
    return time.strftime("%Y%m%d%H%M%S")


def random_hex(n: int) -> str:
    return "".join(random.choice("0123456789abcdef") for _ in range(n))


# ---------------- 核心协议 ----------------

class Ctx:
    def __init__(self, mobile, device_id, app_id):
        self.mobile, self.device_id, self.app_id = mobile, device_id, app_id

    def to_dict(self):
        return {"mobile": self.mobile, "device_id": self.device_id, "app_id": self.app_id}

    @classmethod
    def from_dict(cls, d):
        return cls(d["mobile"], d["device_id"], d["app_id"])


def load_ctx() -> Ctx | None:
    if os.path.exists(STATE):
        try:
            return Ctx.from_dict(json.load(open(STATE, encoding="utf-8")))
        except Exception:
            return None
    return None


def save_ctx(ctx: Ctx):
    json.dump(ctx.to_dict(), open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def headers_for(mobile: str):
    return {
        "User-Agent": user_agent(mobile),
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Requested-With": "com.sinovatech.unicom.ui",
        "Accept": "*/*",
        "Connection": "keep-alive",
    }


def api_send_sms(ctx: Ctx, result_token: str = "") -> dict:
    """发送短信验证码。返回: {status: sent|captcha_required|error, ...}"""
    form = {
        "isFirstInstall": "1", "simCount": "1", "yw_code": "", "deviceOS": "android13",
        "mobile": rsa_encrypt_b64(ctx.mobile), "netWay": "Wifi", "loginCodeLen": "6",
        "deviceId": ctx.device_id, "deviceCode": ctx.device_id, "version": CLIENT_VERSION,
        "send_flag": "", "resultToken": result_token.strip(), "keyVersion": "",
        "provinceChanel": "general", "appId": ctx.app_id, "deviceModel": DEVICE_MODEL,
        "androidId": ctx.device_id[:16], "deviceBrand": DEVICE_BRAND, "timestamp": ts_now(),
    }
    r = requests.post(SEND_SMS_URL, data=form, headers=headers_for(ctx.mobile), timeout=30, verify=False)
    try:
        j = r.json()
    except Exception:
        return {"status": "error", "message": f"非JSON响应 HTTP{r.status_code}: {r.text[:200]}"}
    code = str(j.get("code", ""))
    rsp_code = str(j.get("rsp_code", ""))
    msg = str(j.get("dsc") or j.get("msg") or j.get("rsp_desc") or "")
    if code in ("0", "0000") or rsp_code in ("0", "0000") or j.get("status") == "success" \
            or "验证码已发送" in msg or "发送成功" in msg:
        return {"status": "sent", "message": msg or "验证码已发送"}
    if code in ("ECS99998", "ECS99999") or rsp_code in ("ECS99998", "ECS99999") \
            or "图形验证码" in msg or "安全验证" in msg or "ECS1164" in msg:
        return {"status": "captcha_required", "message": msg,
                "challenge_mobile": str(j.get("mobile") or ""), "url": str(j.get("url") or "")}
    return {"status": "error", "message": f"[{code or rsp_code}] {msg}"}


def api_validate_captcha(ctx: Ctx, challenge_mobile: str, ticket: str, rand_str: str) -> dict:
    """腾讯验证码 -> resultToken"""
    payload = {
        "seq": random_hex(32), "captchaType": "10", "mobile": challenge_mobile,
        "ticket": ticket, "randStr": rand_str, "imei": ctx.device_id,
    }
    h = {
        "Origin": "https://img.client.10010.com",
        "Referer": "https://img.client.10010.com/loginRisk/index.html",
        "User-Agent": user_agent(ctx.mobile),
        "Content-Type": "application/json",
        "X-Requested-With": "com.sinovatech.unicom.ui",
    }
    r = requests.post(CAPTCHA_VALIDATE_URL, json=payload, headers=h, timeout=30, verify=False)
    try:
        j = r.json()
    except Exception:
        return {"status": "error", "message": f"非JSON HTTP{r.status_code}: {r.text[:200]}"}
    code = str(j.get("code", ""))
    if code not in ("0", "0000"):
        return {"status": "error", "message": f"验证码校验失败 [{code}] {j.get('msg') or j.get('dsc') or ''}"}
    result_token = ""
    if isinstance(j.get("data"), dict):
        result_token = str(j["data"].get("resultToken") or "")
    if not result_token:
        return {"status": "error", "message": "校验通过但无 resultToken"}
    return {"status": "ok", "result_token": result_token}


def api_login(ctx: Ctx, sms_code: str) -> dict:
    """短信验证码登录 -> token_online + 凭证"""
    sms_code = sms_code.strip()
    if not (4 <= len(sms_code) <= 8 and sms_code.isdigit()):
        return {"status": "error", "message": "验证码格式错误"}
    form = {
        "isFirstInstall": "1", "simCount": "1", "yw_code": "", "loginStyle": "0",
        "isRemberPwd": "true", "deviceOS": "android13", "mobile": rsa_encrypt_b64(ctx.mobile),
        "netWay": "Wifi", "version": CLIENT_VERSION, "deviceId": ctx.device_id,
        "password": rsa_encrypt_b64(sms_code), "keyVersion": "", "provinceChanel": "general",
        "appId": ctx.app_id, "deviceModel": DEVICE_MODEL, "androidId": ctx.device_id[:16],
        "deviceBrand": DEVICE_BRAND, "timestamp": ts_now(),
    }
    r = requests.post(SMS_LOGIN_URL, data=form, headers=headers_for(ctx.mobile), timeout=30, verify=False)
    try:
        j = r.json()
    except Exception:
        return {"status": "error", "message": f"非JSON HTTP{r.status_code}: {r.text[:200]}"}
    code = str(j.get("code", ""))
    rsp_code = str(j.get("rsp_code", ""))
    token_online = str(j.get("token_online") or "")
    if not token_online and code not in ("0", "0000") and rsp_code not in ("0", "0000"):
        return {"status": "error",
                "message": f"登录失败 [{code or rsp_code}] {str(j.get('dsc') or j.get('msg') or j.get('rsp_desc') or '').strip()}"}
    if not token_online:
        return {"status": "error", "message": f"登录成功但无 token_online: {json.dumps(j, ensure_ascii=False)[:300]}"}

    # 收集 cookie
    parts = []
    for c in r.cookies:
        parts.append(f"{c.name}={c.value}")
    for key in ("JUT", "ecs_token", "ecs_acc"):
        v = str(j.get(key) or "")
        if v:
            parts.append(v if v.startswith(f"{key}=") else f"{key}={v}")
    cookie = "; ".join(parts)
    app_id = str(j.get("appId") or ctx.app_id)

    out = {
        "token_online": token_online, "app_id": app_id, "cookie": cookie,
        "mobile": ctx.mobile, "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
    }
    json.dump(out, open(CREDS, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    # 给桌面脚本用的现成配置行
    with open(os.path.join(BASE, "unicom_cookie_line.txt"), "w", encoding="utf-8") as f:
        f.write(f'chinaUnicomCookie="{token_online}#{app_id}"\n')
    with open(READY_FLAG, "w", encoding="utf-8") as f:
        f.write(out["captured_at"])
    print(f"\n✅ 登录成功! 凭证已保存: {CREDS}")
    print(f"   token_online: {token_online[:32]}... (len={len(token_online)})")
    print(f"   app_id: {app_id[:32]}...")
    print(f"   cookies: {[p.split('=')[0] for p in parts]}")
    return {"status": "ok", "credentials": out}


# ---------------- 本地 HTTP 服务 ----------------

PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>联通短信登录 (本地)</title>
<script src="https://turing.captcha.qcloud.com/TJCaptcha.js"></script>
<style>
  body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; max-width: 520px;
         margin: 40px auto; padding: 0 18px; color: #19202a; }
  h1 { font-size: 20px; } .muted { color: #667085; font-size: 13px; }
  input { width: 100%; box-sizing: border-box; padding: 11px 12px; margin: 6px 0 14px;
          border: 1px solid #d8dee8; border-radius: 8px; font-size: 15px; }
  button { padding: 11px 18px; border: 0; border-radius: 8px; background: #087a66; color: #fff;
           font-size: 15px; cursor: pointer; }
  button:disabled { background: #9db9b1; cursor: default; }
  .msg { margin: 12px 0; padding: 10px 12px; border-radius: 8px; background: #f5f7fb; font-size: 14px; display: none; }
  .msg.ok { background: #e7f5f0; color: #05604f; display: block; }
  .msg.err { background: #fdecea; color: #b42318; display: block; }
  .msg.info { background: #eef4ff; color: #1d4ed8; display: block; }
  pre { background: #0f172a; color: #a7f3d0; padding: 14px; border-radius: 8px; overflow-x: auto;
        font-size: 12px; display: none; }
  .row { display: flex; gap: 10px; align-items: center; }
</style>
</head>
<body>
<h1>中国联通 短信登录</h1>
<p class="muted">本地工具 · 数据仅保存在本机 · 用于获取脚本所需 Token</p>

<label>手机号</label>
<input id="phone" placeholder="11 位手机号" maxlength="11" inputmode="numeric">

<div class="row">
  <button id="sendBtn">发送验证码</button>
  <span id="sendHint" class="muted"></span>
</div>

<div id="msg" class="msg"></div>

<div id="codeArea" style="display:none">
  <label>短信验证码</label>
  <input id="code" placeholder="6 位验证码" maxlength="8" inputmode="numeric">
  <button id="loginBtn">登录</button>
</div>

<pre id="result"></pre>

<script>
"use strict";
const $ = id => document.getElementById(id);
let loginContext = null;
let challengeMobile = "";
let cooldown = 0, cdTimer = null;

function showMsg(text, kind) {
  const m = $("msg");
  m.textContent = text;
  m.className = "msg " + (kind || "info");
}
function setBusy(btn, busy, text) {
  btn.disabled = busy;
  if (text) btn.textContent = text;
}
function startCooldown(sec) {
  cooldown = sec || 60;
  $("sendBtn").disabled = true;
  clearInterval(cdTimer);
  cdTimer = setInterval(() => {
    cooldown--;
    if (cooldown <= 0) { clearInterval(cdTimer); $("sendBtn").disabled = false; $("sendBtn").textContent = "发送验证码"; }
    else $("sendBtn").textContent = cooldown + "s";
  }, 1000);
}
async function postJson(url, body) {
  const r = await fetch(url, { method: "POST", headers: {"Content-Type": "application/json"},
                               body: JSON.stringify(body) });
  const j = await r.json();
  if (!r.ok) throw new Error(j.message || ("HTTP " + r.status));
  return j;
}
async function sendCode(resultToken) {
  const mobile = $("phone").value.trim();
  if (!/^1\\d{10}$/.test(mobile)) { showMsg("请输入 11 位手机号", "err"); return; }
  setBusy($("sendBtn"), true, "发送中…");
  try {
    const p = await postJson("/api/send", { mobile, context: loginContext, result_token: resultToken || "" });
    loginContext = p.context || loginContext;
    if (p.status === "captcha_required") {
      challengeMobile = p.challenge_mobile || "";
      showMsg("需要安全验证：请在弹出的窗口完成滑动验证", "info");
      openCaptcha();
      return;
    }
    if (p.status === "sent") {
      showMsg("验证码已发送，请查看手机短信", "ok");
      $("codeArea").style.display = "block";
      startCooldown(60);
      return;
    }
    showMsg(p.message || "发送失败", "err");
    setBusy($("sendBtn"), false, "发送验证码");
  } catch (e) {
    showMsg(e.message || "发送失败", "err");
    setBusy($("sendBtn"), false, "发送验证码");
  }
}
function openCaptcha() {
  if (typeof window.TencentCaptcha !== "function") {
    showMsg("腾讯验证码组件加载失败，请刷新页面重试", "err");
    setBusy($("sendBtn"), false, "发送验证码");
    return;
  }
  const captcha = new window.TencentCaptcha("195809716", async (res) => {
    if (!res || res.ret !== 0) {
      showMsg("已取消安全验证", "err");
      setBusy($("sendBtn"), false, "发送验证码");
      return;
    }
    try {
      const v = await postJson("/api/captcha/validate", {
        context: loginContext, challenge_mobile: challengeMobile,
        ticket: res.ticket, rand_str: res.randstr
      });
      await sendCode(v.result_token);
    } catch (e) {
      showMsg(e.message || "安全验证失败", "err");
      setBusy($("sendBtn"), false, "发送验证码");
    }
  });
  captcha.show();
}
$("sendBtn").onclick = () => sendCode("");
$("loginBtn").onclick = async () => {
  const code = $("code").value.trim();
  if (!code) { showMsg("请输入短信验证码", "err"); return; }
  setBusy($("loginBtn"), true, "登录中…");
  try {
    const p = await postJson("/api/login", { context: loginContext, sms_code: code });
    showMsg("登录成功！凭证已自动保存到脚本目录", "ok");
    $("result").textContent = JSON.stringify(p.credentials, null, 2);
    $("result").style.display = "block";
    $("phone").value = ""; $("code").value = "";
  } catch (e) {
    showMsg(e.message || "登录失败", "err");
  } finally {
    setBusy($("loginBtn"), false, "登录");
  }
};
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 安静

    def _send(self, code, ctype, body: bytes, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Content-Length", str(len(body)))
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, "application/json; charset=utf-8",
                   json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", PAGE.encode("utf-8"))
        elif self.path == "/health":
            self._json({"ok": True})
        else:
            self._send(404, "text/plain", b"not found")

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            req = json.loads(raw.decode("utf-8"))
        except Exception:
            self._json({"ok": False, "message": "invalid JSON"}, 400)
            return

        try:
            if self.path == "/api/send":
                mobile = str(req.get("mobile") or "").strip()
                if not (len(mobile) == 11 and mobile.isdigit()):
                    self._json({"ok": False, "message": "手机号必须是 11 位数字"}, 400)
                    return
                ctx_d = req.get("context")
                if ctx_d:
                    ctx = Ctx.from_dict(ctx_d)
                else:
                    ctx = Ctx(mobile, uuid.uuid4().hex, generate_app_id())
                    save_ctx(ctx)
                res = api_send_sms(ctx, str(req.get("result_token") or ""))
                res["ok"] = res.get("status") != "error"
                res["context"] = ctx.to_dict()
                self._json(res)
                return

            if self.path == "/api/captcha/validate":
                ctx_d = req.get("context")
                ctx = Ctx.from_dict(ctx_d) if ctx_d else load_ctx()
                if ctx is None:
                    self._json({"ok": False, "message": "缺少会话信息：请先点击“发送验证码”"}, 400)
                    return
                res = api_validate_captcha(ctx, str(req.get("challenge_mobile") or ""),
                                           str(req.get("ticket") or ""), str(req.get("rand_str") or ""))
                res["ok"] = res.get("status") != "error"
                self._json(res, 200 if res.get("ok") else 400)
                return

            if self.path == "/api/login":
                ctx_d = req.get("context")
                ctx = Ctx.from_dict(ctx_d) if ctx_d else load_ctx()
                if ctx is None:
                    self._json({"ok": False, "message": "缺少会话信息：请先点击“发送验证码”"}, 400)
                    return
                res = api_login(ctx, str(req.get("sms_code") or ""))
                res["ok"] = res.get("status") != "error"
                self._json(res, 200 if res.get("ok") else 400)
                return

            self._send(404, "text/plain", b"not found")
        except Exception as e:
            self._json({"ok": False, "message": f"服务器错误: {type(e).__name__}: {e}"}, 500)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    srv = HTTPServer(("127.0.0.1", port), Handler)
    print("=" * 60)
    print(f"联通短信登录工具已启动:  http://127.0.0.1:{port}/")
    print("本机访问 · 数据只保存在脚本目录 · Ctrl+C 退出")
    print("=" * 60)
    print(f"凭证将保存到: {CREDS}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
