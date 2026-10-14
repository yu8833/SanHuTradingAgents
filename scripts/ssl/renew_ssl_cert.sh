#!/usr/bin/env bash
# =============================================================================
# renew_ssl_cert.sh — www.cloudsea.tech Let's Encrypt 证书自动签发/续期/部署
#
# 原理：acme.sh + Let's Encrypt（ec-256），HTTP-01 webroot 校验（走 80 端口）
# 部署：把新证书（叶证书 + 中间链）写入 nginx/ssl 与 proxy-ssl，并 reload nginx
#
# ── 首次上线（服务器上一次性操作）──
#   1. 云安全组/防火墙放行 80 端口
#   2. 外层 nginx compose 增加端口映射与 webroot 卷：
#        ports:   - "80:80"
#        volumes: - /var/www/acme:/var/www/acme
#   3. 确保 proxy-ssl/nginx.conf 已含 /.well-known/acme-challenge/ 转发（本仓库已加）
#   4. 重启外层 nginx 容器，然后执行：
#        ./scripts/ssl/renew_ssl_cert.sh --issue --force
#   5. 验证：openssl s_client -connect www.cloudsea.tech:8443
#
# ── 长期自动续期 ──
#   acme.sh 自带每日 cron（默认安装），到期前约 30 天自动续期，续期成功后
#   自动回调 reloadcmd = `renew_ssl_cert.sh --deploy`（见 issue 阶段注册）。
#
# ── 参数 ──
#   --issue              签发新证书（加 --force 强制重新签发，用于过期后立即换新）
#   --renew              按 acme.sh 规则按需续期（默认 cron 已由 acme.sh 接管）
#   --deploy             仅部署已签发证书 + reload nginx（acme.sh reloadcmd 回调用）
#   --rebuild-frontend   部署后重建前端镜像（前端容器内 nginx 证书是构建时 COPY 的）
#   --force              配合 --issue 使用
# =============================================================================
set -euo pipefail

DOMAIN="${SSL_DOMAIN:-www.cloudsea.tech}"
ACCOUNT_EMAIL="${SSL_ACCOUNT_EMAIL:-admin@cloudsea.tech}"
WEBROOT="${SSL_WEBROOT:-/var/www/acme}"
ACME_HOME="${HOME}/.acme.sh"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
NGINX_SSL_DIR="${REPO_DIR}/nginx/ssl"
PROXY_SSL_DIR="${REPO_DIR}/proxy-ssl"

log() { echo "[$(date '+%F %T')] $*"; }
die() { log "ERROR: $*"; exit 1; }

# ── reload 运行中的 nginx 容器（外层代理负责对外 8443）───────────────────────
reload_nginx_containers() {
  local found=0 c
  while IFS= read -r c; do
    [ -z "$c" ] && continue
    found=1
    log "reload nginx 容器: ${c}"
    docker exec "$c" nginx -s reload 2>/dev/null \
      || docker kill -s HUP "$c" 2>/dev/null \
      || log "容器 ${c} reload 失败，请手动处理"
  done < <(docker ps --format '{{.Names}}' 2>/dev/null | grep -iE 'nginx|proxy' || true)
  [ "$found" -eq 0 ] && log "未发现 nginx 容器，请手动 reload 外层代理"
}

# ── 1. 安装 acme.sh（幂等）───────────────────────────────────────────────────
ensure_acme() {
  if [ ! -x "${ACME_HOME}/acme.sh" ]; then
    log "安装 acme.sh（账号邮箱 ${ACCOUNT_EMAIL}）..."
    curl -fsSL https://get.acme.sh | sh -s email="${ACCOUNT_EMAIL}" || die "acme.sh 安装失败"
  fi
  log "acme.sh 就绪: $("${ACME_HOME}/acme.sh" --version 2>/dev/null | head -1 || echo '版本未知')"
}

# ── 2. 签发 / 续期 ──────────────────────────────────────────────────────────
issue_cert() {
  mkdir -p "${WEBROOT}" || die "无法创建 webroot ${WEBROOT}"
  local args=(--issue -d "${DOMAIN}" --server letsencrypt --keylength ec-256 -w "${WEBROOT}" --home "${ACME_HOME}")
  [ "${FORCE:-}" = "1" ] && args+=(--force)
  log "签发证书: ${DOMAIN}"
  "${ACME_HOME}/acme.sh" "${args[@]}"
}

