# 版本更新说明（Changelog）

本文件记录 `ximalaya-bulk-uploader` 的所有版本变更。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

## [v1.6.0] — 2026-08-24（支持纯音频发布：无配套 .txt 也能上传）

### 新增：音频可独立发布（无需配套 .txt）
- `scan_and_pair()`：音频文件即使没有同名的 `.txt` 简介文件，也会被纳入发布列表（简介路径记为 `None`），不再被整体跳过。
- `publish_all()` / `dry_run()`：无简介的音频以**空简介**发布；`request_confirm` 与 `dry_run` 的提示文案改为"N 个音频无配套简介，将以空简介发布"。
- 适用场景：听力类音频常不带独立简介文件（如英语课文听力）。此前文件夹若无任何 `.txt`，会因 `pairs` 为空而直接"nothing to do"。
- `verify_publish()` 文案同步（"无本地音频文件"）。

### 清理
- 删除一次性探测脚本 `probe_albums.py` / `probe_album2.py` / `probe_album_id*.py`（仅用于定位专辑 ID，已并入流程）。

---

## [v1.5.0] — 2026-08-24（新增 `--order preview-first`：同章内预习先于复习发布）

### 新增：发布顺序控制 `--order`
- `uploader.py`：新增 `--order`（默认 `name`，可选 `preview-first`），并通过环境变量 `XIMALAYA_ORDER` 配置。
- `preview-first` 模式下，上传器按**章节分组**，同一章内**先发布"预习"文件、再发布"复习"文件**，章内其余按自然顺序。适用于文件同时含"预习"/"复习"两类、且希望"先预习后复习"的场景。
- 实现：新增 `_chapter_prefix()` / `_publish_sort_key()`，`scan_and_pair()` 增加 `order` 参数，`dry_run` / `publish_all` / `verify_publish` 同步生效（发布顺序与校验顺序一致）。
- 之所以需要显式选项：纯文件名自然排序时"复习"会排在"预习"前（"复" U+590D < "预" U+9884），无法靠文件名排序得到"预习在前"。

### 文档
- `README.md`：配置表新增"发布顺序"行；新增「发布顺序（预习优先）」小节；近期版本速览追加 v1.5.0。
- `.env.example`：新增 `XIMALAYA_ORDER` 说明。

---

## [v1.4.0] — 2026-08-18（新增 reorder_album.py：不删除重发，按文件名重排专辑顺序）

### 新增：专辑内声音排序脚本 `reorder_album.py`
- 通过调用喜马拉雅创作中心内部 `POST /reform-upload/manage/album/track/changeOrder` 接口，按文件名对专辑内声音重新排序。
- 无需删除任何声音，适合分多批补发后顺序错乱、又不想删了重发的场景。
- 排序规则：完整课声音（不含"复习"）按章节/讲次排在前，复习音频（含"复习"）按章节/复习编号排在后。
- 自动处理旧版完整课使用中文数字章节（第一章）、新版复习使用阿拉伯数字章节（第1章）的混排。
- 支持随机延迟（`--interval` / `--jitter`），避免触发风控。
- 运行前备份原始顺序到 `--backup`（默认 `/tmp/album_order_backup.json`），运行后重新拉取在线顺序验证是否已达标。

### 文档
- `README.md`：新增「🔄 调整专辑内声音顺序」使用说明。

---

## [v1.3.0] — 2026-08-18（上传节奏随机化 + 发布后自动校验完整性/顺序）

结合真实发布复盘与网络反馈（喜马拉雅确有请求限流 `104`、刷量风控 `110`；Playwright 社区一致建议随机间隔模拟人工），两项增强：

### 新增：上传间隔随机化（抗风控）
- `uploader.py`：两次上传等待由固定 `--interval` 改为 `interval + random(0, --interval-jitter)`（默认 `8 + 0~7s`），避免固定节奏被识别为机器流量。
- `uploader.py`：`_publish_one` 内新增随机"思考时间"——进入上传页后等待 `4~5.5s`（原固定 4s），点击「确认发布」前等待 `0.8~2.5s`，进一步打散操作时序。
- 新增 `--interval-jitter` / `XIMALAYA_INTERVAL_JITTER`（默认 7）。

### 新增：发布后自动校验（完整性 + 顺序）
- `uploader.py`：发布结束后自动调用 `verify_publish()`，登录同一浏览器档案、拦截创作中心 `album/tracks` 接口抓取真实在线声音，核对两项：
  1. **完整性**：本地每一对 audio+txt 是否都已在线（缺失清单）。
  2. **顺序**：本批声音在线顺序是否与预期章节 / 自然顺序一致。喜马拉雅声音管理页按"创建时间升序"排列，故单次按序发布应严格等于本地顺序；分多批补发造成的穿插会被判为"顺序错乱"并列出具体错位。
