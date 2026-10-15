> Documentation from the pinned [example-git/haunt-client](https://github.com/example-git/haunt-client/blob/9c8ab59489d7786873d6978b0199c6eb50b94b06/docs/notifications.md) source. Refresh with `python3 scripts/sync-docs.py`.

# Notifications

## Server and user overrides

Choose a server in **Notification Settings**, then search by username or display
name. Only matching users from that server's authenticated member directory are
shown, up to 20 at a time. Empty searches show no users. Changing servers clears
the search. Channel overrides stay below the user results.

User rules and sounds apply to incoming DMs from that user on that server, without
creating or opening a conversation. An explicit conversation override takes
precedence, then the user's DM override, then the server and client defaults.
A muted server or the master notification switch still silences notifications.
These local preferences, including custom sound files, survive restarts and are
included in client backups.
