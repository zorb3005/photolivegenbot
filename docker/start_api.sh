#!/usr/bin/env bash
set -e

APP="app.api.http:app"
PORT="${API_PORT:-8000}"
HOST="${API_HOST:-127.0.0.1}"

SSL_ARGS=""
if [[ -n "$SSL_CERT_FILE" && -n "$SSL_KEY_FILE" && -f "$SSL_CERT_FILE" && -f "$SSL_KEY_FILE" ]]; then
  echo "Starting uvicorn with TLS cert=$SSL_CERT_FILE key=$SSL_KEY_FILE port=$PORT"
  SSL_ARGS="--ssl-certfile $SSL_CERT_FILE --ssl-keyfile $SSL_KEY_FILE"
else
  echo "Starting uvicorn WITHOUT TLS (cert/key not provided or not found)."
fi

exec uvicorn "$APP" --host "$HOST" --port "$PORT" $SSL_ARGS
