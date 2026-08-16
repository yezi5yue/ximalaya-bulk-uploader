# ximalaya-bulk-uploader

把一批音频文件连同同名的 `.txt` 描述文本，批量上传到[喜马拉雅](https://www.ximalaya.com)创作中心，归入指定专辑，并设置可见范围。脚本不绑定任何特定内容，适用于播客、课程、有声书、录音等任意音频。

> Batch-upload audio files (with a same-named text description) to the Ximalaya Creator Center — fully generic, no personal data baked in. 中文说明见上，English summary at the bottom of this file.

---

## ✨ 功能特性

- **通用**：适用于任意音频内容，无任何硬编码。
- **配对上传**：对每个 `NAME.ext` 音频，自动寻找同名 `NAME.txt` 作为声音简介。
- **保留换行**：简介通过富文本编辑器写入，把 `\n` 转换为 `<br>`，段落不丢。
- **自然排序**：按文件名升序发布，正确识别 `02 < 10`、`第一章 < 第二章 < 第三章`（支持中文数字）。
- **可配置**：文件夹、专辑、可见范围、标题前缀、浏览器配置目录，均可用命令行参数或 `.env` 文件设置。
- **默认安全**：发布前支持 dry-run 预览与交互确认；默认可见性为**私密**。
- **一次登录**：扫码一次，登录态持久化保存，后续无需再扫。
- **专辑预检**：批量发布前先校验目标专辑是否存在，不存在立即退出并提示先去创作中心建好。
- **幂等续传**：维护 `publish_manifest.jsonl` 发布清单，已发布的标题自动跳过，中断后重跑不会重复；每次发布生成 `published_*.txt` 结果汇总。
- **实时日志**：标准输出逐行刷新，即使 `> log 2>&1` 重定向也能看到实时进度。

---

## 📌 版本更新说明（Changelog）

### v1.1.0 — 2026-08-16（实战加固版）

基于多批次批量上传实战踩坑，修复并增强（详见 `UPDATE_SUGGESTIONS.md`）：

- **P0 阻断性修复**
  - `login.py`：二维码改为从 `div.qrcode` 背景实时读取 base64 图片（旧逻辑抓到了网站 logo）。
  - `login.py`：登录成功判定改用 cookie（token/uid/session 等）为主判据，页面文本为辅，避免"手机提示成功但会话未写入"的漏判。
  - `uploader.py`：新增 `--headless` 参数兼容（旧版会因该参数直接 `unrecognized arguments` 报错；现在 headless 已是默认行为）。
- **P1 健壮性与可观测性**
  - `uploader.py`：全局 `print` 强制 `flush=True`，重定向到文件也能看到实时进度（P1-1）。
  - `uploader.py`：发布前 `check_album_exists` 预检专辑，不存在立即报错退出，不再逐条超时浪费数分钟（P1-2）。
  - `uploader.py`：引入 `publish_manifest.jsonl` 发布清单实现幂等续传，重跑自动跳过已发布标题，不再依赖手动数数 `--start-from`（P1-3）。
- **P2 体验与可维护性**
  - dry-run 与发布确认明确打印可见性中文（私密/公开/仅粉丝可见）（P2-1）。
  - 发布完成生成 `published_YYYYMMDD_HHMMSS.txt` 结果汇总文件（P2-3）。
  - 新增排障辅助脚本 `verify_login.py`（检查登录态）、`probe_album.py`（检查专辑是否存在）（P1-2 配套）。
  - 固化运行方式与环境约束到 README（P2-2）。
- **文档**：README / `.gitignore` / `.env.example` 同步更新；运行时产物（manifest、summary）已加入 `.gitignore`。

### v1.0.0 — 初始版本

- 通用批量上传：音频 + 同名 txt 简介、自然排序、富文本换行保留、私密默认、dry-run、交互确认、扫码登录。

---

## ⚠️ 免责声明

这是一个**非官方**工具，通过 Playwright 驱动喜马拉雅网页界面完成上传，**并非**官方 API。请自行承担使用风险，遵守喜马拉雅服务条款，并保持合理的上传间隔，避免触发限流。

---

## 📋 环境要求

- Python 3.8+
- [Playwright](https://playwright.dev/) + Chromium
- 一个喜马拉雅账号

```bash
pip install playwright
playwright install chromium
```

---

## 🚀 快速开始

### 1. 一次性登录（创建持久化登录态）

```bash
python login.py                # 登录态保存到 ./xmly_profile
# 或指定自定义配置目录：
python login.py --profile /path/to/profile
```

会显示二维码（或保存为 `_login_qr.png`）。用喜马拉雅 App 扫码，出现 `LOGIN_OK` 后以后都无需再扫。

> **二维码修复（2026-08-16）**：真实登录二维码从 `div.qrcode` 的实时 base64 图片读取——旧代码误抓了网站 logo。若 App 提示"已失效"，重新运行 `login.py` 拉取最新二维码即可。

### 2. 准备文件

把音频文件和同名 `.txt` 放在同一个文件夹：

```
my_audio/
├── Episode-01.mp3
├── Episode-01.txt      ← Episode-01 的简介
├── Episode-02.mp3
├── Episode-02.txt
└── ...
```

只有配对的 `音频 + txt` 会被发布；没有配对的 `.txt` 或音频会被提示并跳过。

### 3. 试运行（不上传）

```bash
python uploader.py --folder my_audio --album "我的专辑"
# 或通过 .env（见 .env.example）：python uploader.py
```

会打印配对结果、生成的标题、简介长度与发布顺序。**不会真正上传。**

### 4. 发布

```bash
python uploader.py --folder my_audio --album "我的专辑" --yes
```

`--yes` 跳过交互确认；不加则会先打印计划，等你输入 `yes` 才发布。

---

## ⚙️ 配置

优先级（高者胜）：**命令行参数 > 环境变量 / `.env` > 默认值**。

| 用途             | 命令行参数          | 环境变量                   | 默认值                                   |
|------------------|---------------------|----------------------------|------------------------------------------|
| 音频文件夹       | `-f/--folder`       | `XIMALAYA_FOLDER`          | *(必填)*                                 |
| 专辑名           | `-a/--album`        | `XIMALAYA_ALBUM`           | *(必填)*                                 |
| 配置目录         | `-p/--profile`      | `XIMALAYA_PROFILE`         | `./xmly_profile`                         |
| 可见范围         | `--visibility`      | `XIMALAYA_VISIBILITY`      | `private`                                |
| 无头浏览器       | `--no-headless` / `--headless` | `XIMALAYA_HEADLESS` | `true`（无头；`--headless` 仅为兼容接受） |
| 跳过清单续传     | `--no-resume`       | —                          | 关闭（默认开启续传）                      |
| 上传间隔（秒）   | `--interval`        | `XIMALAYA_INTERVAL`        | `8`                                      |
| 上传超时（秒）   | `--timeout`         | `XIMALAYA_UPLOAD_TIMEOUT`  | `300`                                    |
| 发布后等待（秒） | `--after`           | `XIMALAYA_AFTER_PUBLISH`   | `5`                                      |
| 标题前缀去除     | `--title-prefix`    | `XIMALAYA_TITLE_PREFIX`    | *(空)*                                   |

把 `.env.example` 复制为 `.env` 即可在多次运行间保留配置。

### 可见范围

`--visibility` 可选 `private`（私密，默认）、`public`（公开）或 `fans`（仅粉丝可见）。

### 标题前缀

如果你的文件名为 `Pod-01.mp3`，但希望发布标题只保留 `01`，设置 `--title-prefix "Pod-"`。留空则保留完整文件名。

### 续传 / 跳过

上传器在 `publish_manifest.jsonl` 中记录每次发布的声音。下一次运行会**自动跳过清单里已有的标题**，所以中断后直接重跑同一条命令即可，不会产生重复：

```bash
python uploader.py --folder my_audio --album "我的专辑" --yes   # 重跑安全
```

两个显式覆盖项：

- `--start-from N` — 从第 N 个配对项（从 1 计数）开始发布，便于手动跳过前几个。
- `--no-resume` — 完全忽略清单，重新发布全部。

每次运行结束会生成 `published_YYYYMMDD_HHMMSS.txt` 结果汇总，含每项的标题 / 链接 / 时间戳。

---

## 🛠 修复已发布声音的简介

如果上传时简介没写对，可重新写入：

```bash
python fix_description.py --folder my_audio --album "我的专辑"
```

它按标题在声音列表里定位每个声音，打开编辑页，写入简介并保存。

---

## 🔧 辅助脚本

- **`verify_login.py`** — 快速检查持久化配置是否仍处于登录态（退出码 0/1）。大批量发布前先跑一下。
  ```bash
  python verify_login.py
  ```
- **`probe_album.py`** — 发布前检查账号里是否存在目标专辑（退出码 0/1）。提前发现名称拼写错误 / 尚未创建，避免逐条失败。
  ```bash
  python probe_album.py "我的专辑"
  ```

---

## 💡 运行注意（重要）

- **重定向时务必用无缓冲输出**以便看到实时进度：`python -u uploader.py ... > log 2>&1`（脚本内部现在也已强制 flush）。
- **登录必须在运行上传器的那台机器上完成**——二维码是用手机喜马拉雅 App 对着本地浏览器配置扫的，沙箱 / 远程机器无法替你登录。请在本地先运行一次 `login.py`。
- **专辑预检**在每次发布开始时自动执行；若专辑缺失，会给出清晰的"请先创建"提示，而不是沉默地逐条失败。

---

## 🐛 故障排查

- **`KindEditor instance not found`** — 上传页布局可能已变化，或文件尚未加载完编辑器。重跑该项。
- **登录失效** — 先 `python verify_login.py` 确认，再 `python login.py` 刷新配置。
- **二维码提示"已失效" / 扫到的不是二维码** — 旧代码误抓了网站 logo。重跑 `login.py`，现在改为读取 `div.qrcode` 实时 base64 图片。
- **`unrecognized arguments: --headless`** — 已修复；现在接受 `--headless`（它本就是默认）。想显示浏览器窗口用 `--no-headless`。
- **找不到专辑** — 预检会以清晰提示中止。请在创作中心 → 专辑里创建，或修正 `--album` 拼写。发布前可用 `probe_album.py` 验证名称。
- **重启后重复上传** — 清单会自动跳过已发布标题；只有确实想重发时才用 `--no-resume`。
- **简介显示成一整块** — 说明 `\n` 没被转换；本版本写入前会把换行转成 `<br>`。若遇到旧行为，用 `fix_description.py` 修复。

---

## 📁 项目结构

```
ximalaya-bulk-uploader/
├── uploader.py          # 主批量上传器（专辑预检 + 清单续传）
├── login.py             # 一次性扫码登录 -> 持久化配置（实时二维码修复）
├── verify_login.py      # 检查配置是否仍处于登录态
├── probe_album.py       # 检查目标专辑是否存在
├── fix_description.py   # 重新写入已发布声音的简介
├── .env.example         # 所有可配置变量
├── requirements.txt
├── LICENSE              # MIT
└── README.md
```

---

## 📄 开源协议

MIT — 见 [LICENSE](LICENSE)。

---

## English

`ximalaya-bulk-uploader` is an unofficial, generic tool that drives the
Ximalaya web UI with Playwright to batch-upload audio files together with a
same-named `.txt` description into a chosen album, with configurable
visibility. Highlights:

- Pairs `NAME.ext` audio with `NAME.txt` as the sound description; preserves
  line breaks (`\n` → `<br>`); natural file-name ordering (Arabic & Chinese
  numerals).
- Safe by default: dry-run + confirmation; private visibility by default.
- Login once via QR (persisted profile). `login.py` now reads the live
  `div.qrcode` base64 image and detects login via session cookies.
- Pre-checks the album exists before a batch; `publish_manifest.jsonl` gives
  idempotent resume (skips already-published titles) and `published_*.txt`
  summarizes each run. `--headless` is now accepted; stdout is flushed live.
- Helper scripts `verify_login.py` and `probe_album.py`.
- MIT licensed. See the Chinese sections above for full usage.
