# Audio plugin development

RNNoise is Haunt's redistributable bundled default. A plugin is a manifest plus
bounded Wasm modules, distributed by a server and processed locally on clients.

Follow these guides in order:

1. [Build the tiny gain example](../client/docs/audio-plugin-authoring.md): exact
   PCM/function ABI, compiler command, settings schema, packaging and sandbox.
2. [Adapt a real model](../audio-plugins/rnnoise/docs/authoring.md): RNNoise source
   layout, input scaling, latency alignment, reproducible builds and voice clips.
3. [Distribute through Haunt Server](../server/docs/audio-plugin-authoring.md):
   permissions, upload, pinned GitHub commits/checksums, limits and validation.

The server's [full plugin reference](../server/docs/audio-plugins.md) explains
caching, download progress and failure behavior. Plugins contain no JavaScript,
UI components, secrets, native executables or networking. ONNX weights alone are
not an executable plugin; a compatible Wasm inference adapter is required.

Users choose their active plugin/model locally. An owner or administrator with
configuration permission can select **Set as server default** to give new clients
the same plugin, model and tuning. Existing personal settings are preserved.
