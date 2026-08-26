# -*- coding: utf-8 -*-
"""Fix the mis-targeted '作文' upload (2026-08-26).

Situation:
  * 34 compositions were wrongly published into album 128168225 (英语作文)
    instead of 121805384 (作文).
  * A later --no-resume re-upload accidentally created 7 DUPLICATE tracks
    (titles 1..7) inside 121805384.

User directive: do NOT delete the 34 originals — instead *change their album*
(修改所属专辑) to 121805384, and upload the remaining (35..50) normally.

This script (dry-run by default):
  1. DELETE from 121805384 any track whose title is a composition title
     (these are exactly the 7 accidental duplicates).
  2. MOVE from 128168225 -> 121805384 any track whose title is a composition
     title (the 34 originals), by editing albumId via anchorTrack/update.
Use --commit to actually perform the changes.
"""
import os
import sys
import json
import time
import random
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE = "/Users/yezi/WorkBuddy/2026-08-11-22-09-49/ximalaya_uploader/xmly_profile"
FOLDER = "/Volumes/5yue/音频文件/语文/作文"
WRONG_ALBUM = 128168225   # 英语作文 (where the 34 wrongly landed)
RIGHT_ALBUM = 121805384   # 作文 (the intended target)
LOG_PATH = Path("/tmp/xmly_move_cleanup.log")


def log(m):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {m}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


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
            log(f"  list {album_id} p{page_num} failed: {resp.get('ret')} {resp.get('msg')}")
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


def composition_titles(folder):
    titles = set()
    for name in os.listdir(folder):
        if name.lower().endswith((".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg")):
            titles.add(os.path.splitext(name)[0])
    return titles


def build_update_payload(d, override_album_id):
    info = d["trackInfo"]
    return {
        "activityId": d.get("activityId"),
        "albumId": override_album_id,
        "coverId": 0,
        "isFree": info.get("isFree", False),
        "isTrailer": False,
        "richIntro": d.get("richIntro", ""),
        "shortRichIntro": "",
        "title": info["title"],
        "trackId": info["trackId"],
        "videoCoverPath": info.get("videoCoverPath") or "",
        "lrcPath": d.get("lrcPath", ""),
        "categoryId": info["categoryId"],
        "visibleCrowdType": info.get("visibleCrowdType"),  # preserve original
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


def delete_track(page, track_id, commit):
    if not commit:
        return True, "dry-run skip"
    resp = fetch_json(page, "https://www.ximalaya.com/reform-upload/anchorTrack/delete",
                      method="POST", payload={"trackId": track_id})
    ok = resp.get("ret") == 0
    return ok, f"ret={resp.get('ret')} {resp.get('msg')}"


def move_track(page, track_id, to_album, commit):
    if not commit:
        return True, "dry-run skip"
    ed = fetch_json(page, f"https://www.ximalaya.com/reform-upload/anchorTrack/edit?trackId={track_id}")
    if ed.get("ret") != 0:
        return False, f"edit failed {ed.get('ret')}"
    payload = build_update_payload(ed["data"], override_album_id=to_album)
    upd = fetch_json(page, "https://www.ximalaya.com/reform-upload/anchorTrack/update",
                     method="POST", payload=payload)
    if upd.get("ret") != 0:
        return False, f"update failed {upd.get('ret')} {upd.get('msg')}"
    # verify
    ed2 = fetch_json(page, f"https://www.ximalaya.com/reform-upload/anchorTrack/edit?trackId={track_id}")
    new_album = ed2["data"]["trackInfo"]["albumId"]
    if str(new_album) == str(to_album):
        return True, f"moved -> {new_album}"
    return False, f"verify failed, album now {new_album}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="Actually perform deletes/moves")
    ap.add_argument("-p", "--profile", default=PROFILE)
    args = ap.parse_args()
    commit = args.commit

    comp = composition_titles(FOLDER)
    log(f"composition titles from folder: {len(comp)}")
    log(f"mode: {'COMMIT' if commit else 'DRY-RUN'}")

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(user_data_dir=args.profile, headless=True)
        page = ctx.new_page()
        page.goto("https://www.ximalaya.com/reform-upload/page/webCenter/upload", timeout=60000)
        page.wait_for_timeout(2500)

        wrong_tracks = get_tracks(page, WRONG_ALBUM)
        right_tracks = get_tracks(page, RIGHT_ALBUM)
        log(f"128168225 (英语作文) tracks: {len(wrong_tracks)}")
        log(f"121805384 (作文) tracks: {len(right_tracks)}")

        # Step 1: delete accidental duplicates in RIGHT album
        to_delete = [(tid, t) for (tid, t) in right_tracks if t in comp]
        log(f"[Step1] will DELETE {len(to_delete)} duplicate track(s) from 121805384:")
        for tid, t in to_delete:
            log(f"    DEL {tid}  {t}")
        del_ok = del_fail = 0
        for tid, t in to_delete:
            ok, reason = delete_track(page, tid, commit)
            log(f"    -> {'OK' if ok else 'FAIL'} {tid} {t}: {reason}")
            if ok: del_ok += 1
            else: del_fail += 1

        # Step 2: move originals from WRONG to RIGHT album
        to_move = [(tid, t) for (tid, t) in wrong_tracks if t in comp]
        log(f"[Step2] will MOVE {len(to_move)} track(s) 128168225 -> 121805384:")
        for tid, t in to_move:
            log(f"    MOV {tid}  {t}")
        mov_ok = mov_fail = 0
        for tid, t in to_move:
            ok, reason = move_track(page, tid, RIGHT_ALBUM, commit)
            log(f"    -> {'OK' if ok else 'FAIL'} {tid} {t}: {reason}")
            if ok: mov_ok += 1
            else: mov_fail += 1
            time.sleep(1.0 + random.random())

        ctx.close()

    log("=" * 50)
    log(f"DELETE  ok={del_ok} fail={del_fail}")
    log(f"MOVE    ok={mov_ok} fail={mov_fail}")
    log("Done.")


if __name__ == "__main__":
    main()
