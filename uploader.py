# -*- coding: utf-8 -*-
"""
ximalaya-bulk-uploader
======================

Batch upload audio files to Ximalaya Creator Center (studio.ximalaya.com)
together with a same-named text file used as the sound description.

It is fully generic:
  * any audio content (podcasts, lessons, audiobooks, recordings ...)
  * the audio title comes from the file name (with an optional prefix stripped)
  * the description is taken from a same-named `.txt` file (line breaks kept)
  * the target album, visibility and browser profile are all configurable

How pairing works
------------------
For every audio file `NAME.ext` in the folder, the script looks for a
companion `NAME.txt`. Only matched pairs are published; unmatched files are
reported and skipped.

Requirements
------------
  * Python 3.8+
  * Playwright + Chromium  (pip install playwright && playwright install chromium)
  * A one-time QR login to create a persisted Chrome profile (see login.py)

Configuration precedence (highest wins):
  CLI argument  >  environment variable / .env  >  built-in default

See `.env.example` for all available variables.

Disclaimer
----------
This is an unofficial tool that drives the Ximalaya web UI. It is not an
official API. Use it at your own risk and respect Ximalaya's terms of service
and rate limits.
"""

import os
import re
import sys
import json
import time
import random
import argparse
import wave
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# P1-1: force unbuffered stdout so progress is visible even when the script's
# output is redirected to a file (e.g. `python uploader.py ... > log 2>&1`).
import builtins as _builtins
_orig_print = _builtins.print


def print(*args, **kwargs):
    kwargs.setdefault("flush", True)
    return _orig_print(*args, **kwargs)

# Ximalaya maps the "visibility" radio buttons to these values:
#   1 = 私密 (private), 2 = 公开 (public), 3 = 仅粉丝可见 (fans)
VISIBILITY_MAP = {"private": "1", "public": "2", "fans": "3"}

# Supported audio extensions (lower-case).
AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".wma", ".mpga"}

# The real upload page (the studio home is just a React shell that embeds it).
UPLOAD_URL = "https://www.ximalaya.com/reform-upload/page/webCenter/upload"

# P1-3 / P2-3: a journal of every successfully published sound, used for
# idempotent resume (skip titles already published) and a human-readable
# summary. One JSON object per line: {"title","url","ts"}.
MANIFEST = os.path.join(SCRIPT_DIR, "publish_manifest.jsonl")


