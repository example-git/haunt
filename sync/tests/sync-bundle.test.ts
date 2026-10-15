import { describe, it, expect } from "vitest";
import { SyncService } from "../packages/browser/src/sync/service";
import { proofKeys, random } from "../packages/browser/src/sync/crypto";

const issuer = process.env.HAUNT_SYNC_BUNDLE_ISSUER;
describe.skipIf(!issuer)("single-container Nexus public HTTPS", () => {
  it("registers, encrypts and restores a backup through its own cloudflared and private database", async () => {
    const service = new SyncService(
      issuer!,
      "https://trusted-publisher.example.test",
    );
    const username = "bundle-check",
      password = "synthetic bundle master " + random();
    await service.register(username, password, await proofKeys());
    const first = await service.signIn(username, password);
    const backup = {
      settings: { theme: "frosted" },
      credential: "synthetic-community-secret",
    };
    await service.write(first, backup, 0);
    const fresh = await service.signIn(username, password);
    expect((await service.read(fresh)).value).toEqual(backup);
    await service.logout(first);
    await service.logout(fresh);
  }, 90_000);
});
