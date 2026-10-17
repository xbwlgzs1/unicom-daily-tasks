# -*- coding: utf-8 -*-
"""探测「天天领现金」真实收益链路的原始接口响应（内核 = core/legacy.py v1.2.1）

== 2026-10-17 收口说明 ==
本探针原先存在两处**失效引用**，实际从未跑在交付内核上：
  1. 硬编码加载 `<旧版脚本路径>/中国联通v1.1.2.py`（v1.1.2 顶层脚本），
     而不是交付内核 `core/legacy.py`（v1.2.1）；
  2. 调用 `u.auth_check()` —— v1.2.1 中该方法已改名为 `ttlxj_auth_check()`。
现在：直接 `import core.legacy`，并使用 v1.2.1 的真实方法名。

== 用法 ==
    python probe_ttlxj.py          # 离线：只校验 v1.2.1 符号契约，不联网、不写文件
    python probe_ttlxj.py --live   # 额外走真实 ttlxj 链路（**只读查询**：不打卡、不抽奖）

== 凭证 ==
读取 `unicom_cookie_line.txt`（格式 `chinaUnicomCookie="<token>"`）。
脚本只打印长度，**不打印 token 明文**。

== 副作用隔离 ==
`legacy.UNICOM_TOKEN_CACHE_PATH` 是**模块级常量**（不读环境变量），登录成功后会写缓存文件。
本探针在 import 之后**直接改属性**指到系统临时目录（与 app/runner.py 的做法一致），
确保只读的 core/ 不被写入任何文件。
"""
import os
import sys
import json
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
sys.stdout.reconfigure(encoding="utf-8")

# ---- 副作用隔离: 临时目录用于重定向内核的运行时写文件 ----
TMP_CACHE = os.path.join(tempfile.gettempdir(), "unicom_probe_token_cache.json")
os.environ["UNICOM_TOKEN_CACHE_PATH"] = TMP_CACHE

COOKIE_FILE = os.path.join(BASE, "unicom_cookie_line.txt")

REQUIRED = {
    "module": ["SCRIPT_VERSION", "STOP_EVENT", "_stopped", "_check_stop", "_sleep",
               "UserService", "globalConfig"],
    "method": ["ttlxj_task", "ttlxj_authorize", "ttlxj_auth_check",
               "ttlxj_do_tasks", "ttlxj_query_available", "openPlatLineNew",
               "get_bizchannelinfo", "get_epay_authinfo", "request",
               "ensure_login", "configure_proxy"],
    # v1.1.2 的旧名（若回归出现，说明内核被降级或误替换）
    "removed": ["auth_check", "YPHD_ENABLE", "WOSTORE_RUN_TASKS", "YPHD_SECRET_KEY"],
}


def check_symbols(legacy):
    """离线符号契约校验，返回 (ok, fail)"""
    ok, fail = [], []

    def want(cond, msg):
        (ok if cond else fail).append(msg)

    want(legacy.SCRIPT_VERSION == "v1.2.1",
         "SCRIPT_VERSION == v1.2.1 (实际 %s)" % legacy.SCRIPT_VERSION)
    for n in REQUIRED["module"]:
        want(hasattr(legacy, n), "module.%s" % n)
    for n in REQUIRED["method"]:
        want(hasattr(legacy.UserService, n), "UserService.%s" % n)
    # 负向断言：v1.1.2 的旧符号必须已不存在
    want(not hasattr(legacy.UserService, "auth_check"),
         "UserService.auth_check 已移除 (v1.2.1 改名 ttlxj_auth_check)")
    for n in REQUIRED["removed"][1:]:
        want(not hasattr(legacy, n), "module.%s 已移除" % n)
    return ok, fail


def load_token():
    if not os.path.exists(COOKIE_FILE):
        return None
    raw = open(COOKIE_FILE, encoding="utf-8").read().strip()
    if not raw:
        return None
    if '"' in raw:
        return raw.split('"')[1]
    for part in raw.split(";"):
        if "=" in part and "token" in part.lower():
            return part.split("=", 1)[1].strip()
    return raw or None