# --renew 时 acme.sh 未到续期窗口会输出 Skip 且返回 0，此时无需部署
renew_cert() {
  mkdir -p "${WEBROOT}"
  local out
  log "按需续期: ${DOMAIN}"
  out="$("${ACME_HOME}/acme.sh" --renew -d "${DOMAIN}" --server letsencrypt --keylength ec-256 --home "${ACME_HOME}" 2>&1)"
  echo "$out"
  if echo "$out" | grep -qi "Skip"; then
    return 1
  fi
  return 0
}

# 注册 acme.sh 的续期回调：续期成功后自动执行 --deploy（拷贝证书 + reload）
register_reloadcmd() {
  log "注册 acme.sh reloadcmd（续期后自动部署）..."
  "${ACME_HOME}/acme.sh" --install-cert -d "${DOMAIN}" --ecc \
    --reloadcmd "${SCRIPT_DIR}/renew_ssl_cert.sh --deploy"
}

# ── 3. 部署：备份旧证书 → 写新证书 → reload nginx ──────────────────────────
deploy_certs() {
  local cert_dir="${ACME_HOME}/${DOMAIN}_ecc"
  local key="${cert_dir}/${DOMAIN}.key"
  local fullchain="${cert_dir}/fullchain.cer"
  [ -f "${key}" ] && [ -f "${fullchain}" ] || die "未找到签发产物（${cert_dir}），请先执行 --issue"

  local ts; ts="$(date +%Y%m%d_%H%M%S)"
  for d in "${PROXY_SSL_DIR}" "${NGINX_SSL_DIR}"; do
    [ -d "$d" ] || mkdir -p "$d"
    [ -f "$d/server.crt" ] && cp -p "$d/server.crt" "$d/server.crt.bak.${ts}"
    [ -f "$d/server.key" ] && cp -p "$d/server.key" "$d/server.key.bak.${ts}"
  done

  # fullchain（叶+中间链）直接作为 nginx 的 server.crt，浏览器即可完成信任链校验
  install -m 644 "${fullchain}" "${PROXY_SSL_DIR}/server.crt"
  install -m 600 "${key}"       "${PROXY_SSL_DIR}/server.key"
  install -m 644 "${fullchain}" "${PROXY_SSL_DIR}/server.crt.fullchain"
  install -m 644 "${fullchain}" "${NGINX_SSL_DIR}/server.crt"
  install -m 600 "${key}"       "${NGINX_SSL_DIR}/server.key"
  log "证书已部署：proxy-ssl/ 与 nginx/ssl/（旧证书备份为 *.bak.${ts}）"

  reload_nginx_containers
}

# 前端容器内 nginx 证书是构建时 COPY 进镜像的（Dockerfile.frontend），需重建镜像
rebuild_frontend() {
  log "重建前端镜像（内层 nginx 证书更新）..."
  if docker compose version >/dev/null 2>&1; then
    docker compose build frontend && docker compose up -d frontend || log "前端镜像重建失败，请手动执行"
  else
    docker-compose build frontend && docker-compose up -d frontend || log "前端镜像重建失败，请手动执行"
  fi
}

# ── 参数解析 ────────────────────────────────────────────────────────────────
ACTION="issue"
FORCE=""
REBUILD=0
while [ $# -gt 0 ]; do
  case "$1" in
    --issue)            ACTION="issue" ;;
    --renew)            ACTION="renew" ;;
    --deploy)           ACTION="deploy" ;;
    --force)            FORCE="1" ;;
    --rebuild-frontend) REBUILD=1 ;;
    -h|--help)          head -60 "$0" | grep -E '^# ' | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "未知参数 $1（支持 --issue / --renew / --deploy / --rebuild-frontend）" ;;
  esac
  shift
done

case "${ACTION}" in
  deploy)
    deploy_certs
    ;;
  renew)
    ensure_acme
    if renew_cert; then
      register_reloadcmd
      deploy_certs
    else
      log "未到续期时间窗口，本次跳过部署"
    fi
    ;;
  issue)
    ensure_acme
    issue_cert
    register_reloadcmd
    deploy_certs
    ;;
esac

[ "${REBUILD}" = "1" ] && rebuild_frontend

log "全部完成"
