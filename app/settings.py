# -*- coding: utf-8 -*-
"""配置与账号存取 (JSON 持久化, 替代原脚本的环境变量 + globalConfig 字典)"""
import copy
import json
import os
import time
import uuid

from . import paths

# ---- 11 个功能模块总开关 (对应 v1.2.1 的 globalConfig) ----
MODULE_SWITCHES = [
    ("enable_sign",     "首页签到",   "六宫格转盘/连签/月签礼包"),
    ("enable_ltzf",     "联通祝福",   "星座配对/大转盘/盲盒抽奖"),
    ("enable_ttlxj",    "天天领现金", "每日打卡/抽奖"),
    ("enable_ttxc",     "通通乡村",   "农场种植/新手引导/任务"),
    ("enable_market",   "权益超市",   "做任务/积分抽奖/自动领奖"),
    ("enable_woread",   "联通阅读",   "自动读书/心跳/抽奖(默认关)"),
    ("enable_aiting",   "联通爱听",   "JF积分签到/模拟阅读"),
    ("enable_security", "安全管家",   "日常任务/安全分"),
    ("enable_ltyp",     "联通云盘",   "海岛逐浪/芒果AI入戏/家乡打卡"),
    ("enable_wostore",  "沃云手机",   "签到/积分抽奖/积分兑换"),
    ("enable_regional", "区域专区",   "安徽超级星期五/辽宁/新疆/河南/云南"),
]

DEFAULT_SETTINGS = {
    # --- 模块总开关 ---
    "enable_sign": True,
    "enable_ltzf": True,
    "enable_ttlxj": True,
    "enable_ttxc": True,
    "enable_market": True,
    "enable_woread": False,      # 原脚本默认关闭
    "enable_aiting": True,
    "enable_security": True,
    "enable_ltyp": True,
    "enable_wostore": True,
    "enable_regional": True,
    "enable_notify": True,

    # --- 签到区子开关 ---
    "run_grab_coupon": False,    # 抢话费券 (需配 9/17点58分 定时)
    # --- 权益超市子开关 ---
    # 注: v1.2.1 已下线「会员中心积分任务」, 原 run_member_center 开关随之移除
    "market_run_task": True,
    "market_run_draw": True,
    "market_run_claim": True,
    # --- 区域专区子开关 ---
    "run_ah_friday": False,
    # --- 设备 ---
    "refresh_device_id": False,

    # --- 推送 ---
    "pushplus_token": "",
    "pushplus_topic": "",

    # --- 常用环境变量 ---
    "query_only": False,         # UNICOM_TEST_MODE=query
    "proxy_api": "",
    "proxy_type": "socks5",
    "grab_amount": "5",          # UNICOM_GRAB_AMOUNT
    "ah_friday_amount": "",      # UNICOM_AH_FRIDAY_AMOUNT
    "attempt_count": "1",        # UNICOM_ATTEMPT_COUNT (新疆抽奖尝试次数)
    "hometown_enable": True,     # UNICOM_HOMETOWN_ENABLE
    "ttxc_garbage_wait": "28",
    "token_cache_dir": "",       # 留空 = 默认数据目录

    # --- 海岛逐浪 / 芒果 AI入戏 (v1.2.1 新增) ---
    "face_images": [],           # 本地上传的人脸图路径列表 (绝对路径) → UNICOM_CMF_LOCAL_IMAGES
    "cmf_img_fid": "",           # UNICOM_CMF_IMG_FID (云盘人脸图 FID)
    "cmf_template_id": "",       # UNICOM_CMF_TEMPLATE_ID
    "cmf_target_id": "",         # UNICOM_CMF_TARGET_ID
    "cmf_source": "",            # UNICOM_CMF_SOURCE
    "cmf_del_cloud_photos": True,  # UNICOM_CMF_DEL_CLOUD_PHOTOS
    "cloud_ttl_hours": "12",     # UNICOM_CLOUD_TTL_HOURS

    # --- 定时 ---
    "schedule_enabled": True,
    "schedule_times": "07:00,20:00",
    "run_on_start": False,
}

_BOOL_KEYS = {k for k in DEFAULT_SETTINGS if isinstance(DEFAULT_SETTINGS[k], bool)}
_LIST_KEYS = {k for k in DEFAULT_SETTINGS if isinstance(DEFAULT_SETTINGS[k], list)}
_INTISH = ("grab_amount", "attempt_count", "ttxc_garbage_wait")


