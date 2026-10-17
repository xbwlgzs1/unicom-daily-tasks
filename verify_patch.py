# -*- coding: utf-8 -*-
"""校验 v1.2.1 内核的开关改动是否生效（内核 = core/legacy.py）

== 2026-10-17 收口说明 ==
本脚本原先是 v1.1.2 时期的临时探针，存在三处**失效引用**，实际从未跑在交付内核上：
  1. 硬编码加载 `<旧版脚本路径>/中国联通v1.1.2.py`（v1.1.2 顶层脚本），
     而不是交付内核 `core/legacy.py`（v1.2.1）；
  2. 引用 v1.2.1 **已移除**的 `YPHD_ENABLE`（旧名，v1.2.1 已随乘风活动下架删除）
     → 会直接抛 AttributeError；
  3. 引用 v1.2.1 **已移除**的 `WOSTORE_RUN_TASKS`（旧开关，已并入活动码列表）
     → 同样抛 AttributeError。
现在：直接 `import core.legacy`，断言改用 v1.2.1 的真实符号，并对旧符号做**负向断言**
（旧符号若回归出现 = 内核被降级或误替换，立即报错）。

== 用法 ==
    python verify_patch.py          # 离线：内核开关/符号契约校验，不联网、不写文件
    python verify_patch.py --live   # 额外实测「沃云手机」「云盘」两个模块（**会真实调用联通接口**）

== 副作用隔离 ==
`legacy.UNICOM_TOKEN_CACHE_PATH` 等是**模块级常量**（不读环境变量），
登录成功后会写缓存文件。import 之后直接改属性指到临时目录，保护只读的 core/。
"""
import os
import sys
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
sys.stdout.reconfigure(encoding="utf-8")

COOKIE_FILE = os.path.join(BASE, "unicom_cookie_line.txt")

# v1.2.1 中与「旧开关」等价的真实符号（替代 YPHD_ENABLE / WOSTORE_RUN_TASKS）
REQUIRED_MODULE = [
    "SCRIPT_VERSION", "globalConfig", "UserService",
    "STOP_EVENT", "_stopped", "_check_stop", "_sleep",
    # 签名常量: v1.1.2 的 YPHD_SECRET_KEY 在 v1.2.1 重命名为 HOMETOWN_LOTTERY_SECRET
    "HOMETOWN_LOTTERY_SECRET",
    # 功能开关（模块级布尔）
    "HOMETOWN_ENABLE",
    # 沃云手机活动码（替代已移除的 WOSTORE_RUN_TASKS 总开关）
    "WOSTORE_CLOUD_ACTIVITY_CODES",
    "WOSTORE_LOTTERY_ACTIVITY_CODES",
    "WOSTORE_CLOUD_ACTIVITY_CODE",
    "WOSTORE_POINTS_ACT_CODE",
    # 海岛逐浪 / 芒果 AI入戏（v1.2.1 新增，替代 v1.1.2 的 YPHD_* 乘风活动）
    "ISLAND_MGTV_BASE", "ISLAND_ACTIVITY_ID", "ISLAND_LOCAL_IMAGES",
    "ISLAND_PRIZE_CACHE_PATH", "ISLAND_DEL_CLOUD_PHOTOS",
]

REQUIRED_METHODS = [
    "wostore_cloud_task", "ltyp_task", "market_task", "sign_task_main",
    "ensure_login", "unicom_login", "execute_daily_tasks", "request",
]

# v1.2.1 已移除的旧符号 —— 必须**不存在**（负向断言）
REMOVED = ["YPHD_ENABLE", "YPHD_MGTV_BASE", "YPHD_SECRET_KEY", "WOSTORE_RUN_TASKS"]


def isolate_writes(legacy):
    """把内核运行时写文件重定向到临时目录（这些是模块常量，不读环境变量）"""
    tmpdir = os.path.join(tempfile.gettempdir(), "unicom_verify_runtime")
    os.makedirs(tmpdir, exist_ok=True)
    out = []
    for attr, fname in (("UNICOM_TOKEN_CACHE_PATH", "unicom_token_cache.json"),
                        ("HOMETOWN_MATERIAL_PATH", "unicom_hometown_material.jpg"),
                        ("ISLAND_PRIZE_CACHE_PATH", "unicom_prize_cache.json")):
        if hasattr(legacy, attr):
            setattr(legacy, attr, os.path.join(tmpdir, fname))
            out.append(attr)
    return out


