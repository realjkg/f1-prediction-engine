#!/usr/bin/env bash
# Self-contained TLS 1.3 + mTLS compose smoke test. Ephemeral local certs only.
set -euo pipefail

TMP="$(mktemp -d)"
export F1E_TLS_CERTS_DIR="$TMP"
export F1E_TLS_BIND_ADDRESS=127.0.0.1
export F1E_TLS_PORT="${F1E_TLS_PORT:-18443}"

cleanup() {
  docker compose -f compose.tls.yaml down --volumes --remove-orphans || true
  rm -rf "$TMP"
}
trap cleanup EXIT

openssl req -x509 -newkey rsa:2048 -noenc -days 1 \
  -keyout "$TMP/ca.key" -out "$TMP/ca.crt" \
  -subj "/CN=F1 Local Test CA" \
  -addext "basicConstraints=critical,CA:TRUE" >/dev/null 2>&1

issue_certificate() {
  local name="$1" cn="$2" usage="$3" san="$4"
  openssl req -new -newkey rsa:2048 -noenc -keyout "$TMP/$name.key" \
    -out "$TMP/$name.csr" -subj "/CN=$cn" >/dev/null 2>&1
  printf "subjectAltName=%s\nextendedKeyUsage=%s\nkeyUsage=digitalSignature,keyEncipherment\n" \
    "$san" "$usage" > "$TMP/$name.ext"
  openssl x509 -req -in "$TMP/$name.csr" \
    -CA "$TMP/ca.crt" -CAkey "$TMP/ca.key" -CAcreateserial \
    -days 1 -sha256 -extfile "$TMP/$name.ext" \
    -out "$TMP/$name.crt" >/dev/null 2>&1
}
issue_certificate "engine" "engine" "serverAuth" "DNS:engine"
issue_certificate "web" "localhost" "serverAuth" "DNS:localhost,IP:127.0.0.1"
issue_certificate "web-client" "f1-web-proxy" "clientAuth" "DNS:f1-web-proxy"
# The engine Docker image deliberately runs as UID 10001; ephemeral CI keys
# are readable for this smoke test. Production keys need properly scoped ACLs.
chmod 644 "$TMP"/*.crt "$TMP"/*.key
docker compose -f compose.tls.yaml config -q
docker compose -f compose.tls.yaml up -d --build --wait --wait-timeout 360 engine web

curl -fsS --cacert "$TMP/ca.crt" --tlsv1.3 --tls-max 1.3 \
  "https://localhost:$F1E_TLS_PORT/" > /tmp/f1-tls-home.html
grep -q '<div id="root">' /tmp/f1-tls-home.html
curl -fsS --cacert "$TMP/ca.crt" --tlsv1.3 --tls-max 1.3 \
  "https://localhost:$F1E_TLS_PORT/api/config" > /tmp/f1-tls-api.json
python3 - <<'PY'
import json
with open("/tmp/f1-tls-api.json", encoding="utf-8") as stream:
    payload = json.load(stream)
assert payload["advisoryOnly"] is True
assert payload["datasetVersion"]
PY

if curl -fsS --cacert "$TMP/ca.crt" --tlsv1.2 --tls-max 1.2 \
  "https://localhost:$F1E_TLS_PORT/api/config" >/dev/null 2>&1; then
  echo "SECURITY FAILURE: TLS 1.2 unexpectedly negotiated" >&2
  exit 1
fi

if curl -fsS "http://localhost:$F1E_TLS_PORT/api/config" >/dev/null 2>&1; then
  echo "SECURITY FAILURE: plaintext ingress unexpectedly served" >&2
  exit 1
fi

if curl -fsS --cacert "$TMP/ca.crt" \
  "https://localhost:$F1E_TLS_PORT/metrics" >/dev/null 2>&1; then
  echo "SECURITY FAILURE: engine metrics exposed through ingress" >&2
  exit 1
fi

echo "PASS: TLS 1.3 public ingress and verified mTLS backend; TLS 1.2 refused"
