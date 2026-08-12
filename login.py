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

After a successful login the script prints "LOGIN_OK" and exits.
"""

import os
import sys
import argparse
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGIN_URL = "https://studio.ximalaya.com/"


def main():
    parser = argparse.ArgumentParser(description="One-time QR login for Ximalaya")
    parser.add_argument("-p", "--profile",
                        default=os.path.join(SCRIPT_DIR, "xmly_profile"),
                        help="Directory to store the persisted Chrome profile")
    parser.add_argument("--headless", action="store_true",
                        help="Run headless (the QR code is still saved as a PNG)")
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

        # Try to find the QR code image and save it.
        try:
            page.wait_for_selector("img", timeout=15000)
            qr = page.locator("img").first
            qr.screenshot(path=qr_path)
            print(f"QR code saved to: {qr_path}")
            if not args.headless:
                print("Open it (or just look at the browser window) and scan with the Ximalaya app.")
            else:
                print(f"Open {qr_path} and scan with the Ximalaya app.")
        except Exception as e:
            print("Could not capture the QR image automatically:", e)
            print("Please scan the code shown in the browser window.")

        # Poll until we are logged in (URL leaves the login page / user menu appears).
        print("Waiting for login (scan the QR code) ...", flush=True)
        deadline = time.time() + 180  # 3 minutes
        logged_in = False
        while time.time() < deadline:
            try:
                text = page.evaluate("() => document.body.innerText")
            except Exception:
                text = ""
            if "退出登录" in text or "创作中心" in text or "上传作品" in text:
                logged_in = True
                break
            # Also detect a fresh login by the absence of a login QR prompt.
            if "扫码登录" not in text and ("我的" in text or "消息" in text):
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
