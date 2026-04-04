"""
test_oauth_login_flow.py — 有头浏览器手动观察 OAuth 重新登录流程中密码后的页面。

用法:
  uv run python test/test_oauth_login_flow.py [email] [password]

如果不传参数则从数据库取第一个成功账号。
截图保存在 test/screenshots/ 目录。
"""
from __future__ import annotations

import asyncio
import sys
import os
import sqlite3
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from src.browser.engine import create_page
from src.browser.helpers import set_react_input, click_submit_or_text, wait_any_element

PROXY = "http://127.0.0.1:10810"
SHOT_DIR = Path(__file__).parent / "screenshots"
SHOT_DIR.mkdir(exist_ok=True)

# Auth0 re-login 入口（模拟 OAuth 流程被踢回登录页的情况）
LOGIN_URL = "https://auth.openai.com/log-in"


def get_test_account():
    db = Path(__file__).parent.parent / "accounts.db"
    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT email, password FROM accounts WHERE status='注册完成' LIMIT 1"
    ).fetchone()
    conn.close()
    return (row[0], row[1]) if row else (None, None)


async def run(email: str, password: str):
    logger.info(f"测试账号: {email}")
    shot_idx = 0

    async def snap(label: str):
        nonlocal shot_idx
        p = SHOT_DIR / f"{shot_idx:02d}_{label}.png"
        await page.screenshot(path=str(p), full_page=True)
        logger.info(f"📸 截图 → {p.name}  |  URL={page.url}")
        shot_idx += 1

    async with create_page(engine="camoufox", proxy=PROXY, headless=False, slow_mo=120) as page:
        # Step 1: 导航到登录页
        logger.info("导航到 auth.openai.com/log-in ...")
        await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(3)
        await snap("01_login_page")

        # Step 2: 填写邮箱
        logger.info("填写邮箱 ...")
        email_result = await wait_any_element(
            page,
            ["input[type='email']", "input[name='email']", "input[name='username']", "#username"],
            timeout_ms=10_000,
        )
        if not email_result:
            logger.error("未找到邮箱输入框")
            await snap("error_no_email_input")
            return

        e_sel, _ = email_result
        await set_react_input(page, e_sel, email)
        await asyncio.sleep(1)
        await snap("02_email_filled")

        await click_submit_or_text(page, ["Continue", "继续", "Next"])
        await asyncio.sleep(3)
        await snap("03_after_email_submit")

        # Step 3: 填写密码
        logger.info("等待密码输入框 ...")
        pw_result = await wait_any_element(
            page,
            ["input[type='password']", "input[name='password']"],
            timeout_ms=15_000,
        )
        if not pw_result:
            logger.error("未找到密码输入框，截图看看当前页面")
            await snap("error_no_password_input")
            return

        p_sel, _ = pw_result
        await set_react_input(page, p_sel, password)
        await asyncio.sleep(1)
        await snap("04_password_filled")

        await click_submit_or_text(page, ["Continue", "Login", "Sign in", "继续"])
        logger.info("已提交密码，等待下一步页面 ...")

        # Step 4: 观察密码提交后出现的页面（连续截图 10 次，每次 2 秒间隔）
        for i in range(10):
            await asyncio.sleep(2)
            await snap(f"05_after_pw_{i:02d}")
            url = page.url
            logger.info(f"  当前 URL: {url}")

            # 检测 OTP / 验证码输入框
            otp_count = await page.locator(
                "input[type='text'][maxlength='1'], input[maxlength='1']"
            ).count()
            otp_single = await page.locator(
                "input[autocomplete='one-time-code'], input[name='code'], input[id*='code']"
            ).count()
            logger.info(f"  OTP 框数量: maxlength=1 → {otp_count}, single-field → {otp_single}")

            if otp_count >= 4 or otp_single > 0:
                logger.success("✅ 发现 OTP / 验证码输入框！密码后确实有邮箱验证码步骤")
                break

            if "chatgpt.com" in url or "about-you" in url or "localhost" in url:
                logger.info("已跳过 OTP 或完成登录")
                break

        logger.info("测试完成，浏览器保持 30 秒供手动查看 ...")
        await asyncio.sleep(30)


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        _email, _password = sys.argv[1], sys.argv[2]
    else:
        _email, _password = get_test_account()
        if not _email:
            logger.error("数据库中无成功注册账号，请传入 email password 参数")
            sys.exit(1)
        logger.info(f"从数据库取账号: {_email}")

    asyncio.run(run(_email, _password))