def isolate_writes(legacy):
    """把内核的运行时写文件重定向到临时目录.

    `UNICOM_TOKEN_CACHE_PATH` / `HOMETOWN_MATERIAL_PATH` / `ISLAND_PRIZE_CACHE_PATH`
    都是**模块级常量**, 不读同名环境变量 —— 必须在 import 之后直接改属性
    (app/runner.py 的 apply_config() 就是这么做的)。
    """
    tmpdir = os.path.join(tempfile.gettempdir(), "unicom_probe_runtime")
    os.makedirs(tmpdir, exist_ok=True)
    moved = []
    for attr, fname in (("UNICOM_TOKEN_CACHE_PATH", "unicom_token_cache.json"),
                        ("HOMETOWN_MATERIAL_PATH", "unicom_hometown_material.jpg"),
                        ("ISLAND_PRIZE_CACHE_PATH", "unicom_prize_cache.json")):
        if hasattr(legacy, attr):
            old = getattr(legacy, attr)
            new = os.path.join(tmpdir, fname)
            setattr(legacy, attr, new)
            moved.append((attr, old, new))
    return moved


def main():
    live = "--live" in sys.argv[1:]

    from core import legacy

    print("=== 内核符号契约 (core/legacy.py) ===")
    ok, fail = check_symbols(legacy)
    for m in ok:
        print("[OK]   " + m)
    for m in fail:
        print("[FAIL] " + m)
    print("符号校验: 通过 %d / 失败 %d" % (len(ok), len(fail)))
    if fail:
        return 1

    print()
    print("=== 写文件重定向 (只读 core/ 保护) ===")
    for attr, old, new in isolate_writes(legacy):
        print("  %-28s -> %s" % (attr, new))

    if not live:
        print()
        print("离线模式结束（未联网）。加 --live 走真实 ttlxj 链路。")
        return 0

    # ---------------- live ----------------
    token = load_token()
    if not token:
        print()
        print("[SKIP] 未找到可用凭证 (%s 为空或缺失)，跳过联网探测。"
              % os.path.basename(COOKIE_FILE))
        return 0

    print()
    print("=== 联网探测 (只读) ===")
    u = legacy.UserService(1, token)
    print("token len:", len(token))
    print("login:", u.ensure_login(), "| ecs_token len:", len(u.ecs_token or ""))
    print()

    ticket_res = u.openPlatLineNew("https://epay.10010.com/ci-mps-st-web/ttlxj/")
    print("ticket_res:", {k: str(v)[:60] for k, v in (ticket_res or {}).items()})
    if not (ticket_res and ticket_res.get("ticket")):
        print("ticket 获取失败, 停止 (网络或凭证问题, 非脚本缺陷)")
        return 1

    ok1 = u.ttlxj_authorize(ticket_res["ticket"], ticket_res.get("type", ""),
                            ticket_res["loc"])
    print("authorize:", ok1)
    # v1.2.1 的真实方法名是 ttlxj_auth_check (v1.1.2 叫 auth_check)
    ok2 = u.ttlxj_auth_check()
    print("auth_check (ttlxj_auth_check):", ok2)
    print()
    if not ok2:
        print("授权未通过, 跳过后续查询")
        return 0

    headers = {"bizchannelinfo": u.get_bizchannelinfo(),
               "authinfo": u.get_epay_authinfo()}

    print("=== userDrawInfo (打卡状态) ===")
    r1 = u.request("post",
                   "https://epay.10010.com/ci-mcss-party-front/v1/ttlxj/userDrawInfo",
                   json={}, headers=headers)
    if r1 is not None:
        print(json.dumps(r1.json(), ensure_ascii=False, indent=1)[:1200])
    print()

    print("=== queryAvailable (可用立减金) ===")
    r2 = u.request("post",
                   "https://epay.10010.com/ci-mcss-party-front/v1/ttlxj/queryAvailable",
                   json={}, headers=headers)
    if r2 is not None:
        print(json.dumps(r2.json(), ensure_ascii=False, indent=1)[:1200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
