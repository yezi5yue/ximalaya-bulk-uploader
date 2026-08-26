# 版本更新说明（Changelog）

本文件记录 `ximalaya-bulk-uploader` 的所有版本变更。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/）。

---

## [v1.7.2] — 2026-08-26（修复：专辑选择改为精确标题匹配 + 发布后校验真实专辑 ID）

### 问题复盘
- 上传「作文」时，34 篇被错误地发布到了 **英语作文（albumId 128168225）**，而非目标 **作文（albumId 121805384）**。
- 根因：旧 `_select_album()` 用 `div.scroll-item-content-252FXLKk:has-text('<专辑名>')` 做**子串匹配**，`:has-text('作文')` 命中了「英语作文」，且选择器 `.first` 取到了错误专辑；同时专辑选择器是**分页**的（每页 ~10 个），目标专辑可能藏在后面的分页里。
- 此外，进程在约 17 分钟处被外部环境回收（日志干净停在中间、无报错），导致只传了 34/50。

### 修复
- `uploader.py` → `_select_album()` 重写为**精确标题匹配**：
  - 用 `span.album-title-text-4EH5AG-r:text-is('<专辑名>')` 取代子串 `has-text`，使「作文」与「英语作文」严格区分；
  - 循环**滚动 / 点击"加载更多"**直到精确条目出现再点击；若始终找不到则抛错中止（不再静默选错专辑）。
- `uploader.py` → `publish_all()` 新增**首条专辑 ID 安全校验**：解析每条发布成功 URL 里的 `/manage/<albumId>`，若与 `--album-id` 不符，立即 `sys.exit(1)` 中止整批，杜绝批量传错专辑。
- 新增 `move_and_cleanup.py`：把误传的音频**改所属专辑**（调 `anchorTrack/update` 改 `albumId`）挪到正确专辑，并删除重复音频（`anchorTrack/delete`），无需删除原件。
- 新增 `verify_zuowen.py`：核对目标专辑里我们上传的标题是否齐全、有无重复。

### 影响
- 此后按专辑名上传会精准命中，且即便选择器异常，首条校验也会在传错第一条后立即熔断。
- 配套工具 `move_and_cleanup.py` / `verify_zuowen.py` 可复用处理"传错专辑 / 重复音频"的善后。

---

## [v1.7.1] — 2026-08-25（修复：权限默认应为私密，杜绝静默发布为公开）

### 问题复盘
- 四个语文专辑（八上/八下/九上/九下语文）批量上传后全部为**公开**，而非预期的私密。
- 根因不在上传器逻辑，而在批量脚本 `run_chinese_uploads.sh` 显式写死了 `--visibility public`，覆盖了上传器默认的 `private`。
- 上传表单「权限设置」栏默认选中**公开（value=2）**；只有显式、且被校验过的点击「私密（value=1）」才会变为私密。

### 修复
- `run_chinese_uploads.sh`：`--visibility public` 改为 `--visibility private`（默认即私密，显式写出以防误改）。
- `uploader.py`：`_set_privacy()` 加固——
  1. 将选择器**限定在「权限设置」表单内**，避免误点未来新增的同 value（如 `1`）的其它单选框；
  2. 点击后**校验**目标单选框是否真的带上 antd `ant-radio-checked` 类；若未生效则返回 `ok:false`，由 `_publish_one` 判定为失败并中止本条发布（宁可发不出去，也绝不静默发成公开）。

### 影响
- 此后任何未显式传 `--visibility public` 的发布都会默认且可靠地设为私密。
- 已通过实测：上传页 `_set_privacy('1')` 后「私密」单选框确为 checked；`_set_privacy('2')` 可正常切回公开。

---

## [v1.7.0] — 2026-08-25（新增 `--order chapter-first`：按章节顺序发布，无章节的音频排最后）

### 新增：章节优先发布顺序
- `uploader.py`：`--order` 新增可选值 `chapter-first`。
- `chapter-first` 模式下，上传器按文件名中的章节号（如 `第一单元`、`第二单元`）升序发布；不带章节标记的音频排在最后，章内/无章节组内再按自然顺序排序。
- 实现：新增 `_CHAPTER_RE` 与 `_extract_chapter()`，`_publish_sort_key()` 返回 `(chapter_number, natural_key)`，`dry_run` / `publish_all` / `verify_publish` 同步生效。
- 适用场景：语文、英语等按"单元/章"组织的课文音频，需要"从第一章开始按顺序上传"且散篇排在末尾。

### 文档
- `README.md`：配置表与 CLI 说明同步新增 `chapter-first`。
- `.env.example`：`XIMALAYA_ORDER` 说明追加 `chapter-first`。

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