class Settings(object):
    def __init__(self):
        self._d = copy.deepcopy(DEFAULT_SETTINGS)
        self.load()

    # ---------- 访问 ----------
    def __getattr__(self, name):
        d = object.__getattribute__(self, "_d")
        if name in d:
            return d[name]
        raise AttributeError(name)

    def __setattr__(self, name, value):
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        d = object.__getattribute__(self, "_d")
        if name in d:
            if name in _LIST_KEYS:
                if isinstance(value, str):
                    value = [x.strip() for x in value.replace("，", ",").split(",")
                             if x.strip()]
                else:
                    value = [str(x).strip() for x in (value or []) if str(x).strip()]
            elif name in _BOOL_KEYS:
                value = bool(value)
            else:
                value = "" if value is None else str(value).strip()
            d[name] = value
        else:
            object.__setattr__(self, name, value)

    def as_dict(self):
        return copy.deepcopy(self._d)

    def update(self, **kw):
        for k, v in kw.items():
            if k in self._d:
                setattr(self, k, v)

    # ---------- 持久化 ----------
    def load(self):
        try:
            with open(paths.SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k, v in data.items():
                    if k in self._d:
                        setattr(self, k, v)
        except Exception:
            pass

    def save(self):
        paths.ensure_dirs()
        try:
            with open(paths.SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._d, f, ensure_ascii=False, indent=2)
            return True, ""
        except Exception as e:
            return False, str(e)

    # ---------- 转环境变量 ----------
    def as_env(self):
        s = self._d
        env = {
            "UNICOM_PROXY_API": s["proxy_api"],
            "UNICOM_PROXY_TYPE": s["proxy_type"] or "socks5",
            "UNICOM_GRAB_AMOUNT": s["grab_amount"] or "5",
            "UNICOM_AH_FRIDAY_AMOUNT": s["ah_friday_amount"],
            "UNICOM_ATTEMPT_COUNT": s["attempt_count"] or "1",
            "UNICOM_HOMETOWN_ENABLE": "1" if s["hometown_enable"] else "0",
            "UNICOM_TTXC_GARBAGE_WAIT": s["ttxc_garbage_wait"] or "28",
            "UNICOM_TEST_MODE": "query" if s["query_only"] else "0",
            "PUSH_PLUS_TOKEN": s["pushplus_token"],
            "PUSH_PLUS_TOPIC": s["pushplus_topic"],
            # --- 海岛逐浪 / 芒果 AI入戏 (v1.2.1) ---
            # 人脸图清单: 以逗号拼接的绝对路径列表; 核心脚本按 "," 切分并逐个校验存在性
            "UNICOM_CMF_LOCAL_IMAGES": ",".join(s.get("face_images") or []),
            "UNICOM_CMF_IMG_FID": s["cmf_img_fid"],
            "UNICOM_CMF_TEMPLATE_ID": s["cmf_template_id"],
            "UNICOM_CMF_TARGET_ID": s["cmf_target_id"],
            "UNICOM_CMF_SOURCE": s["cmf_source"],
            "UNICOM_CMF_DEL_CLOUD_PHOTOS": "1" if s["cmf_del_cloud_photos"] else "0",
            "UNICOM_CLOUD_TTL_HOURS": s["cloud_ttl_hours"] or "12",
        }
        return {k: v for k, v in env.items() if v not in ("", None)}

    # ---------- 转 globalConfig ----------
    def as_global_config(self):
        """生成原脚本的 globalConfig 字典 (模块总开关 + 各子开关)"""
        s = self._d
        cfg = {key: bool(s.get(key, True)) for key, _l, _h in MODULE_SWITCHES}
        cfg["enable_notify"] = bool(s["enable_notify"])
        cfg["refresh_device_id"] = bool(s["refresh_device_id"])
        cfg["sign_config"] = {"run_grab_coupon": bool(s["run_grab_coupon"])}
        # v1.2.1 的 market_config 只有 3 个键 (会员中心任务已下线)
        cfg["market_config"] = {
            "run_task": bool(s["market_run_task"]),
            "run_draw": bool(s["market_run_draw"]),
            "run_claim": bool(s["market_run_claim"]),
        }
        cfg["regional_config"] = {"run_ah_friday": bool(s["run_ah_friday"])}
        return cfg


# ============================================================
# 账号
# ============================================================
class Account(object):
    def __init__(self, **kw):
        # uuid 而非时间戳: 批量导入同一毫秒会生成重复 id, 导致选中/删除互相串
        self.id = str(kw.get("id") or "") or ("a" + uuid.uuid4().hex[:12])
        self.config = str(kw.get("config") or "").strip()
        self.note = str(kw.get("note") or "").strip()
        self.enabled = bool(kw.get("enabled", True))
        self.last_time = str(kw.get("last_time") or "")
        self.last_status = str(kw.get("last_status") or "")
        self.last_balance = str(kw.get("last_balance") or "")

    def label(self):
        if self.note:
            return self.note
        head = self.config.split("#")[0].strip()
        if len(head) == 11 and head.isdigit():
            return head[:3] + "****" + head[7:]
        if len(head) > 12:
            return head[:8] + "..."
        return head or "(空)"

    def to_dict(self):
        return {"id": self.id, "config": self.config, "note": self.note,
                "enabled": self.enabled, "last_time": self.last_time,
                "last_status": self.last_status, "last_balance": self.last_balance}

    @classmethod
    def from_dict(cls, d):
        return cls(**d) if isinstance(d, dict) else cls(config=str(d or ""))


class AccountStore(object):
    def __init__(self):
        self.accounts = []
        self.load()

    def load(self):
        self.accounts = []
        try:
            with open(paths.ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self.accounts = [Account.from_dict(x) for x in data if x]
        except Exception:
            self.accounts = []

    def save(self):
        paths.ensure_dirs()
        try:
            with open(paths.ACCOUNTS_FILE, "w", encoding="utf-8") as f:
                json.dump([a.to_dict() for a in self.accounts], f,
                          ensure_ascii=False, indent=2)
            return True, ""
        except Exception as e:
            return False, str(e)

    def enabled_configs(self):
        return [a.config for a in self.accounts if a.enabled and a.config.strip()]

    def add(self, configs, note=""):
        if isinstance(configs, str):
            parts = [c.strip() for c in configs.replace("&", "\n").splitlines()]
        else:
            parts = [str(c).strip() for c in configs]
        added, existing = 0, {a.config for a in self.accounts}
        for c in parts:
            if not c or c in existing:
                continue
            self.accounts.append(Account(config=c, note=note))
            existing.add(c)
            added += 1
        return added

    def remove(self, ids):
        self.accounts = [a for a in self.accounts if a.id not in set(ids)]

    def toggle(self, ids, enabled=None):
        ids = set(ids)
        for a in self.accounts:
            if a.id in ids:
                a.enabled = (not a.enabled) if enabled is None else bool(enabled)

    def get(self, aid):
        for a in self.accounts:
            if a.id == aid:
                return a
        return None
