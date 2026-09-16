#!/usr/bin/env python3
"""为一个喜马拉雅专辑生成「音频直达链接清单」（Markdown）。

用途：上传完音频后，快速得到一份可直接发给手机/微信的链接表——
      每条音频一个跳转页链接，点开即唤起喜马拉雅 App 播放。

依赖：playwright（托管 Python），以及一份已登录的浏览器 profile。
      不需要任何 API key —— 复用创作中心的登录态 Cookie。

用法：
    PY=/Users/yezi/.workbuddy/binaries/python/envs/default/bin/python
    $PY gen_album_links.py \
        --album-id 121805384 --album 作文 \
        --profile /Users/yezi/WorkBuddy/2026-08-11-22-09-49/ximalaya_uploader/xmly_profile

可选：
    --base <跳转页地址>   默认 https://xmly-open.app.workbuddy.host/
    --out  <输出文件>     默认 ./ximalaya_<albumId>_track_links.md
    --dry-run             只打印，不写文件

注意：本脚本只读，不修改任何线上内容。
"""

import argparse
import datetime
import json
import os
import sys
import urllib.parse


# --- 拉取数据 ---------------------------------------------------------------

# 注意：POST 版不要用三引号拼 Python 字符串（会在 JS 里多一个引号）。
_GET_JSON_JS = ("(u)=>fetch(u,{credentials:'include',"
                "headers:{'Accept':'application/json, text/plain, */*'}})"
                ".then(r=>r.json())")


def _fetch_json(page, url):
    return page.evaluate(_GET_JSON_JS, url)


def fetch_album_tracks(page, album_id, page_size=50):
    """返回 [(trackId, title, visibleCrowdType), ...]，按专辑在线顺序（ASC）。"""
    out, pg = [], 1
    while True:
        url = ("https://www.ximalaya.com/reform-upload/manage/album/tracks"
               f"?albumId={album_id}&page={pg}&pageSize={page_size}"
               "&order=ASC&state=1")
        r = _fetch_json(page, url)
        if r.get("ret") != 0:
            print(f"  ! 接口返回异常 ret={r.get('ret')} (page {pg})，停止翻页")
            break
        d = r.get("data") or {}
        items = d.get("tracks") or d.get("infos") or []
        for it in items:
            out.append((it.get("trackId"), it.get("title"),
                        it.get("visibleCrowdType")))
        total = d.get("totalSize") or d.get("total") or 0
        if not items or pg * page_size >= total:
            break
        pg += 1
    return out


def fetch_track_title(page, track_id):
    """单条核实：返回 (title, albumId, visibleCrowdType)。"""
    url = ("https://www.ximalaya.com/reform-upload/anchorTrack/edit"
           f"?trackId={track_id}")
    r = _fetch_json(page, url)
    ti = (r.get("data") or {}).get("trackInfo") or {}
    return ti.get("title"), ti.get("albumId"), ti.get("visibleCrowdType")


# --- 生成 Markdown ---------------------------------------------------------

BQ = chr(96)  # 反引号，单独取出来避免在 shell 内联时被解析


