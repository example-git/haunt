> Documentation from the pinned [example-git/haunt-server](https://github.com/example-git/haunt-server/blob/3cf3185839d25d52c0b658fc34df911b6d3e13bc/docs/roadmap.md) source. Refresh with `python3 scripts/sync-docs.py`.

# Project direction

Haunt implements independent community services and a shared browser/desktop
client. Current features are described in the component READMEs and API docs.
The goal is convenient messaging and calls for small communities with predictable
storage, bandwidth and operational costs. Accounts remain scoped to their servers.

Ongoing work includes wider device/browser coverage, release and recovery testing,
and independent review of the DM encryption implementation. The shared client core
allows future Android messaging without requiring mobile voice in the first release.
Federated accounts and a public centralized hosting platform are not current goals.

See [testing](testing.md) for the verification harnesses and their limits.
