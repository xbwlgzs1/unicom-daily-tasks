# -*- coding: utf-8 -*-
"""notify 模块: 原脚本 `from notify import send` 依赖的推送实现.

放在程序根目录, 使核心模块的 `from notify import send` 能直接命中本文件.
配置读取 app.settings (界面上的「推送 Token」), 不需要手写 notify.py.
"""
import os


def send(title, content):
    """发送通知; 返回 True=成功. 未配置 Token 时只落日志, 不外发."""
    title = str(title or "")
    content = str(content or "")
    try:
        from app import logstream as _ls
    except Exception:
        _ls = None

    token = ""
    topic = ""
    try:
        from app.settings import Settings
        s = Settings()
        token = s.pushplus_token
        topic = s.pushplus_topic
    except Exception:
        token = os.environ.get("PUSH_PLUS_TOKEN", "").strip()
        topic = os.environ.get("PUSH_PLUS_TOPIC", "").strip()

    if not token:
        _log("⚠️ 未配置推送 Token, 跳过推送 (可在「设置」填写)", "warn")
        _log("──── 推送内容预览 ────", "sys")
        for line in content.splitlines():
            _log(line, "info")
        _log("──── 预览结束 ────", "sys")
        return False

    import requests
    body = {"token": token, "title": title, "content": content, "template": "html"}
    if topic:
        body["topic"] = topic
    try:
        res = requests.post("https://www.pushplus.plus/send", json=body, timeout=20)
        data = res.json()
        if str(data.get("code")) == "200":
            _log(f"✅ 推送成功 (内容长度 {len(content)})", "ok")
            return True
        _log(f"❌ 推送失败: {data}", "error")
    except Exception as e:
        _log(f"❌ 推送异常: {e}", "error")
    return False


def _log(msg, level=None):
    """有 LogBus 就进总线 (界面可见), 否则打到真实 stdout"""
    import sys
    try:
        from app import logstream
        bus = getattr(logstream, "_CURRENT_BUS", None)
        if bus is not None:
            bus.emit(msg, level)
            return
    except Exception:
        pass
    try:
        sys.stdout.write(str(msg) + "\n")
    except Exception:
        pass
