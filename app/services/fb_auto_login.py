"""
Automated Facebook login with TOTP 2FA and 2Captcha support.

Provides `login_on_page(page, account)` which performs a full login
on an *existing* Playwright page — no new browser is launched.
The scraper calls this reactively when it detects an expired session.
"""
import asyncio
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

import pyotp
from playwright.async_api import Page

from ..core.config import settings
from ..core.logging_config import get_logger
from .fb_login_verify import page_has_logged_in_reel_tab_link

logger = get_logger(__name__)

ACCOUNTS_FILE = Path("config/accounts.json")
COOKIE_DIR = Path("cookies")
LOGIN_URL = "https://www.facebook.com/login"
CHECKPOINT_STRINGS = ["checkpoint", "two_step_verification", "loginprotect"]


def load_login_accounts() -> List[Dict]:
    """Load accounts from config/accounts.json for auto-login."""
    if not ACCOUNTS_FILE.exists():
        logger.warning("Accounts file not found: %s", ACCOUNTS_FILE)
        return []
    with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
        accounts = json.load(f)
    return [a for a in accounts if a.get("uid") and a.get("password")]


def _generate_totp(secret: str) -> str:
    cleaned = secret.replace(" ", "").upper()
    return pyotp.TOTP(cleaned).now()


def _get_2captcha_solver():
    try:
        from twocaptcha import TwoCaptcha
    except ImportError:
        logger.warning("2captcha-python not installed — captcha solving unavailable")
        return None
    api_key = settings.CAPTCHA_2CAPTCHA_API_KEY
    if not api_key:
        logger.debug("CAPTCHA_2CAPTCHA_API_KEY not set — captcha solving unavailable")
        return None
    return TwoCaptcha(api_key)


def _sitekey_from_recaptcha_url(url: str) -> Optional[str]:
    """Parse sitekey from a recaptcha anchor/bframe URL (?k=...)."""
    if not url or "recaptcha" not in url.lower():
        return None
    try:
        parsed = urlparse(url)
        k_list = parse_qs(parsed.query).get("k")
        if k_list and k_list[0]:
            return k_list[0].strip()
    except Exception:
        pass
    m = re.search(r"[?&]k=([^&]+)", url)
    if m:
        try:
            return unquote(m.group(1)).strip()
        except Exception:
            return m.group(1).strip()
    return None


async def _extract_recaptcha_sitekey_from_page(page: Page) -> Optional[str]:
    """
    Read site key from any frame: anchor iframe URLs (?k=...), nested iframes, or data-sitekey.

    Facebook embeds reCAPTCHA inside nested iframes — main-frame-only querySelector / page.locator
    often sees nothing, so we must walk page.frames and evaluate inside each frame.
    """
    # 1) Any frame whose own URL is the Google recaptcha anchor/bframe (checkbox / challenge)
    for frame in list(page.frames):
        sk = _sitekey_from_recaptcha_url(frame.url or "")
        if sk:
            logger.debug("reCAPTCHA sitekey from frame URL: %s…", sk[:18])
            return sk

    # 2) Inside each frame, look for child iframes / data-sitekey (nested widget)
    nested_js = r"""
    () => {
        const nodes = document.querySelectorAll(
            'iframe[src*="google.com/recaptcha"], iframe[src*="recaptcha/enterprise"], iframe[src*="recaptcha/api"]'
        );
        for (const f of nodes) {
            const raw = f.getAttribute('src') || '';
            const m = raw.match(/[?&]k=([^&]+)/);
            if (m) return decodeURIComponent(m[1]);
            try {
                const u = new URL(raw, location.href);
                const k = u.searchParams.get('k');
                if (k) return k;
            } catch (e) {}
        }
        const w = document.querySelector('[data-sitekey]');
        if (w) return w.getAttribute('data-sitekey');
        return null;
    }
    """
    for frame in list(page.frames):
        try:
            sk = await frame.evaluate(nested_js)
            if isinstance(sk, str) and sk.strip():
                logger.debug(
                    "reCAPTCHA sitekey from nested DOM in frame %r",
                    (frame.url or "")[:80],
                )
                return sk.strip()
        except Exception as exc:
            logger.debug("sitekey scan frame skip: %s", exc)

    # 3) Last resort: main document only (legacy)
    try:
        sk = await page.evaluate(nested_js)
        if isinstance(sk, str) and sk.strip():
            return sk.strip()
    except Exception as exc:
        logger.debug("extract_recaptcha_sitekey main: %s", exc)
    return None


async def _page_has_recaptcha_widget(page: Page) -> bool:
    """True if reCAPTCHA appears anywhere (including nested iframes)."""
    if await _extract_recaptcha_sitekey_from_page(page):
        return True
    for frame in list(page.frames):
        u = (frame.url or "").lower()
        if "google.com/recaptcha" in u or "recaptcha/enterprise" in u:
            return True
    try:
        n = await page.locator(
            'iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[title*="reCAPTCHA"]'
        ).count()
        return n > 0
    except Exception:
        return False


