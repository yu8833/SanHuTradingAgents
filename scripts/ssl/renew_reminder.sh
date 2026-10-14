#!/usr/bin/env bash
# =============================================================================
# renew_reminder.sh — www.cloudsea.tech 证书到期提醒
#
# 背景：证书用 DNS-01 手动模式签发（因公网只开放 8443，无法用 HTTP-01）。
#       每 90 天续期时，需要人工到新网互联加一条 TXT 记录，本脚本在到期前
#       提前通知用户（macOS 通知 + 日志），并给出需要添加的 TXT 值。
#
# 用法：
#   ./scripts/ssl/renew_reminder.sh            # 检查并提醒（供 launchd 定时调用）
#   ./scripts/ssl/renew_reminder.sh --force    # 立即生成 TXT 值（续期前手动触发）
# =============================================================================
set -uo pipefail

DOMAIN="www.cloudsea.tech"
ACCOUNT_EMAIL="${SSL_ACCOUNT_EMAIL:-admin@cloudsea.tech}"
ACME_HOME="${HOME}/.acme.sh"
CERT="${ACME_HOME}/${DOMAIN}_ecc/${DOMAIN}.cer"
REMIND_DAYS=40
LOG="${HOME}/ssl_renew_reminder.log"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() { echo "[$(date '+%F %T')] $*" | tee -a "${LOG}"; }

notify() {
  # macOS 通知（best effort；未授权时静默失败，不影响日志）
  osascript -e "display notification \"$2\" with title \"SSL 证书续期提醒\"" 2>/dev/null || true
  log "$1: $2"
}

if [ ! -f "${CERT}" ]; then
  log "ERROR: 证书文件不存在 ${CERT}"
  exit 1
fi

# 计算剩余天数
EXPIRY_STR="$(openssl x509 -in "${CERT}" -noout -enddate | cut -d= -f2)"
EXPIRY_EPOCH="$(date -j -f "%b %e %H:%M:%S %Y %Z" "${EXPIRY_STR}" +%s 2>/dev/null)"
DAYS_LEFT=$(( (EXPIRY_EPOCH - $(date +%s)) / 86400 ))
log "证书 ${DOMAIN} 将于 ${EXPIRY_STR} 到期，剩余 ${DAYS_LEFT} 天"

if [ "${1:-}" = "--force" ]; then
  NEED=1
else
  [ "${DAYS_LEFT}" -le "${REMIND_DAYS}" ] && NEED=1 || NEED=0
fi

if [ "${NEED}" = "0" ]; then
  exit 0
fi

# 到期前：发起 DNS-01 手动签发，提取当前 TXT 挑战值
log "进入续期窗口，生成 DNS TXT 挑战值..."
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"
TXT_OUT="$("${ACME_HOME}/acme.sh" --issue --dns -d "${DOMAIN}" --server letsencrypt --keylength ec-256 \
  --yes-I-know-dns-manual-mode-enough-go-ahead-please 2>&1 || true)"
TXT_VALUE="$(echo "${TXT_OUT}" | grep -A1 "TXT value" | grep -oE "'[^']+'" | tail -1 | tr -d "'")"

if [ -n "${TXT_VALUE}" ]; then
  MSG="证书将于 ${EXPIRY_STR} 到期（剩 ${DAYS_LEFT} 天）。请到新网互联把 TXT 记录 _acme-challenge.www 的值改为: ${TXT_VALUE}"
  notify "REPLACE" "${MSG}"
  log "待添加 TXT 值: ${TXT_VALUE}"
  log "添加完成后运行: ${SCRIPT_DIR}/renew_ssl_cert.sh --renew --force"
else
  notify "ERROR" "证书即将到期（剩 ${DAYS_LEFT} 天）且无法生成 TXT 值，请检查 acme.sh 或手动续期"
fi
