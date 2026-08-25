#!/usr/bin/env python3
"""Batch-set Ximalaya tracks to private (visibleCrowdType=1)."""
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

PROFILE = "/Users/yezi/WorkBuddy/2026-08-11-22-09-49/ximalaya_uploader/xmly_profile"
ALBUMS = {
    129010581: "八上语文-课文",
    129010693: "八下语文-课本",
    129010714: "九下语文-课文",
    129010739: "九上语文-课本",
}
LOG_PATH = Path("/tmp/xmly_set_private.log")

def log(msg):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def fetch_json(page, url, method="GET", payload=None):
    if method == "GET":
        return page.evaluate(
            """(url)=>fetch(url,{credentials:'include',headers:{'Accept':'application/json, text/plain, */*'}}).then(r=>r.json())""",
            url,
        )
    return page.evaluate(
        """(args)=>fetch(args.url,{
            method:'POST', credentials:'include',
            headers:{'Content-Type':'application/json;charset=UTF-8','Accept':'application/json, text/plain, */*'},
            body:JSON.stringify(args.payload)
        }).then(r=>r.json())""",
        {"url": url, "payload": payload},
    )


def get_tracks(page, album_id):
    tracks = []
    page_num = 1
    while True:
        url = (
            f"https://www.ximalaya.com/reform-upload/manage/album/tracks?"
            f"albumId={album_id}&page={page_num}&pageSize=10&order=ASC&state=1"
        )
        resp = fetch_json(page, url)
        if resp.get("ret") != 0:
            log(f"  list album {album_id} page {page_num} failed: {resp.get('ret')} {resp.get('msg')}")
            break
        data = resp.get("data", {})
        items = data.get("tracks") or data.get("infos") or []
        for it in items:
            tracks.append((it.get("trackId") or it.get("id"), it.get("title")))
        total = data.get("totalSize") or data.get("total") or 0
        if page_num * 10 >= total:
            break
        page_num += 1
    return tracks


def build_payload(edit_data):
    d = edit_data
    info = d["trackInfo"]
    return {
        "activityId": d.get("activityId"),
        "albumId": info["albumId"],
        "coverId": 0,
        "isFree": False,
        "isTrailer": False,
        "richIntro": d.get("richIntro", ""),
        "shortRichIntro": "",
        "title": info["title"],
        "trackId": info["trackId"],
        "videoCoverPath": info.get("videoCoverPath") or "",
        "lrcPath": d.get("lrcPath", ""),
        "categoryId": info["categoryId"],
        "visibleCrowdType": 1,
        "isCategoryCanModify": None,
        "categoryModifyRemind": None,
        "categoryCanNotModifyWarn": None,
        "saleVipConfig": None,
        "draftPlayPath": d.get("draftPlayPath", ""),
        "timeDraftList": [],
        "paidAlbumTrackType": None,
        "communityWidget": None,
        "isAiTrack": None,
        "soundTags": "{}",
        "topicTags": "{}",
        "timeTrack": 0,
    }


def set_track_private(page, track_id, title, dry_run=False):
    edit_resp = fetch_json(page, f"https://www.ximalaya.com/reform-upload/anchorTrack/edit?trackId={track_id}")
    if edit_resp.get("ret") != 0:
        return False, f"edit fetch failed: {edit_resp.get('ret')} {edit_resp.get('msg')}"
    current = edit_resp["data"]["trackInfo"]["visibleCrowdType"]
    if current == 1:
        return True, "already private"
    if dry_run:
        return True, f"would set private (currently {current})"
    payload = build_payload(edit_resp["data"])
    update_resp = fetch_json(page, "https://www.ximalaya.com/reform-upload/anchorTrack/update", method="POST", payload=payload)
    if update_resp.get("ret") != 0:
        return False, f"update failed: {update_resp.get('ret')} {update_resp.get('msg')}"
    # verify
    verify = fetch_json(page, f"https://www.ximalaya.com/reform-upload/anchorTrack/edit?trackId={track_id}")
    after = verify["data"]["trackInfo"]["visibleCrowdType"]
    if after == 1:
        return True, "set to private"
    return False, f"verify failed, still {after}"


def main():
    LOG_PATH.write_text("", encoding="utf-8")
    log("Starting batch private update for 4 albums")
    total = 0
    changed = 0
    skipped = 0
    failed = 0
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(user_data_dir=PROFILE, headless=True)
        page = ctx.new_page()
        page.goto("https://www.ximalaya.com/reform-upload/page/webCenter/upload", timeout=60000)
        page.wait_for_timeout(2000)
        for album_id, album_name in ALBUMS.items():
            log(f"Album [{album_id}] {album_name}")
            tracks = get_tracks(page, album_id)
            log(f"  found {len(tracks)} tracks")
            for idx, (track_id, title) in enumerate(tracks, 1):
                ok, reason = set_track_private(page, track_id, title)
                total += 1
                if ok and reason == "set to private":
                    changed += 1
                elif ok and reason == "already private":
                    skipped += 1
                elif not ok:
                    failed += 1
                log(f"  [{idx}/{len(tracks)}] track {track_id}: {reason}")
                # gentle pacing
                time.sleep(1.5 + random.random())
        ctx.close()
    log("=" * 50)
    log(f"Total: {total}, Changed: {changed}, Already private: {skipped}, Failed: {failed}")
    log("Done")


if __name__ == "__main__":
    main()
