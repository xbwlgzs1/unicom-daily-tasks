# -*- coding: utf-8 -*-
"""路径解析: 程序目录(资源) 与 数据目录(可写) 分离.

打包成 exe 后 __file__ 会落在临时目录, 因此:
  - 资源放 exe 旁边
  - 配置/缓存/日志统一放 %APPDATA%\\UnicomAllIn1, 保证始终可写
"""
import os
import sys
import time

APP_NAME = "UnicomAllIn1"


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def app_dir():
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    # app/paths.py -> 上一级
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_dir():
    override = os.environ.get("CMF_DATA_DIR", "").strip()
    d = override or os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), APP_NAME)
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        d = app_dir()
    return d


def res(*parts):
    return os.path.join(app_dir(), *parts)


def dat(*parts):
    return os.path.join(data_dir(), *parts)


ACCOUNTS_FILE = dat("accounts.json")
SETTINGS_FILE = dat("settings.json")
WINS_FILE = dat("wins.json")
RESULTS_FILE = dat("results.json")
TOKEN_CACHE_FILE = dat("token_cache.json")
DEVICE_ID_FILE = dat("device_id.json")


def log_file():
    return dat("run_%s.log" % time.strftime("%Y%m%d"))


def ensure_dirs():
    for d in (data_dir(),):
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
