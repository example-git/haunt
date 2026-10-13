# Install and sign in

Haunt runs on the machine where you start it. There is no automatic public
hosting account or fixed default website. Set `HAUNT_PUBLIC_URL` to your own
hostname. The container publishes TCP 80/443 and UDP 50000–50100 by default;
Nginx serves the web client and API, and PostgreSQL stays private inside it.
`ghcr.io/example-git/haunt` hosts the downloadable container image, not a running
community. Independent communities keep separate accounts and data.

## Start the published container

```sh
git clone https://github.com/example-git/haunt.git
cd haunt
cp .env.example .env
```

Set your real `HAUNT_PUBLIC_URL`, `HAUNT_MEDIA_PUBLIC_IP` and server name in
`.env`. Forward the documented ports and point DNS at that host. For automatic
HTTPS, the public hostname and TCP 80 must reach this container. The example
hostname and IP are placeholders, not a hosted installation.

While the image is private, authenticate to GHCR with your own GitHub account
and a token that can read this package. Then:

```sh
docker compose pull
docker compose up -d
docker compose logs --tail 100 -f haunt
```

The hub's Compose file defaults to `ghcr.io/example-git/haunt:latest`. Set
`HAUNT_IMAGE=ghcr.io/example-git/haunt:0.4.5` to pin this release. No local build
or component checkout is required. All installation data persists in the
`haunt-data` volume. Replacing the container preserves its selected application,
accounts, messages and settings.

## First owner credentials

On a fresh volume, the container creates an account named `owner` and a random
initial password. The operator retrieves it locally:

```sh
docker compose exec haunt cat /data/config/owner-password
```

Open your configured address and sign in with `owner` and that password. In the
desktop client the account address is `owner@your-server-hostname`. Change the
password in account settings. The generated password is stored privately in
the volume and is never printed in service logs.

You can supply an initial username/password or a mounted bootstrap-password file
instead; see the [complete container guide](server/container.md). Bootstrap
credentials apply only to a fresh installation and never reset an existing owner.

## Member credentials

The owner, or a member permitted to create invitations, opens **Settings →
Invitations**, creates an invite and shares its link. The recipient opens it
and chooses a username and password to create their account. They later sign in
as `username@server-hostname` with that password. Valid invitations are required;
registration can also be closed by the operator. An invite is not a shared
password, and one server's login does not create an account on another server.

## Updates, HTTPS and backups

The [central release](https://github.com/example-git/haunt/releases/latest)
contains desktop installers, signed client payloads, server binaries and
container-application bundles. Set the container application-update repository
to `example-git/haunt` if you want to check those releases. Private downloads
require a read-only token mounted as documented; automatic application updates
remain an explicit choice.

See the [complete container guide](server/container.md) for certificate modes,
reverse proxies, Cloudflared, application updates and volume backup/restore.
See [server operations](server/operations.md) for standalone binaries.
