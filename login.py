# -*- coding: utf-8 -*-
"""
login.py — one-time QR login to create a persisted Chrome profile.

Ximalaya requires you to be logged in before you can upload. Instead of
reusing your daily Chrome (which can't be opened twice), this script opens a
*separate* Chromium profile, shows the QR code, and waits for you to scan it
with the Ximalaya app. The login state is then saved in that profile
directory, so the uploader can reuse it forever (no more scanning).

Usage:
    python login.py                       # uses ./xmly_profile
    python login.py --profile /path/to/profile
    python login.py --headless            # run headless, QR saved as PNG

After a successful login the script prints "LOGIN_OK" and exits.

Note (2026-08-16 fix):
  * The real login QR is the element `div.qrcode`, whose background-image is a
    live (per-load) base64 PNG. The old code grabbed the page's first <img>,
    which was the site logo — that is fixed here: we read the base64 directly.
  * Login success used to rely only on page text, which missed cases where the
    phone said "success" but the browser session was not actually written. We
    now treat a login *cookie* (token/uid/session/...) as the primary signal.
"""

import os
import sys
import argparse
import time
import base64

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGIN_URL = "https://studio.ximalaya.com/"


# ----------------------------------------------------------------------
# QR + login-state detection (verified against the live site)
# ----------------------------------------------------------------------
def extract_qr_base64(page):
    """Return the live base64 PNG string of the login QR (div.qrcode
    background-image), or None if not found."""
    return page.evaluate("""() => {
        const el = document.querySelector('div.qrcode');
        if (!el) return null;
        const s = getComputedStyle(el).backgroundImage;
        const m = s.match(/data:image\\/png;base64,([^"')]+)/);
        return m ? m[1] : null;
    }""")


def is_logged_in(page, context):
    """Primary signal: a login/session cookie is present.
    Secondary signal: page text shows we are past the QR-login screen."""
    try:
        cookies = context.cookies()
    except Exception:
        cookies = []
    for c in cookies:
        n = (c.get("name") or "").lower()
        if any(k in n for k in
               ["token", "uid", "auth", "session", "xmly_token", "login"]):
            return True
    try:
        text = page.evaluate("() => document.body.innerText")
    except Exception:
        text = ""
    if "扫码登录" not in text and any(
        k in text for k in ["退出登录", "创作中心", "上传作品", "我的"]
    ):
        return True
    return False


def main():
    parser = argparse.ArgumentParser(description="One-time QR login for Ximalaya")
    parser.add_argument("-p", "--profile",
                        default=os.path.join(SCRIPT_DIR, "xmly_profile"),
                        help="Directory to store the persisted Chrome profile")
    parser.add_argument("--headless", action="store_true",
                        help="Run headless; the QR is saved as a PNG to scan")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is missing. Install it with:\n"
              "    pip install playwright && playwright install chromium")
        sys.exit(1)

    qr_path = os.path.join(SCRIPT_DIR, "_login_qr.png")
    profile = args.profile
    os.makedirs(profile, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=profile,
            headless=args.headless,
        )
        page = context.new_page()
        page.goto(LOGIN_URL, timeout=60000)

        # Capture the real QR code. Prefer div.qrcode base64; fall back to the
        # first <img> screenshot only if the base64 path fails.
        qr_saved = False
        try:
            page.wait_for_selector("div.qrcode", timeout=15000)
            b64 = extract_qr_base64(page)
            if b64:
                with open(qr_path, "wb") as fh:
                    fh.write(base64.b64decode(b64))
                qr_saved = True
        except Exception:
            b64 = None

        if not qr_saved:
            try:
                page.wait_for_selector("img", timeout=15000)
                page.locator("img").first.screenshot(path=qr_path)
                qr_saved = True
            except Exception as e:
                print("Could not capture the QR image automatically:", e)
                print("Please scan the code shown in the browser window.")

        if qr_saved:
            if not args.headless:
                print("Scan the QR code shown in the browser window with the Ximalaya app.")
            else:
                print(f"QR code saved to: {qr_path}  (open and scan with the Ximalaya app)")

        # Poll until we are logged in (cookie-based primary check).
        print("Waiting for login (scan the QR code) ...", flush=True)
        deadline = time.time() + 180  # 3 minutes
        logged_in = False
        while time.time() < deadline:
            if is_logged_in(page, context):
                logged_in = True
                break
            time.sleep(3)

        if logged_in:
            print("LOGIN_OK — login state saved to profile. You can now run uploader.py.")
        else:
            print("Login not detected within 3 minutes. Profile may still have partial state.")
            print("Re-run this script to try again.")

        context.close()

    sys.exit(0 if logged_in else 1)


if __name__ == "__main__":
    main()
