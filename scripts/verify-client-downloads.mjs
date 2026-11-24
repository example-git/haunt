import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { Updater, verifyManifest } = require("../client/apps/desktop/updates.cjs");
const [base, feedPath, version] = process.argv.slice(2);
let input = "";
for await (const chunk of process.stdin) input += chunk;
const envelope = JSON.parse(input);
const config = JSON.parse(await fs.readFile(new URL("../client/static/updates.json", import.meta.url), "utf8"));
const payload = JSON.parse(Buffer.from(envelope.payload, "base64").toString("utf8"));
assert.equal(payload.version, version);
const cases = Object.keys(payload.targets).flatMap((target) => [
  { target, kind: "asar" },
  { target, kind: "installer" },
  ...(target.startsWith("linux-") ? [{ target, kind: "installer", format: "rpm" }] : []),
]);
assert.equal(cases.length, 10);
const directory = await fs.mkdtemp(path.join(os.tmpdir(), "haunt-public-downloads-"));
let cursor = 0;
const files = [];
try {
  const worker = async () => {
    while (cursor < cases.length) {
      const test = cases[cursor++];
      const [platform, arch] = test.target.split("-");
      const publisher = { ...config, ...(test.format ? { installerFormat: test.format } : {}) };
      const info = verifyManifest(envelope, publisher, platform, arch);
      const runtime = test.kind === "asar" ? info.runtime : (info.runtime[0] === "0" ? "1" : "0") + info.runtime.slice(1);
      const profile = await fs.mkdtemp(path.join(directory, "client-"));
      const updater = new Updater({ directory: profile, config: publisher, runtime, version: "0.0.0", platform, arch });
      updater.source({ id: "public-verification", origin: new URL(base).origin, manifestURL: new URL(`${feedPath}/haunt-updates.json`, base).href, authenticated: false });
      const checked = await updater.check();
      assert.equal(checked.phase, test.kind === "asar" ? "available" : "runtime-required", checked.message);
      assert.equal(checked.available, version);
      assert.deepEqual(updater.available.envelope, envelope);
      const downloaded = await updater.download();
      assert.equal(downloaded.phase, test.kind === "asar" ? "ready" : "installer-ready", downloaded.message);
      const ready = await updater.verifyReady();
      assert.equal(ready.kind, test.kind);
      assert.equal(ready.info.version, version);
      files.push(info[test.kind].file);
      await fs.rm(profile, { recursive: true, force: true });
    }
  };
  const results = await Promise.allSettled(Array.from({ length: 3 }, worker));
  const failure = results.find((result) => result.status === "rejected");
  if (failure) throw failure.reason;
  assert.equal(new Set(files).size, 10);
  console.log(JSON.stringify(files));
} finally {
  await fs.rm(directory, { recursive: true, force: true });
}