def _token_from_2captcha_result(result: Any) -> Optional[str]:
    if result is None:
        return None
    if isinstance(result, dict):
        return (
            result.get("code")
            or result.get("gRecaptchaResponse")
            or result.get("token")
        )
    if isinstance(result, str) and len(result.strip()) > 20:
        return result.strip()
    code = getattr(result, "code", None)
    if code:
        return str(code)
    return None


_INJECT_GRECAPTCHA_JS = """
(token) => {
    const apply = (el) => {
        if (!el) return;
        el.value = token;
        if ('innerHTML' in el) el.innerHTML = token;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
    };
    document.querySelectorAll('textarea[name="g-recaptcha-response"]').forEach(apply);
    apply(document.getElementById('g-recaptcha-response'));

    // Notify widget if Google left a callback in cfg (structure varies by version)
    try {
        const tryFire = (obj, depth) => {
            if (!obj || depth > 8) return false;
            if (typeof obj === 'function') return false;
            if (typeof obj.callback === 'function') {
                try { obj.callback(token); return true; } catch (e) {}
            }
            if (typeof obj === 'object') {
                for (const k of Object.keys(obj)) {
                    if (tryFire(obj[k], depth + 1)) return true;
                }
            }
            return false;
        };
        if (typeof ___grecaptcha_cfg !== 'undefined' && ___grecaptcha_cfg.clients) {
            tryFire(___grecaptcha_cfg.clients, 0);
        }
    } catch (e) {}
    return document.querySelectorAll('textarea[name="g-recaptcha-response"]').length;
}
"""


async def _inject_grecaptcha_response(page: Page, token: str) -> None:
    """Put 2Captcha token in every frame (widget + parent form often differ)."""
    injected = 0
    for frame in list(page.frames):
        try:
            n = await frame.evaluate(_INJECT_GRECAPTCHA_JS, token)
            if isinstance(n, int):
                injected += n
        except Exception as exc:
            logger.debug("g-recaptcha inject skip frame: %s", exc)
    if injected == 0:
        logger.warning(
            "No textarea[name=g-recaptcha-response] found in any frame after token inject "
            "(Facebook may still accept callback-only flow)"
        )


def _find_bframe(page: Page):
    """Find the reCAPTCHA challenge iframe (bframe) among all frames."""
    for frame in list(page.frames):
        fu = (frame.url or "").lower()
        if "recaptcha" in fu and "bframe" in fu:
            return frame
    for frame in list(page.frames):
        try:
            fu = (frame.url or "").lower()
            if "recaptcha" in fu and "anchor" not in fu:
                return frame
        except Exception:
            continue
    return None


async def _find_challenge_frame(page: Page):
    """Find the frame containing #rc-imageselect (the visual grid challenge)."""
    bframe = _find_bframe(page)
    if bframe:
        try:
            if await bframe.locator("#rc-imageselect").count() > 0:
                return bframe
        except Exception:
            pass
    for frame in list(page.frames):
        try:
            if await frame.locator("#rc-imageselect").count() > 0:
                return frame
        except Exception:
            continue
    return None


async def _extract_grid_info(challenge_frame):
    """Extract instruction text and grid dimensions from the challenge frame."""
    instruction = ""
    for sel in (
        ".rc-imageselect-desc-no-canonical",
        ".rc-imageselect-desc",
        ".rc-imageselect-instructions",
    ):
        try:
            loc = challenge_frame.locator(sel).first
            if await loc.count() > 0:
                instruction = (await loc.inner_text()).strip()
                if instruction:
                    break
        except Exception:
            continue
    if not instruction:
        instruction = "Select all matching images"

    rows, cols = 4, 4
    try:
        table = challenge_frame.locator(
            'table[class*="rc-imageselect-table"]'
        ).first
        if await table.count() > 0:
            table_class = await table.get_attribute("class") or ""
            if "table-33" in table_class:
                rows, cols = 3, 3
            elif "table-44" in table_class:
                rows, cols = 4, 4
    except Exception:
        pass

    return instruction, rows, cols


