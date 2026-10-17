// A bounded observation from the existing authenticated SDK stream. No second
// Photon connection and no model-controlled endpoint or destination.
import net from "node:net";

export function developmentObservation(event) {
  const content = event?.content?.type === "reply" ? event.content.content : event?.content;
  if (!event || content?.type !== "text") return null;
  return {
    messageId: event.messageId,
    direction: event.direction ?? null,
    sender: { id: event.sender?.id ?? null },
    space: { id: event.space?.id ?? null, type: event.space?.type ?? null },
    nativeReplyTargetGuid: event.nativeReplyTargetGuid ?? null,
    nativeThreadOriginatorGuid: event.nativeThreadOriginatorGuid ?? null,
    nativeIsForward: event.nativeIsForward ?? null,
    content: { type: "text", text: content.text },
    timestamp: event.timestamp,
  };
}

export async function observeDevelopmentEvent(socketPath, event) {
  const observation = developmentObservation(event);
  if (!socketPath || !observation) return { state: "not_applicable" };
  const body = JSON.stringify({ op: "observe", event: observation });
  if (Buffer.byteLength(body) > 64 * 1024) return { state: "unavailable" };
  return await new Promise((resolve) => {
    const client = net.createConnection({ path: socketPath });
    let settled = false;
    let answer = "";
    const finish = (value) => {
      if (settled) return;
      settled = true;
      client.destroy();
      resolve(value);
    };
    // The existing Intake handles one socket request at a time. Queue a native
    // owner reply beyond its bounded 30s development send (root caller: 40s).
    // This changes no SDK connection or event identity.
    client.setTimeout(45000, () => finish({ state: "unavailable" }));
    client.on("error", () => finish({ state: "unavailable" }));
    client.on("connect", () => client.write(body + "\n"));
    client.on("data", (chunk) => {
      answer += chunk.toString("utf8");
      if (answer.length > 1024) return finish({ state: "unavailable" });
      if (!answer.includes("\n")) return;
      try {
        const result = JSON.parse(answer.split("\n", 1)[0]);
        finish(result?.ok === true ? { state: result.state } : { state: "unavailable" });
      } catch {
        finish({ state: "unavailable" });
      }
    });
  });
}
