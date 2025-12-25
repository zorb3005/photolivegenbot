#!/usr/bin/env bash
set -euo pipefail

# Генерирует самоподписанный сертификат для вебхуков YooKassa.
# Пример:
#   bash docker/gen_selfsigned.sh mydomain.com
#
# Результат: certs/selfsigned.crt и certs/selfsigned.key

DOMAIN="${1:-localhost}"
OUT_DIR="${2:-certs}"

mkdir -p "${OUT_DIR}"

CRT="${OUT_DIR}/selfsigned.crt"
KEY="${OUT_DIR}/selfsigned.key"

echo "Generating self-signed TLS cert for CN=${DOMAIN}..."
openssl req -x509 -nodes -newkey rsa:2048 \
  -subj "/CN=${DOMAIN}" \
  -days 365 \
  -keyout "${KEY}" \
  -out "${CRT}"

echo "Done. Files:"
echo "  ${CRT}"
echo "  ${KEY}"
