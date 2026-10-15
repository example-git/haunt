# Install and sign in

Haunt runs on the machine where you start it. There is no automatic public
hosting account or fixed default website. Set `HAUNT_PUBLIC_URL` to your own
hostname. The container publishes TCP 80/443 and UDP 50000–50100 by default;
Nginx serves the web client and API, and PostgreSQL stays private inside it.
`ghcr.io/example-git/haunt` hosts the downloadable container image, not a running
community. Independent communities keep separate accounts and data.

> **Prebuilt-container port boundary:** forward client and setup traffic to TCP
> 80/443 on the host running Compose by default. Those host ports map to bundled
> Nginx on container TCP 80/443 and can be overridden with `HAUNT_HTTP_PORT` and
> `HAUNT_HTTPS_PORT`. The supplied image uses `127.0.0.1:8080` for the private
> Haunt backend behind Nginx; the supplied Compose file does not publish it.

## Terminal installer

Run `python3 install.py` from the main Haunt checkout. It retrieves the exact
pinned server, client, and optional sync components, then opens the guided container/bare-metal
installer. The TUI explains each setting, creates the first owner from a private
password file, and asks whether to preload RNNoise. Its container path generates
an environment file and Compose overlay, then prints the exact start command.

Using the generated profile creates the owner during first startup and skips the
browser wizard. Starting the container without that profile keeps the browser
setup flow described below.

## Start the published container

```sh
git clone https://github.com/example-git/haunt.git
cd haunt
cp .env.example .env
```

Set your real `HAUNT_PUBLIC_URL`, `HAUNT_MEDIA_PUBLIC_IP` in
`.env`. Choose the server name in the setup wizard. Forward TCP 80 and 443 to
the default host mappings—or the ports selected with `HAUNT_HTTP_PORT` and
`HAUNT_HTTPS_PORT`—forward the documented UDP range, and point DNS at that host.
For automatic HTTPS, the public hostname and mapped HTTP port must reach bundled
Nginx in this container. The example
hostname and IP are placeholders, not a hosted installation.

The published image is intended to be anonymously pullable from GHCR. Then:

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
to `example-git/haunt` if you want to check those releases. Public downloads do
not require a GitHub token; automatic application updates remain an explicit
choice. A token file is supported only for an operator-selected private mirror.

See the [complete container guide](server/container.md) for certificate modes,
reverse proxies, Cloudflared, application updates and volume backup/restore.
See [server operations](server/operations.md) for standalone binaries.
