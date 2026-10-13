<table align="center" border="0" cellspacing="0" cellpadding="0">
  <tr>
    <td align="center" valign="middle">
      <img src="assets/demo/logo.png" alt="Haunt owl logo" width="144">
    </td>
    <td align="left" valign="middle">
      <h1 align="left">Haunt</h1>
    </td>
  </tr>
</table>
Haunt recreates the everyday convenience of Discord from scratch around independent,
self-hosted communities. Channels, direct messages, calls, profiles and moderation
belong to the server you choose. The client keeps several communities within reach,
without a central account directory or platform owning them all.

This is the project's home for documentation, screenshots, coordinated releases and
container publishing. The repositories are private while development continues.
Haunt is built for friends and small groups, with storage and bandwidth budgets an
individual can manage. It does not claim complete Discord parity or an independent
security audit.

![Haunt channels, audio settings and a voice call](assets/demo/Multiple-Horizontal.png)

## Choose a starting point

| What you want | Where to go |
| --- | --- |
| Run a server in one container | [Install and retrieve credentials](docs/installation.md) |
| Build a server with the web client embedded | [Server build guide](docs/server/index.md) |
| Build a desktop or separately hosted web client | [Client build guide](docs/client/index.md) |
| Create a noise-suppression plugin | [Plugin developer map](docs/audio-plugins.md) |
| See the interface | [Demo gallery](docs/gallery.md) |
| Download the desktop client | [Central downloads](https://github.com/example-git/haunt/releases/latest) |
| Find coordinated releases | [Master releases](https://github.com/example-git/haunt/releases) |
| Browse all documentation | [Documentation index](docs/index.md) |
| Understand release publishing | [Release layout](docs/releases.md) |

A release appears only when its artifacts have actually been prepared. A source
checkout is not an installer, and private downloads require repository access.

## Independent components, pinned together

| Checkout | Repository | Responsibility |
| --- | --- | --- |
| `server/` | [haunt-server](https://github.com/example-git/haunt-server) | Go API, accounts, storage, media relay, embedded web client and container runtime |
| `client/` | [haunt-client](https://github.com/example-git/haunt-client) | Browser UI, desktop shell, reusable client libraries |
| `audio-plugins/rnnoise/` | [haunt-audio-rnnoise](https://github.com/example-git/haunt-audio-rnnoise) | Redistributable bundled audio plugin and adapter example |

All three are Git submodules pinned to reviewed commits. Source and component tests
stay in their repositories. This master repository records combinations that belong
together and is the intended home for combined downloads and container images.
The server retains its own `client/` submodule so it remains buildable independently.
The top-level client and `server/client` must point to the same commit; they are two
checkouts of one repository, not independent clients.

```sh
git clone --recurse-submodules https://github.com/example-git/haunt.git
cd haunt
python3 scripts/check-pins.py
```

Build the complete server with `cd server && scripts/build-server.sh`, or use the published image with the
[central installation guide](docs/installation.md). Work on the client in `client/`; after a
client release/version commit, update both client pins deliberately before updating
the master. Do not use `git submodule update --remote` as a release procedure.

RNNoise ships as the default on fresh servers. Plugins process microphone audio
locally through a restricted Wasm interface. Server operators can add compatible
plugins; private operator packages are never part of this source tree or images.

## Trust and recovery

Accounts use `username@server-address` and belong to that service. Servers do not
federate identities or messages. DMs support client-side encryption; server channels
and relayed media have different trust boundaries. HTTPS, backups, account security
and operator maintenance still matter. Read the component security and recovery
documentation before deploying a community.

Haunt is independent of Discord. Product names describe familiar behavior, not an
affiliation. Existing component repositories remain private; coordinated downloads and containers live here; existing users'
update sources remain compatible.
