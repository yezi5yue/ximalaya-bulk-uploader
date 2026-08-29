#!/usr/bin/env python3
"""Delete tracks from an album whose titles match audio basenames in a folder."""
import os
import sys
import time
import argparse
from playwright.sync_api import sync_playwright


def fetch_json(page, url, method="GET", payload=None):
    if method == "GET":
        return page.evaluate(
            "(url)=>fetch(url,{credentials:'include',headers:{'Accept':'application/json, text/plain, */*'}}).then(r=>r.json())",
            url)
    return page.evaluate(
        "(a)=>fetch(a.url,{method:'POST',credentials:'include',"
        "headers:{'Content-Type':'application/json;charset=UTF-8','Accept':'application/json, text/plain, */*'},"
        "body:JSON.stringify(a.payload)}).then(r=>r.json())",
        {"url": url, "payload": payload})


def get_tracks(page, album_id):
    tracks = []
    page_num = 1
    while True:
        url = (f"https://www.ximalaya.com/reform-upload/manage/album/tracks?"
               f"albumId={album_id}&page={page_num}&pageSize=50&order=ASC&state=1")
        resp = fetch_json(page, url)
        if resp.get("ret") != 0:
            print(f"  list p{page_num} failed: {resp.get('ret')} {resp.get('msg')}")
            break
        data = resp.get("data", {})
        items = data.get("tracks") or data.get("infos") or []
        for it in items:
            tracks.append((it.get("trackId") or it.get("id"), it.get("title")))
        total = data.get("totalSize") or data.get("total") or 0
        if page_num * 50 >= total:
            break
        page_num += 1
    return tracks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--album-id", required=True)
    parser.add_argument("--folder", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()

    target_titles = set()
    for name in os.listdir(args.folder):
        if name.lower().endswith((".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg")):
            target_titles.add(os.path.splitext(name)[0])

    print(f"Target titles ({len(target_titles)}):")
    for t in sorted(target_titles):
        print(f"  {t}")

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=args.profile,
            headless=True,
            args=["--disable-features=IsolateOrigins,site-per-process"],
        )
        page = ctx.new_page()
        page.goto("https://www.ximalaya.com/reform-upload/page/webCenter/upload", timeout=60000)
        page.wait_for_timeout(2500)

        tracks = get_tracks(page, args.album_id)
        to_delete = [(tid, title) for tid, title in tracks if title in target_titles]

        print(f"\nAlbum {args.album_id} has {len(tracks)} tracks; {len(to_delete)} match target titles.")
        if not args.commit:
            print("Dry-run: no changes. Use --commit to delete.")
            ctx.close()
            return

        ok_count = 0
        for tid, title in to_delete:
            resp = fetch_json(page, "https://www.ximalaya.com/reform-upload/anchorTrack/delete",
                              method="POST", payload={"trackId": tid})
            if resp.get("ret") == 0:
                print(f"  DEL OK: {title} ({tid})")
                ok_count += 1
            else:
                print(f"  DEL FAIL: {title} ({tid}) ret={resp.get('ret')} msg={resp.get('msg')}")
            time.sleep(0.5)

        print(f"\nDeleted {ok_count}/{len(to_delete)} tracks.")
        ctx.close()


if __name__ == "__main__":
    main()
