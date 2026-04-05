"""
browser/oauth.py — Post-registration OAuth PKCE token acquisition.

After registration completes, the browser holds valid auth.openai.com cookies.
This module uses those cookies to complete a Codex OAuth2 PKCE flow without
re-entering credentials.

Flow:
  1. Generate PKCE code_verifier + code_challenge
  2. Register a Playwright route interceptor for http://localhost:1455/**
  3. Navigate the browser to /oauth/authorize — auth0 auto-authenticates via
     the existing registration-session cookies
  4. Handle the consent / workspace-select page if it appears (click Allow)
  5. Extract the authorization code from the intercepted callback URL
  6. POST /oauth/token to exchange code → access / refresh / id tokens
  7. Return a TokenResult dataclass
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import urlencode, urlparse, parse_qs

import httpx
from loguru import logger
from playwright.async_api import Page

from src.browser.helpers import (
    human_move_and_click,
    wait_any_element,
    set_react_input,
    click_submit_or_text,
)
from src.mail.base import MailClient

# ── OAuth constants (mirrors plan/chatgpt_register_sentinel.py defaults) ────
OAUTH_ISSUER       = "https://auth.openai.com"
OAUTH_CLIENT_ID    = "app_EMoamEEZ73f0CkXaXp7hrann"
OAUTH_REDIRECT_URI = "http://localhost:1455/auth/callback"
OAUTH_SCOPE        = "openid profile email offline_access"

# Selectors covering ALL pages in the OAuth redirect chain:
#   consent (Allow/Authorize), about-you (Continue), workspace/org (Continue),
#   terms agreement (Accept/Agree), etc.
# Priority: explicit Allow/Authorize first; generic Continue/Submit last.
_FLOW_SELECTORS: list[str] = [
    "button:has-text('Allow')",
    "button:has-text('Authorize')",
    "button[data-testid='allow-button']",
    "button[data-testid='consent-allow']",
    "button[data-action='allow']",
    "input[type='submit'][value*='Allow' i]",
    "input[type='submit'][value*='Authorize' i]",
    # Intermediate OAuth pages (about-you, workspace, org, age-verification, terms)
    "button:has-text('Continue')",
    "button:has-text('Accept')",
    "button:has-text('Agree')",
    "button:has-text('Next')",
    "button[type='submit']:not([disabled])",
]

# Keep the old name for backwards compatibility (used in unit tests / imports)
_CONSENT_SELECTORS = _FLOW_SELECTORS


# ── Token result model ───────────────────────────────────────────────────────

@dataclass
class TokenResult:
    access_token:  str
    refresh_token: str
    id_token:      str
    expires_in:    int
    email:         str = ""
    account_id:    str = ""
    expires_at:    str = ""

    @classmethod
    def from_response(cls, data: dict, email: str = "") -> "TokenResult":
        at      = data.get("access_token", "")
        payload = _decode_jwt(at)
        auth    = payload.get("https://api.openai.com/auth", {})
        acc_id  = auth.get("chatgpt_account_id", "")
        exp     = payload.get("exp", 0)
        expires_at = ""
        if exp:
            dt = datetime.fromtimestamp(exp, tz=timezone(timedelta(hours=8)))
            expires_at = dt.strftime("%Y-%m-%dT%H:%M:%S+08:00")
        return cls(
            access_token  = at,
            refresh_token = data.get("refresh_token", ""),
            id_token      = data.get("id_token", ""),
            expires_in    = data.get("expires_in", 0),
            email         = email,
            account_id    = acc_id,
            expires_at    = expires_at,
        )

    def to_dict(self) -> dict:
        now = datetime.now(tz=timezone(timedelta(hours=8)))
        return {
            "type":          "codex",
            "email":         self.email,
            "account_id":    self.account_id,
            "access_token":  self.access_token,
            "refresh_token": self.refresh_token,
            "id_token":      self.id_token,
            "expired":       self.expires_at,
            "last_refresh":  now.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        }


# ── PKCE helpers ─────────────────────────────────────────────────────────────

def _generate_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) as per RFC 7636."""
    verifier  = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def _decode_jwt(token: str) -> dict:
    """Decode the payload section of a JWT (no signature verification)."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return {}


def _extract_code(url: str) -> Optional[str]:
    """Extract the 'code' query parameter from a URL, or None."""
    if not url or "code=" not in url:
        return None
    try:
        return parse_qs(urlparse(url).query).get("code", [None])[0]
    except Exception:
        return None


# ── Main entry point ─────────────────────────────────────────────────────────

async def acquire_tokens_via_browser(
    page: Page,
    email: str,
    password: str = "",
    first_name: str = "",
    last_name: str = "",
    birthday: Optional[dict] = None,
    proxy: Optional[str] = None,
    timeout: float = 45.0,
    timeouts: Optional[dict] = None,
    mail_client: Optional[MailClient] = None,
    mobile: bool = False,
    log_fn=None,
) -> Optional[TokenResult]:
    """
    Use the browser's existing authenticated session to perform a Codex PKCE
    OAuth2 authorization and acquire access / refresh / id tokens.

    The browser must already hold valid ``auth.openai.com`` cookies (i.e. the
    registration flow has just completed on the same page context).

    Args:
        page:         Playwright page with an active OpenAI auth session.
        email:        The registered e-mail (used to label the token result).
        password:     Account password — used if Auth0 shows the login page.
        first_name:   First name — used to fill about-you form if encountered.
        last_name:    Last name — used to fill about-you form if encountered.
        birthday:     Dict {year, month, day} — used to fill about-you form.
        proxy:        Optional HTTP proxy URL for the token-exchange request.
        timeout:      Hard deadline (seconds) for the entire OAuth flow.
                      Overridden by ``timeouts["oauth_total"]`` when provided.
        timeouts:     Per-stage timeout dict (from cfg["timeouts"]).  All values
                      are in seconds.  Keys used here:
                        oauth_total, oauth_navigate, oauth_login_email,
                        oauth_login_password, oauth_flow_element,
                        oauth_token_exchange, otp_code.
        mail_client:  Optional mail client used to poll for the email OTP when
                      Auth0 demands email verification after password login.
        log_fn:       Optional callable(msg: str) — brief status messages are
                      forwarded to the WebUI job log panel.
        mobile:       When True, a fresh Chromium context with a mobile
                      fingerprint (random iOS/Android UA, touch viewport, mobile
                      stealth JS) is created for the OAuth flow.  Cookies from
                      the existing ``page`` context are copied across so the
                      Auth0 session is preserved.  When False (default) the
                      existing ``page`` is reused as-is.

    Returns:
        ``TokenResult`` on success, ``None`` on any failure (always non-fatal).
    """
    _to    = timeouts or {}
    _total = _to.get("oauth_total", timeout)
    verifier, challenge = _generate_pkce()
    state = secrets.token_urlsafe(24)

    authorize_url = (
        f"{OAUTH_ISSUER}/oauth/authorize?"
        + urlencode({
            "response_type":         "code",
            "client_id":             OAUTH_CLIENT_ID,
            "redirect_uri":          OAUTH_REDIRECT_URI,
            "scope":                 OAUTH_SCOPE,
            "code_challenge":        challenge,
            "code_challenge_method": "S256",
            "state":                 state,
        })
    )

    # Choose between a fresh mobile context or the existing page.
    # contextlib.nullcontext(page) passes ``page`` through unchanged.
    if mobile:
        from src.browser.engine import create_oauth_mobile_page
        _page_ctx = create_oauth_mobile_page(source_page=page, proxy=proxy)
        logger.info(f"[oauth] Mobile fingerprint mode enabled for {email}")
    else:
        _page_ctx = contextlib.nullcontext(page)

    async with _page_ctx as oauth_page:
        # ── Register localhost callback interceptor ──────────────────────
        captured: list[str] = []

        async def _intercept(route):
            url  = route.request.url
            code = _extract_code(url)
            if code:
                captured.append(code)
                logger.debug(f"[oauth] Callback intercepted — code len={len(code)}")
            try:
                await route.abort()   # localhost doesn't actually exist — just abort
            except Exception:
                pass

        await oauth_page.route("http://localhost:1455/**", _intercept)

        async def _run_flow() -> Optional[TokenResult]:
            # ── URL-based code extractor (route-handler bypass guard) ────────
            # page.route() intercepts fetch/navigation requests, but JS redirects
            # (window.location.replace) may bypass it.  Calling this at every
            # checkpoint ensures we never miss a code that's already visible in
            # the page URL.
            def _sync_capture_from_url() -> bool:
                """Extract OAuth code from current page URL → captured.  Sync."""
                try:
                    cur = oauth_page.url
                    if "code=" not in cur:
                        return False
                    if "localhost:1455" not in cur and OAUTH_REDIRECT_URI.split("?")[0] not in cur:
                        return False
                    code = _extract_code(cur)
                    if code and code not in captured:
                        captured.append(code)
                        logger.info(f"[oauth] Code extracted from page URL directly: {cur[:120]}")
                        return True
                except Exception:
                    pass
                return False

            # Detect fingerprint mode from the page's actual User-Agent so the
            # log is accurate regardless of whether `mobile` was set explicitly
            # or inherited from the registration session.
            try:
                _ua_snip = await oauth_page.evaluate("() => navigator.userAgent")
                _fp_label = "mobile" if ("Mobile" in _ua_snip or "Android" in _ua_snip) else "desktop"
            except Exception:
                _fp_label = "mobile" if mobile else "desktop"
            logger.info(
                f"[oauth] Starting PKCE OAuth flow for {email} [{_fp_label}]"
            )
            if log_fn:
                log_fn(f"[OAuth] 开始获取访问令牌…")

            # ── Navigate to OAuth authorize endpoint ─────────────────────
            try:
                await oauth_page.goto(
                    authorize_url, wait_until="commit",
                    timeout=int(_to.get("oauth_navigate", 20) * 1000),
                )
            except Exception as e:
                err = str(e)
                if any(s in err for s in ("ERR_CONNECTION_REFUSED", "ERR_ABORTED",
                                           "net::ERR", "NS_BINDING_ABORTED")):
                    logger.debug("[oauth] Expected localhost navigation error — checking capture")
                else:
                    logger.debug(f"[oauth] goto exception: {e}")

            if captured:
                logger.info("[oauth] Code immediately captured — exchanging for tokens")
                if log_fn:
                    log_fn("[OAuth] 授权码已获取，正在交换令牌…")
                return await _exchange_code(captured[0], verifier, email, proxy, _to)

            # ── Handle Auth0 login page ──────────────────────────────────
            await asyncio.sleep(2.0)
            _sync_capture_from_url()
            current_url = oauth_page.url
            logger.debug(f"[oauth] Post-goto URL: {current_url}")

            if "log-in" in current_url or "/login" in current_url:
                logger.info(
                    f"[oauth] Auth0 login page detected — filling credentials "
                    f"({'mobile UA' if mobile else 'desktop UA'})"
                )
                if log_fn:
                    log_fn("[OAuth] 检测到登录页，正在填写凭据…")

                email_result = await wait_any_element(
                    oauth_page,
                    ["input[type='email']", "input[name='email']", "input[name='username']",
                     "#username", "input[id*='email']"],
                    timeout_ms=int(_to.get("oauth_login_email", 8) * 1000),
                )
                if email_result:
                    e_sel, _ = email_result
                    await set_react_input(oauth_page, e_sel, email)
                    logger.debug("[oauth] Filled email on login page")
                    await asyncio.sleep(1.0)
                    await click_submit_or_text(oauth_page, ["Continue", "Next", "继续", "Submit"])
                    await asyncio.sleep(2.0)

                if password:
                    pw_result = await wait_any_element(
                        oauth_page,
                        ["input[type='password']", "input[name='password']"],
                        timeout_ms=int(_to.get("oauth_login_password", 10) * 1000),
                    )
                    if pw_result:
                        p_sel, _ = pw_result
                        await set_react_input(oauth_page, p_sel, password)
                        logger.debug("[oauth] Filled password on login page")
                        await asyncio.sleep(1.0)
                        await click_submit_or_text(
                            oauth_page, ["Continue", "Login", "Sign in", "Submit", "继续"]
                        )
                        await asyncio.sleep(3.0)

                        # ── Handle email OTP verification (if Auth0 requires it) ──
                        if mail_client:
                            await _handle_oauth_otp(oauth_page, email, mail_client, _to, log_fn=log_fn)
                    else:
                        # Auth0 may have skipped the password step and gone straight
                        # to email OTP verification (passwordless flow).
                        logger.info(
                            "[oauth] Password input not found after email submit — "
                            "Auth0 may have jumped directly to OTP step"
                        )
                        if log_fn:
                            log_fn("[OAuth] 未出现密码框，检测是否直接跳到验证码步骤…")
                        if mail_client:
                            await _handle_oauth_otp(oauth_page, email, mail_client, _to, log_fn=log_fn)
                        else:
                            logger.warning(
                                "[oauth] Password input not found and no mail_client — cannot proceed"
                            )
                else:
                    logger.warning("[oauth] No password provided — cannot log in via OAuth login page")
                    # Even without a password, Auth0 may show a passwordless OTP flow.
                    if mail_client:
                        logger.info("[oauth] No password — attempting passwordless OTP detection")
                        if log_fn:
                            log_fn("[OAuth] 无密码模式，尝试检测验证码步骤…")
                        await _handle_oauth_otp(oauth_page, email, mail_client, _to, log_fn=log_fn)

            # ── Early-capture check: code may have arrived during login/OTP ──
            # Give the event loop a tick so any in-flight route handlers can run.
            await asyncio.sleep(0.5)
            _sync_capture_from_url()
            if captured:
                logger.info("[oauth] Code captured during login/OTP phase — exchanging for tokens")
                if log_fn:
                    log_fn("[OAuth] 授权码已获取（登录阶段），正在交换令牌…")
                return await _exchange_code(captured[0], verifier, email, proxy, _to)

            # ── Handle consent / about-you / workspace pages ─────────────
            for attempt in range(1, 8):
                _sync_capture_from_url()
                if captured:
                    logger.info(f"[oauth] Code captured (len={len(captured[0])}) — exchanging for tokens")
                    if log_fn:
                        log_fn("[OAuth] 授权码已获取，正在交换令牌…")
                    return await _exchange_code(captured[0], verifier, email, proxy, _to)

                logger.info(f"[oauth] Attempting OAuth flow click-through (try {attempt})")

                if "about-you" in oauth_page.url:
                    fn = first_name or "James"
                    ln = last_name or "Smith"
                    bd = birthday or {"year": 1990, "month": 6, "day": 15}
                    logger.info(f"[oauth] About-you page — filling profile ({fn} {ln})")
                    if log_fn:
                        log_fn(f"[OAuth] 填写 about-you 个人资料页…")
                    await _fill_about_you_js(oauth_page, fn, ln, bd)
                    await asyncio.sleep(1.5)

                element = await wait_any_element(
                    oauth_page, _FLOW_SELECTORS,
                    timeout_ms=int(_to.get("oauth_flow_element", 8) * 1000),
                )
                if not element:
                    logger.warning(
                        f"[oauth] No elements found for click-through "
                        f"(try {attempt}) at {oauth_page.url}"
                    )
                    continue

                matched_sel, btn = element
                logger.info(f"[oauth] Clicking flow button (sel={matched_sel!r}) at {oauth_page.url}")
                await human_move_and_click(oauth_page, btn)

                await asyncio.sleep(3.0)
                _sync_capture_from_url()
                if captured:
                    logger.info(f"[oauth] Code captured (len={len(captured[0])}) — exchanging for tokens")
                    if log_fn:
                        log_fn("[OAuth] 授权码已获取，正在交换令牌…")
                    return await _exchange_code(captured[0], verifier, email, proxy, _to)

            # ── Final fallback: code may have been captured during the loop ──
            await asyncio.sleep(0.5)
            _sync_capture_from_url()
            if captured:
                logger.info("[oauth] Late code capture after consent loop — exchanging for tokens")
                if log_fn:
                    log_fn("[OAuth] 授权码已获取（延迟），正在交换令牌…")
                return await _exchange_code(captured[0], verifier, email, proxy, _to)

            logger.warning(f"[oauth] Failed to complete OAuth flow for {email} — code not captured")
            if log_fn:
                log_fn("[OAuth] ⚠️ 授权流程失败，未能获取授权码")
            return None

        try:
            result = await asyncio.wait_for(_run_flow(), timeout=_total)
            return result
        except asyncio.TimeoutError:
            logger.warning(f"[oauth] OAuth flow timed out after {_total}s for {email}")
            if log_fn:
                log_fn(f"[OAuth] ⚠️ 令牌获取超时（>{_total}s）")
            return None
        finally:
            try:
                await oauth_page.unroute("http://localhost:1455/**")
            except Exception:
                pass



# ── OAuth OTP handling ────────────────────────────────────────────────────────

# Keywords that indicate Auth0 rejected the submitted OTP code.
_OAUTH_OTP_ERROR_KEYWORDS = (
    "incorrect code",
    "invalid code",
    "wrong code",
    "code is incorrect",
    "code is invalid",
    "code has expired",
    "code expired",
    "验证码错误",
    "验证码无效",
    "验证码已过期",
    "输入的验证码不正确",
    "code entered is incorrect",
)


async def _oauth_otp_is_incorrect(page: Page) -> bool:
    """Return True if Auth0 is showing an OTP-rejected error message."""
    try:
        text: str = await page.evaluate("""
            () => {
                const picks = [
                    ...document.querySelectorAll('[role="alert"]'),
                    ...document.querySelectorAll('[aria-live]'),
                    ...document.querySelectorAll('[class*="error"],[class*="invalid"],[class*="alert"]'),
                    ...document.querySelectorAll('p, span, small'),
                ];
                return picks
                    .filter(el => {
                        const r = el.getBoundingClientRect();
                        return r.width > 0 && r.height > 0;
                    })
                    .map(el => (el.innerText || "").toLowerCase())
                    .join(" ");
            }
        """)
        return any(kw in text for kw in _OAUTH_OTP_ERROR_KEYWORDS)
    except Exception:
        return False


async def _oauth_otp_inputs_present(page: Page) -> bool:
    """Return True if OTP input controls are still visible on the current page."""
    _OTP_BOX = "input[type='text'][maxlength='1'], input[maxlength='1']"
    try:
        if await page.locator(_OTP_BOX).count() >= 4:
            return True
    except Exception:
        pass
    for sel in ("input[autocomplete='one-time-code']", "input[name='code']", "input[id*='code']"):
        try:
            if await page.locator(sel).first.is_visible():
                return True
        except Exception:
            pass
    return False


async def _oauth_click_resend(page: Page) -> bool:
    """Click the 'Resend' button on the Auth0 OTP page. Returns True on success."""
    for text in ("Resend email", "Resend", "Send again", "重新发送", "Didn't receive"):
        for loc in (
            page.get_by_role("button", name=text, exact=False),
            page.get_by_role("link",   name=text, exact=False),
            page.get_by_text(text, exact=False),
        ):
            try:
                if await loc.first.is_visible(timeout=800):
                    await loc.first.click()
                    logger.info(f"[oauth] Resend button clicked ({text!r})")
                    return True
            except Exception:
                pass
    for sel in ("[data-action-button-secondary]", "button[class*='resend']", "a[class*='resend']"):
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=500):
                await loc.click()
                logger.info(f"[oauth] Resend button clicked (CSS: {sel!r})")
                return True
        except Exception:
            pass
    logger.debug(f"[oauth] Resend button not found (URL={page.url})")
    return False


async def _oauth_poll_fresh_code(
    mail_client: MailClient,
    email: str,
    *,
    previous_code: Optional[str],
    timeout: int,
) -> Optional[str]:
    """Poll mailbox until a code *different* from previous_code arrives."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        remaining = max(1, int(deadline - asyncio.get_event_loop().time()))
        fresh = await mail_client.poll_code(email, timeout=min(15, remaining))
        if fresh and fresh != previous_code:
            return fresh
        if fresh == previous_code:
            logger.debug(f"[oauth] Still seeing old OTP {fresh} — waiting for new one")
        await asyncio.sleep(1.0)
    return None


