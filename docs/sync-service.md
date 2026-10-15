# Sync service implementation contract

This document records the requested behavior and security boundaries. The service is implemented and verified with isolated protocol, rendered client, SMTP transport and container restart checks. It is not a claim of a hosted or independently audited service.

Sync is disabled until a user explicitly enables it. Ordinary community sign-in,
local settings and the desktop client work without a sync account. No backup or
credential is uploaded while sync is off.

Email authentication and recovery are optional. Delivery can use an existing
authenticated SMTP service or a private send-only relay. Email verification can
restore account access; decrypting an existing backup still requires the master
password, an offline recovery key or an already trusted device. A mail-provider
or service-operator override must not become a backup decryption path.

## Outcome and executable path

The desktop sign-in screen and client settings offer a separate sync account.
The master password authenticates through OPAQUE and unlocks the encrypted backup
on trusted client code. After sign-in the client restores saved server addresses,
usernames, credentials and preferences, then periodically encrypts and uploads
updates. Explicit logout or device revocation ends a sync session; elapsed time
does not. Server operators receive ciphertext, not backup keys or passwords.

A community web client offers a banner for desktop installation and a single-server
sync action. OAuth authorization code with S256 PKCE opens a separately trusted
sign-in page. That page uses the browser-authenticated requesting origin, derives
only its server key, wraps it to the requesting client's public key, and returns
a grant bound to that origin and proof key. The community page never receives the
master password, full-backup key, full session or another community's credentials.
The scope is checked both by the service and by the authenticated encryption.
Changing a client flag, scope parameter, redirect or API response must not widen it.

## Cryptographic and authentication requirements

- OPAQUE RFC 9807, using matching Ristretto255/SHA-512 parameters and Argon2id
  with 64 MiB, three iterations and four lanes on the client. The password and
  client export key never enter an HTTP request or the server store. The AKE
  session key is shared with the server and must not be used as the backup key.
- A random 256-bit backup key is wrapped with a domain-separated key derived
  from the client-only OPAQUE export key. Backup bodies use AES-256-GCM with a
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

The Go data service does not serve the master-password entry page. That page must
come from a separately trusted client publisher, not from a community or backup
storage operator. Its initial web request comes through an exact-origin
`postMessage` exchange; keys and scopes must not be selected from mutable service
responses. Deployment must keep this distinction intact. A storage operator who
can replace trusted client code could steal keys; encryption does not make
compromised client software safe. Local malware and a guessed master password
are also outside an absolute confidentiality guarantee. No claim of "iron clad"
or independent audit is made without that evidence.

## Required verification

Run real browser/Go registration and login, wrong-password and transcript-tamper
checks, encrypted upload and restore on a fresh client, and database inspection
for synthetic plaintext credentials. Test concurrent users and conflicting
revisions, indefinite session validity, logout/revocation, cross-account denial,
PKCE mismatch/replay, redirect manipulation, origin forgery, key substitution,
and web attempts to retrieve or decrypt another server's data. Verify the desktop
and web UI in isolated demos, and test the container only in disposable storage.
Passing unit tests alone does not establish the requested restore behavior.

References: [OPAQUE](https://www.rfc-editor.org/rfc/rfc9807.html),
[OAuth security](https://www.rfc-editor.org/rfc/rfc9700.html),
[PKCE](https://www.rfc-editor.org/rfc/rfc7636.html),
[native application authorization](https://www.rfc-editor.org/rfc/rfc8252.html).
