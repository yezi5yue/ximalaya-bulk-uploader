# 版本更新说明（Changelog）

本文件记录 `ximalaya-bulk-uploader` 的所有版本变更。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

## [v1.1.0] — 2026-08-16（实战加固版）

基于多批次批量上传实战踩坑，修复并增强（详见 `UPDATE_SUGGESTIONS.md`）。

### 修复（Bug Fixes / P0 阻断性）
- `login.py`：二维码改为从 `div.qrcode` 背景实时读取 base64 图片（旧逻辑误抓到了网站 logo，扫码无效）。
- `login.py`：登录成功判定改用 cookie（token/uid/session 等）为主判据、页面文本为辅，避免"手机提示成功但会话未写入"的漏判。
- `uploader.py`：新增 `--headless` 参数兼容（旧版会因该参数直接 `unrecognized arguments` 报错；现在 headless 已是默认行为）。

### 增强（Enhancements / P1 健壮性与可观测性）
- `uploader.py`：全局 `print` 强制 `flush=True`，重定向到文件也能看到实时进度（P1-1）。
- `uploader.py`：发布前 `check_album_exists` 预检专辑，不存在立即报错退出，不再逐条超时浪费数分钟（P1-2）。
- `uploader.py`：引入 `publish_manifest.jsonl` 发布清单实现幂等续传，重跑自动跳过已发布标题，不再依赖手动数数 `--start-from`（P1-3）。
- 新增排障辅助脚本 `verify_login.py`（检查登录态）、`probe_album.py`（检查专辑是否存在）（P1-2 配套）。

### 体验与可维护性（P2）
- dry-run 与发布确认明确打印可见性中文（私密 / 公开 / 仅粉丝可见）（P2-1）。
- 发布完成生成 `published_YYYYMMDD_HHMMSS.txt` 结果汇总文件（P2-3）。
- 固化运行方式与环境约束到 README（P2-2）。
- 文档：README / `.gitignore` / `.env.example` 同步更新；运行时产物（manifest、summary）已加入 `.gitignore`。

---

## [v1.0.0] — 初始版本

通用批量上传核心能力：
- 音频 + 同名 `.txt` 简介配对上传。
- 自然排序（支持阿拉伯数字与中文数字）。
- 富文本编辑器保留简介换行（`\n` → `<br>`）。
- 默认私密、dry-run 预览、交互确认。
- 扫码一次性登录，登录态持久化。

---

[v1.1.0]: https://github.com/yezi5yue/ximalaya-bulk-uploader/releases/tag/v1.1.0
[v1.0.0]: https://github.com/yezi5yue/ximalaya-bulk-uploader/releases/tag/v1.0.0
