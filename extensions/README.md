![Haunt](../assets/haunt-wordmark.png)

# Server extensions

Standalone executable packages extend Haunt's server and contribute settings and
voices dynamically to browser and desktop clients. They are separate from the
Wasm microphone processors in `audio-plugins/`.

- [TikTok TTS](tiktok-tts-plugin/): a speech extension with provider implementation,
  configuration fields, grouped voice catalog, package builder and protocol tests.

The projects are maintained in separate repositories and pinned here as Git
submodules. Initialize the TikTok source with:

```sh
git submodule update --init extensions/tiktok-tts-plugin
```

Follow the extension's build instructions, install its output under the server's
`server-extensions/packages/` data directory, and reload installed extensions in
Server settings. Packages can be updated independently of the server binary.

The [server extension guide](../server/docs/server-extensions.md) documents package
metadata, dynamic menus, the execution protocol and host APIs. The server manages
authentication, encrypted configuration, limits and caching. Clients manage
personal speech preferences and playback.
