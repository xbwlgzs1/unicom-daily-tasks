# -*- coding: utf-8 -*-
"""任务执行: 同步配置 → 载入核心逻辑 → 逐账号执行 → 记录落盘 → 汇总推送.

核心逻辑直接复用 core/legacy.py (原脚本 v1.2.1), 不改其业务实现;
本模块只负责: 环境变量注入、globalConfig 注入、停止控制、结果回收、记录抽取、汇总推送.
"""
import importlib
import os
import threading
import time
import traceback
from datetime import datetime

from . import records
from .settings import MODULE_SWITCHES


# ------------------------------------------------------------
# 配置注入
# ------------------------------------------------------------
def sync_env(settings, store):
    env = settings.as_env()
    cookie = "\n".join(store.enabled_configs())
    if cookie:
        env["chinaUnicomCookie"] = cookie
    else:
        os.environ.pop("chinaUnicomCookie", None)
    # 清掉本程序上一次写入、这次已不再提供的键, 否则旧值会残留
    # (例如用户清空了人脸图清单, 但 os.environ 里还留着上一轮的路径)
    for k in [k for k in os.environ if k.startswith("UNICOM_") or k == "PUSH_PLUS_TOKEN"
              or k == "PUSH_PLUS_TOPIC" or k == "chinaUnicomCookie"]:
        if k not in env:
            os.environ.pop(k, None)
    for k, v in env.items():
        os.environ[k] = str(v)
    return cookie


def load_legacy():
    from core import legacy
    try:
        importlib.reload(legacy)
    except Exception:
        traceback.print_exc()
    return legacy


def apply_config(legacy, settings, stop_event):
    """把界面上的开关/路径写进已载入的核心模块"""
    legacy.globalConfig = settings.as_global_config()
    # 原脚本把运行时文件写死在脚本目录, exe 下会落到临时目录 → 一律指到数据目录
    try:
        from . import paths
        legacy.UNICOM_TOKEN_CACHE_PATH = paths.TOKEN_CACHE_FILE
        # v1.2.1 新增: 中奖缓存 + 家乡打卡上传素材 (运行时会写入, 必须持久化)
        legacy.ISLAND_PRIZE_CACHE_PATH = paths.dat("prize_cache.json")
        legacy.HOMETOWN_MATERIAL_PATH = paths.dat("hometown_material.jpg")
        # 人脸图清单: 界面已选 → 用界面的; 否则回落到数据目录下的 face_images/
        face_dir = paths.dat("face_images")
        chosen = [p for p in (getattr(settings, "face_images", None) or [])
                  if os.path.exists(p)]
        if chosen:
            legacy.ISLAND_LOCAL_IMAGES = chosen
        elif os.path.isdir(face_dir):
            legacy.ISLAND_LOCAL_IMAGES = sorted(
                os.path.join(face_dir, f) for f in os.listdir(face_dir)
                if f.lower().endswith((".jpg", ".jpeg", ".png")))
        else:
            legacy.ISLAND_LOCAL_IMAGES = []
    except Exception:
        traceback.print_exc()
    legacy.STOP_EVENT = stop_event


# ------------------------------------------------------------
# 抢兑模式判定 (复刻 legacy.main 的时间窗口逻辑)
# ------------------------------------------------------------
def detect_grab_mode(legacy, settings, query_only):
    if query_only:
        return False, False
    now = datetime.now()
    grab, ah = False, False
    sc = legacy.globalConfig.get("sign_config", {})
    rc = legacy.globalConfig.get("regional_config", {})
    if sc.get("run_grab_coupon") and legacy.globalConfig.get("enable_sign", True) \
            and now.hour in (9, 17) and 58 <= now.minute <= 59:
        grab = True
    ah_amount = str(legacy.AH_FRIDAY_AMOUNT or "")
    if (ah_amount and now.weekday() == 4 and rc.get("run_ah_friday", True)
            and legacy.globalConfig.get("enable_regional", True)
            and now.hour == 9 and 58 <= now.minute <= 59):
        ah, grab = True, True
    return grab, ah


# ------------------------------------------------------------
# 汇总 HTML
# ------------------------------------------------------------
def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_summary_html(results, win_count):
    th = 'style="padding:5px 10px;"'
    td = 'style="padding:5px 10px;white-space:nowrap;"'
    rows = []
    for r in results:
        cls = ' style="color:#C0392B;"' if "失败" in r.get("状态", "") else ""
        rows.append(
            f'<tr><td {td}>{_esc(r.get("序号", ""))}</td>'
            f'<td {td}>{_esc(r.get("手机号", "—"))}</td>'
            f'<td {td}{cls}>{_esc(r.get("状态", ""))}</td>'
            f'<td {td}>{_esc(r.get("话费余额", "—"))}</td>'
            f'<td {td}>{_esc(r.get("本次收益", "—") or "—")}</td></tr>')
    head = (
        f'<h3 style="margin:14px 0 6px;">📋 中国联通日常任务汇总 '
        f'({len(results)}账号) · {datetime.now().strftime("%Y-%m-%d %H:%M")}</h3>'
        '<table border="1" cellspacing="0" style="border-collapse:collapse;'
        'min-width:560px;font-size:13px;">'
        f'<tr style="background:#e8ecf1;"><th {th}>账号</th><th {th}>手机号</th>'
        f'<th {th}>状态</th><th {th}>话费余额</th><th {th}>本次收益</th></tr>'
        + "".join(rows) + "</table>")
    foot = (f'<p style="color:#7f8c8d;font-size:12px;">本次共捕获 {win_count} 条中奖/获取记录，'
            '完整明细见程序「中奖记录」页。</p>')
    return head + foot


