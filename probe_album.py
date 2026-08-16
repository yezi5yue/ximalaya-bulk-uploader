# -*- coding: utf-8 -*-
"""
probe_album.py — check whether a target album exists in the logged-in
Ximalaya account, before running a large batch.

Catches the "album name typo / not created yet" case early, so the uploader
does not fail per-item on 10s timeouts.

Usage:
    python probe_album.py "My Album"
    python probe_album.py "My Album" --profile /path/to/profile

Exits 0 if the album is found, 1 otherwise.
"""

import os
import sys
import argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_URL = "https://www.ximalaya.com/reform-upload/page/webCenter/upload"


def main():
    parser = argparse.ArgumentParser(description="Probe a Ximalaya album")
    parser.add_argument("album", help="Exact album (作品目录) name to look for")
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

    found = False
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=args.profile, headless=True)
        page = context.new_page()
        try:
            page.goto(UPLOAD_URL, timeout=60000)
            page.wait_for_timeout(2500)
            page.locator("button.search-select-album-btn-2fDgDdbT").first.click()
            page.wait_for_timeout(1500)
            items = page.locator("div.scroll-item-content-252FXLKk").all_inner_texts()
            found = any(args.album in t for t in items)
            if not found:
                print(f"Album '{args.album}' was NOT found. "
                      f"Albums listed in the picker:")
                for t in items:
                    print(f"    - {t}")
        except Exception as e:
            print(f"Error while probing album: {e}")
            found = False
        context.close()

    if found:
        print(f"ALBUM_FOUND — '{args.album}' exists, safe to publish.")
        sys.exit(0)
    else:
        print(f"ALBUM_NOT_FOUND — create '{args.album}' in the Creator Center "
              f"first, then re-run.")
        sys.exit(1)


if __name__ == "__main__":
    main()
