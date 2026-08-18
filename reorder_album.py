#!/usr/bin/env python3
"""Reorder the tracks in a Ximalaya album by title, without deleting anything.

Uses the Creator Center's internal changeOrder API (the same endpoint used by the
sortable drag-and-drop UI). The script:

1. Fetches the real current order via the signed `album/tracks` API.
2. Separates "full lessons" (titles containing "第.*讲") from "review" tracks
   (titles containing "复习"), sorts each group by title, then concatenates:
   [full lessons in chapter order] + [review tracks in chapter order].
3. Performs insertion-sort style moves using `changeOrder` until the album order
   matches the desired order.
4. Waits between moves with a random jitter to stay human-like.

Usage:
    python reorder_album.py --album-id 128358894 --profile /path/to/xmly_profile
"""
import os
import sys
import json
import time
import random
import argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def fetch_current_tracks(page, album_id):
    """Capture all tracks in current album order via the page's signed API."""
    captured = []
    def on_resp(resp):
        if "reform-upload/manage/album/tracks" in resp.url:
            try:
                j = resp.json()
                if isinstance(j, dict) and j.get("ret") == 0:
                    captured.append(j)
            except Exception:
                pass

    page.on("response", on_resp)
    ref = f"https://www.ximalaya.com/reform-upload/page/sound/manage/{album_id}"
    page.goto(ref, timeout=60000)
    page.wait_for_timeout(4500)
    # click through pagination (pageSize=10)
    for pg in ["2", "3", "4", "5", "6", "7", "8", "9", "10"]:
        try:
            loc = page.locator(".ant-pagination-item", has_text=pg)
            if loc.count() == 0:
                break
            loc.first.click(timeout=5000)
            page.wait_for_timeout(2200)
        except Exception:
            break
    page.remove_listener("response", on_resp)

    tracks = []
    seen = set()
    for j in captured:
        for it in j.get("data", {}).get("infos", []):
            tid = it.get("trackId")
            if tid and tid not in seen:
                seen.add(tid)
                tracks.append({"trackId": tid, "title": it.get("title", "")})
    return tracks


def call_change_order(page, album_id, track_id, before_id, after_id, retries=3):
    url = "https://www.ximalaya.com/reform-upload/manage/album/track/changeOrder"
    body = {"albumId": album_id, "trackId": track_id,
            "targetBeforeTrackId": before_id, "targetAfterTrackId": after_id}
    last_err = None
    for attempt in range(retries):
        try:
            res = page.evaluate(f"""async () => {{
                const r = await fetch("{url}", {{
                    method: "POST",
                    headers: {{"Content-Type": "application/json"}},
                    body: JSON.stringify({json.dumps(body)}),
                    credentials: "include"
                }});
                return {{status: r.status, text: await r.text()}};
            }}""")
            text = res.get("text", "")
            try:
                j = json.loads(text)
            except Exception:
                j = {"ret": -999, "msg": text[:200]}
            if j.get("ret") == 0:
                return j
            last_err = j
            print(f"  ⚠ changeOrder ret={j.get('ret')} msg={j.get('msg')} (retry {attempt+1}/{retries})")
            time.sleep(2 + random.random() * 3)
        except Exception as e:
            last_err = {"ret": -999, "msg": str(e)}
            print(f"  ⚠ changeOrder exception: {e} (retry {attempt+1}/{retries})")
            time.sleep(2 + random.random() * 3)
    raise RuntimeError(f"changeOrder failed after {retries} retries: {last_err}")


def _track_sort_key(title):
    """Sort key that respects chapter/lesson/review order.

    Full lessons come before reviews for the same chapter.  Old full lessons use
    Chinese numerals (第一章), reviews use Arabic numerals (第1章).
    """
    import re
    CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
              "七": 7, "八": 8, "九": 9, "十": 10}

    def chapter_num(s):
        m = re.match(r"第(\d+)章", s)
        if m:
            return int(m.group(1))
        m = re.match(r"第([一二三四五六七八九十]+)章", s)
        if m:
            return CN_NUM.get(m.group(1), 999)
        return 999

    def sub_num(s):
        # full lesson: 第XX讲 ; review: 复习-XX-
        m = re.search(r"第(\d+)讲", s)
        if m:
            return int(m.group(1))
        m = re.search(r"复习-(\d+)-", s)
        if m:
            return int(m.group(1))
        return 999

    is_review = 1 if "复习" in title else 0
    return (chapter_num(title), is_review, sub_num(title))