def check_switches(legacy):
    ok, fail = [], []

    def want(cond, msg):
        (ok if cond else fail).append(msg)

    want(legacy.SCRIPT_VERSION == "v1.2.1",
         "SCRIPT_VERSION == v1.2.1 (实际 %s)" % legacy.SCRIPT_VERSION)

    gc = legacy.globalConfig
    want(gc.get("enable_sign") is not None, "globalConfig.enable_sign 存在")
    # 权益超市: v1.2.1 已下线「会员中心积分任务」, market_config 只应剩 3 个键
    want(set(gc.get("market_config", {}).keys()) == {"run_task", "run_draw", "run_claim"},
         "market_config == {run_task, run_draw, run_claim} (会员中心任务已下线), 实际 %s"
         % sorted(gc.get("market_config", {}).keys()))
    want(set(gc.get("sign_config", {}).keys()) == {"run_grab_coupon"},
         "sign_config == {run_grab_coupon}")
    want(set(gc.get("regional_config", {}).keys()) == {"run_ah_friday"},
         "regional_config == {run_ah_friday}")
    # 11 个模块总开关
    mods = [k for k in gc if k.startswith("enable_") and isinstance(gc[k], bool)]
    want(len(mods) == 12, "globalConfig 有 12 个 enable_* 布尔 (11 模块 + enable_notify), 实际 %d" % len(mods))

    for n in REQUIRED_MODULE:
        want(hasattr(legacy, n), "module.%s" % n)
    for n in REQUIRED_METHODS:
        want(hasattr(legacy.UserService, n), "UserService.%s" % n)

    # 负向断言: 旧符号必须已不存在
    for n in REMOVED:
        want(not hasattr(legacy, n), "module.%s 已移除 (v1.2.1 不再提供)" % n)

    # 沃云手机: 旧 WOSTORE_RUN_TASKS 关闭的做法, 现在由活动码列表表达
    want(legacy.WOSTORE_LOTTERY_ACTIVITY_CODES == ["HD2026092100322"],
         "WOSTORE_LOTTERY_ACTIVITY_CODES == ['HD2026092100322'], 实际 %s"
         % (legacy.WOSTORE_LOTTERY_ACTIVITY_CODES,))
    want(bool(legacy.WOSTORE_CLOUD_ACTIVITY_CODES),
         "WOSTORE_CLOUD_ACTIVITY_CODES 非空: %s" % (legacy.WOSTORE_CLOUD_ACTIVITY_CODES,))

    # 签名常量 (YPHD_SECRET_KEY 的 v1.2.1 位置)
    want(legacy.HOMETOWN_LOTTERY_SECRET == "s8Hf3LqP9xN2vM5bR7tY1wZ4cA6eG0K",
         "HOMETOWN_LOTTERY_SECRET 值正确")
    return ok, fail


def load_token():
    if not os.path.exists(COOKIE_FILE):
        return None
    raw = open(COOKIE_FILE, encoding="utf-8").read().strip()
    if not raw:
        return None
    if '"' in raw:
        return raw.split('"')[1]
    return raw or None


def main():
    live = "--live" in sys.argv[1:]

    from core import legacy

    print("=== v1.2.1 内核开关/符号契约 (core/legacy.py) ===")
    ok, fail = check_switches(legacy)
    for m in ok:
        print("[OK]   " + m)
    for m in fail:
        print("[FAIL] " + m)
    print()
    print("开关校验: 通过 %d / 失败 %d" % (len(ok), len(fail)))
    if fail:
        return 1

    print("写文件已重定向到临时目录: %s" % ", ".join(isolate_writes(legacy)))

    if not live:
        print()
        print("离线模式结束（未联网）。加 --live 实测沃云手机 / 云盘两个模块。")
        return 0

    token = load_token()
    if not token:
        print()
        print("[SKIP] 未找到可用凭证 (%s 为空或缺失)，跳过联网实测。"
              % os.path.basename(COOKIE_FILE))
        return 0

    print()
    print("=== 联网实测 ===")
    u = legacy.UserService(1, token)
    print("login:", u.ensure_login())
    print()
    print("=== 实测 沃云手机 (期望: 签到 + 积分签到, 无 12 个任务刷屏) ===")
    u.wostore_cloud_task()
    print()
    print("=== 实测 云盘 (期望: 会员体验正常, 乘风已下线显示跳过, 清理保留) ===")
    u.ltyp_task()
    print()
    print("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
