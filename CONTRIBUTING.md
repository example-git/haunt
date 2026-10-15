# Contributing

Haunt is developed across separate server, client, sync, and audio-plugin
repositories. Make a source change in the repository that owns it, verify it
there, and update the hub's submodule pins only after that component commit is
ready to coordinate.

## Before submitting a change

- Keep credentials, deployment data, private plugins, generated releases, and
  local configuration out of Git.
- Add or update tests with behavior changes.
- Update the owning component's documentation before refreshing hub copies.
- Avoid using `git submodule update --remote` as a release procedure.

For hub changes, initialize the pinned components and run:

```sh
git submodule update --init --recursive
python3 scripts/check-pins.py
python3 scripts/sync-docs.py --check
python3 scripts/check-docs.py
```

Component repositories document their own build and test commands. A coordinated
change may require separate reviews before this repository advances its pins.

Report security issues through the private process in [SECURITY.md](SECURITY.md),
not in a public issue.

