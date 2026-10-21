# Documentation

This repository is the central documentation and download home. Detailed guides
are copied from the exact component revisions pinned here, with provenance in
[`sources.json`](sources.json). Source-code links point to those same revisions.

- [Install, hosting defaults, first-owner password and member invitations](installation.md)
- [Coordinated releases, signatures and container publishing](releases.md)
- [Server installation and development](server/index.md)
- [Container runtime, HTTPS, updates and backups](server/container.md)
- [API and authentication](server/api.md), [OpenAPI](server/openapi.json), [WebSocket contract](server/websocket.json)
- [Administration and moderation](server/moderation.md), [runtime settings](server/runtime-settings.md)
- [Media transports](server/media-transports.md), [native capture](server/client-native-capture.md)
- [Client build and development](client/index.md), [desktop updates](client/releases.md)
- [Appearance](client/appearance.md), [notifications](client/notifications.md)
- [Audio plugin development](audio-plugins.md), [server extensions](server/server-extensions.md)
- [Demo gallery](gallery.md)
- [Optional encrypted sync](../sync/README.md), [protocol and trust contract](sync-service.md)

Refresh the detailed guides after updating coordinated pins with
`python3 scripts/sync-docs.py`. The source-pin workflow checks that these copies
match their component sources.
