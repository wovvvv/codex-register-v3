"""
test_oauth_full_flow.py — 用有头浏览器跑真实 PKCE OAuth 流程，逐步截图。

用法:
  uv run python test/test_oauth_full_flow.py

自动从 DB 取第一个成功账号，构造 OAuth 授权 URL，观察密码提交后出现什么页面。
截图保存在 test/screenshots/ 目录，按顺序编号。
"""
from __future__ import annotations

import asyncio
import sys
import base64
import hashlib
import secrets
import sqlite3
import json
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from src.browser.engine import create_page
from src.browser.helpers import set_react_input, click_submit_or_text, wait_any_element

PROXY = "http://127.0.0.1:10810"
SHOT_DIR = Path(__file__).parent / "screenshots"
SHOT_DIR.mkdir(exist_ok=True)

# OAuth 常量（与 oauth.py 一致）
OAUTH_ISSUER      = "https://auth.openai.com"
OAUTH_CLIENT_ID   = "app_EMoamEEZ73f0CkXaXp7hrann"
OAUTH_REDIRECT    = "http://localhost:1455/auth/callback"
OAUTH_SCOPE       = "openid profile email offline_access"


def _pkce():
    verifier  = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def get_test_account():
    db = Path(__file__).parent.parent / "accounts.db"
    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT email, password FROM accounts WHERE status='注册完成' LIMIT 1"
    ).fetchone()
    conn.close()
    return (row[0], row[1]) if row else (None, None)


async def run(email: str, password: str):
    _, challenge = _pkce()
    state = secrets.token_urlsafe(24)
    auth_url = (
        f"{OAUTH_ISSUER}/oauth/authorize?"
        + urlencode({
            "response_type":         "code",
            "client_id":             OAUTH_CLIENT_ID,
            "redirect_uri":          OAUTH_REDIRECT,
            "scope":                 OAUTH_SCOPE,
            "code_challenge":        challenge,
            "code_challenge_method": "S256",
            "state":                 state,
        })
    )

    logger.info(f"测试账号: {email}")
    logger.info(f"OAuth URL: {auth_url[:80]}...")
    shot_idx = 0

    async def snap(label: str):
        nonlocal shot_idx
        p = SHOT_DIR / f"{shot_idx:02d}_{label}.png"
        try:
            await page.screenshot(path=str(p), full_page=True)
        except Exception as e:
            logger.warning(f"截图失败: {e}")
        logger.info(f"📸 [{shot_idx:02d}] {label}  |  URL={page.url}")
        shot_idx += 1

    async with create_page(engine="camoufox", proxy=PROXY, headless=False, slow_mo=120) as page:

        # Step 1: 导航到 OAuth 授权 URL（预期被 302 → login 或直接给 code）
        logger.info("Step 1: 导航到 OAuth 授权 URL ...")
        try:
            await page.goto(auth_url, wait_until="commit", timeout=25_000)
        except Exception as e:
            if any(s in str(e) for s in ("ERR_CONNECTION_REFUSED", "ERR_ABORTED", "net::ERR")):
                logger.info("localhost 回调被中止（正常）")
            else:
                logger.warning(f"goto 异常: {e}")

        await asyncio.sleep(2)
        await snap("01_after_oauth_goto")

        current_url = page.url
        logger.info(f"当前 URL: {current_url}")

        # Step 2: 如果重定向到登录页，填邮箱
        if "log-in" in current_url or "/login" in current_url or "auth.openai.com" in current_url:
            logger.info("Step 2: 检测到登录/auth 页面，填邮箱 ...")

            # 先等待页面加载完成
            await asyncio.sleep(3)
            await snap("02_login_page")

            # 尝试找邮箱输入框
            email_result = await wait_any_element(
                page,
                ["input[type='email']", "input[name='email']", "input[name='username']",
                 "#username", "input[id*='email']", "input[autocomplete='email']"],
                timeout_ms=15_000,
            )
            if email_result:
                e_sel, _ = email_result
                logger.info(f"找到邮箱输入框: {e_sel!r}")
                await set_react_input(page, e_sel, email)
                await asyncio.sleep(1)
                await snap("03_email_filled")

                # 点击继续
                await click_submit_or_text(page, ["Continue", "继续", "Next"])
                await asyncio.sleep(3)
                await snap("04_after_email_submit")
            else:
                logger.warning("未找到邮箱输入框，查看页面内容 ...")
                # 用 JS 看看有什么 input
                inputs = await page.evaluate("""
                    () => Array.from(document.querySelectorAll('input')).map(el => ({
                        type: el.type, name: el.name, id: el.id, placeholder: el.placeholder,
                        visible: el.getBoundingClientRect().width > 0
                    }))
                """)
                logger.info(f"页面所有 input: {inputs}")
                await snap("03_no_email_input_found")

        # Step 3: 填密码
        logger.info("Step 3: 等待密码输入框 ...")
        pw_result = await wait_any_element(
            page,
            ["input[type='password']", "input[name='password']"],
            timeout_ms=20_000,
        )
        if pw_result:
            p_sel, _ = pw_result
            logger.info(f"找到密码输入框: {p_sel!r}")
            await set_react_input(page, p_sel, password)
            await asyncio.sleep(1)
            await snap("05_password_filled")

            # 点击继续
            await click_submit_or_text(page, ["Continue", "Login", "Sign in", "继续"])
            logger.info("已提交密码，等待下一步页面 ...")
        else:
            logger.warning("未找到密码输入框")
            await snap("05_no_password_input")

        # Step 4: 密码提交后，连续观察页面变化（20 秒内，每 2 秒一次）
        logger.info("Step 4: 观察密码提交后的页面 ...")
        for i in range(10):
            await asyncio.sleep(2)
            url = page.url
            await snap(f"06_after_pw_{i:02d}")
            logger.info(f"  [{i:02d}] URL: {url}")

            # 检查 OTP
            otp_boxes = await page.locator(
                "input[type='text'][maxlength='1'], input[maxlength='1']"
            ).count()
            otp_single = await page.locator(
                "input[autocomplete='one-time-code'], input[name='code']"
            ).count()
            all_inputs = await page.evaluate("""
                () => Array.from(document.querySelectorAll('input')).map(el => ({
                    type: el.type, name: el.name, id: el.id,
                    maxlength: el.maxLength, autocomplete: el.autocomplete,
                    visible: el.getBoundingClientRect().width > 0
                })).filter(el => el.visible)
            """)
            logger.info(f"  OTP boxes (maxlength=1): {otp_boxes}")
            logger.info(f"  OTP single field: {otp_single}")
            if all_inputs:
                logger.info(f"  可见 input 字段: {all_inputs}")

            if otp_boxes >= 4 or otp_single > 0:
                logger.success("✅ 发现 OTP 验证码输入框！密码后确实有邮箱验证码步骤")
                break

            if "chatgpt.com" in url or "localhost" in url:
                logger.info("已完成 OAuth 流程或获取到 code")
                break

            if "about-you" in url:
                logger.info("跳转到 about-you 页面")
                break

        logger.info("观察完成，浏览器保持 60 秒供手动查看 ...")
        await asyncio.sleep(60)


if __name__ == "__main__":
    _email, _password = get_test_account()
    if not _email:
        logger.error("数据库中无成功注册账号")
        sys.exit(1)
    logger.info(f"从数据库取账号: {_email}")
    asyncio.run(run(_email, _password))