def build_markdown(album_id, album_name, tracks, base):
    n_private = sum(1 for t in tracks if t[2] == 1)
    L = []
    L.append(f"# {album_name} · 音频直达链接清单")
    L.append("")
    L.append("生成时间：%s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    L.append("")
    L.append(f"专辑：**{album_name}**（albumId {BQ}{album_id}{BQ}）"
             f" | 在线 {len(tracks)} 条 | 其中私密 {n_private} 条")
    L.append("")
    L.append(f"跳转页：{base}  （手机浏览器打开会唤起喜马拉雅 App）")
    L.append("")
    L.append("## 一键打开整个专辑")
    L.append("")
    L.append("| 用途 | 链接 |")
    L.append("|---|---|")
    L.append("| 网页（微信可传） | %s?a=%d&n=%s |"
             % (base, album_id, urllib.parse.quote(album_name)))
    L.append("| 前缀写法（原链接拼在域名后） | %s#https://www.ximalaya.com/album/%d |"
             % (base, album_id))
    L.append("| App 深链（直接跳 App） | iting://open?msg_type=13&album_id=%d |"
             % album_id)
    L.append("")
    L.append("## 单条音频（按专辑在线顺序）")
    L.append("")
    L.append("| # | 标题 | 直达链接 |")
    L.append("|---:|---|---|")
    for i, (tid, title, _vis) in enumerate(tracks, 1):
        safe = (title or "(无标题)").replace("|", "\\|")
        L.append("| %d | %s | %s?t=%s |" % (i, safe, base, tid))
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 使用说明")
    L.append("")
    L.append('1. **微信里点不开 iting:// 深链**（微信屏蔽自定义 scheme）。要发给别人就发上面的'
             '**网页链接**——微信可传，页内会引导"在浏览器打开"，再点按钮唤起 App。')
    L.append("2. **必须登录音频所属账号**：私密音频（visibleCrowdType=1）只有该账号登录的"
             "喜马拉雅 App 才能播放。")
    L.append("3. **链接本身不带权限**：换别人点开只能看到跳转页，播放会失败。")
    L.append("4. 想让跳转页显示自定义名称，在链接后加 `&n=你的名称`。")
    L.append("5. **不想查 ID？用前缀写法**：把原始链接直接拼在跳转页域名后（中间加一个 `#`）——")
    L.append("   `<跳转页>/#https://www.ximalaya.com/sound/<trackId>` 或")
    L.append("   `<跳转页>/#https://www.ximalaya.com/album/<albumId>`，")
    L.append("   效果与 `?t=` / `?a=` 完全一致。`#` 必须保留：静态托管不支持路径回退，缺了会 404。")
    return "\n".join(L) + "\n"


# --- 主流程 ---------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="生成喜马拉雅专辑音频直达链接清单")
    ap.add_argument("--album-id", type=int, required=True)
    ap.add_argument("--album", required=True, help="专辑名（用于标题与 ?a=&n=）")
    ap.add_argument("--profile", required=True, help="已登录的浏览器 profile 目录")
    ap.add_argument("--base", default="https://xmly-open.app.workbuddy.host/",
                    help="跳转页地址，结尾必须带 /")
    ap.add_argument("--out", default=None)
    ap.add_argument("--verify-track", type=int, default=None,
                    help="额外核实某条 trackId 的标题/所属专辑")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.base.endswith("/"):
        args.base += "/"
    if not os.path.isdir(args.profile):
        sys.exit(f"登录态目录不存在：{args.profile}")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=args.profile, headless=True)
        page = ctx.new_page()
        page.goto("https://www.ximalaya.com/reform-upload/page/webCenter/upload",
                  timeout=60000)
        page.wait_for_timeout(2500)

        if args.verify_track:
            t, aid, vis = fetch_track_title(page, args.verify_track)
            print(f"[核实] trackId={args.verify_track} 标题={t!r} "
                  f"albumId={aid} visibleCrowdType={vis}")
            if aid != args.album_id:
                print(f"  ! 该音频属于专辑 {aid}，不是 --album-id {args.album_id}")

        print(f"[拉取] 专辑 {args.album_id} 音轨…")
        tracks = fetch_album_tracks(page, args.album_id)
        ctx.close()

    if not tracks:
        sys.exit("没有取到任何音轨，请检查 --album-id 与登录态。")

    n_private = sum(1 for t in tracks if t[2] == 1)
    print(f"[结果] 共 {len(tracks)} 条（私密 {n_private} 条）")

    md = build_markdown(args.album_id, args.album, tracks, args.base)
    out = args.out or f"./ximalaya_{args.album_id}_track_links.md"

    if args.dry_run:
        print(md[:1500])
        print("... (dry-run，未写文件)")
        return
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[写出] {os.path.abspath(out)}")

    # 顺带打印前 3 条示例
    print("\n示例链接：")
    for tid, title, _ in tracks[:3]:
        print(f"  {title}\n    {args.base}?t={tid}")


if __name__ == "__main__":
    main()
