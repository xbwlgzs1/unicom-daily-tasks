# -*- coding: utf-8 -*-
"""联网自检: 不需要真实账号, 只验证联通/合作方各业务域名可达 + 请求构造正确"""
import os
import sys
import time

_BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _BASE)
sys.stdout.reconfigure(encoding="utf-8")

from core import legacy

ok, fail = [], []


def chk(name, fn):
    try:
        r = fn()
        ok.append(name)
        print("[OK]   %s%s" % (name, (" -> %s" % r) if r else ""))
    except Exception as e:
        import traceback
        traceback.print_exc()
        fail.append(name)
        print("[FAIL] %s -> %s" % (name, e))


def probe(url, timeout=20, allow=(200, 301, 302, 401, 403, 404, 405)):
    """连通性探测: 能拿到 HTTP 响应即视为可达.

    412/429/503 是 WAF 或风控对「无会话裸 GET」的拦截响应 —— 服务器已应答,
    说明网络与域名都通; 真正的脚本请求带完整 token/签名头, 不会命中这一层.
    """
    import requests
    t0 = time.time()
    res = requests.get(url, timeout=timeout, verify=False,
                       headers={"User-Agent": legacy.COMMON_CONSTANTS["UA"]})
    ms = int((time.time() - t0) * 1000)
    sc = res.status_code
    tag = "" if sc in allow else " [WAF/风控拦截, 可达]"
    assert 100 <= sc < 600, "无有效 HTTP 响应"
    return "HTTP %d%s (%dms, %d bytes)" % (sc, tag, ms, len(res.content))


# ---- 1 联通主站 ----
def t_main():
    return probe("https://m.client.10010.com/mobileService/business/get/getCity")
chk("联通主站 m.client.10010.com", t_main)


# ---- 2 用假 token 走 onLine: 证明请求链构造正确 (业务失败而非网络失败) ----
def t_online():
    u = legacy.UserService(1, "FAKE_TOKEN_FOR_CONNECTIVITY_TEST")
    t0 = time.time()
    r = u.session.post(
        "https://m.client.10010.com/mobileService/onLine.htm",
        data={'isFirstInstall': '1', 'netWay': 'Wifi', 'version': 'android@11.0000',
              'token_online': 'FAKE_TOKEN_FOR_CONNECTIVITY_TEST',
              'provinceChanel': 'general', 'deviceModel': 'ALN-AL10',
              'step': 'dingshi', 'androidId': '291a7deb1d716b5a',
              'reqtime': int(time.time() * 1000)},
        timeout=15)
    ms = int((time.time() - t0) * 1000)
    assert r.status_code == 200, r.status_code
    body = r.json() if "json" in r.headers.get("content-type", "") or r.text[:1] in "{[" else {}
    code = str(body.get("code", "")) if isinstance(body, dict) else ""
    assert code != "0", "假 token 不应登录成功"
    return "HTTP 200 code=%s (%dms)" % (code or "?", ms)
chk("onLine 登录接口 (假 token)", t_online)


# ---- 3 签到活动 ----
def t_sign():
    return probe("https://activity.10010.com/sixPalaceGridTurntableLottery/signin/getContinuous")
chk("签到活动 activity.10010.com", t_sign)


# ---- 4 权益超市 ----
def t_market():
    return probe("https://contact.bol.wo.cn/market")
chk("权益超市 contact.bol.wo.cn", t_market)


# ---- 5 安全管家 ----
def t_sec():
    return probe("https://uca.wo116114.com/")
chk("安全管家 uca.wo116114.com", t_sec)


# ---- 6 联通云盘 ----
def t_cloud():
    return probe("https://panservice.mail.wo.cn/h5/activitymobile/aiActor")
chk("联通云盘 panservice.mail.wo.cn", t_cloud)


# ---- 7 芒果TV 渠道 ----
def t_mgtv():
    import requests
    # v1.1.2 叫 YPHD_MGTV_BASE, v1.2.1 重命名为 ISLAND_MGTV_BASE (海岛逐浪)
    base = getattr(legacy, "ISLAND_MGTV_BASE", None) or getattr(
        legacy, "YPHD_MGTV_BASE", "https://mgcact.api.mgtv.com")
    res = requests.get(base + "/api/cu/queryAvailableTimes",
                       params={"ticket": "FAKE", "t": int(time.time() * 1000)},
                       headers={"User-Agent": legacy.COMMON_CONSTANTS["UA"]},
                       timeout=15, verify=False)
    assert res.status_code in (200, 400, 401), res.status_code
    return "HTTP %d" % res.status_code
chk("芒果TV mgcact.api.mgtv.com", t_mgtv)


# ---- 8 云手机 / 沃商店 ----
def t_wostore():
    return probe("https://uphone.wostore.cn/")
chk("沃云手机 uphone.wostore.cn", t_wostore)


# ---- 9 积分 / JF ----
def t_jf():
    return probe("https://m.jf.10010.com/")
chk("积分平台 m.jf.10010.com", t_jf)


# ---- 10 联通阅读 ----
def t_woread():
    return probe("https://10010.woread.com.cn/")
chk("联通阅读 10010.woread.com.cn", t_woread)


# ---- 11 核心脚本的 RSA 登录公钥能用 ----
def t_rsa():
    from Crypto.Cipher import PKCS1_v1_5
    from Crypto.PublicKey import RSA
    key = RSA.import_key(legacy.LOGIN_PUB_KEY)
    assert key.size_in_bits() == 1024
    enc = PKCS1_v1_5.new(key).encrypt(b"12345678")
    assert len(enc) == 128
    return "RSA-1024 加密 %d 字节" % len(enc)
chk("RSA 登录加密 (账号密码登录依赖)", t_rsa)


# ---- 12 停止信号可在真实等待中生效 ----
def t_stop():
    import threading
    ev = threading.Event()
    legacy.STOP_EVENT = ev
    t0 = time.time()
    ev.set()
    assert legacy._sleep(30) is True, "停止信号未生效"
    ms = int((time.time() - t0) * 1000)
    legacy.STOP_EVENT = None
    assert ms < 2000, "应立即返回, 实际 %dms" % ms
    return "耗时 %dms" % ms
chk("运行中可被停止信号中断", t_stop)


print()
print("=" * 50)
print("联网自检: 通过 %d / 失败 %d" % (len(ok), len(fail)))
if fail:
    print("失败项: " + ", ".join(fail))
print("=" * 50)
sys.exit(1 if fail else 0)