async def _solve_recaptcha_visual_grid(page: Page, max_rounds: int = 12) -> bool:
    """
    Solve reCAPTCHA v2 Enterprise IMAGE CHALLENGE via 2Captcha Grid API.

    Instead of sending a sitekey and getting a token (which Facebook rejects
    because the challenge is session-bound), this:
    1. Screenshots the actual puzzle grid from the browser
    2. Sends it to 2Captcha workers who identify which tiles to click
    3. Clicks those tiles in the challenge iframe
    4. Clicks Verify / Skip
    5. Repeats if new images appear (up to max_rounds)
    """
    solver = _get_2captcha_solver()
    if not solver:
        logger.error("[Grid] No 2Captcha solver — set CAPTCHA_2CAPTCHA_API_KEY")
        return False

    for round_idx in range(max_rounds):
        challenge_frame = await _find_challenge_frame(page)
        if not challenge_frame:
            if round_idx > 0:
                logger.info(
                    "[Grid] Challenge frame gone after round %d — puzzle likely solved",
                    round_idx,
                )
                return True
            logger.warning("[Grid] Could not find reCAPTCHA challenge frame (#rc-imageselect)")
            return False

        instruction, rows, cols = await _extract_grid_info(challenge_frame)
        logger.info(
            "[Grid] Round %d/%d — instruction: %r, grid: %dx%d",
            round_idx + 1,
            max_rounds,
            instruction[:80],
            rows,
            cols,
        )

        # Screenshot the image grid
        tmp_path = None
        try:
            target = challenge_frame.locator("#rc-imageselect-target").first
            if await target.count() == 0:
                target = challenge_frame.locator(".rc-imageselect-challenge").first
            if await target.count() == 0:
                logger.error("[Grid] Cannot find image grid element to screenshot")
                return False
            screenshot_bytes = await target.screenshot()
        except Exception as exc:
            logger.error("[Grid] Failed to screenshot challenge grid: %s", exc)
            return False

        try:
            fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="fb_grid_")
            try:
                os.write(fd, screenshot_bytes)
            finally:
                os.close(fd)

            logger.info("[Grid] Sending %dx%d grid image to 2Captcha workers...", rows, cols)

            path_str = str(tmp_path)

            def _run():
                return solver.grid(
                    path_str,
                    rows=rows,
                    cols=cols,
                    hintText=instruction,
                    canSkip=1,
                    lang="en",
                )

            result = await asyncio.get_event_loop().run_in_executor(None, _run)
            logger.info("[Grid] 2Captcha raw result: %r", result)

            code = (
                result.get("code", "") if isinstance(result, dict) else str(result)
            )

            if not code:
                logger.error("[Grid] Empty response from 2Captcha")
                return False

            if "No_matching_images" in code:
                logger.info("[Grid] No matching images — clicking Skip")
                try:
                    skip_btn = challenge_frame.locator(
                        "#recaptcha-verify-button"
                    ).first
                    await skip_btn.click(timeout=5000)
                except Exception as exc:
                    logger.warning("[Grid] Failed to click Skip: %s", exc)
                await asyncio.sleep(4)
                continue

            if not code.startswith("click:"):
                logger.error("[Grid] Unexpected response format: %s", code)
                return False

            tile_nums = []
            for p in code.replace("click:", "").split("/"):
                p = p.strip()
                if p.isdigit():
                    tile_nums.append(int(p))
            if not tile_nums:
                logger.error("[Grid] No tile numbers parsed from: %s", code)
                return False

            logger.info("[Grid] Clicking tiles: %s (1-indexed)", tile_nums)

            for tile_num in tile_nums:
                tile_idx = tile_num - 1
                try:
                    tile = challenge_frame.locator(
                        f'td.rc-imageselect-tile[id="{tile_idx}"]'
                    ).first
                    if await tile.count() == 0:
                        tile = challenge_frame.locator(f'td[id="{tile_idx}"]').first
                    if await tile.count() > 0:
                        await tile.click(timeout=3000)
                        logger.debug("[Grid] Clicked tile %d (id=%d)", tile_num, tile_idx)
                    else:
                        logger.warning("[Grid] Tile id=%d not found in DOM", tile_idx)
                except Exception as exc:
                    logger.warning("[Grid] Failed to click tile %d: %s", tile_num, exc)
                await asyncio.sleep(0.4)

            await asyncio.sleep(1.5)

            # Click Verify
            try:
                verify_btn = challenge_frame.locator(
                    "#recaptcha-verify-button"
                ).first
                if await verify_btn.count() > 0:
                    btn_text = (await verify_btn.inner_text()).strip()
                    await verify_btn.click(timeout=5000)
                    logger.info("[Grid] Clicked Verify/Skip button (%s)", btn_text)
                else:
                    logger.warning("[Grid] Verify button not found")
            except Exception as exc:
                logger.warning("[Grid] Failed to click Verify: %s", exc)

            await asyncio.sleep(4)

        except Exception as exc:
            logger.error("[Grid] 2Captcha grid solve failed: %s", exc)
            return False
        finally:
            if tmp_path:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass

    # Check if challenge frame is gone (success)
    cf = await _find_challenge_frame(page)
    if cf is None:
        logger.info("[Grid] Challenge frame gone after all rounds — success")
        return True

    logger.warning("[Grid] Challenge frame still present after %d rounds", max_rounds)
    return False


