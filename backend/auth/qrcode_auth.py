"""
auth/qrcode_auth.py
扫码认证 — B站 / 抖音
流程：生成二维码 → 用户扫码 → 轮询登录状态 → 获取 token 保存
"""

import time
import logging
import hashlib
import requests
from typing import Optional, Dict, Any
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from auth.token_store import get_token_store, TokenData

logger = logging.getLogger(__name__)


def _make_qr_image_base64(url: str) -> str:
    """
    已废弃：二维码现在由前端 JavaScript (qrcode.js) 生成
    后端只需返回 qrcode_url，前端负责渲染
    保留此函数仅为向后兼容，始终返回空字符串
    """
    return ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Bilibili 扫码登录
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BILI_PASSPORT = "https://passport.bilibili.com"

def bilibili_get_qrcode() -> Dict[str, Any]:
    """
    申请 B站 扫码 URL
    返回: {qrcode_key, qrcode_url, qrcode_image_b64, expires_in}
    """
    try:
        resp = requests.get(
            f"{BILI_PASSPORT}/x/passport-login/web/qrcode/generate",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            return {"error": data.get("message", "申请二维码失败")}

        url = data["data"]["url"]
        key = data["data"]["qrcode_key"]
        return {
            "qrcode_key": key,
            "qrcode_url": url,
            "qrcode_image_b64": _make_qr_image_base64(url),
            "expires_in": 180,   # B站二维码 3 分钟有效
        }
    except Exception as e:
        logger.error(f"[Bilibili QR] 生成失败: {e}")
        return {"error": str(e)}


def bilibili_poll_qrcode(qrcode_key: str, user_id: str) -> Dict[str, Any]:
    """
    轮询 B站 扫码状态
    返回:
      status: "waiting"     待扫描
              "scanned"      已扫描未确认
              "confirmed"    已确认，token 已保存
              "expired"      已过期
              "error"        出错
    """
    try:
        resp = requests.get(
            f"{BILI_PASSPORT}/x/passport-login/web/qrcode/poll",
            params={"qrcode_key": qrcode_key},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        code = data.get("data", {}).get("code", -1)

        if code == 0:
            # 登录成功，提取三个关键 Cookie
            cookies = resp.cookies.get_dict()
            sessdata = cookies.get("SESSDATA", "")
            bili_jct = cookies.get("bili_jct", "")
            dedeuserid = cookies.get("DedeUserID", "")

            # 如果 Set-Cookie 中没有，尝试从 URL 参数中解析
            if not sessdata:
                url = data["data"].get("url", "")
                import urllib.parse as up
                parsed = dict(up.parse_qsl(up.urlparse(url).query))
                sessdata = parsed.get("SESSDATA", "")
                bili_jct = parsed.get("bili_jct", "")
                dedeuserid = parsed.get("DedeUserID", "")

            if not sessdata:
                logger.warning(f"[Bilibili QR] 登录成功但未获取到 SESSDATA, cookies: {cookies}, url: {data['data'].get('url', '')}")
                return {"status": "error", "error": "未获取到 SESSDATA"}

            # 保存三个独立的 cookie 字段
            _save_bilibili_cookies(sessdata, bili_jct, dedeuserid, user_id)
            return {"status": "confirmed"}

        elif code == 86101:
            return {"status": "waiting"}
        elif code == 86090:
            return {"status": "scanned"}
        elif code == 86038:
            return {"status": "expired"}
        else:
            return {"status": "waiting"}

    except Exception as e:
        logger.error(f"[Bilibili QR Poll] 失败: {e}")
        return {"status": "error", "error": str(e)}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 抖音扫码登录（开放平台网页版）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DOUYIN_API = "https://open.douyin.com"

def douyin_get_qrcode() -> Dict[str, Any]:
    """
    申请抖音扫码 URL（网页授权版，无需应用审核）
    """
    try:
        import config
        # 抖音网页版登录
        token = hashlib.md5(str(time.time()).encode()).hexdigest()
        # 使用抖音开放平台的扫码登录接口
        resp = requests.get(
            "https://sso.douyin.com/get_qrcode/",
            params={
                "service": "https://www.douyin.com",
                "need_logo": "false",
                "need_short_url": "true",
            },
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.douyin.com/",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("err_code") != 0:
            return {"error": data.get("err_msg", "申请失败")}

        qr_url = data.get("data", {}).get("qrcode_index_url", "")
        token = data.get("data", {}).get("token", "")

        return {
            "qrcode_key": token,
            "qrcode_url": qr_url,
            "qrcode_image_b64": _make_qr_image_base64(qr_url),
            "expires_in": 120,
        }
    except Exception as e:
        logger.error(f"[Douyin QR] 生成失败: {e}")
        return {"error": str(e)}


def douyin_poll_qrcode(qrcode_key: str, user_id: str) -> Dict[str, Any]:
    """轮询抖音扫码状态"""
    try:
        resp = requests.get(
            "https://sso.douyin.com/check_qrconnect/",
            params={"token": qrcode_key, "service": "https://www.douyin.com"},
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.douyin.com/",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        err_code = data.get("err_code", -1)

        if err_code == 0:
            # 登录成功
            cookies = resp.cookies.get_dict()
            cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
            _save_cookie_token("douyin", cookie_str, user_id, cookies=resp.cookies)
            return {"status": "confirmed"}
        elif err_code == 10011:
            return {"status": "waiting"}   # 待扫描
        elif err_code == 10012:
            return {"status": "scanned"}   # 已扫描未确认
        elif err_code == 10010:
            return {"status": "expired"}
        else:
            return {"status": "waiting"}

    except Exception as e:
        logger.error(f"[Douyin QR Poll] 失败: {e}")
        return {"status": "error", "error": str(e)}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 通用工具
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _save_cookie_token(platform: str, cookie_str: str, user_id: str, cookies=None) -> None:
    """将扫码获得的 Cookie 保存到 TokenStore"""
    from datetime import datetime, timedelta
    store = get_token_store(user_id)
    store.save(TokenData(
        platform=platform,
        auth_mode="cookie",
        cookie=cookie_str,
        status="connected",
        expires_at=(datetime.utcnow() + timedelta(days=30)).isoformat(),
        last_refresh=datetime.utcnow().isoformat(),
        extra={"login_method": "qrcode"},
    ))
    logger.info(f"[QRCode] {platform} 扫码登录成功，Cookie 已保存")


def _save_bilibili_cookies(sessdata: str, bili_jct: str, dedeuserid: str, user_id: str) -> None:
    """保存 B站三个关键 Cookie（SESSDATA, bili_jct, DedeUserID）"""
    from datetime import datetime, timedelta
    store = get_token_store(user_id)
    store.save(TokenData(
        platform="bilibili",
        auth_mode="cookie",
        cookie=f"SESSDATA={sessdata}; bili_jct={bili_jct}; DedeUserID={dedeuserid}",
        sessdata=sessdata,
        bili_jct=bili_jct,
        dedeuserid=dedeuserid,
        status="connected",
        expires_at=(datetime.utcnow() + timedelta(days=30)).isoformat(),
        last_refresh=datetime.utcnow().isoformat(),
        extra={"login_method": "qrcode"},
    ))
    logger.info(f"[QRCode] B站扫码登录成功，SESSDATA/bili_jct/DedeUserID 已保存")


# 分发函数
def get_qrcode(platform: str) -> Dict[str, Any]:
    if platform == "bilibili":
        return bilibili_get_qrcode()
    elif platform == "douyin":
        return douyin_get_qrcode()
    else:
        return {"error": f"平台 {platform} 不支持扫码登录"}


def poll_qrcode(platform: str, qrcode_key: str, user_id: str) -> Dict[str, Any]:
    if platform == "bilibili":
        return bilibili_poll_qrcode(qrcode_key, user_id)
    elif platform == "douyin":
        return douyin_poll_qrcode(qrcode_key, user_id)
    else:
        return {"status": "error", "error": f"平台 {platform} 不支持扫码登录"}
