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
Before starting builds, it verifies the signing key and hosted web authentication.

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
uses the already verified archive. After the hosted web job succeeds, the hub activates the stable feed and promotes the verified container manifests. Operators can install the published binaries locally.

Re-run failed jobs to reuse the saved release plan and completed artifacts.
Re-running the whole workflow also restores the plan for the same run. A retry
cannot change the source revision, selected targets, or version. Existing release
files are compared with their recorded bytes rather than overwritten.

An expired saved artifact prevents resuming that run. If setup failed before a
plan was saved, start a new run after configuring the missing settings.

## Repository configuration

Configure these hub repository secrets before enabling stable releases:

| Secret                     | Purpose                                                    |
| -------------------------- | ---------------------------------------------------------- |
| `HAUNT_UPDATE_PRIVATE_KEY` | Existing Ed25519 key matching `client/static/updates.json` |
| `CLOUDFLARE_API_TOKEN`     | Deploy the standalone Worker                               |
| `CLOUDFLARE_ACCOUNT_ID`    | Worker account                                             |

Run **Verify hub release setup** after rotating release signing or hosted web credentials.

## Local validation

```sh
python3 -m unittest discover -s scripts/tests -v
go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.12 .github/workflows/*.yml
npm --prefix client run test:version
npm --prefix client test -- --run tests/desktop-updates.test.ts tests/desktop-profile.test.ts
```