async def _solve_recaptcha_enterprise_2captcha(page: Page) -> bool:
    """
    Solve reCAPTCHA v2 Enterprise — tries visual grid solver first (primary),
    then falls back to token-based approach.
    """
    solver = _get_2captcha_solver()
    if not solver:
        logger.error(
            "[Enterprise] CAPTCHA_2CAPTCHA_API_KEY missing or twocaptcha not installed"
        )
        return False

    # PRIMARY: Visual grid solver (screenshot tiles → 2Captcha workers → click)
    challenge_frame = await _find_challenge_frame(page)
    if challenge_frame:
        logger.info("[Enterprise] Visual challenge detected — using Grid API")
        if await _solve_recaptcha_visual_grid(page, max_rounds=12):
            await asyncio.sleep(3)
            return True
        logger.warning("[Enterprise] Grid solver failed — trying token fallback")

    # FALLBACK: Token-based (usually fails on Facebook Enterprise, but try anyway)
    sitekey = await _extract_recaptcha_sitekey_from_page(page)
    if not sitekey:
        logger.error(
            "[Enterprise] No sitekey found. Frame URLs: %s",
            [f.url[:120] for f in page.frames if "recaptcha" in (f.url or "").lower()],
        )
        return False

    page_url = page.url or ""
    if "facebook.com" not in page_url.lower():
        page_url = "https://www.facebook.com/"

    logger.info(
        "[Enterprise-Token] Trying token approach — sitekey=%s…",
        sitekey[:20],
    )

    def _run() -> Any:
        return solver.recaptcha(sitekey=sitekey, url=page_url, enterprise=1)

    try:
        result = await asyncio.get_event_loop().run_in_executor(None, _run)
    except Exception as exc:
        logger.error("[Enterprise-Token] 2Captcha call failed: %s", exc)
        return False

    token = _token_from_2captcha_result(result)
    if not token or len(token) < 20:
        logger.error("[Enterprise-Token] No usable token (result=%r)", result)
        return False

    logger.info("[Enterprise-Token] Got token (length=%d), injecting...", len(token))
    await _inject_grecaptcha_response(page, token)
    await asyncio.sleep(3)

    submitted = await _click_captcha_submit_button(page)
    if submitted:
        logger.info("[Enterprise-Token] Clicked submit after token injection")

    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    await asyncio.sleep(3)
    return True


async def _click_captcha_submit_button(page: Page) -> bool:
    """Try clicking Continue/Submit/Next after captcha token injection."""
    submit_selectors = [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Continue")',
        'button:has-text("Submit")',
        'button:has-text("Next")',
        '[role="button"]:has-text("Continue")',
        'div[role="button"]:has-text("Continue")',
    ]
    for sel in submit_selectors:
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0:
                await btn.wait_for(state="visible", timeout=3000)
                await btn.click(timeout=8000)
                return True
        except Exception:
            continue
    return False


async def _is_captcha_or_challenge_page(page: Page) -> bool:
    """True while Facebook is showing a captcha / robot check (before or after OTP).

    Checks URL patterns, main-frame DOM, AND nested iframes (reCAPTCHA is nested).
    """
    url = (page.url or "").lower()
    if any(
        x in url
        for x in (
            "captcha",
            "/checkpoint/block/?",
            "challenge",
            "login/device-based/",
        )
    ):
        return True

    # Check all frames for reCAPTCHA (widget is nested inside iframes)
    for frame in list(page.frames):
        fu = (frame.url or "").lower()
        if "google.com/recaptcha" in fu or "recaptcha/enterprise" in fu:
            return True

    try:
        return await page.evaluate(
            """
            () => {
                if (document.querySelector('iframe[src*="recaptcha"]')) return true;
                if (document.querySelector('iframe[src*="hcaptcha"]')) return true;
                if (document.querySelector('iframe[title*="reCAPTCHA"]')) return true;
                if (document.querySelector('img[src*="captcha"]')) return true;
                return false;
            }
            """
        )
    except Exception:
        return False


async def _context_has_c_user(page: Page) -> bool:
    try:
        cookies = await page.context.cookies()
        return any(c.get("name") == "c_user" for c in cookies)
    except Exception:
        return False


async def _try_click_recaptcha_label_once(page: Page) -> bool:
    """Single pass: find label in any frame and click. Returns True if clicked."""
    selectors = (
        "label#recaptcha-anchor-label",
        "label.rc-anchor-center-item.rc-anchor-checkbox-label",
        "label.rc-anchor-checkbox-label",
    )
    for frame in list(page.frames):
        for sel in selectors:
            try:
                loc = frame.locator(sel)
                if await loc.count() == 0:
                    continue
                first = loc.first
                await first.wait_for(state="visible", timeout=2000)
                await first.click(timeout=10000)
                logger.info(
                    "Clicked reCAPTCHA I am not a robot label (%s, frame=%r)",
                    sel,
                    (frame.url or "")[:100],
                )
                await asyncio.sleep(2.5)
                return True
            except Exception as exc:
                logger.debug("reCAPTCHA label %s in frame: %s", sel, exc)
    return False