# ------------------------------------------------------------
# 单账号执行
# ------------------------------------------------------------
def _run_one(legacy, u, query_only, stop_event):
    """复刻 legacy.main 的单账号流程 (不含 notify)"""
    result = {"序号": u.index, "手机号": "", "状态": "", "话费余额": "",
              "本次收益": "", "notify": []}
    try:
        u.configure_proxy()
        if not u.ensure_login():
            u.log("登录流程失败，跳过该账号")
            result["状态"] = "登录失败"
        else:
            u.execute_daily_tasks(query_only=query_only)
            result["状态"] = "仅查询" if query_only else "完成"
    except Exception as e:
        traceback.print_exc()
        try:
            u.log(f"❌ 账号执行异常: {e}")
        except Exception:
            pass
        result["状态"] = f"异常: {e}"

    phone = u.mobile or u.account_mobile or ""
    if phone and len(phone) == 11 and phone.isdigit():
        phone = phone[:3] + "****" + phone[7:]
    result["手机号"] = phone
    result["notify"] = [str(x) for x in (getattr(u, "notify_logs", None) or [])]
    return result


# ------------------------------------------------------------
# 整批执行
# ------------------------------------------------------------
def run_batch(settings, store, bus, stop_event, on_account=None):
    started = time.time()
    results = []

    cookie = sync_env(settings, store)
    enabled = [a for a in store.accounts if a.enabled and a.config.strip()]
    if not cookie:
        bus.emit("❌ 没有启用的账号, 请先在「账号管理」中添加并启用账号", "error")
        return {"results": [], "wins": 0, "pushed": False, "aborted": True}

    query_only = bool(settings.query_only)
    bus.emit("=" * 46, "sys")
    bus.emit(f"🚀 开始运行 · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · "
             f"{len(enabled)} 个账号 · {'查询模式' if query_only else '完整模式'}", "sys")
    bus.emit("=" * 46, "sys")

    legacy = load_legacy()
    if not legacy:
        bus.emit("❌ 核心模块载入失败", "error")
        return {"results": [], "wins": 0, "pushed": False, "aborted": True}

    apply_config(legacy, settings, stop_event)

    # 打印开关状态 (与原脚本一致的可读输出)
    for key, label, _hint in MODULE_SWITCHES:
        st = "运行" if legacy.globalConfig.get(key, True) else "关闭"
        if query_only:
            st = "仅查询" if legacy.globalConfig.get(key, True) else "关闭"
        bus.emit(f"{label}设置为: {st}", "info")

    # 构造用户
    users = []
    for i, cfg in enumerate([a.config for a in enabled]):
        try:
            users.append(legacy.UserService(i + 1, cfg))
        except Exception:
            traceback.print_exc()
            bus.emit(f"❌ 账号[{i + 1}] 配置解析失败", "error")

    run_start_idx = len(bus.snapshot())

    grab_mode, ah_mode = detect_grab_mode(legacy, settings, query_only)
    try:
        if grab_mode:
            results = _run_grab(legacy, users, enabled, settings, bus, stop_event,
                                ah_mode)
        else:
            bus.emit("🚀 开始串行执行日常任务...", "sys")
            for i, u in enumerate(users):
                if stop_event.is_set():
                    bus.emit("🛑 已按停止按钮中断, 剩余账号跳过", "warn")
                    break
                account = enabled[i] if i < len(enabled) else None
                if on_account:
                    try:
                        on_account(i + 1, len(users),
                                   account.label() if account else "")
                    except Exception:
                        pass
                bus.emit("-" * 40, "sys")
                res = _run_one(legacy, u, query_only, stop_event)
                results.append(res)
                if stop_event.is_set():
                    res["状态"] = "已停止"
                if account:
                    account.last_time = time.strftime("%Y-%m-%d %H:%M")
                    account.last_status = res["状态"]
                    account.last_balance = res["话费余额"]
                time.sleep(2)
        if not stop_event.is_set() and not query_only:
            try:
                legacy.cross_view_security_share_keys(users)
            except Exception:
                traceback.print_exc()
    except Exception as e:
        traceback.print_exc()
        bus.emit(f"❌ 运行异常: {e}", "error")

    # ---------- 记录抽取 ----------
    new_lines = bus.snapshot()[run_start_idx:]
    wins_added, results_rows = _collect_records(new_lines, results, enabled, settings)
    if results_rows:
        records.append_results(results_rows)
    store.save()

    # ---------- 汇总推送 ----------
    pushed = False
    if results:
        if settings.pushplus_token:
            html = build_summary_html(results, wins_added)
            try:
                from notify import send
                pushed = bool(send(f"中国联通日常任务 {datetime.now().strftime('%m-%d %H:%M')}", html))
            except Exception as e:
                bus.emit(f"⚠️ 推送失败: {e}", "warn")
        else:
            bus.emit("ℹ️ 未配置推送 Token, 跳过推送 (可在「设置」填写)", "warn")

    if stop_event.is_set():
        bus.emit("🛑 本次运行被手动停止", "warn")
    bus.emit("=" * 46, "sys")
    bus.emit(f"✅ 运行结束, 用时 {time.strftime('%M:%S', time.gmtime(time.time() - started))} · "
             f"{len(results)}/{len(users)} 账号 · 新增中奖记录 {wins_added} 条", "sys")
    bus.emit("=" * 46, "sys")

    return {"results": results, "wins": wins_added, "pushed": pushed,
            "aborted": stop_event.is_set()}