async def _handle_oauth_otp(
    page: Page,
    email: str,
    mail_client: MailClient,
    timeouts: dict,
    log_fn=None,
) -> None:
    """
    After the OAuth login page password submit, detect whether Auth0 shows an
    email OTP verification step and, if so, poll the mailbox for the code,
    fill it, then click Continue.

    If Auth0 rejects the code ("Incorrect code"), the function automatically
    clicks the Resend button, polls for a *fresh* code (different from the
    previous one), and retries up to ``_OAUTH_OTP_WRONG_MAX`` times.

    OTP input detection mirrors register.py ``_wait_for_otp_inputs``:
      - ≥ 4 individual maxlength=1 boxes  → fill digit-by-digit
      - single autocomplete="one-time-code" / name="code" input → React fill

    The inbox polling timeout is taken from ``timeouts["otp_code"]`` (default
    180 s, same key used by the registration flow).
    """
    # ── Detect OTP inputs (quick non-blocking scan, up to ~5 s) ──────────────
    _OTP_BOX  = "input[type='text'][maxlength='1'], input[maxlength='1']"
    _OTP_SINGLE = [
        "input[autocomplete='one-time-code']",
        "input[name='code']",
        "input[id*='code']",
    ]

    otp_detected = False
    for _ in range(10):          # 10 × 0.5 s = 5 s window
        try:
            count = await page.locator(_OTP_BOX).count()
            if count >= 4:
                otp_detected = True
                break
        except Exception:
            pass
        for sel in _OTP_SINGLE:
            try:
                if await page.locator(sel).first.is_visible():
                    otp_detected = True
                    break
            except Exception:
                pass
        if otp_detected:
            break
        await asyncio.sleep(0.5)

    if not otp_detected:
        logger.debug("[oauth] No OTP input detected after password submit — skipping OTP step")
        return

    logger.info(f"[oauth] Email OTP required — polling inbox for {email}")
    if log_fn:
        log_fn("[OAuth] 检测到邮箱验证码步骤，正在获取验证码…")

    # ── Poll mailbox ──────────────────────────────────────────────────────────
    otp_timeout = int(timeouts.get("otp_code", 180))
    code = await mail_client.poll_code(email, timeout=otp_timeout)

    if not code:
        logger.warning(f"[oauth] OTP code not received within {otp_timeout}s — continuing without fill")
        if log_fn:
            log_fn("[OAuth] ⚠️ 验证码超时未收到，跳过 OTP 填写")
        return

    logger.info(f"[oauth] OTP code received — filling: {code}")
    if log_fn:
        log_fn(f"[OAuth] 验证码已获取，正在填写…")

    # ── Fill + submit loop with Incorrect-Code retry ──────────────────────────
    _OAUTH_OTP_WRONG_MAX = 2

    async def _fill_otp_inputs(otp_code: str) -> None:
        boxes = page.locator(_OTP_BOX)
        box_count = await boxes.count()
        if box_count >= 4:
            for i, ch in enumerate(otp_code[:box_count]):
                box = boxes.nth(i)
                try:
                    await box.click()
                except Exception:
                    pass
                await box.fill(ch)
                await asyncio.sleep(0.1)
        else:
            for sel in _OTP_SINGLE:
                ok = await set_react_input(page, sel, otp_code)
                if ok:
                    break

    for _wrong_attempt in range(_OAUTH_OTP_WRONG_MAX + 1):
        if _wrong_attempt > 0:
            logger.warning(
                f"[oauth] OTP 被判定错误，准备重发并拉取新验证码 "
                f"（第 {_wrong_attempt}/{_OAUTH_OTP_WRONG_MAX} 次）"
            )
            if log_fn:
                log_fn(
                    f"[OAuth] ⚠️ 验证码错误，重新发送并获取新验证码"
                    f"（{_wrong_attempt}/{_OAUTH_OTP_WRONG_MAX}）…"
                )

            resent = await _oauth_click_resend(page)
            if not resent:
                logger.warning("[oauth] 重发按钮未找到，停止 OTP 重试")
                if log_fn:
                    log_fn("[OAuth] ⚠️ 未找到重发按钮，放弃重试")
                break

            await asyncio.sleep(3.0)
            new_code = await _oauth_poll_fresh_code(
                mail_client, email,
                previous_code=code,
                timeout=otp_timeout,
            )
            if not new_code:
                logger.warning("[oauth] 重发后未收到新验证码，放弃重试")
                if log_fn:
                    log_fn("[OAuth] ⚠️ 重发后仍未收到新验证码")
                break

            code = new_code
            logger.info(f"[oauth] 新验证码 → {code}")
            if log_fn:
                log_fn(f"[OAuth] 新验证码已获取，正在填写…")

        # ── Fill OTP inputs ───────────────────────────────────────────────────
        try:
            await _fill_otp_inputs(code)
        except Exception as exc:
            logger.warning(f"[oauth] OTP fill error: {exc}")
            return

        await asyncio.sleep(1.0)
        await click_submit_or_text(page, ["Continue", "Verify", "Submit", "继续"])

        # ── Wait up to 6 s and classify the result ────────────────────────────
        _deadline = asyncio.get_event_loop().time() + 6.0
        _result = "pending"
        while asyncio.get_event_loop().time() < _deadline:
            if await _oauth_otp_is_incorrect(page):
                _result = "incorrect"
                break
            # Accepted if OTP inputs disappeared (page advanced) or URL changed
            if not await _oauth_otp_inputs_present(page):
                _result = "accepted"
                break
            await asyncio.sleep(0.5)

        if _result == "accepted":
            logger.info(f"[oauth] OTP accepted — continuing OAuth flow")
            if log_fn:
                log_fn("[OAuth] 验证码已验证，继续流程…")
            return

        if _result == "incorrect":
            logger.warning(
                f"[oauth] Auth0 rejected OTP (attempt {_wrong_attempt + 1}/{_OAUTH_OTP_WRONG_MAX + 1})"
            )
            continue   # → next iteration: resend + fresh code

        # pending — no decisive signal; treat as accepted and let the flow continue
        logger.info(f"[oauth] OTP submit result pending — continuing OAuth flow")
        if log_fn:
            log_fn("[OAuth] 验证码已提交，继续流程…")
        return

    logger.warning(f"[oauth] OTP verification failed after {_OAUTH_OTP_WRONG_MAX + 1} attempts")
    if log_fn:
        log_fn("[OAuth] ⚠️ OTP 多次错误，放弃重试")


