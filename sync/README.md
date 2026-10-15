# Haunt Sync

Optional encrypted settings and saved-sign-in backups. This service runs separately
from a community server, as a Go binary or container. It has no automatic hosting;
the operator chooses the public HTTPS hostname and stores its database locally.
The client integration has been checked with isolated rendered clients and the real Go service. Releases are published only after both architecture checks finish.

Desktop clients restore a complete backup and synchronize every minute while open.
A community web client synchronizes only its own origin through a separately
trusted sign-in page, OAuth authorization codes, S256 PKCE and proof-bound grants.
Multiple communities require Haunt desktop. Community sign-in works without sync.

The data service stores encrypted vault bodies and wrapped keys. The master
password and backup keys stay in trusted client code. Email verification restores
account access, but an existing backup still requires the master password, saved
offline recovery key or an already unlocked trusted device. Email alone cannot
decrypt it. There is no operator recovery key.

## Container

The compose file runs a private PostgreSQL database, this service, and an HTTPS
gateway. PostgreSQL is not published to the host. Set a public hostname, point DNS
to your host, copy `.env.example` to `.env`, choose a private random database
password using URL-safe characters, and set the independently trusted sign-in
origin. Then start this directory's compose project.

The default image reference is `ghcr.io/example-git/haunt:sync-latest`; availability
is confirmed by its publishing workflow, not by this example. Keep sync data and
community data in separate projects and volumes. The gateway terminates HTTPS and
forwards to the service's loopback listener in the same network namespace. Only
that configured gateway is trusted for client addresses and rate limits.

## Standalone binary

Build with Go 1.26.9 or newer: `go build ./cmd/haunt-sync`. Supply
`HAUNT_SYNC_DATABASE_URL`, `HAUNT_SYNC_ISSUER`, and `HAUNT_SYNC_PORTAL_ORIGIN`.
The database user needs permission to create its own `haunt_sync` schema. The
default listener is `127.0.0.1:8090` for an existing local HTTPS proxy. An externally
bound listener requires both `HAUNT_SYNC_TLS_CERT` and `HAUNT_SYNC_TLS_KEY` and
accepts TLS 1.3. Set `HAUNT_SYNC_TRUSTED_PROXIES` explicitly if using a proxy.

The issuer and OPAQUE server identity are persisted. Changing the issuer is not a
rename operation; startup refuses it. Back up the entire sync database, including
the saved OPAQUE key material, accounts and ciphertexts. Copying only vault rows
would break master-password unlock after restoration.

## Optional email

Configure an existing send-only SMTP service with `HAUNT_SYNC_SMTP_HOST`,
`HAUNT_SYNC_SMTP_PORT`, `HAUNT_SYNC_MAIL_FROM`, and optional authentication through
`HAUNT_SYNC_SMTP_USERNAME` and `HAUNT_SYNC_SMTP_PASSWORD`. Port 465 uses direct TLS;
other ports require STARTTLS. Certificates are checked and TLS cannot be disabled. For a private send-only relay, `HAUNT_SYNC_SMTP_CA_FILE` can name its trusted CA certificate; mount that public certificate read-only.
Do not expose an unauthenticated relay to the public Internet. Email features fail
visibly when unconfigured or when delivery fails; username/master-password sign-in
continues to work without SMTP. Verification links are one-use, expire in ten
minutes, and are bound to the requesting device's proof key. Copy the link into
the Haunt window that requested it.

## Trusted sign-in page

Build the pinned client checkout with `npm run build:sync-portal`. Serve the resulting
`dist-sync-portal/` on a separate HTTPS origin controlled by the client publisher.
The data-service container does not serve this page. Use CSP with `frame-ancestors
'none'`, allow its bundled Wasm and its selected HTTPS data service, and preserve
cross-origin opener messaging; do not use a policy that severs its opener.
The page validates the requesting browser origin and independently wraps only its
server key. It never gives the community page the complete-backup key.

A hostname difference alone is not independent trust: someone able to replace
trusted client code could steal its keys. Prefer the installed desktop client and
a separately controlled publisher for password entry. An operator sees account
metadata, delegated origins, timings and sizes; it can withhold, corrupt or replay
old data. A known device detects older revisions, but a brand-new device lacks an
independent history. Encryption does not defeat compromised clients or guessed
master passwords. The Go OPAQUE implementation has not had an independent audit.

## Sessions and conflicts

Established sync sessions have no elapsed-time expiry. They are proof-bound and
revoked by logout, password recovery or the user's device controls. Proof freshness
and short-lived authorization codes do not expire an established session. Logout
stops local sync immediately, removes local vault keys, and retains only the
proof-bound token needed to retry remote revocation if offline.

Ciphertexts authenticate account, issuer, scope and revision. Concurrent writes
compare revisions; independent edits merge and competing edits require an explicit
client choice. Unavailable community credentials produce a visible sign-in notice;
they do not stop other settings from synchronizing. Server sessions retain their
own revocation and expiry policies. Backups have a 20 MiB plaintext limit.

## Verification

Tests use the separate `chatxo-identity-check` fixture at `127.0.0.1:32768`, with a
dedicated `haunt_sync_iteration` database and a disposable schema per run. Configure
`HAUNT_SYNC_TEST_DATABASE_URL` and `HAUNT_SYNC_CLIENT_CHECKOUT`, install client
dependencies, then run `go test -race ./...`. The HTTP integration test launches
the actual browser OPAQUE library against production Go handlers and PostgreSQL.
Rendered browser checks additionally require a disposable community fixture and
built client/portal bundles. They never use saved personal accounts or browsers.

Protocol and trust requirements are in [the implementation contract](../docs/sync-service.md).