def load_published():
    """Return the set of titles already recorded in the manifest."""
    if not os.path.exists(MANIFEST):
        return set()
    done = set()
    with open(MANIFEST, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                done.add(json.loads(line)["title"])
            except Exception:
                pass
    return done


def record_published(title, url):
    """Append a published sound to the manifest and return its timestamp."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(MANIFEST, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"title": title, "url": url, "ts": ts},
                            ensure_ascii=False) + "\n")
    return ts


def _make_key_file():
    """Create a tiny silent .wav used only to open the upload form (the upload
    page is a landing page now; we must enter the form before the album picker
    is reachable). Returns the temp file path."""
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 8000)  # 1 second of silence
    return path


def _enter_form(page, key_file):
    """Open the upload landing page and enter the single-file upload form by
    clicking the webuploader '上传音频' entry and feeding the key file through
    the native file chooser it triggers."""
    page.goto(UPLOAD_URL, timeout=60000)
    page.wait_for_timeout(4000)
    pick = page.locator("div.webuploader-pick", has_text="上传音频").first
    pick.wait_for(timeout=15000)
    with page.expect_file_chooser(timeout=10000) as fc:
        pick.click()
    fc.value.set_files(key_file)
    # Wait until the form fields are rendered (title input appears).
    page.locator("input.ant-input[placeholder='请输入声音标题']").wait_for(timeout=20000)
    page.wait_for_timeout(800)


def check_album_exists(page, album_name, key_file=None, timeout=10000):
    """Open the album picker and verify the target album is listed.

    Called once before a batch: if the album does not exist we abort early
    instead of failing per-item (which wastes minutes on timeouts).
    Returns True if found, False otherwise.

    The upload page is now a landing page; the album picker only exists inside
    the upload form, so we first enter the form (using `key_file`) before
    probing the picker.
    """
    if key_file:
        try:
            _enter_form(page, key_file)
        except Exception as e:
            print(f"  (could not open the upload form: {e})")
            return False
    else:
        # Legacy path (kept for safety): assume the form is already open.
        try:
            page.goto(UPLOAD_URL, timeout=60000)
            page.wait_for_timeout(2500)
        except Exception:
            return False
    try:
        page.locator("button.search-select-album-btn-2fDgDdbT").first.click()
        page.wait_for_timeout(1500)
        items = page.locator("div.scroll-item-content-252FXLKk").all_inner_texts()
        return any(album_name in t for t in items)
    except Exception:
        return False


# ----------------------------------------------------------------------
# Config loading (CLI > env/.env > defaults)
# ----------------------------------------------------------------------
def _load_env_file(path):
    """Read a simple KEY=VALUE .env file (no external dependency)."""
    data = {}
    if not os.path.exists(path):
        return data
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            val = val.strip().strip('"').strip("'")
            data[key.strip()] = val
    return data


def _coerce_bool(value):
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def _coerce_int(value, default):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def build_config():
    """Merge defaults, .env / environment variables and CLI arguments."""
    defaults = {
        "folder": None,
        "album": None,
        "album_id": None,
        "profile": os.path.join(SCRIPT_DIR, "xmly_profile"),
        "visibility": "private",
        "headless": True,
        "interval": 8,
        "interval_jitter": 7,
        "upload_timeout": 300,
        "after_publish": 5,
        "title_prefix": "",
        "verify": True,
        "verify_order": "strict",
        "verify_fail_exit": True,
        "order": "name",
    }

    # 1) .env file, then process environment (env wins over file).
    env = _load_env_file(os.path.join(SCRIPT_DIR, ".env"))
    env.update({k: v for k, v in os.environ.items() if k.startswith("XIMALAYA_")})

    key_map = {
        "XIMALAYA_FOLDER": "folder",
        "XIMALAYA_ALBUM": "album",
        "XIMALAYA_ALBUM_ID": "album_id",
        "XIMALAYA_PROFILE": "profile",
        "XIMALAYA_VISIBILITY": "visibility",
        "XIMALAYA_HEADLESS": "headless",
        "XIMALAYA_INTERVAL": "interval",
        "XIMALAYA_INTERVAL_JITTER": "interval_jitter",
        "XIMALAYA_UPLOAD_TIMEOUT": "upload_timeout",
        "XIMALAYA_AFTER_PUBLISH": "after_publish",
        "XIMALAYA_TITLE_PREFIX": "title_prefix",
        "XIMALAYA_VERIFY": "verify",
        "XIMALAYA_VERIFY_ORDER": "verify_order",
        "XIMALAYA_VERIFY_FAIL_EXIT": "verify_fail_exit",
        "XIMALAYA_ORDER": "order",
    }
    for env_key, cfg_key in key_map.items():
        if env_key in env and env[env_key] != "":
            val = env[env_key]
            if cfg_key == "headless":
                defaults[cfg_key] = _coerce_bool(val)
            elif cfg_key in ("interval", "interval_jitter", "upload_timeout",
                              "after_publish", "album_id"):
                defaults[cfg_key] = _coerce_int(val, defaults[cfg_key])
            elif cfg_key in ("verify", "verify_fail_exit"):
                defaults[cfg_key] = _coerce_bool(val)
            else:
                defaults[cfg_key] = val

    # 2) CLI arguments (highest priority).
    parser = argparse.ArgumentParser(
        description="Batch upload audio + same-named txt to Ximalaya Creator Center"
    )
    parser.add_argument("-f", "--folder", help="Folder with audio + same-named .txt files")
    parser.add_argument("-a", "--album", help="Exact album (作品目录) name in your account")
    parser.add_argument("-p", "--profile", help="Persisted Chrome profile directory")
    parser.add_argument("--visibility", choices=list(VISIBILITY_MAP.keys()),
                        help="private (default) / public / fans")
    parser.add_argument("--no-headless", action="store_true",
                        help="Show the browser window (default is headless)")
    parser.add_argument("--headless", action="store_true",
                        help="Run headless (this is already the default; "
                             "accepted only for compatibility)")
    parser.add_argument("--interval", type=int, help="Seconds between uploads")
    parser.add_argument("--timeout", type=int, dest="upload_timeout",
                        help="Upload wait timeout in seconds")
    parser.add_argument("--after", type=int, dest="after_publish",
                        help="Seconds to wait after clicking publish")
    parser.add_argument("--title-prefix", help="Strip this prefix from titles")
    parser.add_argument("--order", choices=["name", "preview-first", "chapter-first"],
                        default=None,
                        help="Publish order: 'name' (default) = ascending natural "
                             "sort of file names; 'preview-first' = group by "
                             "chapter, publish 预习 (preview) files before 复习 "
                             "(review) files within each chapter, then natural "
                             "sort inside the group; 'chapter-first' = sort by "
                             "chapter number (第一单元, 第二单元 ...) ascending, "
                             "files without a chapter marker go last. Env: "
                             "XIMALAYA_ORDER.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Only scan + pair + print, do not publish")
    parser.add_argument("--yes", action="store_true",
                        help="Skip the interactive confirmation prompt")
    parser.add_argument("--start-from", type=int, default=1, metavar="N",
                        help="Start publishing from the N-th item (1-based)")
    parser.add_argument("--config", help="Path to an alternative .env file")
    parser.add_argument("--no-resume", action="store_true",
                        help="Ignore the publish manifest and re-publish "
                             "everything (otherwise already-published titles are skipped)")
    parser.add_argument("-i", "--album-id",
                        help="Numeric album id (from the Creator Center URL). "
                             "Required for the automatic post-publish verification "
                             "(completeness + order). If omitted, verification is skipped.")
    parser.add_argument("--interval-jitter", type=int,
                        help="Extra random seconds ADDED on top of --interval "
                             "between uploads (default 7). The real wait becomes "
                             "interval + random(0..jitter), which avoids a fixed "
                             "rhythm that platforms flag as bot traffic.")
    parser.add_argument("--no-verify", action="store_true",
                        help="Skip the automatic post-publish verification "
                             "(completeness + order).")
    parser.add_argument("--verify-order", choices=["strict", "monotonic", "off"],
                        default="strict",
                        help="Order check strictness after publishing: "
                             "'strict' (default) requires the online order to "
                             "exactly match the chapter/natural order; "
                             "'monotonic' accepts either ascending or descending; "
                             "'off' skips the order check (still checks completeness).")
    parser.add_argument("--no-verify-fail-exit", action="store_true",
                        help="Do not exit with a non-zero code when verification "
                             "finds missing or out-of-order sounds (just report).")
    args = parser.parse_args()

    if args.config:
        env.update(_load_env_file(args.config))
        # re-apply mapped keys from the alternate file
        for env_key, cfg_key in key_map.items():
            if env_key in env and env[env_key] != "":
                val = env[env_key]
                if cfg_key == "headless":
                    defaults[cfg_key] = _coerce_bool(val)
                elif cfg_key in ("interval", "upload_timeout", "after_publish"):
                    defaults[cfg_key] = _coerce_int(val, defaults[cfg_key])
                else:
                    defaults[cfg_key] = val

    if args.folder:
        defaults["folder"] = args.folder
    if args.album:
        defaults["album"] = args.album
    if args.profile:
        defaults["profile"] = args.profile
    if args.visibility:
        defaults["visibility"] = args.visibility
    if args.no_headless:
        defaults["headless"] = False
    if args.interval is not None:
        defaults["interval"] = args.interval
    if args.upload_timeout is not None:
        defaults["upload_timeout"] = args.upload_timeout
    if args.after_publish is not None:
        defaults["after_publish"] = args.after_publish
    if args.title_prefix is not None:
        defaults["title_prefix"] = args.title_prefix
    if args.headless:
        defaults["headless"] = True
    elif args.no_headless:
        defaults["headless"] = False
    defaults["dry_run"] = args.dry_run
    defaults["no_resume"] = args.no_resume
    defaults["yes"] = args.yes
    defaults["start_from"] = args.start_from
    if args.album_id is not None:
        defaults["album_id"] = args.album_id
    if args.interval_jitter is not None:
        defaults["interval_jitter"] = args.interval_jitter
    if args.no_verify:
        defaults["verify"] = False
    if args.verify_order is not None:
        defaults["verify_order"] = args.verify_order
    if args.order is not None:
        defaults["order"] = args.order
    if args.no_verify_fail_exit:
        defaults["verify_fail_exit"] = False

    # Validate required values.
    if not defaults["folder"]:
        parser.error("folder is required (use --folder or XIMALAYA_FOLDER in .env)")
    if not defaults["album"]:
        parser.error("album is required (use --album or XIMALAYA_ALBUM in .env)")
    if defaults["visibility"] not in VISIBILITY_MAP:
        parser.error("visibility must be one of: " + ", ".join(VISIBILITY_MAP))

    return defaults


# ----------------------------------------------------------------------
# Natural sort (handles Arabic and Chinese numerals)
# ----------------------------------------------------------------------
_CN_NUM = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
           "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _cn_to_int(s):
    """Parse a run of digits / Chinese numerals into an int."""
    if s.isdigit():
        return int(s)
    if s == "十":
        return 10
    if "十" in s:
        left, _, right = s.partition("十")
        tens = _CN_NUM.get(left, 1) if left else 1
        ones = _CN_NUM.get(right, 0) if right else 0
        return tens * 10 + ones
    val = 0
    for ch in s:
        val = val * 10 + _CN_NUM.get(ch, 0)
    return val


_NUM_RUN = re.compile(r"([0-9零一二两三四五六七八九十百千]+)")


def natural_key(text):
    """Sort key so that '02' < '10' and '第一章' < '第二章' < '第三章' ..."""
    key = []
    for tok in _NUM_RUN.split(text):
        if not tok:
            continue
        if _NUM_RUN.fullmatch(tok):
            key.append((0, _cn_to_int(tok)))
        else:
            key.append((1, tok))
    return key


# ----------------------------------------------------------------------
# Scan & pair
# ----------------------------------------------------------------------
def _chapter_prefix(base):
    """Return the chapter prefix (e.g. '第1章-相交线与平行线') so that 预习/复习
    variants of the same chapter group together when sorting."""
    for marker in ("-预习", "-复习"):
        idx = base.find(marker)
        if idx != -1:
            return base[:idx]
    return base


# Chapter markers we recognise in file names: 第一单元, 第3章, 第二课, etc.
_CHAPTER_RE = re.compile(r"第([0-9零一二两三四五六七八九十百千]+)[单元章课]")


def _extract_chapter(base):
    """Return the integer chapter number if the file name contains a marker
    such as '第一单元', '第3章', '第二课'; otherwise return None."""
    m = _CHAPTER_RE.search(base)
    if m:
        return _cn_to_int(m.group(1))
    return None


def _publish_sort_key(base, order):
    """Sort key for the publish list.

    - 'chapter-first': ascending by chapter number (第一单元 < 第二单元 ...);
      files without a chapter marker are placed at the end, then natural sort.
    - 'preview-first': group by chapter, then 预习 (rank 0) before 复习
      (rank 1) within the chapter, then natural sort inside the group.
    - 'name' (default): plain natural sort of the file name.
    """
    if order == "chapter-first":
        ch = _extract_chapter(base)
        return (ch if ch is not None else float("inf"), natural_key(base))
    if order == "preview-first":
        prefix = _chapter_prefix(base)
        if "预习" in base:
            rank = 0
        elif "复习" in base:
            rank = 1
        else:
            rank = 2
        return (prefix, rank, natural_key(base))
    return natural_key(base)


def scan_and_pair(folder, order="name"):
    """Return (pairs, orphan_audio, orphan_txt).

    pairs        : list of (base, audio_path, txt_path) — txt_path may be None
                   (audio-only; published with an empty description).
    orphan_audio : list of (base, audio_path) — reserved; currently always
                   empty because every audio file is published (txt optional).
    orphan_txt   : list of (base, txt_path) — txt without a matching audio.
    """
    audio_files, txt_files = {}, {}
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        base, ext = os.path.splitext(name)
        ext = ext.lower()
        if ext in AUDIO_EXTS:
            audio_files[base] = path
        elif ext == ".txt":
            txt_files[base] = path

    pairs, orphan_audio, orphan_txt = [], [], []
    for base, apath in audio_files.items():
        # txt is optional: publish the audio even without a matching description
        # file (common for listening-audio batches that ship no separate notes).
        pairs.append((base, apath, txt_files.get(base)))
    for base, tpath in txt_files.items():
        if base not in audio_files:
            orphan_txt.append((base, tpath))

    # Publish order: 'preview-first' groups by chapter and puts 预习 before 复习;
    # 'name' (default) is a plain ascending natural sort of the file name.
    pairs.sort(key=lambda x: _publish_sort_key(x[0], order))
    return pairs, orphan_audio, orphan_txt


def read_description(txt_path):
    """Read the whole txt file as the description (keep newlines)."""
    with open(txt_path, "r", encoding="utf-8") as fh:
        return fh.read().strip()


def title_from_audio(base, prefix=""):
    """Title = file base name, optionally with a prefix stripped."""
    if prefix and base.startswith(prefix):
        return base[len(prefix):]
    return base


# ----------------------------------------------------------------------
# Dry run report
# ----------------------------------------------------------------------
def dry_run(folder, config):
    pairs, orphan_audio, orphan_txt = scan_and_pair(folder, config.get("order", "name"))
    prefix = config["title_prefix"]
    order_mode = config.get("order", "name")
    print("=" * 60)
    print(f"Dry run scan: {folder}")
    if order_mode == "preview-first":
        order_label = "preview-first (预习 before 复习, grouped by chapter)"
    elif order_mode == "chapter-first":
        order_label = "chapter-first (chapter number ascending, no-chapter files last)"
    else:
        order_label = "ascending natural sort of file names"
    print(f"Publish order: {order_label}")
    print(f"Visibility  : {config['visibility']} "
          f"({'仅自己可见' if config['visibility'] == 'private' else '公开' if config['visibility'] == 'public' else '仅粉丝可见'})")
    no_desc = sum(1 for _, _, tp in pairs if tp is None)
    print(f"Files to publish: {len(pairs)}  (audio-only / no txt: {no_desc})")
    print(f"Txt without audio: {len(orphan_txt)}")
    print("=" * 60)
    for i, (base, apath, tpath) in enumerate(pairs, 1):
        desc = read_description(tpath) if tpath else ""
        final = title_from_audio(base, prefix)
        if final != base:
            print(f"\n[{i}] Title: {final}   (original: {base})")
        else:
            print(f"\n[{i}] Title: {final}")
        print(f"    audio : {apath}")
        print(f"    desc  ({len(desc)} chars): {desc[:80]}{'…' if len(desc) > 80 else ''}")
    if no_desc:
        print(f"\nℹ {no_desc} file(s) have no matching txt and will be published "
              f"with an empty description.")
    if orphan_txt:
        print("\n⚠ Txt without a same-named audio (ignored):")
        for base, tpath in orphan_txt:
            print(f"    - {tpath}")
    print("\n(Dry run complete — nothing was uploaded.)")


# ----------------------------------------------------------------------
# Pre-publish confirmation
# ----------------------------------------------------------------------
def request_confirm(folder, album, pairs, orphan_audio, orphan_txt, config):
    prefix = config["title_prefix"]
    print("=" * 64)
    print("⚠ Confirm before publishing")
    print(f"Folder : {folder}")
    print(f"Album  : {album}")
    print(f"Visibility: {config['visibility']} "
          f"({'仅自己可见' if config['visibility'] == 'private' else '公开' if config['visibility'] == 'public' else '仅粉丝可见'})")
    print(f"Will publish {len(pairs)} items in this order:")
    for i, (base, _, _) in enumerate(pairs, 1):
        print(f"  {i:>3}. {title_from_audio(base, prefix)}")
    no_desc = sum(1 for _, _, tp in pairs if tp is None)
    if no_desc:
        print(f"({no_desc} audio files have no matching txt and will be "
              f"published with an empty description)")
    if orphan_txt:
        print(f"({len(orphan_txt)} txt files have no audio and will be ignored)")
    print("=" * 64)
    ans = input("Type 'yes' or '确认' to start, anything else to cancel: ").strip()
    return ans in ("确认", "yes", "YES", "Yes", "y", "Y")


# ----------------------------------------------------------------------
# Browser publishing helpers (site-specific selectors, verified working)
# ----------------------------------------------------------------------
def _select_album(page, album_name, timeout=20000):
    """Open the album picker and choose the target album by EXACT title.

    The picker is paginated (loads ~10 albums per page) and a naive substring
    match (has-text) previously selected '英语作文' when the user meant '作文'
    (see issue #album-selection-2026-08-26). We therefore:
      1. match the title span EXACTLY via :text-is (so '作文' != '英语作文');
      2. scroll / click "加载更多" to load every page until the exact item
         appears (the intended album may be several pages deep);
      3. click it. If it never appears we raise (and the batch aborts) instead
         of silently picking the wrong album.
    """
    page.locator("button.search-select-album-btn-2fDgDdbT").first.click()
    page.wait_for_timeout(800)

    title_sel = f"span.album-title-text-4EH5AG-r:text-is('{album_name}')"
    loaded = False
    for _ in range(25):
        if page.locator(title_sel).count() > 0:
            loaded = True
            break
        # Try a "加载更多" (load more) button first.
        more = page.locator("button:has-text('加载更多'), div:has-text('加载更多')").first
        clicked = False
        try:
            if more.count() and more.is_visible(timeout=400):
                more.click()
                clicked = True
                page.wait_for_timeout(600)
        except Exception:
            pass
        if not clicked:
            # Otherwise scroll the nearest scrollable ancestor of the items.
            page.evaluate(
                "() => { const el = document.querySelector('span.album-title-text-4EH5AG-r');"
                " if(!el) return; let p = el; for(let k=0;k<8;k++){ p = p.parentElement;"
                " if(!p) break; if(p.scrollHeight > p.clientHeight){ p.scrollTop = p.scrollHeight; return; } }"
                " window.scrollTo(0, document.body.scrollHeight); }")
            page.wait_for_timeout(600)

    if not loaded:
        seen = page.evaluate(
            "() => Array.from(document.querySelectorAll('span.album-title-text-4EH5AG-r'))"
            ".map(e => e.innerText)")
        raise RuntimeError(
            f"Album '{album_name}' not found in the picker after loading all pages. "
            f"Albums visible: {seen}")

    page.locator(title_sel).first.click()
    page.wait_for_timeout(600)


def _set_title(page, title):
    """Overwrite the auto-filled title with the cleaned one."""
    inp = page.locator("input.ant-input[placeholder='请输入声音标题']")
    inp.click()
    inp.fill("")
    inp.fill(title)
    page.wait_for_timeout(400)


def _set_description(page, desc):
    """Set the description via the KindEditor instance and sync to the
    hidden textarea. IMPORTANT: the editor is HTML, so a plain '\\n' would
    be collapsed and line breaks lost — we convert '\\n' to '<br>'.

    Returns a dict {ok: bool, reason: str}."""
    return page.evaluate(
        """(desc) => {
            const KE = window.KindEditor;
            const editor = (KE && KE.instances) ? KE.instances['0'] : null;
            if (!editor) return {ok:false, reason:'KindEditor instance not found'};
            const esc = desc.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
            const html = esc.replace(/\\n/g, '<br>');
            editor.html(html);
            try { KE.sync('soundRichIntro'); } catch(e) {}
            try { editor.sync(); } catch(e) {}
            const t = document.querySelector('textarea#soundRichIntro');
            return {ok:true, len:desc.length, synced: t ? t.value.length : 0};
        }""",
        desc,
    )


def _set_privacy(page, value='1'):
    """Select the visibility radio button (1=private, 2=public, 3=fans).

    Robustness: we scope the search to the '权限设置' form item so a future
    unrelated radio with the same value (e.g. value='1') cannot be mis-clicked.
    We also VERIFY that the target radio actually shows the antd
    `ant-radio-checked` class after the click. If it does not, we return
    ok:false so the caller aborts the publish loudly instead of silently
    publishing with the platform default (公开 / public).

    The Ximalaya upload form defaults the 权限设置 radio to 公开 (public).
    The *only* thing that makes a sound private is an explicit, verified click
    on the 私密 (value='1') radio — so we must never assume it stuck."""
    return page.evaluate(
        """(value) => {
            const items = Array.from(document.querySelectorAll('.ant-form-item'))
                .filter(it => {
                    const l = it.querySelector('.ant-form-item-label');
                    return l && /权限设置/.test(l.innerText);
                });
            if (!items.length) return {ok:false, reason:'权限设置 form item not found'};
            const item = items[0];
            const radios = Array.from(item.querySelectorAll('input.ant-radio-input'));
            const input = radios.find(r => r.value === value);
            if (!input) return {ok:false, reason:'visibility radio value=' + value + ' not found'};
            const label = input.closest('label.ant-radio-wrapper');
            if (label) label.click();
            else input.click();
            // Re-read the checked wrapper to confirm the UI actually moved.
            const wrap = input.closest('.ant-radio-wrapper');
            const dot = wrap ? wrap.querySelector('.ant-radio') : null;
            const checked = dot ? dot.classList.contains('ant-radio-checked') : input.checked;
            if (!checked) return {ok:false, reason:'visibility radio did not become checked'};
            return {ok:true, labelText: label ? label.innerText.trim() : ''};
        }""",
        value,
    )


def _wait_upload_done(page, timeout_sec=300):
    """Poll the page until '上传中' disappears."""
    for _ in range(max(1, timeout_sec // 2)):
        uploading = page.evaluate("() => document.body.innerText.includes('上传中')")
        if not uploading:
            return True
        page.wait_for_timeout(2000)
    return False


# Phrases that indicate the platform has throttled / challenged the session
# (risk control, captcha, "please verify you are human", rate limit ...).
# Seeing any of these means continuing to hammer the UI is pointless — we
# should stop and let the user intervene. Network feedback confirms Ximalaya
# enforces rate limits (error 104) and an anti-"brush" risk control (error
# 110), so detecting the challenge page early saves wasted minutes.
_BLOCK_TEXTS = [
    "验证码", "安全验证", "请完成安全验证", "操作过于频繁", "访问受限",
    "人机验证", "请验证你是人类", "网络异常请稍后重试", "您的操作过于频繁",
]


def _blocked(page):
    """Return True if the page shows a captcha / risk-control challenge."""
    try:
        txt = page.evaluate("() => document.body.innerText") or ""
    except Exception:
        return False
    return any(k in txt for k in _BLOCK_TEXTS)


def _publish_one(page, apath, title, desc, album, visibility_value='1',
                 after_publish_sec=5, upload_timeout_sec=300):
    """Publish a single audio file on the already-open browser page.
    Returns (success: bool, message: str)."""
    page.goto(UPLOAD_URL, timeout=60000)
    # v1.3.0: vary the landing-page settle time so navigation timing is not
    # perfectly periodic (a fixed rhythm is a classic bot tell).
    page.wait_for_timeout(4000 + random.randint(0, 1500))

    # 1. Choose the file. The upload page now shows a landing page with a
    #    webuploader "上传音频" entry; clicking it opens a native file chooser,
    #    so we capture the chooser and feed the file in (set_input_files on the
    #    hidden input alone no longer works because the form isn't rendered yet).
    pick = page.locator("div.webuploader-pick", has_text="上传音频").first
    pick.wait_for(timeout=15000)
    with page.expect_file_chooser(timeout=10000) as fc:
        pick.click()
    fc.value.set_files(apath)
    page.wait_for_timeout(1500)
    # Positively confirm webuploader accepted the file (its name or an
    # "uploaded" hint must appear). Otherwise the later publish would fail
    # silently — we surface it as a real failure instead of a false success.
    _name = apath.rsplit("/", 1)[-1]
    try:
        page.wait_for_function(
            "() => { const t = document.body.innerText; "
            f"return t.includes({json.dumps(_name)}) || t.includes('上传成功'); }}",
            timeout=60000,
        )
    except Exception:
        return False, "file chooser did not accept the file (not selected)"
    # Wait for webuploader to finish uploading the chosen file.
    if not _wait_upload_done(page, timeout_sec=upload_timeout_sec):
        return False, "timed out waiting for upload to finish"
    page.wait_for_timeout(1000)

    # 2. Select album.
    _select_album(page, album)

    # 3. Title.
    _set_title(page, title)

    # 4. Description.
    r_desc = _set_description(page, desc)
    if not r_desc.get("ok"):
        return False, f"description failed: {r_desc}"

    # 5. Visibility.
    r_priv = _set_privacy(page, visibility_value)
    if not r_priv.get("ok"):
        return False, f"visibility failed: {r_priv}"

    # 6. Wait for the upload to finish.
    if not _wait_upload_done(page, timeout_sec=upload_timeout_sec):
        return False, "timed out waiting for upload to finish"

    # 6.5 Stop early (instead of wasting the retry budget) if the platform has
    #     raised a captcha / risk-control challenge on this session.
    if _blocked(page):
        return False, ("platform risk-control / captcha challenge detected — "
                       "stop and retry later (do not keep hammering the UI)")

    # 7. Tick the "我已阅读并同意《知识产权承诺》" agreement if present.
    #    The 确认发布 button stays DISABLED until this is checked, which is
    #    exactly why some publishes silently did nothing (page never left
    #    webCenter/upload). Ticking it up front makes the click reliable.
    try:
        page.evaluate("""() => {
            const labels = Array.from(document.querySelectorAll('label,span,div'));
            const hit = labels.find(el => el.innerText && el.innerText.includes('知识产权承诺'));
            const cb = hit ? hit.querySelector('input[type=checkbox]') : null;
            if (cb && !cb.checked) {
                cb.checked = true;
                cb.dispatchEvent(new Event('change', {bubbles:true}));
                cb.dispatchEvent(new Event('click', {bubbles:true}));
            }
        }""")
    except Exception:
        pass
    page.wait_for_timeout(800)

    # 7.5 Human-like "think time" before committing the publish: a short random
    #     pause makes the click timing irregular (anti-bot best practice — a
    #     perfectly steady cadence is a well-known automation signature).
    page.wait_for_timeout(random.randint(800, 2500))

    # 8. Click "确认发布" with retries. The button can be momentarily disabled
    #    while the audio finishes server-side processing, so we wait for it to
    #    become enabled, click, and re-check for the success navigation — up to
    #    4 attempts — before giving up.
    publish_btn = page.locator("button.confirm-publish-btn-new-3F0EvXXa").first
    success = False
    last_url = page.url
    for attempt in range(4):
        try:
            publish_btn.wait_for(state="enabled", timeout=15000)
        except Exception:
            pass
        try:
            publish_btn.click(timeout=10000, force=True)
        except Exception:
            pass
        try:
            page.wait_for_url(lambda u: "uploadSuccess" in u, timeout=20000)
            success = True
            break
        except Exception:
            body = page.evaluate("() => document.body.innerText")
            if "发布成功" in body:
                success = True
                break
            last_url = page.url
            page.wait_for_timeout(3000)
    if success:
        return True, page.url
    # DIAGNOSTIC: surface what the page shows so we can see why publish stalled.
    diag = page.evaluate("() => document.body.innerText") or ""
    diag = diag.replace("\n", " ").strip()[:500]
    return False, f"no success signal within timeout, URL: {last_url} | page: {diag}"


def publish_all(folder, config, skip_confirm=False, start_from=1):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is missing. Install it with:\n"
              "    pip install playwright && playwright install chromium")
        sys.exit(1)

    pairs, orphan_audio, orphan_txt = scan_and_pair(folder, config.get("order", "name"))
    if not pairs:
        print("No matched audio+txt pairs found, nothing to do.")
        return

    start_idx = max(0, start_from - 1)
    if start_idx >= len(pairs):
        print(f"--start-from={start_from} exceeds total {len(pairs)}, nothing to publish.")
        return
    if start_idx > 0:
        print(f"Skipping the first {start_idx} item(s); starting at #{start_from}.")
    pairs = pairs[start_idx:]

    # P1-3: idempotent resume — load titles already published.
    published = set() if config.get("no_resume") else load_published()
    if published:
        print(f"Manifest: {len(published)} title(s) already published — "
              f"they will be skipped (use --no-resume to force re-publish).")

    if not skip_confirm and not request_confirm(
            folder, config["album"], pairs, orphan_audio, orphan_txt, config):
        print("Publish cancelled.")
        return

    visibility_value = VISIBILITY_MAP[config["visibility"]]
    prefix = config["title_prefix"]
    total = len(pairs)
    success_count = 0
    results = []  # (title, ok, message) for the summary file

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=config["profile"],
            headless=config["headless"],
        )
        page = context.new_page()

        # P1-2: pre-check the album exists before burning minutes on timeouts.
        print("Pre-checking that the album exists in your account ...")
        _key = _make_key_file()
        if not check_album_exists(page, config["album"], key_file=_key):
            print(f"\n❌ Album not found: {config['album']}")
            print("   Please create this album first in the Ximalaya Creator "
                  "Center (创作中心 → 专辑), then re-run.")
            context.close()
            sys.exit(1)
        print("   Album found. Starting publish.\n")

        for i, (base, apath, tpath) in enumerate(pairs, 1):
            title = title_from_audio(base, prefix)

            # P1-3: skip titles already recorded in the manifest.
            if title in published:
                print(f"\n[{i}/{total}] ⏭ Already published, skipping: {title}")
                results.append((title, True, "skipped (already in manifest)"))
                continue

            desc = read_description(tpath) if tpath else ""
            print(f"\n[{i}/{total}] Publishing: {title}")
            try:
                ok, msg = _publish_one(
                    page, apath, title, desc, config["album"],
                    visibility_value=visibility_value,
                    after_publish_sec=config["after_publish"],
                    upload_timeout_sec=config["upload_timeout"],
                )
                if ok:
                    # Safety net: confirm the publish actually landed in the
                    # intended album. The success URL embeds the album id
                    # (/sound/manage/<albumId>); if it differs from --album-id
                    # we abort the whole batch instead of mis-publishing the
                    # remaining items to the wrong album.
                    expected_id = config.get("album_id")
                    if expected_id is not None:
                        m = re.search(r"/manage/(\d+)", msg or "")
                        got_id = m.group(1) if m else None
                        if got_id is not None and str(got_id) != str(expected_id):
                            print(f"\n❌ SAFETY ABORT: track was published to "
                                  f"album {got_id}, but the intended album is "
                                  f"{expected_id}. Stopping now to avoid "
                                  f"mis-publishing the rest of the batch.")
                            context.close()
                            sys.exit(1)
                    ts = record_published(title, msg)  # P1-3: journal it
                    success_count += 1
                    print(f"  ✅ Success: {msg}  ({ts})")
                    results.append((title, True, msg))
                else:
                    print(f"  ❌ Failed: {msg}")
                    results.append((title, False, msg))
            except Exception as e:  # keep going, record the failure
                print(f"  ❌ Error: {type(e).__name__}: {e}")
                results.append((title, False, f"{type(e).__name__}: {e}"))

            if i < total:
                base = config["interval"]
                jitter = config.get("interval_jitter") or 0
                wait = base + random.uniform(0, jitter)
                print(f"  ⏳ Waiting {wait:.1f}s (base {base}s + jitter {jitter}s) ...")
                page.wait_for_timeout(int(wait * 1000))

        context.close()

    print(f"\nDone: {success_count}/{total} published successfully.")

    # P2-3: write a human-readable summary file (merged with the manifest).
    summary_path = os.path.join(
        SCRIPT_DIR, f"published_{time.strftime('%Y%m%d_%H%M%S')}.txt")
    with open(summary_path, "w", encoding="utf-8") as fh:
        fh.write(f"发布结果 {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        fh.write(f"专辑：{config['album']}  可见性：{config['visibility']}\n")
        fh.write(f"成功 {success_count}/{total}\n")
        fh.write("-" * 48 + "\n")
        for t, ok, m in results:
            fh.write(f"{'✅' if ok else '❌'} {t}\n   {m}\n")
    print(f"结果汇总已写入：{summary_path}")

    # v1.3.0: automatic post-publish verification (completeness + order).
    verify_failed = False
    if config.get("verify") and config.get("album_id"):
        print("\n" + "=" * 60)
        print("🔎 Verifying published results (completeness + order) ...")
        verify_failed = verify_publish(folder, config["album_id"],
                                       config["profile"], config)
    elif config.get("verify") and not config.get("album_id"):
        print("\n⚠ Verification skipped: pass --album-id / XIMALAYA_ALBUM_ID "
              "to enable automatic post-publish verification.")

    return {
        "success_count": success_count,
        "total": total,
        "verify_failed": verify_failed,
    }


def _is_monotonic(seq, ref):
    """True if `seq` (a permutation of `ref`, in some order) is either strictly
    ascending or strictly descending relative to `ref`'s order. Used by the
    'monotonic' verify mode, which accepts a fully reversed list (e.g. a
    platform that displays newest-first) as long as it is not scrambled."""
    idx = {t: i for i, t in enumerate(ref)}
    pos = [idx[t] for t in seq]
    asc = all(pos[i] < pos[i + 1] for i in range(len(pos) - 1))
    desc = all(pos[i] > pos[i + 1] for i in range(len(pos) - 1))
    return asc or desc


def verify_publish(folder, album_id, profile, config):
    """Verify (1) every local audio+txt pair is actually online, and (2) the
    online order of those sounds matches the intended order (natural sort, or
    preview-first when --order preview-first is used).

    Ximalaya's Creator-Center 'sound manage' page lists a track's sounds in
    *creation (upload) order, oldest first*. So a clean sequential publish in
    natural order yields an online order identical to the local order; any
    batch that appended out of order shows up as scrambled here.

    Returns True if verification found a problem (so the caller can exit
    non-zero / alert), False if everything is fine.
    """
    pairs, orphan_audio, orphan_txt = scan_and_pair(folder, config.get("order", "name"))
    prefix = config.get("title_prefix", "")
    intended = [title_from_audio(b, prefix) for b, _, _ in pairs]  # per --order
    intended_set = set(intended)

    if not intended:
        print("  (no local audio files to verify)")
        return False

    # ---- capture the real online titles via the album/tracks API ----
    captured = []

    def on_resp(resp):
        if "reform-upload/manage/album/tracks" in resp.url:
            try:
                j = resp.json()
                if isinstance(j, dict) and j.get("ret") == 0:
                    captured.append(j)
            except Exception:
                pass

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  ⚠ playwright missing — cannot verify online.")
        return False

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=profile, headless=True)
        page = ctx.new_page()
        page.on("response", on_resp)
        page.goto(
            f"https://www.ximalaya.com/reform-upload/page/sound/manage/{album_id}",
            timeout=60000)
        page.wait_for_timeout(4500)
        # Page through using the "next" button (robust to windowed pagination).
        for _ in range(30):
            nx = page.locator(".ant-pagination-next")
            if nx.count() == 0:
                break
            cls = nx.first.get_attribute("class") or ""
            if "ant-pagination-disabled" in cls:
                break
            try:
                nx.first.click(timeout=5000)
                page.wait_for_timeout(2200)
            except Exception:
                break
        ctx.close()

    online = []
    seen = set()
    for j in captured:
        for it in j.get("data", {}).get("infos", []):
            if isinstance(it, dict) and it.get("title"):
                t = it["title"]
                if t not in seen:
                    seen.add(t)
                    online.append(t)

    online_set = set(online)

    # ---- 1. completeness ----
    missing = [t for t in intended if t not in online_set]

    # ---- 2. order (only among this batch's titles, preserving online order) ----
    batch_online = [t for t in online if t in intended_set]
    order_mode = config.get("verify_order", "strict")
    if order_mode == "off":
        order_ok, order_label = None, "skipped (--verify-order off)"
    elif order_mode == "monotonic":
        order_ok = _is_monotonic(batch_online, intended)
        order_label = "monotonic (asc or desc accepted)"
    else:  # strict
        order_ok = (batch_online == intended)
        order_label = "strict (must equal chapter/natural order)"

    # ---- derive mismatched positions (for reporting) ----
    mismatches = []
    if order_ok is False:
        for i, t in enumerate(batch_online):
            exp = intended[i] if i < len(intended) else None
            if t != exp:
                mismatches.append((i + 1, t,
                                   intended.index(t) + 1 if t in intended_set else -1))

    # ---- render report ----
    report = []
    report.append(f"校验时间：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"专辑 ID：{album_id}   校验模式：{order_label}")
    report.append(f"本地配对：{len(intended)}   在线声音：{len(online)}")
    report.append("")
    report.append(f"[1] 完整性：{'✅ 全部在线' if not missing else '❌ 缺失 ' + str(len(missing)) + ' 条'}")
    for m in missing:
        report.append(f"    缺：{m}")
    report.append("")
    if order_ok is None:
        report.append(f"[2] 顺序：⏭ 未检查（--verify-order off）")
    elif order_ok:
        report.append(f"[2] 顺序：✅ 在线顺序与预期一致（{order_label}）")
    else:
        report.append(f"[2] 顺序：❌ 在线顺序错乱（{order_label}），共 {len(mismatches)} 处不一致")
        for pos, t, exp in mismatches[:15]:
            report.append(f"    在线第{pos}位 = {t}   （应在第{exp}位）")
        if len(mismatches) > 15:
            report.append(f"    … 其余 {len(mismatches) - 15} 处省略")

    text = "\n".join(report)
    print(text)

    report_path = os.path.join(
        SCRIPT_DIR, f"verify_report_{time.strftime('%Y%m%d_%H%M%S')}.txt")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print(f"校验报告已写入：{report_path}")

    problem = bool(missing) or (order_ok is False)
    return problem


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------
def main():
    config = build_config()
    folder = config["folder"]

    if not os.path.isdir(folder):
        print(f"Folder does not exist: {folder}")
        sys.exit(1)

    if config["dry_run"]:
        dry_run(folder, config)
    else:
        res = publish_all(folder, config, skip_confirm=config["yes"],
                          start_from=config["start_from"])
        if res and res.get("verify_failed") and config.get("verify_fail_exit"):
            print("\n❌ Verification failed (missing or out-of-order sounds). "
                  "Exiting with status 2 so the run can be flagged/retried.")
            sys.exit(2)


if __name__ == "__main__":
    main()
