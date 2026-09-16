# 喜马拉雅深链跳转页 —— 自托管指南

页面本体只有 `index.html`（约 5.7 KB），**零外部依赖**：没有 CDN、没有字体、没有 JS 库、没有后端、不请求任何接口。所有逻辑都在一个内联 `<script>` 里，只用浏览器原生 API（`URLSearchParams`、`location.href`）。

这意味着自托管的门槛极低 —— 任何能返回这个静态文件的 HTTP 服务都行。

---

## 一、页面怎么用

```
https://你的域名/?t=<音频ID>&n=<显示名称>     打开单条音频
https://你的域名/?a=<专辑ID>&n=<显示名称>     打开专辑
```

`n` 可省略。实际例子：

```
?t=1015366669&n=风景这边独好
?a=121805384&n=作文
```

手机浏览器打开后，页面自动尝试唤起喜马拉雅 App；失败则显示橙色按钮兜底 + 原因提示。

### 三条分流逻辑

| 环境 | 行为 |
|---|---|
| 手机 + 已装 App | 自动 `location.href = iting://...` 唤起；用 `visibilitychange`/`pagehide`/`blur` 判断是否真的跳走了 |
| 微信 / QQ 内置浏览器 | 不自动跳（屏蔽自定义 scheme），提示「右上角 →「在浏览器打开」」 |
| 桌面浏览器 | 明确提示「请在手机上打开」，不做无效跳转 |

---

## 二、三种托管路线与依赖

### 路线 A：复用现有 VPS + Cloudflare Tunnel（推荐，最稳）

你已有：美国 VPS `192.255.152.50`（Debian 13）+ 已装 nginx + 已在跑的 `cloudflared-subscription` tunnel（`sub.wucang.com` 就是它）。

| 项目 | 依赖 |
|---|---|
| VPS 软件 | nginx（已装）、cloudflared（已装）—— **无需新装任何东西** |
| 本机软件 | `ssh`、`scp`（macOS 自带） |
| 证书 | **不需要 certbot** —— HTTPS 由 Cloudflare 边缘证书提供 |
| DNS | **不需要手动加记录** —— 在面板加 Public Hostname 时自动创建 |
| 开放端口 | **不需要** —— nginx 只监听 `127.0.0.1`，由 tunnel 内网转发 |
| 费用 | 0（已有资源） |

一键脚本：

```bash
cd /Users/yezi/WorkBuddy/2026-08-11-22-09-49/ximalaya-bulk-uploader/app-open/selfhost
./deploy.sh            # 部署/更新
./deploy.sh --check    # 只看状态，不上传（只读）
./deploy.sh --rollback # 卸载
```

脚本做四件事：建目录 → 传 `index.html` → 写一份**新增的** nginx conf（不动现有的 `default.conf` / `subscribe.conf`）→ `nginx -t` 校验通过后 `reload`。校验失败会自动回滚配置文件、不重载，现有服务不受影响。

**唯一需要手动的一步**：Cloudflare 面板加 Public Hostname（因为你的 tunnel 是 token 模式，ingress 规则只存在 Cloudflare 云端，本地没有配置文件可改）：

```
https://one.dash.cloudflare.com/
→ Networks → Tunnels →（你的 subscription tunnel）
→ Public Hostname → Add a public hostname
   Subdomain : open
   Domain    : wucang.com
   Type      : HTTP
   URL       : 127.0.0.1:9082
→ Save
```

保存后立即生效，得到 `https://open.wucang.com/`。

---

### 路线 B：Cloudflare Pages（不碰服务器）

| 项目 | 依赖 |
|---|---|
| 本机软件 | Node.js + `wrangler`，或一个 GitHub 仓库 |
| DNS / 证书 / 端口 | 全自动，无需配置 |
| 费用 | 0 |

```bash
# 方式一：直接用 wrangler 上传（无需 Git）
cd /Users/yezi/WorkBuddy/2026-08-11-22-09-49/ximalaya-bulk-uploader/app-open
npx wrangler pages deploy . --project-name=xmly-open
# 首次会要求浏览器授权登录 Cloudflare

# 方式二：连 GitHub 仓库，推送即部署
# Cloudflare Dashboard → Workers & Pages → Create → Pages → 连仓库
# Build output directory 填 app-open
```

优点：零运维、全球 CDN。缺点：多一层 Cloudflare 账号授权，且你的 tunnel 已经能干同样的事。

---

### 路线 C：GitHub Pages（零服务器，但国内访问不稳）

| 项目 | 依赖 |
|---|---|
| 软件 | 仅 `git` |
| 配置 | 仓库 Settings → Pages → Source 选分支 + 目录 |

因为仓库是公开的，把 `app-open/` 设为 Pages 源目录即可得到 `https://yezi5yue.github.io/ximalaya-bulk-uploader/`。

**但不推荐**：GitHub Pages 在国内访问时快时慢，而这个链接是要发到手机上打开的，稳定性优先。

---

## 三、自托管的必备知识（踩过的坑）

1. **SSH 前必须清代理环境变量。** 你本机跑着 TUN 代理，不清会 hang 住：
   ```bash
   unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY
   ```
   脚本里已经内置这一步。

2. **VPS 的 443 端口已被 xray 占用**（`*:443`），nginx 不能直接监听 443。所以：
   - 走 tunnel（路线 A）→ 完全不涉及 443，最省事；
   - 若坚持 nginx 直接对外，只能走 80，且必须做证书才能用 HTTPS —— 不划算。

3. **token 模式的 tunnel 没有本地配置文件。** `ExecStart=/usr/bin/cloudflared tunnel --no-autoupdate run --token ${TUNNEL_TOKEN}` —— 想改 ingress 只能去 Cloudflare 面板，别去翻 `/etc/cloudflared/`（那里只有 `subscription.env`）。

4. **`iting://` 在微信里点不开**（微信屏蔽自定义 scheme）。所以要发给孩子时：
   - 优先发**网页链接** `https://open.wucang.com/?t=xxx`（微信可传，页内会引导用浏览器打开）；
   - 或者把 `iting://...` 放进「备忘录 / 提醒事项 / 短信」里点。

5. **链接本身不带权限。** 能否播放只取决于打开者登录的喜马拉雅账号。孩子设备必须登录**音频所属账号**才能听到私密内容。

6. **页面不需要改就能换内容。** 所有目标都由 URL 参数决定，托管的是同一份文件 —— 以后新增音频，直接拼新链接即可，不用重新部署。

---

## 四、更新页面

改完 `index.html` 后：

```bash
# 路线 A
cd .../app-open/selfhost && ./deploy.sh

# 路线 B
cd .../app-open && npx wrangler pages deploy . --project-name=xmly-open
```

nginx 配置里已加 `Cache-Control: no-store`，所以更新后手机刷新即可看到新版，不用清缓存。
