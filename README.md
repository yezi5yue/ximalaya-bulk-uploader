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
| Headless browser   | `--no-headless`     | `XIMALAYA_HEADLESS`        | `true`                 |
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

`--start-from N` republishes starting from the N-th matched item (1-based),
handy when the first few were already published manually.

## 🛠 Fix already-published descriptions

If a description was not written correctly during upload, re-apply it:

```bash
python fix_description.py --folder my_audio --album "My Album"
```

It locates each sound by title in your sound list, opens the edit page, sets
the description and saves.

## 🐛 Troubleshooting

- **`KindEditor instance not found`** — the upload page layout may have
  changed, or the file had not finished loading the editor. Re-run the item.
- **Login expired** — re-run `python login.py` to refresh the profile.
- **QR code not captured** — open the browser window (omit `--headless` in
  `login.py`) and scan the on-screen code.
- **Description shows as one block** — that means `\n` was not converted; this
  version converts newlines to `<br>` before writing. Use `fix_description.py`
  if you hit the old behaviour.

## 📁 Project structure

```
ximalaya-bulk-uploader/
├── uploader.py          # main batch uploader
├── login.py             # one-time QR login -> persisted profile
├── fix_description.py   # re-apply descriptions to published sounds
├── .env.example         # all configurable variables
├── requirements.txt
├── LICENSE              # MIT
└── README.md
```

## 📄 License

MIT — see [LICENSE](LICENSE).
