# ximalaya-bulk-uploader

> Batch-upload audio files (with a same-named text description) to the
> [Ximalaya](https://www.ximalaya.com) Creator Center — fully generic, no
> personal data baked in.

**中文**：把一批音频文件连同同名的 `.txt` 描述文本，批量上传到喜马拉雅创作中心，归入指定专辑，并设置可见范围。脚本不绑定任何特定内容，适用于播客、课程、有声书、录音等任意音频。

---

## ✨ Features

- **Generic** — works with any audio content; nothing is hard-coded.
- **Pairing** — for each `NAME.ext` audio it finds a companion `NAME.txt` and
  uses that text as the sound description.
- **Line breaks preserved** — the description is written through the rich-text
  editor with `\n` converted to `<br>`, so your paragraphs survive.
- **Natural ordering** — publishes in ascending order of file name, correctly
  handling `02 < 10` and `第一章 < 第二章 < 第三章`.
- **Configurable** — folder, album, visibility, title prefix and the browser
  profile are all set via CLI args or a `.env` file.
- **Safe by default** — a dry-run mode and an interactive confirmation step
  before anything is published; default visibility is **private**.
- **One-time login** — scan the QR code once, the session is persisted.
- **Album pre-check** — before a batch, verifies the target album actually
  exists in your account and aborts early (with a clear message) if not.
- **Idempotent resume** — keeps a `publish_manifest.jsonl` journal; already
  published titles are skipped automatically, so an interrupted batch can be
  re-run without creating duplicates. A `published_*.txt` summary is written.
- **Real-time logs** — stdout is flushed line-by-line, so `> log 2>&1`
  redirection still shows live progress.

## ⚠️ Disclaimer

This is an **unofficial** tool that drives the Ximalaya web UI with Playwright.
It is **not** an official API. Use it at your own risk, respect Ximalaya's
terms of service, and keep the per-upload interval reasonable to avoid
triggering rate limits.

## 📋 Requirements

- Python 3.8+
- [Playwright](https://playwright.dev/) + Chromium
- A Ximalaya account

```bash
pip install playwright
playwright install chromium
```

## 🚀 Quick start

### 1. One-time login (creates a persisted profile)

```bash
python login.py                # saves the session to ./xmly_profile
# or specify a custom profile directory:
python login.py --profile /path/to/profile
```

A QR code is shown (or saved to `_login_qr.png`). Scan it with the Ximalaya
app. After `LOGIN_OK` you never need to scan again.

> **QR fix (2026-08-16):** the real login QR is read from `div.qrcode`'s
> live base64 image — the old code grabbed the site logo. If the app says the
> code is "已失效", just re-run `login.py` to fetch a fresh one.

### 2. Prepare your files

Put audio files and their same-named `.txt` in one folder:

```
my_audio/
├── Episode-01.mp3
├── Episode-01.txt      ← description for Episode-01
├── Episode-02.mp3
├── Episode-02.txt
└── ...
```

Only matched `audio + txt` pairs are published. A `.txt` without an audio (or
vice-versa) is reported and skipped.

### 3. Dry run (no upload)

```bash
python uploader.py --folder my_audio --album "My Album"
# or via .env (see .env.example):  python uploader.py
```

This prints the matched pairs, the computed titles, description lengths and the
publish order. **Nothing is uploaded.**

### 4. Publish

```bash
python uploader.py --folder my_audio --album "My Album" --yes
```

`--yes` skips the interactive confirmation. Without it, the script prints the
plan and asks you to type `yes` before publishing.

## ⚙️ Configuration

Precedence (highest wins): **CLI argument > environment variable / `.env` > default**.

| Purpose            | CLI flag            | Env var                    | Default                |
|--------------------|---------------------|----------------------------|------------------------|
| Audio folder       | `-f/--folder`       | `XIMALAYA_FOLDER`          | *(required)*           |
| Album name         | `-a/--album`        | `XIMALAYA_ALBUM`           | *(required)*           |
| Profile directory  | `-p/--profile`      | `XIMALAYA_PROFILE`         | `./xmly_profile`       |
| Visibility         | `--visibility`      | `XIMALAYA_VISIBILITY`      | `private`              |
| Headless browser   | `--no-headless` / `--headless` | `XIMALAYA_HEADLESS`   | `true` (headless; `--headless` accepted for compatibility) |
| Skip manifest resume | `--no-resume`    | —                          | off (resume is on)     |
| Interval (sec)     | `--interval`        | `XIMALAYA_INTERVAL`        | `8`                    |
| Upload timeout     | `--timeout`         | `XIMALAYA_UPLOAD_TIMEOUT`  | `300`                  |
| After-publish wait | `--after`           | `XIMALAYA_AFTER_PUBLISH`   | `5`                    |
| Title prefix strip | `--title-prefix`    | `XIMALAYA_TITLE_PREFIX`    | *(empty)*              |

Copy `.env.example` to `.env` to keep your settings between runs.

### Visibility

`--visibility` accepts `private` (私密, default), `public` (公开) or
`fans` (仅粉丝可见).

### Title prefix

If your files are named like `Pod-01.mp3` but you want the published title to
be just `01`, set `--title-prefix "Pod-"`. Leave it empty to keep full names.

### Resume / skip

The uploader keeps a journal at `publish_manifest.jsonl` of every sound it
publishes. On the next run it **automatically skips any title already in that
journal**, so you can just re-run the same command after an interruption and
nothing gets duplicated:

```bash
python uploader.py --folder my_audio --album "My Album" --yes   # re-run is safe
```

There are two explicit overrides:

- `--start-from N` — republish starting from the N-th matched item (1-based).
  Handy when you want to skip the first few manually.
- `--no-resume` — ignore the manifest entirely and (re)publish everything.

After each run a `published_YYYYMMDD_HHMMSS.txt` summary is written with the
title/url/timestamp of every item.

## 🛠 Fix already-published descriptions

If a description was not written correctly during upload, re-apply it:

```bash
python fix_description.py --folder my_audio --album "My Album"
```

It locates each sound by title in your sound list, opens the edit page, sets
the description and saves.

## 🔧 Helper scripts

- **`verify_login.py`** — quickly check whether the persisted profile is still
  logged in (exits 0/1). Run it before a big batch.
  ```bash
  python verify_login.py
  ```
- **`probe_album.py`** — check whether a target album exists in your account
  before publishing (exits 0/1). Catches name typos / not-yet-created albums
  early instead of failing per-item.
  ```bash
  python probe_album.py "My Album"
  ```

## 💡 Runtime notes (important)

- **Use unbuffered output** when redirecting to a file so you see live progress:
  `python -u uploader.py ... > log 2>&1` (the script also flushes internally now).
- **Login must happen on the machine that runs the uploader** — the QR is
  scanned with the Ximalaya phone app against the local browser profile, so a
  sandbox / remote box cannot log in for you. Run `login.py` locally once.
- **Album pre-check** runs automatically at the start of every publish; if the
  album is missing you'll get a clear "create it first" message instead of
  silent per-item failures.

## 🐛 Troubleshooting

- **`KindEditor instance not found`** — the upload page layout may have
  changed, or the file had not finished loading the editor. Re-run the item.
- **Login expired** — re-run `python verify_login.py` to confirm, then
  `python login.py` to refresh the profile.
- **QR shows "已失效" / not a QR** — the old code grabbed the site logo.
  Re-run `login.py`; it now reads the live `div.qrcode` base64 image.
- **`unrecognized arguments: --headless`** — fixed; `--headless` is now
  accepted (it is the default anyway). Use `--no-headless` to show the window.
- **Album not found** — the pre-check aborts with a clear message. Create the
  album in 创作中心 → 专辑, or fix the `--album` spelling. `probe_album.py`
  can verify the name beforehand.
- **Duplicate uploads after a restart** — the manifest auto-skips already
  published titles; use `--no-resume` only if you really want to re-publish.
- **Description shows as one block** — that means `\n` was not converted; this
  version converts newlines to `<br>` before writing. Use `fix_description.py`
  if you hit the old behaviour.

## 📁 Project structure

```
ximalaya-bulk-uploader/
├── uploader.py          # main batch uploader (album pre-check + manifest resume)
├── login.py             # one-time QR login -> persisted profile (live QR fix)
├── verify_login.py      # check whether the profile is still logged in
├── probe_album.py       # check whether a target album exists
├── fix_description.py   # re-apply descriptions to published sounds
├── .env.example         # all configurable variables
├── requirements.txt
├── LICENSE              # MIT
└── README.md
```

## 📄 License

MIT — see [LICENSE](LICENSE).