- 校验模式 `--verify-order`：`strict`（默认，必须等于章节顺序）/ `monotonic`（升序或降序均可）/ `off`（仅查完整性）。
- 校验失败（缺失或错乱）时进程以**退出码 2** 结束（可用 `--no-verify-fail-exit` 降级为仅报告），报告写入 `verify_report_<时间戳>.txt`。
- 需提供 `--album-id` / `XIMALAYA_ALBUM_ID`（创作中心 URL 中的数字专辑 ID）才会执行校验；未提供则跳过并提示。

### 新增：风控 / 验证码提前检测
- `uploader.py`：新增 `_blocked()`，发布前若页面出现验证码 / 安全验证 / 操作过于频繁 / 访问受限等提示，立即判定失败并提示人工介入，避免无效重试浪费时间。

---

## [v1.2.2] — 2026-08-18（修复「确认发布」按钮置灰导致静默失败）

批量补发时发现：部分条目反复发布失败，日志显示「no success signal within timeout, URL: webCenter/upload」，但页面其实已显示音频「上传成功」、专辑已选好、「确认发布」按钮也在。根因是未勾选《知识产权承诺》时，「确认发布」按钮处于**禁用态**，点击无效，页面始终停在上传页；该勾选状态在会话间不稳定，导致偶发失败。

### 修复
- `uploader.py`：`_publish_one` 在点击「确认发布」前，先通过 JS 勾选《知识产权承诺》复选框并派发 change/click 事件。
- `uploader.py`：点击「确认发布」改为「等待按钮变为 enabled → 点击 → 检测成功跳转」的**重试循环**（最多 4 次，每次最长 20s），覆盖音频服务端处理中按钮暂时禁用的情况。
- `uploader.py`：失败分支增加**页面诊断输出**（打印当时页面文本），便于定位卡住原因。

### 验证
- 用修复后的逻辑重发此前 7 条反复失败的条目，全部返回真实成功信号；再次抓取平台 `album/tracks` 接口确认 43 条复习音频 `MISSING: 0`，全部在线。

---

## [v1.2.1] — 2026-08-18（修复发布成功误判导致遗漏）

批量发布后复核发现：部分条目日志显示成功、但平台实际缺失。根因是 `_publish_one` 的成功判定依赖了上传页导航栏常驻的「内容管理」字样，导致页面仍停在上传页（URL 为 `webCenter/upload`）却被误判为发布成功；另有个别条目文件未被 webuploader 真正接收也未被发现。

### 修复
- `uploader.py`：`_publish_one` 成功判定改为严格模式——必须等待页面跳转至 `uploadSuccess` 或页面出现明确的「发布成功」提示，超时（30s）才判失败（移除「内容管理」等常驻导航词）。
- `uploader.py`：`set_files` 后增加**正向确认**——等待页面出现文件名或「上传成功」提示，确认 webuploader 真正接收了文件，否则明确判失败，杜绝静默漏发。
- `verify_album.py`（新增）：拦截创作中心声音管理页的 `album/tracks` 接口响应并翻页，抓取专辑全部真实声音标题，用于发布后核对是否遗漏。

### 验证
- 清理误记录的 manifest 后重发 18 条缺失条目，均返回真实成功信号；再次抓取平台标题确认 43 条齐全。

---

## [v1.2.0] — 2026-08-18（适配喜马拉雅上传页改版）

喜马拉雅上传页 `reform-upload/page/webCenter/upload` 改为 landing 页，直接 `goto` 不再渲染上传表单，导致旧版文件选择（`set_input_files`）与专辑预检（直接点专辑按钮）全部失效。

### 修复
- `uploader.py`：`_publish_one` 的文件选择改为先点击 webuploader「上传音频」入口（`div.webuploader-pick`），再捕获原生文件对话框（`page.expect_file_chooser`）填入音频，从而进入真正的上传表单。
- `uploader.py`：`check_album_exists` 预检改为先用一个临时静音 wav 钥匙文件（`_make_key_file` / `_enter_form`）进入表单，再展开专辑列表核对；否则 landing 页无专辑按钮会误报「专辑不存在」。
- 新增依赖：`wave` / `tempfile`（均为标准库，无需额外安装）。

### 验证
- 单条冒烟测试通过（发布成功返回 `sound/manage` 链接）；随后批量发布 43 条（含嵌套章节结构拍平）到「七下数学」专辑。
- ⚠️ 后续复核（见 v1.2.1）发现本次批量中 18 条因成功判定误判而实际未发布，已在 v1.2.1 修复并补全。

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
