# -*- coding: utf-8 -*-
"""
verify_login.py — check whether the persisted profile (xmly_profile) is
already logged in to Ximalaya.

Useful after a long time, or before a big batch, to confirm the session is
still valid without opening the full uploader.

Usage:
    python verify_login.py
    python verify_login.py --profile /path/to/profile

Exits 0 if logged in, 1 otherwise.
"""

import os
import sys
import argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGIN_URL = "https://studio.ximalaya.com/"


def is_logged_in(page, context):
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
    parser = argparse.ArgumentParser(description="Check Ximalaya login state")
    parser.add_argument("-p", "--profile",
                        default=os.path.join(SCRIPT_DIR, "xmly_profile"),
                        help="Persisted Chrome profile directory")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is missing. Install it with:\n"
              "    pip install playwright && playwright install chromium")
        sys.exit(1)

    if not os.path.isdir(args.profile):
        print(f"Profile directory not found: {args.profile}")
        print("Run `python login.py` first to create it.")
        sys.exit(1)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=args.profile, headless=True)
        page = context.new_page()
        try:
            page.goto(LOGIN_URL, timeout=60000)
            page.wait_for_timeout(3000)
            ok = is_logged_in(page, context)
        except Exception as e:
            print(f"Error while checking login state: {e}")
            ok = False
        context.close()

    if ok:
        print("LOGGED_IN — the profile is valid, you can publish.")
        sys.exit(0)
    else:
        print("NOT_LOGGED_IN — run `python login.py` to (re)scan the QR code.")
        sys.exit(1)


if __name__ == "__main__":
    main()
