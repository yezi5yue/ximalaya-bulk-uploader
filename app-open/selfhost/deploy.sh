#!/usr/bin/env bash
# 把 app-open/index.html 自托管到自己的 VPS，并复用已有的 Cloudflare Tunnel 对外发布。
#
# 依赖（VPS 侧）：nginx（已装）、cloudflared tunnel（已装，token 模式）
# 依赖（本机侧）：ssh、scp  —— 无 Node / 无 Python / 无需 npm 包
#
# 用法：
#   ./deploy.sh              # 部署/更新
#   ./deploy.sh --check      # 只检查远端状态，不上传
#   ./deploy.sh --rollback   # 移除 nginx 配置与站点目录
#
# 可覆盖的变量：
#   VPS_HOST / SSH_KEY / LISTEN_PORT / DOMAIN / SUB

set -euo pipefail

VPS_HOST="${VPS_HOST:-192.255.152.50}"
SSH_KEY="${SSH_KEY:-$HOME/Downloads/id_ed25519_dallas}"
DOMAIN="${DOMAIN:-wucang.com}"
SUB="${SUB:-open}"                       # 最终域名 = $SUB.$DOMAIN
LISTEN_PORT="${LISTEN_PORT:-9082}"       # nginx 只监听回环，由 tunnel 转发
REMOTE_DIR="${REMOTE_DIR:-/var/www/xmly-open}"
CONF_NAME="xmly-open.conf"
CONF_PATH="/etc/nginx/conf.d/${CONF_NAME}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_HTML="$(cd "$HERE/.." && pwd)/index.html"

# SSH 前清除代理，否则连不上（本机有 TUN 代理时会 hang）
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY

SSH_OPTS=(-i "$SSH_KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=15 -o BatchMode=yes)
ssh_do() { ssh "${SSH_OPTS[@]}" "root@${VPS_HOST}" "$@"; }

MODE="${1:-deploy}"

# ---------- 只检查 ----------
if [ "$MODE" = "--check" ]; then
  echo "== 远端状态 =="
  ssh_do "
    echo -n '站点目录      : '; [ -d ${REMOTE_DIR} ] && echo ${REMOTE_DIR} || echo '(未创建)'
    echo -n 'index.html    : '; [ -f ${REMOTE_DIR}/index.html ] && stat -c '%s bytes' ${REMOTE_DIR}/index.html || echo '(缺失)'
    echo -n 'nginx 配置    : '; [ -f ${CONF_PATH} ] && echo ${CONF_PATH} || echo '(未创建)'
    echo -n '端口 ${LISTEN_PORT} 监听 : '; ss -tln 2>/dev/null | grep -q ':${LISTEN_PORT} ' && echo 'YES' || echo 'NO'
    echo -n 'cloudflared   : '; systemctl is-active cloudflared-subscription 2>/dev/null || echo unknown
    echo -n '443 占用      : '; ss -tlnp 2>/dev/null | grep ':443 ' | grep -o 'users:((\"[a-z]*\"' | head -1 || echo '(空闲)'
  "
  echo
  echo "== 公网验证 =="
  curl -s -o /dev/null -w "https://${SUB}.${DOMAIN}/  ->  HTTP %{http_code}\n" \
       "https://${SUB}.${DOMAIN}/" || echo "(无法访问，多半是 Cloudflare 侧还没加 Public Hostname)"
  exit 0
fi

# ---------- 卸载 ----------
if [ "$MODE" = "--rollback" ]; then
  echo "移除 nginx 配置与站点目录…"
  ssh_do "rm -f ${CONF_PATH} && nginx -t && systemctl reload nginx && rm -rf ${REMOTE_DIR} && echo ROLLBACK_OK"
  echo "已移除。Cloudflare 面板里的 Public Hostname 请自行删除。"
  exit 0
fi

# ---------- 部署 ----------
[ -f "$SRC_HTML" ] || { echo "找不到源文件：$SRC_HTML"; exit 1; }
[ -f "$SSH_KEY" ]  || { echo "找不到 SSH 私钥：$SSH_KEY"; exit 1; }

echo "[1/5] 创建远端目录 ${REMOTE_DIR}"
ssh_do "mkdir -p ${REMOTE_DIR}"

echo "[2/5] 上传 index.html"
scp "${SSH_OPTS[@]}" "$SRC_HTML" "root@${VPS_HOST}:${REMOTE_DIR}/index.html"

echo "[3/5] 写入 nginx 配置（仅监听回环，不开放公网端口）"
ssh_do "cat > ${CONF_PATH}" <<NGINX
# 喜马拉雅深链跳转页 —— 由 Cloudflare Tunnel 转发，不直接对公网暴露端口
server {
    listen 127.0.0.1:${LISTEN_PORT};
    server_name ${SUB}.${DOMAIN};

    root ${REMOTE_DIR};
    index index.html;

    # 支持「域名 + 原始链接」的纯路径写法：不把 // 合并成 /，
    # 否则 https://www.ximalaya.com/... 会被压成 https:/www.ximalaya.com/...
    merge_slashes off;

    # 跳转页是纯静态资源，不缓存，方便随时更新
    location / {
        try_files \$uri \$uri/ /index.html;
        add_header Cache-Control "no-store" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "no-referrer" always;
    }

    access_log /var/log/nginx/${SUB}.${DOMAIN}.access.log;
    error_log  /var/log/nginx/${SUB}.${DOMAIN}.error.log;
}
NGINX

echo "[4/5] 校验并重载 nginx"
if ssh_do "nginx -t"; then
  ssh_do "systemctl reload nginx && echo RELOAD_OK"
else
  echo "nginx 配置校验失败，已中止（未重载，现有服务不受影响）"
  ssh_do "rm -f ${CONF_PATH}"
  exit 1
fi

echo "[5/5] 本机回环自测"
ssh_do "curl -s -o /dev/null -w 'local http://127.0.0.1:${LISTEN_PORT}/ -> HTTP %{http_code}\n' http://127.0.0.1:${LISTEN_PORT}/"

cat <<TIPS

============================================================
VPS 侧完成。还差一步 —— Cloudflare 面板加 Public Hostname
（token 模式的 tunnel，ingress 规则只能在这里改）：

  1. 打开 https://one.dash.cloudflare.com/
  2. Networks -> Tunnels -> 选你那个 subscription tunnel
  3. Public Hostname 标签 -> Add a public hostname
  4. 填：
       Subdomain : ${SUB}
       Domain    : ${DOMAIN}
       Type      : HTTP
       URL       : 127.0.0.1:${LISTEN_PORT}
  5. Save

保存后立刻生效，HTTPS 由 Cloudflare 边缘证书自动提供，DNS 记录自动创建，
不需要 certbot、不需要开放 80/443。

验证：
  curl -I https://${SUB}.${DOMAIN}/
  curl -s -o /dev/null -w '%{http_code}\n' "https://${SUB}.${DOMAIN}/?t=1015366669"
============================================================
TIPS
