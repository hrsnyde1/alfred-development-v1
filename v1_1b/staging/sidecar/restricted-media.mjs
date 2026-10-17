// The restricted Hermes token may send bytes already staged in this one spool.
// It never supplies a broker-side path or gains the protected control token.
import { constants } from "node:fs";
import { open } from "node:fs/promises";
import { join, isAbsolute } from "node:path";

export const MAX_RESTRICTED_MEDIA_BYTES = 64 * 1024 * 1024;

export async function readRestrictedMedia(root, id, hermesUid) {
  if (!isAbsolute(root) || !/^[a-f0-9]{32}$/.test(id)
      || !Number.isSafeInteger(hermesUid) || hermesUid <= 0) {
    throw new Error("invalid restricted media request");
  }
  const parent = await open(root, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
  try {
    const file = await open(join(root, id), constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
    try {
      const info = await file.stat();
      if (!info.isFile() || info.nlink !== 1 || info.uid !== hermesUid
          || info.size < 1 || info.size > MAX_RESTRICTED_MEDIA_BYTES) {
        throw new Error("restricted media denied");
      }
      const bytes = await file.readFile();
      if (bytes.length !== info.size) throw new Error("restricted media changed while reading");
      return bytes;
    } finally {
      await file.close();
    }
  } finally {
    await parent.close();
  }
}