# ── About-you profile fill helper ────────────────────────────────────────────

async def _fill_about_you_js(
    page: Page,
    first_name: str,
    last_name: str,
    birthday: dict,
) -> None:
    """
    Fill the auth.openai.com/about-you profile form using JavaScript.

    The about-you page currently has:
      - input[type='text', name='name']   — combined full name field
      - input[type='number', name='age']  — age in years (appears reactively after name is set)
      - 3 custom ARIA spinbuttons         — year / month / day birthday pickers
        (these are NOT regular <input> elements → not found by querySelectorAll('input'))

    Strategy:
      1. Fill the name input via React native setter
      2. Wait up to 2 s for the age input to appear (it's conditionally rendered)
      3. Fill the age input with the computed integer age
      4. Fill any birthday spinbuttons (native <input type='number'>) via direct JS
    """
    import json as _json
    from datetime import datetime as _dt

    full_name = _json.dumps(f"{first_name} {last_name}")

    # Compute integer age from birthday
    bd = birthday or {"year": 1990, "month": 1, "day": 1}
    today = _dt.now()
    age = today.year - bd["year"]
    if (today.month, today.day) < (bd["month"], bd["day"]):
        age -= 1
    age_str = _json.dumps(str(max(age, 1)))

    date_str = _json.dumps(
        f"{bd['year']}/{str(bd['month']).zfill(2)}/{str(bd['day']).zfill(2)}"
    )

    # ── Step 1: Fill visible non-control inputs (name + optionally age) ──
    result = await page.evaluate(f"""
        () => {{
            const BAD = new Set(['hidden','password','checkbox','radio',
                                  'submit','button','file','image','reset']);
            const inputs = Array.from(document.querySelectorAll('input')).filter(el => {{
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0 && !BAD.has(el.type);
            }});
            const nv = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            );
            const fire = (el, val) => {{
                nv.set.call(el, val);
                el.dispatchEvent(new Event('input',  {{bubbles: true}}));
                el.dispatchEvent(new Event('change', {{bubbles: true}}));
                el.dispatchEvent(new Event('blur',   {{bubbles: true}}));
            }};
            if (inputs.length > 0) fire(inputs[0], {full_name});
            if (inputs.length > 1) {{
                // If second input is a number type it is the age field — fill with integer age.
                // Otherwise fall back to date string for date-type inputs.
                const val = inputs[1].type === 'number' ? {age_str} : {date_str};
                fire(inputs[1], val);
            }}
            return inputs.map(el => ({{type: el.type, name: el.name, id: el.id}}));
        }}
    """)
    logger.debug(f"[oauth] About-you JS fill — inputs found: {result}")

    # ── Step 2: Wait briefly for age input to appear (conditional render) ─
    await asyncio.sleep(1.5)

    # ── Step 3: Re-scan — age input may now be visible after name was set ─
    result2 = await page.evaluate(f"""
        () => {{
            const BAD = new Set(['hidden','password','checkbox','radio',
                                  'submit','button','file','image','reset']);
            const inputs = Array.from(document.querySelectorAll('input')).filter(el => {{
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0 && !BAD.has(el.type);
            }});
            const nv = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            );
            const fire = (el, val) => {{
                nv.set.call(el, val);
                el.dispatchEvent(new Event('input',  {{bubbles: true}}));
                el.dispatchEvent(new Event('change', {{bubbles: true}}));
                el.dispatchEvent(new Event('blur',   {{bubbles: true}}));
            }};
            let filled = [];
            for (const el of inputs) {{
                if (el.name === 'name' || el.type === 'text') {{
                    if (!el.value) fire(el, {full_name});
                    filled.push('name:' + el.value.substring(0, 10));
                }} else if (el.type === 'number') {{
                    fire(el, {age_str});
                    filled.push('age:' + {age_str});
                }} else if (el.type === 'date') {{
                    fire(el, {date_str});
                    filled.push('date:' + {date_str});
                }}
            }}
            return filled;
        }}
    """)
    if result2:
        logger.debug(f"[oauth] About-you re-scan fill result: {result2}")

    # ── Step 4: Fill birthday spinbuttons ─────────────────────────────────
    # Use page.evaluate() for one-shot detection — avoids locator.evaluate() 30 s
    # per-element timeout that caused 4-minute hangs on every OAuth retry.
    try:
        sb_info = await page.evaluate("""
            () => {
                const sbs = Array.from(document.querySelectorAll('[role="spinbutton"]'));
                return sbs.map((el, i) => ({
                    idx:   i,
                    label: (el.getAttribute('aria-label') || '').toLowerCase(),
                    max:   parseInt(el.getAttribute('aria-valuemax') || '0', 10),
                    now:   parseInt(el.getAttribute('aria-valuenow') || el.innerText || '0', 10),
                }));
            }
        """)
        logger.debug(f"[oauth] Spinbutton info (one-shot): {sb_info}")

        if sb_info and len(sb_info) >= 3:
            def _detect_sb(info: dict) -> str:
                label = info.get("label", "")
                mx    = info.get("max", 0)
                if "year"  in label or mx > 200:        return "year"
                if "month" in label or (0 < mx <= 12): return "month"
                if "day"   in label or (12 < mx <= 31): return "day"
                return "unknown"

            field_order = [_detect_sb(sb) for sb in sb_info[:3]]
            if set(field_order) != {"year", "month", "day"}:
                field_order = ["month", "day", "year"]
            logger.debug(f"[oauth] Spinbutton order: {field_order}")

            from src.browser.helpers import fill_spinbutton
            for i, field in enumerate(field_order):
                val = bd.get(field, 1)
                await fill_spinbutton(page, i, val)
                logger.debug(f"[oauth] sb[{i}] {field}={val} done")
        else:
            logger.debug(f"[oauth] Only {len(sb_info) if sb_info else 0} spinbuttons found — skipping date fill")
    except Exception as _e:
        logger.debug(f"[oauth] Spinbutton fill skipped: {_e}")


