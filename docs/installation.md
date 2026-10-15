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

Set your real `HAUNT_PUBLIC_URL`, `HAUNT_MEDIA_PUBLIC_IP` in
`.env`. Choose the server name in the setup wizard. Forward the documented ports and point DNS at that host. For automatic
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
`HAUNT_IMAGE=ghcr.io/example-git/haunt:0.5.2` to pin this release. No local build
or component checkout is required. All installation data persists in the
`haunt-data` volume. Replacing the container preserves its selected application,
accounts, messages and settings.

## First-time setup

On a fresh volume, open the **private setup link printed in the startup log**.
The wizard uses your server’s normal public address and port. Confirm the
connection details, choose the server name and policies, then set the owner
username and password. The container provides a private database automatically;
there is no generated password to retrieve or app-pairing command to run.

Select **Open Haunt** when setup finishes and sign in with the credentials you
chose. In the desktop client, use `username@your-server-hostname`. Setup is disabled
after the owner is created. Existing installations preserve their accounts and
skip the wizard. Keep the installer link and startup logs private until setup
has finished.

The public hostname and certificate mode are supplied before container startup
so HTTPS is available for setup. Environment-controlled settings appear locked
in the wizard. Other choices are saved privately in the data volume; owner
passwords are stored as database hashes. Explicit bootstrap credentials remain
supported for unattended fresh installs and never reset an existing account.

Standalone binaries use the same wizard on their main service listener and
also let you enter the dedicated PostgreSQL connection. See
[first-time setup](server/first-run.md) and the
[complete container guide](server/container.md).

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