async def _click_recaptcha_im_not_a_robot_label(
    page: Page,
    *,
    pre_wait_seconds: float = 10.0,
    poll_seconds: float = 15.0,
) -> None:
    """
    Click only Google's reCAPTCHA v2 checkbox label (inside the recaptcha iframe).

    The widget often injects late; wait *pre_wait_seconds* before searching, then poll
    every 0.5s for up to *poll_seconds* so we catch the iframe right after it mounts.
    """
    if pre_wait_seconds > 0:
        logger.info(
            "Waiting %.0f s for reCAPTCHA to load, then locating the I am not a robot checkbox",
            pre_wait_seconds,
        )
        await asyncio.sleep(pre_wait_seconds)

    attempts = max(1, int(poll_seconds / 0.5))
    for i in range(attempts):
        if await _try_click_recaptcha_label_once(page):
            return
        await asyncio.sleep(0.5)

    logger.debug(
        "reCAPTCHA anchor label not found after %.0f s pre-wait + %.1f s polling",
        pre_wait_seconds,
        poll_seconds,
    )


async def _solve_captcha_if_present(
    page: Page, *, skip_recaptcha_primer: bool = False
) -> bool:
    """
    Detect and solve captcha on the current page.

    1. Classic image captcha (img[src*="captcha"]) → 2Captcha normal() API
    2. reCAPTCHA Enterprise (iframe widget) → 2Captcha recaptcha() Enterprise API
    3. If nothing is detected → return False (page is clean)

    skip_recaptcha_primer: True when caller already clicked the "I'm not a robot"
    checkbox (e.g. pre-auth flow). MUST NOT click the checkbox again — a second
    click toggles it OFF and dismisses the challenge iframe!
    """
    # Step 1: If primer wasn't done yet, click the checkbox now
    if not skip_recaptcha_primer:
        logger.info("[solve_captcha] Clicking reCAPTCHA checkbox (primer)...")
        await _click_recaptcha_im_not_a_robot_label(
            page, pre_wait_seconds=10.0, poll_seconds=15.0
        )
        await asyncio.sleep(5)

    # Step 2: Check for classic image captcha (rare on Facebook login)
    captcha_img = page.locator('img[src*="captcha"]')
    if await captcha_img.count() > 0:
        logger.info("[solve_captcha] Classic image captcha detected — using 2Captcha normal()")
        return await _solve_classic_image_captcha(page, captcha_img)

    # Step 3: Check for reCAPTCHA widget (nested iframes — the puzzle after checkbox)
    has_widget = await _page_has_recaptcha_widget(page)
    logger.info(
        "[solve_captcha] reCAPTCHA widget present across all frames: %s", has_widget
    )
    if has_widget:
        logger.info("[solve_captcha] Calling 2Captcha Enterprise to solve reCAPTCHA puzzle...")
        if await _solve_recaptcha_enterprise_2captcha(page):
            return True
        logger.error(
            "[solve_captcha] reCAPTCHA Enterprise solve FAILED. "
            "Check CAPTCHA_2CAPTCHA_API_KEY, 2Captcha balance/dashboard, "
            "or solve manually in the browser window."
        )
        return False

    logger.info("[solve_captcha] No captcha detected (no image, no reCAPTCHA widget in any frame)")
    return False


async def _solve_classic_image_captcha(page: Page, captcha_img) -> bool:
    """Solve a classic image captcha via 2Captcha normal() file upload."""
    solver = _get_2captcha_solver()
    if not solver:
        logger.error("Cannot solve image captcha — no 2Captcha solver (CAPTCHA_2CAPTCHA_API_KEY)")
        return False

    tmp_path = None
    try:
        screenshot_bytes = await captcha_img.first.screenshot()
        fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="fb_captcha_")
        try:
            os.write(fd, screenshot_bytes)
        finally:
            os.close(fd)

        path_str = str(tmp_path)
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: solver.normal(path_str)
        )

        captcha_code = result.get("code", "") if isinstance(result, dict) else str(result)
        logger.info("2Captcha image solved: %s", captcha_code[:10])

        captcha_input = page.locator(
            'input[name="captcha_response"], input[name="captcha_persist_data"]'
        ).first
        if await captcha_input.count() == 0:
            captcha_input = page.locator('input[type="text"]').first
        await captcha_input.fill(captcha_code)
        await page.locator('button[type="submit"], input[type="submit"]').first.click()
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        logger.info("Image captcha submitted")
        return True
    except Exception as exc:
        logger.error("Image captcha solve failed: %s", exc)
        return False
    finally:
        if tmp_path is not None:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass


async def _post_login_resolve_challenges(
    page: Page, totp_secret: str, uid: str, max_rounds: int = 35
) -> bool:
    """
    Facebook may show captcha before or after password, and before 2FA.
    Never navigate away while a challenge is still visible.
    """
    checkpoint_attempts = 0
    for round_idx in range(max_rounds):
        await asyncio.sleep(2)

        if await _is_captcha_or_challenge_page(page):
            logger.info(
                "Post-login: captcha/challenge detected (round %s/%s)",
                round_idx + 1,
                max_rounds,
            )
            solved = await _solve_captcha_if_present(page)
            if not solved:
                await asyncio.sleep(1.5)
                if await _is_captcha_or_challenge_page(page):
                    logger.error(
                        "Still on captcha/challenge for %s — not continuing (avoid losing the challenge page)",
                        uid,
                    )
                    return False
            await asyncio.sleep(2)
            continue

        if await _is_checkpoint_page(page):
            if not totp_secret:
                logger.error("Checkpoint requires 2FA but no totp_secret for %s", uid)
                return False
            checkpoint_attempts += 1
            if checkpoint_attempts > 5:
                logger.error("Too many checkpoint rounds for %s", uid)
                return False
            logger.info("Checkpoint / 2FA for %s (attempt %s)", uid, checkpoint_attempts)

            page_url = (page.url or "").lower()
            # two_step_verification?flow=pre_authentication shows reCAPTCHA *before* OTP field
            if "two_step_verification" in page_url or "pre_authentication" in page_url:
                # Quick check: if OTP field is already visible, skip captcha entirely
                quick_otp = await _wait_for_2fa_code_input(page, timeout_seconds=5.0)
                if quick_otp:
                    logger.info(
                        "OTP field already visible on pre-auth page — no captcha needed (UID=%s)",
                        uid,
                    )
                else:
                    logger.info(
                        "Two-step pre-auth page — running reCAPTCHA checkbox before OTP (UID=%s)",
                        uid,
                    )
                    # 1) Click checkbox once
                    await _click_recaptcha_im_not_a_robot_label(
                        page, pre_wait_seconds=10.0, poll_seconds=20.0
                    )
                    # 2) Wait for challenge iframe to fully load after checkbox
                    logger.info("Waiting 8s for challenge iframe to appear after checkbox click...")
                    await asyncio.sleep(8)
                    # 3) Solve the puzzle via 2Captcha Enterprise (do NOT click checkbox again!)
                    captcha_solved = await _solve_captcha_if_present(page, skip_recaptcha_primer=True)
                    if captcha_solved:
                        logger.info("reCAPTCHA solved — waiting for page to advance before 2FA...")
                        await asyncio.sleep(5)
                    else:
                        logger.warning(
                            "reCAPTCHA solve returned False for %s — "
                            "2FA field may not appear; trying anyway...",
                            uid,
                        )
                        await asyncio.sleep(3)

            if not await _handle_2fa(page, totp_secret):
                logger.error("2FA handling failed for %s", uid)
                return False
            await asyncio.sleep(2)
            continue

        if await _context_has_c_user(page):
            logger.info("c_user cookie present for %s — challenges resolved", uid)
            return True

        url = (page.url or "").lower()
        if "facebook.com/login" in url and round_idx > 8:
            try:
                snippet = await page.evaluate(
                    "() => (document.body && document.body.innerText || '').slice(0, 400)"
                )
            except Exception:
                snippet = ""
            if snippet and (
                "incorrect password" in snippet.lower()
                or "wrong password" in snippet.lower()
            ):
                logger.error("Login rejected for %s (password error on page)", uid)
                return False

        if round_idx == max_rounds - 1:
            break

    if await _is_captcha_or_challenge_page(page):
        logger.error("Timed out still on captcha/challenge for %s", uid)
        return False
    if await _is_checkpoint_page(page):
        logger.error("Timed out still on checkpoint for %s", uid)
        return False

    return await _context_has_c_user(page)


async def _is_checkpoint_page(page: Page) -> bool:
    url = page.url.lower()
    return any(s in url for s in CHECKPOINT_STRINGS)


async def _wait_for_2fa_code_input(page: Page, timeout_seconds: float = 90.0):
    """
    Wait for Facebook's OTP field after reCAPTCHA / interstitials (loads late on pre-auth).
    Returns a Locator ready to fill, or None.
    """
    selectors = (
        'input[name="approvals_code"]',
        'input#approvals_code',
        'input[id="approvals_code"]',
        'input[type="text"][maxlength="6"]',
        'input[type="tel"][maxlength="6"]',
        'input[inputmode="numeric"][maxlength="6"]',
        'input[placeholder*="code" i]',
        'input[aria-label*="code" i]',
        'input[autocomplete="one-time-code"]',
    )
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        for sel in selectors:
            loc = page.locator(sel).first
            try:
                if await loc.count() == 0:
                    continue
                await loc.wait_for(state="visible", timeout=2500)
                logger.info("Found 2FA input: %s", sel)
                return loc
            except Exception:
                continue
        await asyncio.sleep(0.8)
    return None