def compute_desired_order(tracks):
    """Return desired list of track IDs: full-lessons first, then reviews,
    each group sorted by chapter/lesson or chapter/review number."""
    full = [t for t in tracks if "复习" not in t["title"]]
    review = [t for t in tracks if "复习" in t["title"]]
    full_sorted = sorted(full, key=lambda t: _track_sort_key(t["title"]))
    review_sorted = sorted(review, key=lambda t: _track_sort_key(t["title"]))
    return [t["trackId"] for t in full_sorted + review_sorted]


def reorder(page, album_id, tracks, desired_ids, interval=10, jitter=10):
    """Insertion-sort using changeOrder. Assumes desired[0] is already first."""
    current = [t["trackId"] for t in tracks]
    n = len(current)
    if current[0] != desired_ids[0]:
        raise RuntimeError(
            f"First track mismatch: current={current[0]} desired={desired_ids[0]}. "
            "Cannot safely reorder position 0 via this API."
        )

    moves = []
    for i in range(1, n):
        if current[i] == desired_ids[i]:
            continue
        before_id = current[i - 1]
        after_id = current[i]
        track_id = desired_ids[i]
        title = next(t["title"] for t in tracks if t["trackId"] == track_id)
        print(f"[{i}/{n-1}] moving track {track_id} ({title[:40]}) between {before_id} and {after_id}")
        call_change_order(page, album_id, track_id, before_id, after_id)
        # update local model: remove from old position and insert at i
        old_idx = current.index(track_id)
        current.pop(old_idx)
        current.insert(i, track_id)
        moves.append(i)
        if i < n - 1:
            wait = interval + random.uniform(0, jitter)
            print(f"  ⏳ wait {wait:.1f}s")
            time.sleep(wait)
    return moves


def main():
    ap = argparse.ArgumentParser(description="Reorder Ximalaya album tracks by title via changeOrder API.")
    ap.add_argument("--album-id", required=True, help="Numeric album id.")
    ap.add_argument("--profile", default=os.path.join(SCRIPT_DIR, "xmly_profile"),
                    help="Playwright persistent profile dir (must be logged in).")
    ap.add_argument("--interval", type=float, default=10,
                    help="Base seconds between move operations (default 10).")
    ap.add_argument("--jitter", type=float, default=10,
                    help="Random extra seconds 0..jitter between moves (default 10).")
    ap.add_argument("--backup", default="/tmp/album_order_backup.json",
                    help="Where to save the original order JSON.")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is missing. Install it with:\n    pip install playwright && playwright install chromium")
        sys.exit(1)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=args.profile, headless=True, args=["--no-sandbox"]
        )
        page = ctx.new_page()
        print("Fetching current album order...")
        tracks = fetch_current_tracks(page, args.album_id)
        print(f"Fetched {len(tracks)} tracks.")
        with open(args.backup, "w", encoding="utf-8") as f:
            json.dump(tracks, f, ensure_ascii=False, indent=2)
        print(f"Original order backed up to {args.backup}")

        desired_ids = compute_desired_order(tracks)
        print(f"\nDesired order: {len([t for t in tracks if '复习' not in t['title']])} full-lessons + "
              f"{len([t for t in tracks if '复习' in t['title']])} reviews.")

        current_ids = [t["trackId"] for t in tracks]
        if current_ids == desired_ids:
            print("Album is already in desired order. Nothing to do.")
            ctx.close()
            return

        misplaced = sum(1 for a, b in zip(current_ids, desired_ids) if a != b)
        print(f"Misplaced tracks: {misplaced}. Starting reorder (this may take several minutes)...")
        moves = reorder(page, args.album_id, tracks, desired_ids,
                        interval=args.interval, jitter=args.jitter)
        print(f"\nCompleted {len(moves)} move operations.")

        print("\nRe-fetching to verify...")
        final_tracks = fetch_current_tracks(page, args.album_id)
        final_ids = [t["trackId"] for t in final_tracks]
        if final_ids == desired_ids:
            print("✅ Album order matches desired order.")
        else:
            print("❌ Final order still does not match desired order.")
            diff = sum(1 for a, b in zip(final_ids, desired_ids) if a != b)
            print(f"   {diff} tracks still misplaced.")
            for i, (a, b) in enumerate(zip(final_ids, desired_ids)):
                if a != b:
                    print(f"   pos {i}: current={final_tracks[i]['title'][:40]} expected={desired_ids[i]}")
        ctx.close()


if __name__ == "__main__":
    main()
