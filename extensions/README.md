# Server extensions

This directory is the home for separately maintained server-extension projects,
distinct from the microphone processors in `audio-plugins/`.

- [TikTok TTS](tiktok-tts-plugin/): direct TikTok speech provider for Haunt's
  server-side relay, with server-owner configuration and testing.

The TikTok project is maintained in a separate repository and pinned here as a
Git submodule. Initialize it with:

```sh
git submodule update --init extensions/tiktok-tts-plugin
```

Publish plugin commits to their remote before sharing an updated Haunt pin so
other checkouts can fetch the referenced revision. The server currently bundles
its own adapter; this source submodule is not yet a Go module dependency.

Haunt's server owns authentication, encrypted credential persistence, extension
configuration, limits and caching. Clients own playback and personal TTS settings.
No provider credentials belong in an extension repository or client preferences.
