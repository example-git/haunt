# Release and download layout

The master repository is the distribution home. Component repositories remain the
source of builds and tests; master submodule pins identify the exact combination.
No historical release or existing client's updater source is moved automatically.
All repositories and new packages remain private until deliberately made public.

## Desktop and server downloads

Use a master tag such as `v0.3.0` for a coordinated release. Component versions can
differ; record the source tags and commits in the master release notes. Publish
installers only after their component builds finish, and make a draft release
before promoting it. The intended asset set is:

- Windows x64 installer, Linux x64/arm64 AppImages and macOS arm64 DMG.
- The small desktop ASAR payloads and their **unchanged signed** `haunt-updates.json`.
- Linux amd64/arm64 server binaries, with the web client embedded.
- `haunt-app-linux-*.tar.gz` and `haunt-app.json` for container application updates.
- RNNoise package, source revisions and a release-wide SHA-256 file.

Prepare component releases at the pinned commits first. The client release
workflow owns signing and platform builds. Keep its private signing key there;
this repository must not re-sign or edit its signed payload. Mirroring its bytes
preserves the existing application/repository identity checked by installed
clients. Installer filenames and manifest-relative paths must stay together.
A new hosted manifest address can be configured through Haunt Server without
putting private GitHub credentials in clients.

The server application's `haunt-app.json` is not signed and contains absolute
asset URLs. If those archives are mirrored into a master release, change those
URLs to the corresponding master release while retaining their verified hashes,
sizes, version and runtime contract. Set `HAUNT_APP_UPDATE_REPOSITORY=example-git/haunt`
only once the master release actually includes a valid `haunt-app.json` and both
archives. Private server-side downloads still require a contents-read token file.

Do not point an updater at an empty release hub. The current component releases
and Oracle distribution remain operational while the master gains coordinated
releases. At creation, this repository provides the hub and workflows; it does not
claim that a new desktop/server installer release has already been published.

## Container images

Run **Publish coordinated container** in this repository's Actions with a version
such as `0.3.0`. It checks all pinned components, builds natively on Linux amd64 and
arm64, and runs the complete disposable-container test suite on each image before
publishing architecture tags. Only after both pass does it publish the combined
`ghcr.io/example-git/haunt:0.3.0` tag. Architecture staging tags include the master
commit to avoid combining outputs from different source revisions. There is no
moving `latest` tag or automatic deployment to a live server.

The runtime image contains Nginx, PostgreSQL and Supervisor, and persists its data
and application release in a volume. Normal application updates do not rebuild
the image; system/runtime changes do. See the [container guide](../server/docs/container.md).
Private GHCR images require registry authentication. GitHub package visibility is
separate from repository visibility; deliberately check both before a public release.

## Repository access in CI

The master uses three separate read-only deploy keys: `HAUNT_SERVER_READ_KEY`,
`HAUNT_CLIENT_READ_KEY` and `HAUNT_PLUGIN_READ_KEY`. Each grants access to exactly
one component repository. No personal access token or deployment credential is
embedded in the source, container or client. `GITHUB_TOKEN` writes packages only
from the explicitly invoked container publishing workflow.

Before pinning a client update, wait for that repository's automatic version commit.
Update `server/client` and commit the server reference, then pin that server plus
the matching top-level `client` here. Check the bundled RNNoise hash against the
plugin source pin with `python3 scripts/check-pins.py`. Build artifacts belong in
releases or registries, not large files in this master Git history.
