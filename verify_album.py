#!/usr/bin/env python3
"""Verify which audio files from a folder actually made it onto Ximalaya.

The uploader only knows what the page told it; a publish can *look* successful
while the sound never lands (e.g. the file was not really accepted by the
uploader, or the success page never appeared). This script logs into the same
browser profile, opens the album's sound-management page in the Creator Center,
captures the real `album/tracks` API responses (paged), and lists every sound
title that is actually online.

Pass --folder to also report which local audio+txt pairs are MISSING online
(so you know exactly what to re-publish).

Usage:
    python verify_album.py --album-id 128358894
    python verify_album.py --album-id 128358894 --folder /path/to/staged --profile /path/to/xmly_profile
"""
import os
import sys
import json
import argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser(description="Verify published sounds on Ximalaya.")
    ap.add_argument("--album-id", required=True, help="Numeric album id (from the Creator Center URL).")
    ap.add_argument("--folder", help="Optional local folder of audio+txt pairs to diff against.")
    ap.add_argument("--profile", default=os.path.join(SCRIPT_DIR, "xmly_profile"),
                    help="Playwright persistent profile dir (must be logged in).")
    ap.add_argument("--out", default="published_check.txt", help="Where to write the title list.")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is missing. Install it with:\n    pip install playwright && playwright install chromium")
        sys.exit(1)

    ALBUM = args.album_id
    ref = f"https://www.ximalaya.com/reform-upload/page/sound/manage/{ALBUM}"

    captured = []
    def on_resp(resp):
        if "reform-upload/manage/album/tracks" in resp.url:
            try:
                j = resp.json()
                if isinstance(j, dict) and j.get("ret") == 0:
                    captured.append(j)
            except Exception:
                pass

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(user_data_dir=args.profile, headless=True)
        page = ctx.new_page()
        page.on("response", on_resp)
        page.goto(ref, timeout=60000)
        page.wait_for_timeout(4500)
        # Click through pagination (album/tracks returns 10 per page).
        for pg in ["2", "3", "4", "5", "6", "7", "8", "9", "10"]:
            try:
                loc = page.locator(".ant-pagination-item", has_text=pg)
                if loc.count() == 0:
                    break
                loc.first.click(timeout=5000)
                page.wait_for_timeout(2200)
            except Exception:
                break
        ctx.close()

    all_titles = []
    for j in captured:
        for it in j.get("data", {}).get("infos", []):
            if isinstance(it, dict) and it.get("title"):
                all_titles.append(it["title"])
    seen = set(); final = []
    for t in all_titles:
        if t not in seen:
            seen.add(t); final.append(t)

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(final))
    print(f"Captured {len(captured)} page(s); {len(final)} unique sound(s) online in album {ALBUM}.")
    for i, t in enumerate(final, 1):
        print(f"{i:3d}. {t}")

    if args.folder:
        local = []
        for fn in sorted(os.listdir(args.folder)):
            if fn.lower().endswith((".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".amr")):
                local.append(fn[:-4])
        online_set = set(final)
        missing = [x for x in local if x not in online_set]
        print("\n" + "=" * 60)
        print(f"Local audio files: {len(local)}")
        print(f"Online (this album): {len(online_set)}")
        print(f"MISSING online: {len(missing)}")
        for m in missing:
            print(f"  ✗ {m}")


if __name__ == "__main__":
    main()
