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

The default compose deployment uses Cloudflare Tunnel; see [Haunt Nexus setup](#cloudflare-tunnel-haunt-nexus) below. The published image is
`ghcr.io/example-git/haunt:sync-latest` (Linux amd64 and arm64).
Keep sync data and community data in separate projects and volumes.

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

## Cloudflare Tunnel (Haunt Nexus)

`ghcr.io/example-git/haunt:sync-latest` is a **single container** containing Haunt
Sync, PostgreSQL and cloudflared. All processes run as UID 65532. PostgreSQL and
the sync API listen only on loopback; no host ports are published. The default
Compose project has one service, with its data persisted in `sync_data`.

1. Create a named, remotely managed tunnel (suggested name: `haunt-nexus`).
   Add its public hostname (suggested address: `nexus.xo.vg`) with service
   `http://127.0.0.1:8090`. Keep the public address unchanged for saved backups.
2. Copy `.env.example` to `.env`, keep it mode `0600`, and set
   `HAUNT_SYNC_HOST`, `HAUNT_SYNC_TUNNEL_TOKEN`, and the separately trusted client
   publisher's HTTPS sign-in origin. The example names do not establish hosting.
   On startup, a nonempty token is written atomically to
   `/data/run/cloudflared-token` with mode `0600`; cloudflared receives its file
   path through `--token-file`. The token value is not included in arguments or
   logs. After editing `.env`, rerun Compose `up -d` to recreate the container
   with the new environment. A plain container restart retains the old environment.
   The new value replaces the saved token during startup.
3. Start the dedicated project:

   ```sh
   docker compose --project-name haunt-nexus pull
   docker compose --project-name haunt-nexus up -d
   ```

The private database password is generated on first startup and persisted in
`/data/database-password`. An optional `HAUNT_SYNC_DB_PASSWORD` must use 32-256
URL-safe characters and match the saved password on subsequent starts. Back up
the complete `/data` volume while stopped. Replacing the named-tunnel container
preserves its identity, accounts and ciphertexts. Never mount a community or
existing PostgreSQL volume into this container.

Startup **refuses an empty token** unless `HAUNT_SYNC_QUICK_TUNNEL=true` is
explicitly set. Quick mode prints a random `trycloudflare.com` HTTPS address and
uses it as the issuer. It is for fresh, disposable volumes: the address changes
on a full restart, and the current protocol binds backup keys to that address.
An existing installation with a different issuer fails visibly; it is never
silently reset or given a new identity. Quick mode and a token cannot be selected
together. Use a named tunnel for lasting backups.

Cloudflare provides public HTTPS and an encrypted outbound connection. No inbound
firewall or port forwarding is required. The sync service trusts only loopback
proxy headers. `/healthz` reports database readiness; verify `/v1/config` through
the public hostname before connecting clients. Leave Cloudflare Access browser
login/challenges off these API routes: Haunt clients use proof-bound authentication.
Bypass cache for `/v1/*`; only public `/client-updates/*` may be cached. Keep
cloudflared at normal log verbosity, since debug logging can expose headers.
If a child process exits, the supervisor shuts down the whole bundle visibly.

The standalone binary remains available for operators supplying their own
PostgreSQL and HTTPS gateway; it does not run the container's tunnel supervisor.

## Signed desktop update distribution

Sync also serves a **public update feed**, without requiring a sync account or
sharing credentials. Desktop clients connected to sync add
`https://YOUR_SYNC_HOST/client-updates/haunt-updates.json` to their update sources.
They choose the newest valid signed release and prefer sync for equal versions;
other connected sources still work if the sync mirror is unavailable. Logging out
removes that sync update source. Publisher signatures, file hashes and desktop
rollback checks remain mandatory.

Download a complete signed desktop release from the central Haunt releases into
a staging directory, then import it from the hub checkout:

```sh
python3 scripts/import-sync-updates.py /path/to/downloaded/release
```

The importer checks the pinned client publisher key and all eight file hashes
before publishing the manifest. It preserves the signed bytes and refuses to
replace a version with different files. The default `.local/sync-updates`
directory is mounted read-only inside the sync container; no restart is required
for a newly imported release. Keep older release directories for clients already
downloading them. Set `HAUNT_SYNC_UPDATES_PATH` to choose a different host directory.
For a standalone process set `HAUNT_SYNC_UPDATES_DIR` to the same release directory.
Updates use four independent streaming slots, separate from sync authentication.
The feed is optional and returns `client_update_unavailable` until populated.

Community operators can also advertise the public Nexus feed to desktop users
who do not use sync accounts:

```dotenv
HAUNT_CLIENT_UPDATE_MANIFEST_URL=https://nexus.xo.vg/client-updates/haunt-updates.json
```

Use the address of your actual Nexus deployment; the hostname above is a proposed
project address, not a claim that it is already hosted. This server option
distributes public releases without forwarding community authentication tokens.
