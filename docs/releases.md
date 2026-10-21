# Release and download layout

The hub repository is the distribution home. Component repositories remain the
source of builds and tests; hub submodule pins identify the exact combination.
Repositories, coordinated downloads and release packages are public; signing and
deployment credentials remain private.

## Desktop and server downloads

Use a tag such as `v0.4.5` in the hub for a coordinated release. Component versions can
differ; record the source tags and commits in the coordinated release notes. Publish
installers only after their component builds finish, and make a draft release
before promoting it. The intended asset set is:

- Windows x64 installer, Linux x64/arm64 AppImages and macOS arm64 DMG.
- The small desktop ASAR payloads and their **unchanged signed** `haunt-updates.json`.
- Linux amd64/arm64 server binaries, with the web client embedded.
- `haunt-app-linux-*.tar.gz` and `haunt-app.json` for container application updates.
- RNNoise package, source revisions and a release-wide SHA-256 file.
- Optional sync binaries for Linux amd64/arm64, copied from the successful sync
  workflow for the same hub revision.

Prepare component releases at the pinned commits first. The client release
workflow owns signing and platform builds. Keep its private signing key there;
this repository must not re-sign or edit its signed payload. Mirroring its bytes
preserves the existing application/repository identity checked by installed
clients. Installer filenames and manifest-relative paths must stay together.
A new hosted manifest address can be configured through Haunt Server without
putting private GitHub credentials in clients.

The server application's `haunt-app.json` is not signed and contains absolute
asset URLs. If those archives are mirrored into a coordinated release, change those
URLs to the corresponding hub release while retaining their verified hashes,
sizes, version and runtime contract. Set `HAUNT_APP_UPDATE_REPOSITORY=example-git/haunt`
only once the coordinated release actually includes a valid `haunt-app.json` and both
archives. A contents-read token file is needed only for a private operator mirror.

## Container images

Run **Publish coordinated container** in this repository's Actions with a version
such as `0.4.5`. It checks all pinned components, builds natively on Linux amd64 and
arm64, and runs the complete disposable-container test suite on each image before
publishing architecture tags. Only after both pass does it publish the combined
`ghcr.io/example-git/haunt:0.4.5` tag. Architecture staging tags include the hub
commit to avoid combining outputs from different source revisions. The version tag and `latest` are verified to resolve to the same manifest,
containing exactly Linux amd64 and arm64. Publishing does not deploy to a live server.

The runtime image contains Nginx, PostgreSQL and Supervisor, and persists its data
and application release in a volume. Normal application updates do not rebuild
the image; system/runtime changes do. See the [installation guide](installation.md) and [complete container guide](server/container.md).
The release image must be anonymously pullable. GitHub package visibility is
separate from repository visibility; verify both before every public release.

## Repository access in CI

The hub checks out each public component at the exact gitlink commit without a
deploy key. No personal access token or deployment credential is embedded in the
source, container or client. `GITHUB_TOKEN` writes packages only from explicitly
invoked publishing workflows.

Before pinning a client update, wait for that repository's automatic version commit.
Update `server/client` and commit the server reference, then pin that server plus
the matching top-level `client` here. Check the bundled RNNoise hash against the
plugin source pin with `python3 scripts/check-pins.py`. Build artifacts belong in
releases or registries, not large files in this hub's Git history.

## Publish a coordinated release

After both component releases succeed at the pinned revisions, update the hub's
source pins and regenerate the central guides. The script checks source tags,
GitHub asset metadata, the shipped client's Ed25519 verifier, every signed
installer/payload hash, server checksums and native archive metadata before a
release can be published. Existing signed client manifests stay byte-for-byte
unchanged; only unsigned server archive URLs are rebased onto this repository.

```sh
python3 scripts/check-pins.py
python3 scripts/sync-docs.py
python3 scripts/publish-release.py 0.4.5
# Commit and push source pins/docs before tagging:
git tag v0.4.5
git push origin v0.4.5
python3 scripts/publish-release.py 0.4.5 --publish
```

Authenticate `gh` with access to read component artifacts and publish hub releases.
Release downloads are retained in ignored `release/` and checked again on each run. Signing keys
remain in the component repository, and no broad personal credential is copied
into hub CI. A published coordinated release is never silently overwritten. The tag
also starts the central native container workflow. Source component releases
remain available for compatibility; this hub is the primary download home.

The signed client's application identity remains `example-git/haunt-client` so
existing installations accept the same verified payloads. Copying it here does
not change installed clients' configured feeds. Private client distribution can
continue through an authenticated Haunt server mirror; changing a feed remains
an explicit operator choice. The container updater can use
`HAUNT_APP_UPDATE_REPOSITORY=example-git/haunt` after the matching central release
has been published.

## Optional sync publishing

The hub’s `Build and publish optional sync` workflow runs real Go/browser protocol
and SMTP transport checks, builds both native Linux targets, and verifies the
production TLS container through encrypted upload and restart restore. It publishes
the exact checked images as `ghcr.io/example-git/haunt-sync:VERSION` and
`ghcr.io/example-git/haunt-sync:latest`. The package is linked to the Haunt Sync
repository and supports Linux amd64 and arm64.

For releases including sync, pass `--sync-run RUN_ID` to `scripts/publish-release.py`
after that workflow succeeds. Assembly requires its source revision to match the
hub release tag, checks artifact hashes and binary architectures, and includes
`haunt-sync-linux-amd64` and `haunt-sync-linux-arm64` in the central download set
and release-wide checksum file. Provenance records both the workflow's hub
revision and the pinned sync source revision.