# ── Token exchange ───────────────────────────────────────────────────────────

async def _exchange_code(
    code: str,
    verifier: str,
    email: str,
    proxy: Optional[str] = None,
    timeouts: Optional[dict] = None,
) -> Optional[TokenResult]:
    """
    POST /oauth/token to exchange an authorization code for tokens.

    Uses httpx (async) with optional proxy support.
    """
    _to = timeouts or {}
    body = urlencode({
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  OAUTH_REDIRECT_URI,
        "client_id":     OAUTH_CLIENT_ID,
        "code_verifier": verifier,
    }).encode()

    # Build the AsyncClient kwargs; httpx >= 0.24 accepts proxy= directly.
    client_kwargs: dict = {"timeout": _to.get("oauth_token_exchange", 30.0)}
    if proxy:
        client_kwargs["proxy"] = proxy

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.post(
                f"{OAUTH_ISSUER}/oauth/token",
                content=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except Exception as exc:
        logger.error(f"[oauth] Token exchange request failed: {exc}")
        return None

    if resp.status_code != 200:
        logger.warning(
            f"[oauth] /oauth/token returned {resp.status_code}: {resp.text[:300]}"
        )
        return None

    try:
        data = resp.json()
    except Exception:
        logger.warning("[oauth] Token response body is not valid JSON")
        return None

    if not data.get("access_token"):
        logger.warning(
            f"[oauth] Token response missing access_token — keys: {list(data.keys())}"
        )
        return None

    result = TokenResult.from_response(data, email=email)
    logger.success(
        f"[oauth] ✅ Tokens acquired — email={email} "
        f"account_id={result.account_id} expires={result.expires_at}"
    )
    return result