async def _handle_2fa(page: Page, totp_secret: str) -> bool:
    logger.info("Waiting for 2FA code field (up to 90s; appears after captcha on pre-auth flow)...")
    code_input = await _wait_for_2fa_code_input(page, timeout_seconds=90.0)
    if code_input is None:
        logger.error("Could not find 2FA input field after waiting")
        return False

    code = _generate_totp(totp_secret)
    logger.info("Generated TOTP code: %s", code)

    await code_input.fill(code)
    await asyncio.sleep(0.5)

    # Try Enter first (form often submits on Enter)
    await code_input.press("Enter")
    logger.info("Pressed Enter after OTP fill")
    try:
        await page.wait_for_load_state("networkidle", timeout=12000)
    except Exception:
        pass

    # If still on checkpoint, click the Continue / Submit button (multiple selectors)
    if await _is_checkpoint_page(page):
        continue_selectors = [
            'button[id="checkpointSubmitButton"]',
            'input[name="submit"][type="submit"]',
            'button[type="submit"]',
            'input[type="submit"]',
            'button:has-text("Continue")',
            'button:has-text("Submit")',
            '[role="button"]:has-text("Continue")',
            'div[role="button"]:has-text("Continue")',
            'a[role="button"]:has-text("Continue")',
        ]
        for sel in continue_selectors:
            try:
                btn = page.locator(sel).first
                await btn.wait_for(state="visible", timeout=3000)
                await btn.click(timeout=8000, force=True)
                logger.info("Clicked 2FA continue button with selector: %s", sel)
                break
            except Exception as e:
                logger.debug("2FA button selector %s failed: %s", sel, e)
                continue
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

    for _ in range(3):
        if not await _is_checkpoint_page(page):
            break
        continue_btn_selectors = [
            'button[id="checkpointSubmitButton"]',
            'button:has-text("Continue")',
            'button[type="submit"], input[type="submit"]',
        ]
        clicked = False
        for sel in continue_btn_selectors:
            try:
                continue_btn = page.locator(sel).first
                if await continue_btn.count() > 0:
                    await continue_btn.click(timeout=5000, force=True)
                    logger.info("Post-2FA confirmation — clicked: %s", sel)
                    clicked = True
                    break
            except Exception:
                continue
        if not clicked:
            break
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

    return True


async def _is_logged_in(page: Page) -> bool:
    """
    Session must have c_user and show the logged-in Reels tab link in the DOM
    (same rule as the scraper — see fb_login_verify).
    """
    try:
        cookies = await page.context.cookies()
        if not any(c.get("name") == "c_user" for c in cookies):
            return False
        if not await page_has_logged_in_reel_tab_link(page):
            logger.error(
                "Login check: c_user present but Reels tab link (/reel/?s=tab) not found in DOM"
            )
            return False
        return True
    except Exception:
        return False


