# Refresh the banner and demo screenshots

From this hub checkout, run:

```sh
python3 scripts/update-banner.py
```

The command builds the web client, starts disposable local server fixtures, and
captures the actual interface in headless Chrome with Playwright. It refreshes
`assets/demo/Multiple-Horizontal.png`, the gallery images, and their manifests.
No hosted account or login is used. The fictional community, messages and two
voice participants are created by `client/scripts/capture-demo.mjs` in the server
checkout. Native desktop effects are not simulated.

The banner places chat with a floating call, audio settings, and the voice room
side by side. Each 1600×1000 screenshot stays at its original size. The 4880×1040
PNG has 20-pixel black padding and gutters, 12-pixel screenshot corners and a
32-pixel outer radius. The pixels outside the outer corners are transparent, so
the rounded frame works on both light and dark GitHub backgrounds.

## Prerequisites and options

Use a Linux development checkout with the submodules initialized, Go, Node/npm,
Docker and `/usr/bin/google-chrome`. Install the server's client dependencies
with `npm ci --prefix server/client` and prepare the web build dependencies from
the [client development guide](server/client-development.md). The dedicated
`chatxo-identity-check` PostgreSQL test container must be running on
`127.0.0.1:32768`; the integration harness verifies its identity before connecting
and creates its own disposable databases. Existing application databases are not
used. The script cleans Go build and test caches when the capture finishes or
fails.

Build the RNNoise package using its [development instructions](../audio-plugins/rnnoise/README.md).
The default package path is `audio-plugins/rnnoise/dist/haunt-plugin.zip`. You can
choose a separate development checkout, package, or theme:

```sh
python3 scripts/update-banner.py --server /path/to/haunt-server \
  --audio-plugin /path/to/haunt-plugin.zip --theme "Rose Slate"
```

The default theme is Midnight, matching the original banner. Unknown theme names
fail instead of silently choosing another preset. Every run captures all 13
presets for the gallery; the selected theme controls the three banner scenes.
The script stops only the browser it launches with its own private profile.

Inspect the generated banner before committing it. `assets/demo/banner.json`
records the theme, source commit, whether the checkout had uncommitted changes,
image dimensions, corner/gutter checks and SHA-256 checksums for each panel and
the final PNG. A refresh changes screenshots only; commit and publish them through
the normal repository workflow when a major UI change is ready.
