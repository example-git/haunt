# Sync protocol and security boundaries

Haunt Sync stores encrypted settings and saved sign-ins for clients connected to
an independently operated sync service.

Sync is disabled until a user explicitly enables it. Ordinary community sign-in,
local settings and the desktop client work without a sync account. No backup or
credential is uploaded while sync is off.

Email authentication and recovery are optional. Delivery can use an existing
authenticated SMTP service or a private send-only relay. Email verification can
restore account access; decrypting an existing snapshot still requires the master
password and private keyword, an offline recovery key or an already trusted device. A mail-provider
or service-operator override must not become a backup decryption path.

## Independent instances and disposable storage

A sync instance is a separate service, never a shared community-server process.
A group of friends selects its own instance and creates a sync account there;
that account synchronizes the distinct logins for the group’s community servers.
Neither account creation nor unlocking requires a project-wide authentication
service. The host pays for storage but receives no payload decryption keys.

Local client data is the working copy. The service keeps current encrypted
snapshots for synchronization, with no promise of archival history or retention.
An unavailable service, failed authentication or missing snapshot cannot erase
local settings. A new sync account starts from the client’s local copy. Losing
the instance cannot recover data that no client still retains.

## Sign-in, synchronization and browser pairing

The desktop sign-in screen and client settings offer a separate sync account.
The master password authenticates through OPAQUE. The password and private keyword
derive the root and unlock snapshots entirely in client code. After sign-in the client restores saved server addresses,
usernames, credentials and preferences, then periodically encrypts and uploads
updates. Explicit logout or device revocation ends a sync session; elapsed time
does not. Server operators receive ciphertext, not backup keys or passwords.

A community web client offers desktop installation and a single-server pairing
action. Its private exchange and proof keys remain in that browser. A public-key
request is copied to a signed-in desktop; the user checks the exact origin and
fingerprint before approving. Desktop returns a scoped key wrapped to that
browser. S256 PKCE and proof-bound redemption prevent another browser from using
the approval. The web client receives only its origin-scoped key, not the master
password, private keyword or complete root.

Password or keyword changes re-encrypt every current ciphertext on the client.
The service verifies a signed complete migration and exact revisions under a
per-account transaction; no partial password/ciphertext change commits. All old
devices and in-flight authentication challenges are revoked. The client then
forces full resync, including unchanged full and scoped snapshots. Failure stays
visible and local working settings remain available. Initial account setup and
email recovery also require that full resync.

## Cryptographic and authentication requirements

- OPAQUE RFC 9807, using matching Ristretto255/SHA-512 parameters and Argon2id
  with 64 MiB, three iterations and four lanes on the client. The password and
  client export key never enter an HTTP request or the server store. The AKE
  session key is shared with the server and must not be used as the backup key.
- A deterministic 256-bit root is derived locally with Argon2id v1.3 (64 MiB,
  three iterations, four lanes), using the exact password and private keyword.
  The keyword contributes a local SHA-256 salt under a fixed versioned domain;
  neither value nor its salt/root is sent to the service. A root-derived,
  domain-separated key wraps the client recovery signer; the root itself is
  recomputed on ordinary sign-in. Backup bodies use AES-256-GCM with a
  fresh random nonce and authenticated account, scope and revision fields.
- Per-server keys are domain separated by canonical HTTPS origin. A web grant
  cannot decrypt the full backup or another origin's backup, even if an operator
  returns those ciphertexts. Service account metadata, sizes and timing remain
  visible to the operator.
- TLS protects transport. Non-loopback HTTP fails visibly. Public URLs, issuer,
  OAuth callbacks and message origins are validated exactly; PKCE downgrade,
  duplicate/replayed codes, wildcard redirects and broad web scopes are rejected.
- Persistent device tokens are revocable and bound to proof keys. Stored tokens
  are hashed. Code and authentication challenges are one-use and bounded; those
  bounds do not expire established sessions. Logout removes the device's local
  key material and revokes its service token.
- Concurrent uploads use database transactions and revision comparisons. No
  global worker or process lock serializes unrelated users. Conflicting snapshots
  are merged or fail visibly; they must not silently overwrite another device.

## Code trust

Both secrets and all payload encryption belong to installed client code trusted
by the user. A sync host supplies authentication records and encrypted storage,
not an authentication webpage. Browser pairing carries only public keys and a
single-server encrypted approval package. A community host can modify its page
and read its own approved scope, but cannot receive the global secrets through
this flow. Compromised client code or guessed secrets can expose encrypted data.
See the [security model](../sync/docs/security.md) for the threat boundaries.

## Required verification

Run real browser/Go registration and login, wrong-password and transcript-tamper
checks, encrypted upload and restore on a fresh client, and database inspection
for synthetic plaintext credentials. Test concurrent users and conflicting
revisions, indefinite session validity, logout/revocation, cross-account denial,
PKCE mismatch/replay, redirect manipulation, origin forgery, key substitution,
and web attempts to retrieve or decrypt another server's data. Verify the desktop
and web UI in isolated demos, and test the container only in disposable storage.

References: [OPAQUE](https://www.rfc-editor.org/rfc/rfc9807.html),
[OAuth security](https://www.rfc-editor.org/rfc/rfc9700.html),
[PKCE](https://www.rfc-editor.org/rfc/rfc7636.html),
[native application authorization](https://www.rfc-editor.org/rfc/rfc8252.html).