async def login_on_page(page: Page, account: Dict) -> bool:
    """
    Perform a full Facebook login on an *existing* Playwright page.

    1. Navigates to facebook.com/login
    2. Fills email + password
    3. Handles captcha (2Captcha) if present
    4. Handles 2FA checkpoint (TOTP) if present
    5. Verifies c_user cookie
    6. Saves cookies to cookies/{uid}.json

    Returns True on success, False on failure.
    """
    uid = account["uid"]
    password = account["password"]
    totp_secret = account.get("totp_secret", "")

    logger.info("=" * 50)
    logger.info("AUTO-LOGIN: Logging in as %s on existing page", uid)
    logger.info("=" * 50)

    try:
        # Load login page and wait for it to be stable (avoid proceeding before FB redirects)
        await page.goto(LOGIN_URL, wait_until="load", timeout=30000)
        logger.info("Loaded login page, waiting for form to be stable...")

        # Wait for the login form to appear (email input). Do NOT click cookie consent
        # first — it often triggers a full page reload and can prevent login.
        email_input = page.locator('#email, input[name="email"]').first
        await email_input.wait_for(state="visible", timeout=15000)
        await asyncio.sleep(2)  # Let any client-side redirect/refresh finish

        # If the page navigated away (e.g. refresh), wait for login form again
        if "facebook.com/login" not in page.url:
            logger.info("Page navigated to %s, going back to login", page.url)
            await page.goto(LOGIN_URL, wait_until="load", timeout=30000)
            await email_input.wait_for(state="visible", timeout=15000)
            await asyncio.sleep(2)

        pass_input = page.locator('#pass, input[name="pass"]').first
        if await pass_input.count() == 0:
            # Cookie banner might be covering the form — try dismissing once, then re-wait for form
            try:
                accept_btn = page.locator(
                    'button[data-cookiebanner="accept_button"], button[title="Allow all cookies"], [aria-label="Allow all cookies"]'
                ).first
                if await accept_btn.count() > 0:
                    await accept_btn.click(timeout=3000)
                    logger.info("Dismissed cookie banner (form was not visible)")
                    await asyncio.sleep(3)  # Wait for possible reload to finish
                    await email_input.wait_for(state="visible", timeout=10000)
                    pass_input = page.locator('#pass, input[name="pass"]').first
            except Exception:
                pass
        if await pass_input.count() == 0:
            logger.error("Password field not found — cookie banner or layout may be blocking")
            return False

        await email_input.fill(uid)
        await pass_input.fill(password)
        logger.info("Filled email and password for %s", uid)

        login_url_before = page.url
        submitted = False

        # 1) Try Enter on password field (often submits the form)
        await pass_input.press("Enter")
        logger.info("Pressed Enter to submit login for %s", uid)
        try:
            await page.wait_for_url(
                lambda u: "login" not in u.lower() or "checkpoint" in u.lower(),
                timeout=10000,
            )
            submitted = True
        except Exception:
            pass
        if not submitted:
            await asyncio.sleep(2)
            if page.url != login_url_before or "checkpoint" in page.url.lower():
                submitted = True

        # 2) If still on login page, click the login button (multiple selectors, short timeout)
        if not submitted and "facebook.com/login" in page.url:
            login_btn_selectors = [
                'input[name="login"]',
                'button[name="login"]',
                'button[type="submit"]',
                'form[action*="login"] button[type="submit"]',
                'form[action*="login"] input[type="submit"]',
                'button:has-text("Log in")',
                'input[type="submit"]',
            ]
            for sel in login_btn_selectors:
                try:
                    btn = page.locator(sel).first
                    await btn.wait_for(state="visible", timeout=3000)
                    await btn.click(timeout=5000, force=True)
                    logger.info("Clicked login button with selector: %s", sel)
                    submitted = True
                    break
                except Exception as e:
                    logger.debug("Login button selector %s failed: %s", sel, e)
                    continue

        if not submitted:
            logger.warning("Could not submit login form (no navigation after Enter or click)")

        try:
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        await asyncio.sleep(3)

        logger.info("Page URL after login submit: %s", page.url)

        # Save a debug screenshot so we can see what happened
        try:
            debug_path = Path(f"logs/login_debug_{uid}.png")
            debug_path.parent.mkdir(exist_ok=True)
            await page.screenshot(path=str(debug_path))
            logger.info("Debug screenshot saved: %s", debug_path)
        except Exception:
            pass

        # Captcha may appear before or after 2FA — never navigate away while it is showing
        if not await _post_login_resolve_challenges(page, totp_secret, uid):
            try:
                fail_path = Path(f"logs/login_challenge_fail_{uid}.png")
                fail_path.parent.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=str(fail_path))
                logger.info("Saved challenge-fail screenshot: %s", fail_path)
            except Exception:
                pass
            return False

        if await _is_captcha_or_challenge_page(page):
            logger.error(
                "Refusing to leave captcha/challenge page for %s (solve manually in the window if needed)",
                uid,
            )
            return False

        # Load home so left nav (incl. Reels tab) is present for the same check the scraper uses
        try:
            await page.goto(
                "https://www.facebook.com",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            await asyncio.sleep(4)
        except Exception as nav_exc:
            logger.warning("Post-login navigation to facebook.com for verification: %s", nav_exc)

        if not await _is_logged_in(page):
            logger.error(
                "Login failed for %s — missing c_user cookie or Reels tab link (/reel/?s=tab)",
                uid,
            )
            try:
                screenshot_path = Path(f"logs/login_fail_{uid}.png")
                screenshot_path.parent.mkdir(exist_ok=True)
                await page.screenshot(path=str(screenshot_path))
                logger.info("Saved failure screenshot: %s", screenshot_path)
            except Exception:
                pass
            return False

        # Save cookies so future scraper runs can reuse this session
        COOKIE_DIR.mkdir(exist_ok=True)
        storage_state = await page.context.storage_state()
        cookie_path = COOKIE_DIR / f"{uid}.json"
        with open(cookie_path, "w", encoding="utf-8") as f:
            json.dump(storage_state, f, indent=2)

        cookie_count = len(storage_state.get("cookies", []))
        logger.info(
            "Auto-login successful for %s — saved %d cookies to %s",
            uid, cookie_count, cookie_path,
        )
        return True

    except Exception as exc:
        logger.exception("Auto-login error for %s: %s", uid, exc)
        return False
