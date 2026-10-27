# Hub development and stable releases

The hub owns the release version, component source revisions, build inventory,
publication, and deployment. Work is integrated on `dev` and squash-promoted to
`main` before a stable release. Component repositories run their regressions;
they do not independently bump versions, publish stable images, or deploy web.

## Development

**Hub development prerelease** runs on hub `dev` pushes or manual dispatch.
Set the comma-separated `targets` input for a manual run. Automatic runs use the
`HAUNT_DEV_TARGETS` repository variable, defaulting to `linux-x64`.

Supported targets:

- `win32-x64`, `linux-x64`, `linux-arm64`, `darwin-arm64`
- `web`
- `server-linux-amd64`, `server-linux-arm64`
- `sync-linux-amd64`, `sync-linux-arm64`

Only selected targets build. A service build includes the dependencies needed to
produce and test that service. Successful targets publish independently, so a
failure in another selected target does not hide their downloads. Tested Docker
archives remain available as workflow artifacts.

Development versions use the next patch after the latest reserved/published hub
version and the workflow run number, such as `0.17.9-dev.42`. They publish under a
`dev-v` tag as GitHub prereleases. Development builds have no stable update
manifest, production deployment, or `latest` container publication. Desktop
packages use a separate application identity, `haunt-dev` profile, and
`haunt-dev:` protocol. Linux development packages are AppImages; stable RPMs
continue through the full stable pipeline. Development updates are manual.

## Stable release

Start **Hub stable release** from `main`. Select patch, minor, major, or provide
an explicit higher `X.Y.Z` version. The workflow reserves a draft hub release,
records exact gitlink revisions, and stamps package versions in build checkouts.
It does not create generated version commits in component branches.
Before starting builds, it verifies the signing key, hosted web authentication,
deployment connections, and existing service prerequisites.

Desktop manifests retain the `example-git/haunt-client` publisher identity and
existing Ed25519 trust key. Hosting their signed bytes in the hub does not change
what installed clients trust. Server application manifests use absolute hub
asset URLs while retaining the runtime compatibility contract and archive hashes.
The source inventory uses `haunt-release.json` schema 2; the client and server
update-manifest formats remain unchanged.

The workflow runs client/browser, server/race/million-message, and sync protocol
checks. It builds all nine targets, including all four native desktop installers,
both server and Nexus architectures, and standalone web. Native upgrade,
packaging, capture, Fedora RPM, and bundled Linux runtime checks remain required.

Build outputs carry their source revisions and hashes. The publisher verifies
the complete inventory, signs desktop artifacts with the client trust key, and
publishes the tested multiarch images and coordinated downloads. Web deployment
uses the already verified archive. SSH deployment backs up server/Nexus state,
preserves configuration and identity, and retains rollback material. The Nexus
feed importer publishes its manifest only after all verified files are present.

After deployment, the stable GitHub feed is activated. Public service readiness,
CORS, identity, web assets, and every signed desktop download are verified.
Verified container manifests then become `latest`. Services and publication
endpoints update sequentially; the workflow reports failure if any stage fails.

Re-run failed jobs to reuse the saved release plan and completed artifacts.
Re-running the whole workflow also restores the plan for the same run. A retry
cannot change the source revision, selected targets, or version. Existing release
files are compared with their recorded bytes rather than overwritten. Successful
deployment records allow retries to verify an installed version without
restarting it again. Server binary rollback is automatic while the database
schema remains compatible; an advanced schema retains its backup for recovery
without automatically discarding new database contents.

An expired saved artifact prevents resuming that run. If setup failed before a
plan was saved, start a new run after configuring the missing settings.

## Repository configuration

Configure these hub repository secrets before enabling stable releases:

| Secret                     | Purpose                                                    |
| -------------------------- | ---------------------------------------------------------- |
| `HAUNT_UPDATE_PRIVATE_KEY` | Existing Ed25519 key matching `client/static/updates.json` |
| `CLOUDFLARE_API_TOKEN`     | Deploy the standalone Worker                               |
| `CLOUDFLARE_ACCOUNT_ID`    | Worker account                                             |
| `HAUNT_DEPLOY_SSH_KEY`     | SSH identity authorized for both deployment hosts          |
| `HAUNT_DEPLOY_KNOWN_HOSTS` | Pinned SSH host keys for both hosts                        |

The deployment identity needs passwordless execution of the staged deployment
helper through `sudo python3`, plus staging with `sudo install` and `sudo tar`.
The server host needs Python 3.11 or later, systemd, Docker access to its configured
PostgreSQL container, and existing server installation files. The Nexus host
needs Python 3.11 or later, Docker Compose, and its existing Compose deployment. Deployment
helpers do not install host display or GPU services.

Configure two JSON repository variables. `HAUNT_SERVER_DEPLOYMENT`:

```json
{
  "kind": "server",
  "ssh_target": "ubuntu@server.example.test",
  "service": "chatxo-test.service",
  "binary": "/usr/local/bin/haunt",
  "data": "/var/lib/chatxo-test",
  "database_container": "chatxo-identity-check",
  "database_port": 32768,
  "arch": "arm64",
  "local_origin": "http://127.0.0.1:8080",
  "web_origin": "https://haunt-web.example.workers.dev",
  "preserved_files": [
    "/etc/chatxo-test.env",
    "/etc/systemd/system/chatxo-test.service",
    "/var/lib/chatxo-test/storage-provider.key"
  ],
  "public_origins": ["https://chat.example.test"]
}
```

`HAUNT_SYNC_DEPLOYMENT`:

```json
{
  "kind": "sync",
  "ssh_target": "deploy@nexus.example.test",
  "compose_directory": "/srv/haunt/sync",
  "project": "haunt-nexus",
  "container": "haunt-nexus-nexus-1",
  "updates_directory": "/srv/haunt/.local/sync-updates",
  "public_origins": ["https://nexus.example.test"]
}
```

The public server feed must offer installers and all signed payloads through its
configured external release source. `web_origin` must match
`client/web-deployment.json`. Secrets and private installation settings remain in
GitHub configuration and on their hosts. The release checks configuration before
starting expensive builds; missing credentials cannot silently skip deployment.

Deployment connections default to SSH port 22. A LAN host reached through a
gateway can set `ssh_port` and `jump_host` (`user@host`). Both connections use the
deployment key and pinned host keys. A reverse SSH relay must listen only on the
gateway's loopback interface; pin the destination key under its forwarded
`[host]:port` address. Keep the relay key separate from the deployment key and
restrict it to that listener.

Run **Verify hub release setup** from `main` after configuring or rotating
credentials. It checks the signing key, hosted web authentication, both SSH
connections, and the existing service prerequisites. It does not publish builds,
change update feeds, or restart application services.

## Local validation

```sh
python3 -m unittest discover -s scripts/tests -v
go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.12 .github/workflows/*.yml
npm --prefix client run test:version
npm --prefix client test -- --run tests/desktop-updates.test.ts tests/desktop-profile.test.ts
```
