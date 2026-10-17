import { PREVIEW_TEXT } from "./policy.mjs";

// Called only for an explicit operator command after routing preflight.
export async function sendPreview(space, label, textBuilder) {
  if (!Object.hasOwn(PREVIEW_TEXT, label) || !space || typeof space.send !== "function") {
    throw new Error("INVALID_PREVIEW_REQUEST");
  }
  const result = await space.send(textBuilder(PREVIEW_TEXT[label]));
  if (typeof result?.id !== "string" || !result.id) throw new Error("MISSING_OUTBOUND_ID");
  return result.id;
}