# ------------------------------------------------------------
# 抢兑并发模式 (复刻 legacy.main 的 ThreadPoolExecutor 分支)
# ------------------------------------------------------------
def _run_grab(legacy, users, enabled, settings, bus, stop_event, ah_mode):
    from concurrent.futures import ThreadPoolExecutor

    sc = legacy.globalConfig.get("sign_config", {})
    tasks = []
    if sc.get("run_grab_coupon") and legacy.globalConfig.get("enable_sign", True):
        tasks.append("%s元话费券" % legacy.GRAB_AMOUNT)
    if ah_mode:
        tasks.append("安徽%s元红包" % legacy.AH_FRIDAY_AMOUNT)
    bus.emit(f"🚨🚨🚨 [抢兑模式] 目标: {' + '.join(tasks)} 🚨🚨🚨", "sys")

    results = []

    def run_one(i, u):
        if stop_event.is_set():
            return
        u.configure_proxy()
        if not u.ensure_login():
            u.log("登录流程失败，跳过该账号")
            return
        with ThreadPoolExecutor(max_workers=2) as sub:
            fs = []
            if sc.get("run_grab_coupon") and legacy.globalConfig.get("enable_sign", True):
                fs.append(sub.submit(u.sign_grabCoupon))
            if ah_mode:
                fs.append(sub.submit(u.ah_friday_task))
            for f in fs:
                try:
                    f.result()
                except Exception as e:
                    u.log(f"抢兑子任务异常: {e}")

    with ThreadPoolExecutor(max_workers=max(1, len(users))) as ex:
        futs = [ex.submit(run_one, i, u) for i, u in enumerate(users)]
        for f in futs:
            try:
                f.result()
            except Exception as e:
                bus.emit(f"[-] Thread Error: {e}", "error")

    for i, u in enumerate(users):
        phone = u.mobile or u.account_mobile or ""
        if phone and len(phone) == 11 and phone.isdigit():
            phone = phone[:3] + "****" + phone[7:]
        results.append({"序号": u.index, "手机号": phone, "状态": "抢兑完成",
                        "话费余额": "", "本次收益": "",
                        "notify": [str(x) for x in (u.notify_logs or [])]})
        if i < len(enabled):
            enabled[i].last_time = time.strftime("%Y-%m-%d %H:%M")
            enabled[i].last_status = "抢兑完成"
    return results


# ------------------------------------------------------------
# 从本次日志抽取 资产 / 中奖
# ------------------------------------------------------------
def _collect_records(new_lines, results, enabled, settings):
    by_serial = {}
    for r in results:
        by_serial[r["序号"]] = r

    wins, asset_map = [], {}
    for rec in new_lines:
        serial = rec.get("account") or 0
        text = rec.get("text") or ""
        for name, val in records.extract_assets(text):
            asset_map.setdefault(serial, {})[name] = val
        w = records.extract_win(text)
        if w:
            acct = enabled[serial - 1] if 1 <= serial <= len(enabled) else None
            phone = (acct.label() if acct else "")
            wins.append({
                "时间": rec.get("t") or "",
                "账号": serial,
                "手机号": by_serial.get(serial, {}).get("手机号") or phone,
                "来源": w["来源"],
                "类型": w["类型"],
                "内容": w["内容"],
                "账号ID": acct.id if acct else "",
            })

    # 写回每账号的资产与收益
    rows = []
    for r in results:
        assets = asset_map.get(r["序号"], {})
        r["资产"] = assets
        if assets.get("话费余额"):
            r["话费余额"] = "¥" + assets["话费余额"]
        wins_for = [w["内容"] for w in wins if w["账号"] == r["序号"] and w["类型"] == "奖品"]
        r["本次收益"] = "、".join(wins_for[:3]) + ("等%d项" % len(wins_for) if len(wins_for) > 3 else "")
        rows.append({
            "时间": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "账号": r["序号"],
            "手机号": r.get("手机号", ""),
            "状态": r.get("状态", ""),
            "话费余额": r.get("话费余额", ""),
            "本次收益": r.get("本次收益", ""),
        })
    added = records.ingest_wins(wins)
    return added, rows
