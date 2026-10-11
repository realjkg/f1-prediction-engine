# TLS 1.3 communications — secure deployment

The default `compose.yaml` is a **loopback HTTP development demonstrator**.
Do not expose or rename it as a production deployment. Use the separately
specified `compose.tls.yaml` when serving the F1 Prediction Engine on any
remote or externally accessible network.

## Network boundary

```text
React browser / native app
    -- HTTPS TLS 1.3 (certificate + hostname verified) -->
Nginx secure edge :8443
    -- HTTPS TLS 1.3 + mutual certificate authentication -->
FastAPI/Uvicorn internal :8000
    -- local mounted evidence & pinned datasets (no network) -->

OpenF1 backend collector
    -- MQTT over TLS 1.3, account token, peer certificate/hostname verification -->
OpenF1 broker :8883
```

The API instance serves only on the Compose network and does not publish
port 8000. The secure web server exposes **only** HTTPS on port 8443;
no HTTP listener, TLS 1.2 downgrade, or unauthenticated internal engine
connection is part of secure Compose. Runtime certificates are **mounted**,
not built into container images, committed, or supplied in client bundles.
The engine requires the trusted Nginx client certificate as well as its own
certificate and private key.

## Certificates and startup

Provision certificate material through your PKI or secret manager. The
mounted directory must contain:

- `ca.crt` — trusted CA certificate(s) for private backend mTLS (not a key)
- `engine.crt`, `engine.key` — valid server certificate with SAN `DNS:engine`;
  full chain if needed, readable only by the engine's UID 10001
- `web-client.crt`, `web-client.key` — clientAuth-enabled certificate
  issued by the trusted private CA, readable only by the Nginx process
- `web.crt`, `web.key` — public HTTPS server certificate and chain with SAN
  matching the actual public API/app hostname (use a publicly trusted CA
  for real browser/device access)

The smoke test uses **temporary**, one-day certificates and cleans them up.
It never creates or commits production identities. Ensure keys have
minimum required process ACLs and that production certificates are renewed.

```bash
export F1E_TLS_CERTS_DIR=/absolute/path/to/mounted/certs
export F1E_TLS_BIND_ADDRESS=127.0.0.1
export F1E_TLS_PORT=8443

docker compose -f compose.tls.yaml up -d --build --wait engine web
```

For public service, put a properly configured public DNS name and firewall
in front of this secure endpoint, or explicitly bind the approved public IP
and restrict exposure. Do not use a TLS 1.2-offloading intermediary: every
TLS termination/re-initiation hop must independently enforce TLS 1.3.
Update the allowed CORS origins and native backend URLs deliberately;
do not allow wildcard credentials or distribute internal CA private keys.

## Required verification

```bash
# Use the issuing CA only for private test deployments; public PKI
# deployments should verify against the system browser/device trust store.
curl --tlsv1.3 --tls-max 1.3 --fail https://your-real-host:8443/api/config

# Must fail: the secure ingress does not negotiate TLS 1.2.
curl --tlsv1.2 --tls-max 1.2 https://your-real-host:8443/api/config
```

Run `bash scripts/test-secure-stack.sh` with Docker Compose on an isolated
test machine. The GitHub Actions secure smoke workflow runs real TLS 1.3
handshakes through Nginx and a certificate-required FastAPI backend, then
asserts no TLS 1.2 or HTTP ingress and no public `/metrics`.

For live telemetry, independently verify the broker can negotiate TLS 1.3
using licensed OpenF1 credentials. Its published endpoint alone is not proof
of TLS 1.3 support. The backend collector must refuse negotiation failure;
it must never disable hostname checks or fall back to plaintext.

## What remains outside this secure Compose service

- The optional offline trainer, current-season external source refresh, and
  optional Ollama briefing are **not** started by secure Compose. A separately
  deployed remote trainer or briefing service must adopt TLS 1.3+ for every
  network hop before it becomes part of a production service.
- Mobile app backend URL validation requires HTTPS and the server refuses
  TLS 1.2. Device certificate policies, app authentication and session
  authorization still need real public-environment verification.
- Encryption in transit does not validate telemetry data rights, dataset
  chronology, model calibration, or the authenticity of customer data.
  Those controls remain separate release requirements.

This deployment provides a TLS 1.3-capable topology. Actual production
availability requires valid certificates, selected DNS/ingress, approved
credentials, firewalling, host hardening and observed successful handshakes.
