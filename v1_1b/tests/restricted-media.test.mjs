import assert from "node:assert/strict";
import { constants } from "node:fs";
import { mkdtemp, writeFile, symlink, link, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { readRestrictedMedia, MAX_RESTRICTED_MEDIA_BYTES } from "../staging/sidecar/restricted-media.mjs";
import { attachment, voice } from "/home/alfred/.hermes/hermes-agent/plugins/platforms/photon/sidecar/node_modules/spectrum-ts/dist/index.js";

test("restricted media reads only a regular Hermes-owned opaque spool entry", async () => {
  const root = await mkdtemp(join(tmpdir(), "photon-media-review-"));
  const id = "a".repeat(32);
  try {
    await writeFile(join(root, id), Buffer.from("photo"));
    assert.equal((await readRestrictedMedia(root, id, process.getuid())).toString(), "photo");
    await assert.rejects(readRestrictedMedia(root, "../outside", process.getuid()));
    await assert.rejects(readRestrictedMedia(root, id, process.getuid() + 1));
    const bad = "b".repeat(32);
    await symlink(join(root, id), join(root, bad));
    await assert.rejects(readRestrictedMedia(root, bad, process.getuid()));
    const hard = "c".repeat(32);
    await link(join(root, id), join(root, hard));
    await assert.rejects(readRestrictedMedia(root, id, process.getuid()));
    const huge = "d".repeat(32);
    await writeFile(join(root, huge), Buffer.alloc(1));
    const file = await import("node:fs/promises").then(fs => fs.open(join(root, huge), constants.O_RDWR));
    await file.truncate(MAX_RESTRICTED_MEDIA_BYTES + 1);
    await file.close();
    await assert.rejects(readRestrictedMedia(root, huge, process.getuid()));
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("pinned Spectrum builders accept restricted media bytes without a second connection", async () => {
  const photo = await attachment(Buffer.from("photo"),
    { name: "photo.jpg", mimeType: "image/jpeg" }).build();
  const audio = await voice(Buffer.from("voice"),
    { name: "voice.caf", mimeType: "audio/x-caf" }).build();
  assert.equal(photo.name, "photo.jpg");
  assert.equal(photo.mimeType, "image/jpeg");
  assert.equal((await photo.read()).toString(), "photo");
  assert.equal(audio.name, "voice.caf");
  assert.equal((await audio.read()).toString(), "voice");
});
