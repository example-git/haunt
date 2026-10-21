![Haunt](assets/haunt-wordmark.png)

Haunt is self-hosted community chat with channels, direct messages, voice/video
calls, profiles, permissions, and moderation. Accounts and data belong to the
independently operated server where they were created.

This repository provides central documentation, installation tools, screenshots,
and coordinated releases of Haunt's components. The project is under active
development and has not received an independent security audit.

![Haunt channels, audio settings and a voice call](assets/demo/Multiple-Horizontal.png)

## Get started

| Goal | Guide |
| --- | --- |
| Install a server | `python3 install.py` · [installation guide](docs/installation.md) |
| Download the desktop client | [Downloads](https://github.com/example-git/haunt/releases/latest) · [platform installation](docs/client/index.md#platforms) |
| Build the server or client | [Server](docs/server/index.md) · [Client](docs/client/index.md) |
| Explore the interface | [Demo gallery](docs/gallery.md) |
| Browse documentation | [Documentation index](docs/index.md) |
| Contribute or publish releases | [Contributing](CONTRIBUTING.md) · [Release guide](docs/releases.md) |

## Components

| Checkout | Responsibility |
| --- | --- |
| [server/](https://github.com/example-git/haunt-server) | Accounts, messaging, media, storage, administration, and the embedded web client |
| [client/](https://github.com/example-git/haunt-client) | Browser and desktop applications, shared client libraries |
| [sync/](https://github.com/example-git/haunt-sync) | Optional encrypted settings and saved-sign-in synchronization |
| [audio-plugins/rnnoise/](https://github.com/example-git/haunt-audio-rnnoise) | Local microphone noise suppression |
| [extensions/tiktok-tts-plugin/](https://github.com/example-git/tiktok-tts-plugin) | Server-hosted speech extension |

Each component is maintained in its own repository and pinned here as a Git
submodule. The server also pins the client for independent embedded-client builds.

```sh
git clone --recurse-submodules https://github.com/example-git/haunt.git
cd haunt
python3 scripts/check-pins.py
```

## Trust and recovery

Accounts use `username@server-address`; servers do not federate identities or
messages. DMs support client-side encryption. Server channels and relayed media
have different trust boundaries. See the [security policy](SECURITY.md),
[DM security guide](docs/server/dm-security.md), and
[backup and recovery guide](docs/server/operations.md).

## License and participation

Haunt-owned code uses the [BSD 3-Clause License](LICENSE). Submodules and
third-party content retain their own licenses and notices. Haunt is independent
of Discord. See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidance and
[SECURITY.md](SECURITY.md) for private vulnerability reports.
