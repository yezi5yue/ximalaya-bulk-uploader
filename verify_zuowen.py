# -*- coding: utf-8 -*-
"""Verify the final state of album 121805384 (作文):
   - count our 50 composition titles, flag any duplicates
   - count non-composition (pre-existing) titles
"""
import os, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

PROFILE = "/Users/yezi/WorkBuddy/2026-08-11-22-09-49/ximalaya_uploader/xmly_profile"
FOLDER = "/Volumes/5yue/音频文件/语文/作文"
ALBUM = 121805384

def fetch_json(page, url):
    return page.evaluate(
        "(url)=>fetch(url,{credentials:'include',headers:{'Accept':'application/json, text/plain, */*'}}).then(r=>r.json())",
        url)

def get_tracks(page, album_id):
    tracks = []
    p = 1
    while True:
        url = (f"https://www.ximalaya.com/reform-upload/manage/album/tracks?"
               f"albumId={album_id}&page={p}&pageSize=50&order=ASC&state=1")
        resp = fetch_json(page, url)
        if resp.get("ret") != 0:
            print("list failed", resp.get("ret"), resp.get("msg")); break
        data = resp.get("data", {})
        items = data.get("tracks") or data.get("infos") or []
        for it in items:
            tracks.append(it.get("title"))
        total = data.get("totalSize") or data.get("total") or 0
        if p * 50 >= total: break
        p += 1
    return tracks

def main():
    comp = set()
    for n in os.listdir(FOLDER):
        if n.lower().endswith((".mp3",".wav",".m4a",".flac",".aac",".ogg")):
            comp.add(os.path.splitext(n)[0])
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(user_data_dir=PROFILE, headless=True)
        page = ctx.new_page()
        page.goto("https://www.ximalaya.com/reform-upload/page/webCenter/upload", timeout=60000)
        page.wait_for_timeout(2500)
        titles = get_tracks(page, ALBUM)
        ctx.close()
    print(f"Album {ALBUM} total online sounds: {len(titles)}")
    ours = [t for t in titles if t in comp]
    others = [t for t in titles if t not in comp]
    # duplicates among ours
    from collections import Counter
    cnt = Counter(ours)
    dups = {t: c for t, c in cnt.items() if c > 1}
    print(f"Our composition titles present: {len(ours)} (expected 50)")
    print(f"  duplicates among ours: {dups if dups else 'NONE'}")
    missing = comp - set(titles)
    print(f"  missing (local but not online): {missing if missing else 'NONE'}")
    print(f"Pre-existing (non-composition) titles: {len(others)}")
    for t in others:
        print("   -", t)

if __name__ == "__main__":
    main()
