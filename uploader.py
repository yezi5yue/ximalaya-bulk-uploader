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
        "profile": os.path.join(SCRIPT_DIR, "xmly_profile"),
        "visibility": "private",
        "headless": True,
        "interval": 8,
        "upload_timeout": 300,
        "after_publish": 5,
        "title_prefix": "",
    }

    # 1) .env file, then process environment (env wins over file).
    env = _load_env_file(os.path.join(SCRIPT_DIR, ".env"))
    env.update({k: v for k, v in os.environ.items() if k.startswith("XIMALAYA_")})

    key_map = {
        "XIMALAYA_FOLDER": "folder",
        "XIMALAYA_ALBUM": "album",
        "XIMALAYA_PROFILE": "profile",
        "XIMALAYA_VISIBILITY": "visibility",
        "XIMALAYA_HEADLESS": "headless",
        "XIMALAYA_INTERVAL": "interval",
        "XIMALAYA_UPLOAD_TIMEOUT": "upload_timeout",
        "XIMALAYA_AFTER_PUBLISH": "after_publish",
        "XIMALAYA_TITLE_PREFIX": "title_prefix",
    }
    for env_key, cfg_key in key_map.items():
        if env_key in env and env[env_key] != "":
            val = env[env_key]
            if cfg_key == "headless":
                defaults[cfg_key] = _coerce_bool(val)
            elif cfg_key in ("interval", "upload_timeout", "after_publish"):
                defaults[cfg_key] = _coerce_int(val, defaults[cfg_key])
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
def scan_and_pair(folder):
    """Return (pairs, orphan_audio, orphan_txt).

    pairs        : list of (base, audio_path, txt_path)
    orphan_audio : list of (base, audio_path)   audio without a txt
    orphan_txt   : list of (base, txt_path)     txt without an audio
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
        if base in txt_files:
            pairs.append((base, apath, txt_files[base]))
        else:
            orphan_audio.append((base, apath))
    for base, tpath in txt_files.items():
        if base not in audio_files:
            orphan_txt.append((base, tpath))

    # Publish in ascending natural order of file name.
    pairs.sort(key=lambda x: natural_key(x[0]))
    orphan_audio.sort(key=lambda x: natural_key(x[0]))
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
    pairs, orphan_audio, orphan_txt = scan_and_pair(folder)
    prefix = config["title_prefix"]
    print("=" * 60)
    print(f"Dry run scan: {folder}")
    print(f"Publish order: ascending natural sort of file names")
    print(f"Visibility  : {config['visibility']} "
          f"({'仅自己可见' if config['visibility'] == 'private' else '公开' if config['visibility'] == 'public' else '仅粉丝可见'})")
    print(f"Matched pairs (audio + txt): {len(pairs)}")
    print(f"Audio without txt: {len(orphan_audio)}")
    print(f"Txt without audio: {len(orphan_txt)}")
    print("=" * 60)
    for i, (base, apath, tpath) in enumerate(pairs, 1):
        desc = read_description(tpath)
        final = title_from_audio(base, prefix)
        if final != base:
            print(f"\n[{i}] Title: {final}   (original: {base})")
        else:
            print(f"\n[{i}] Title: {final}")
        print(f"    audio : {apath}")
        print(f"    desc  ({len(desc)} chars): {desc[:80]}{'…' if len(desc) > 80 else ''}")
    if orphan_audio:
        print("\n⚠ Audio without a same-named txt (will be skipped):")
        for base, apath in orphan_audio:
            print(f"    - {apath}")
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
    if orphan_audio:
        print(f"({len(orphan_audio)} audio files have no txt and will be skipped)")
    if orphan_txt:
        print(f"({len(orphan_txt)} txt files have no audio and will be ignored)")
    print("=" * 64)
    ans = input("Type 'yes' or '确认' to start, anything else to cancel: ").strip()
    return ans in ("确认", "yes", "YES", "Yes", "y", "Y")


# ----------------------------------------------------------------------
# Browser publishing helpers (site-specific selectors, verified working)
# ----------------------------------------------------------------------
def _select_album(page, album_name, timeout=10000):
    """Open the album picker and choose the target album."""
    page.locator("button.search-select-album-btn-2fDgDdbT").first.click()
    page.wait_for_timeout(800)
    item_sel = f"div.scroll-item-content-252FXLKk:has-text('{album_name}')"
    page.locator(item_sel).first.wait_for(timeout=timeout)
    page.locator(item_sel).first.click()
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
    """Select the visibility radio button (1=private, 2=public, 3=fans)."""
    return page.evaluate(
        """(value) => {
            const input = document.querySelector('input.ant-radio-input[value="' + value + '"]');
            if (!input) return {ok:false, reason:'radio value=' + value + ' not found'};
            const label = input.closest('label.ant-radio-wrapper');
            if (label) label.click();
            input.checked = true;
            input.dispatchEvent(new Event('change', {bubbles:true}));
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


def _publish_one(page, apath, title, desc, album, visibility_value='1',
                 after_publish_sec=5, upload_timeout_sec=300):
    """Publish a single audio file on the already-open browser page.
    Returns (success: bool, message: str)."""
    page.goto(UPLOAD_URL, timeout=60000)
    page.wait_for_timeout(4000)

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

    # 7. Click "确认发布".
    page.locator("button.confirm-publish-btn-new-3F0EvXXa").first.click()
    page.wait_for_timeout(after_publish_sec * 1000)

    # 8. Detect success: wait for the page to navigate to the success page.
    #    NOTE: do NOT rely on vague navbar text like "内容管理" — the upload
    #    page always shows it, so it once caused false successes (the page
    #    stayed on webCenter/upload yet was marked done). We require the
    #    explicit uploadSuccess navigation or a clear "发布成功" message.
    success = False
    try:
        page.wait_for_url(lambda u: "uploadSuccess" in u, timeout=30000)
        success = True
    except Exception:
        body = page.evaluate("() => document.body.innerText")
        if "发布成功" in body:
            success = True
    if success:
        return True, page.url
    return False, f"no success signal within timeout, URL: {page.url}"


def publish_all(folder, config, skip_confirm=False, start_from=1):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is missing. Install it with:\n"
              "    pip install playwright && playwright install chromium")
        sys.exit(1)

    pairs, orphan_audio, orphan_txt = scan_and_pair(folder)
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

            desc = read_description(tpath)
            print(f"\n[{i}/{total}] Publishing: {title}")
            try:
                ok, msg = _publish_one(
                    page, apath, title, desc, config["album"],
                    visibility_value=visibility_value,
                    after_publish_sec=config["after_publish"],
                    upload_timeout_sec=config["upload_timeout"],
                )
                if ok:
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
                print(f"  ⏳ Waiting {config['interval']}s ...")
                page.wait_for_timeout(config["interval"] * 1000)

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
        publish_all(folder, config, skip_confirm=config["yes"],
                    start_from=config["start_from"])


if __name__ == "__main__":
    main()
