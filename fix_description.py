# -*- coding: utf-8 -*-
"""
fix_description.py — re-apply the companion .txt as the description of
already-published sounds.

Use this as a recovery tool when, for any reason, the description was not
written during upload (e.g. the editor failed to sync). It finds each sound
by its title in the Ximalaya sound list, opens the edit page, sets the
description via KindEditor and clicks save.

It reuses the same config resolution as uploader.py (CLI > env/.env > defaults),
so the same --folder / --album / --profile / --title-prefix / .env work here.

Usage:
    python fix_description.py --folder /path --album "My Album"
    python fix_description.py            # reads .env
"""

import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LIST_URL = "https://www.ximalaya.com/reform-upload/page/sound/list"
MAX_PAGES = 100


def _click_save(page):
    """Click the save button whose label contains '保存' (may render as '保 存')."""
    page.evaluate(
        """() => {
            const btns = Array.from(document.querySelectorAll('button, a'));
            const target = btns.find(b => {
                const t = (b.innerText || '').replace(/\\s+/g, '');
                return t.includes('保存');
            });
            if (target) { target.click(); return true; }
            return false;
        }"""
    )


def _find_edit_url(page, title, max_pages=MAX_PAGES):
    """Locate the edit URL of a sound by its title, walking through pages."""
    seen = set()
    for _ in range(max_pages):
        # Collect edit links together with their ancestor text.
        data = page.evaluate(
            """(title) => {
                const links = Array.from(document.querySelectorAll('a[href*="/reform-upload/page/sound/edit/"]'));
                const out = [];
                for (const a of links) {
                    let node = a, txt = '';
                    for (let i = 0; i < 25 && node; i++) {
                        const t = node.innerText || '';
                        if (t) { txt = t; break; }
                        node = node.parentElement;
                    }
                    out.push({href: a.getAttribute('href'), txt});
                    if (txt.includes(title)) return {found: a.getAttribute('href')};
                }
                return {found: null, sig: out.map(o => o.href).join('|')};
            }""",
            title,
        )
        if data.get("found"):
            return data["found"]
        sig = data.get("sig", "")
        if sig in seen:
            break  # no progress -> stop
        seen.add(sig)

        # Try to go to the next page.
        clicked = page.evaluate(
            """() => {
                const els = Array.from(document.querySelectorAll('a, button, li'));
                const next = els.find(e => {
                    const t = (e.innerText || '').replace(/\\s+/g, '');
                    return t === '下一页' || t === '下页';
                });
                if (!next) return false;
                const disabled = next.disabled ||
                    (next.getAttribute && next.getAttribute('aria-disabled') === 'true') ||
                    (next.className && /disabled/.test(next.className));
                if (disabled) return false;
                next.click();
                return true;
            }"""
        )
        if not clicked:
            break
        page.wait_for_timeout(1500)

    return None


def fix_one(page, title, desc):
    """Open the edit page for `title`, set its description, save, verify."""
    edit_url = _find_edit_url(page, title)
    if not edit_url:
        return False, "could not locate the sound in the list"
    if not edit_url.startswith("http"):
        edit_url = "https://www.ximalaya.com" + edit_url
    page.goto(edit_url, timeout=60000)
    page.wait_for_timeout(5000)

    result = page.evaluate(
        """(desc) => {
            const KE = window.KindEditor;
            const editor = (KE && KE.instances) ? KE.instances['0'] : null;
            if (!editor) return {ok:false, reason:'KindEditor instance not found'};
            const esc = desc.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
            const html = esc.replace(/\\n/g, '<br>');
            editor.html(html);
            try { KE.sync('richIntro'); } catch(e) {}
            try { editor.sync(); } catch(e) {}
            const t = document.querySelector('textarea#richIntro');
            return {ok:true, synced: t ? t.value.length : 0};
        }""",
        desc,
    )
    if not result.get("ok"):
        return False, f"editor failed: {result}"

    _click_save(page)
    page.wait_for_timeout(3000)

    # Verify the saved value matches (ignoring whitespace / html tags).
    saved = page.evaluate("() => {const t=document.querySelector('textarea#richIntro'); return t?t.value:'';}")
    plain = re.sub(r"<[^>]+>", "", saved)
    plain_norm = re.sub(r"\s+", "", plain)
    local_norm = re.sub(r"\s+", "", desc)
    if plain_norm == local_norm:
        return True, "updated & verified"
    return False, f"save may have failed (len={len(plain_norm)} vs {len(local_norm)})"


def main():
    # Reuse uploader's config resolution (needs folder + album).
    sys.path.insert(0, SCRIPT_DIR)
    from uploader import build_config, scan_and_pair, read_description, title_from_audio

    config = build_config()
    folder = config["folder"]
    if not os.path.isdir(folder):
        print(f"Folder does not exist: {folder}")
        sys.exit(1)

    pairs, _, _ = scan_and_pair(folder)
    if not pairs:
        print("No matched audio+txt pairs found.")
        sys.exit(1)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is missing. Install it with:\n"
              "    pip install playwright && playwright install chromium")
        sys.exit(1)

    prefix = config["title_prefix"]
    total = len(pairs)
    ok_count = 0

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=config["profile"],
            headless=config["headless"],
        )
        page = context.new_page()
        page.goto(LIST_URL, timeout=60000)
        page.wait_for_timeout(3000)

        for i, (base, apath, tpath) in enumerate(pairs, 1):
            title = title_from_audio(base, prefix)
            desc = read_description(tpath)
            print(f"[{i}/{total}] Fixing: {title}")
            try:
                ok, msg = fix_one(page, title, desc)
                if ok:
                    ok_count += 1
                    print(f"  ✅ {msg}")
                else:
                    print(f"  ❌ {msg}")
            except Exception as e:
                print(f"  ❌ Error: {type(e).__name__}: {e}")

        context.close()

    print(f"\nDone: {ok_count}/{total} descriptions fixed.")


if __name__ == "__main__":
    main()
