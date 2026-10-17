import fs from "node:fs";
import net from "node:net";

export async function createControlServer(socketPath, handleCommand) {
  let queue = Promise.resolve();
  const server = net.createServer((client) => {
    client.setTimeout(5000, () => client.destroy());
    let line = "";
    client.on("data", (part) => {
      line += part.toString("utf8");
      if (line.length > 128) { client.destroy(); return; }
      const newline = line.indexOf("\n");
      if (newline < 0) return;
      const command = line.slice(0, newline);
      line = "";
      client.pause();
      queue = queue.then(() => handleCommand(command));
      void queue.then((result) => client.end(`${result === "OK" ? "OK" : "DENIED"}\n`),
        () => client.end("DENIED\n"));
    });
  });
  server.maxConnections = 1;
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(socketPath, () => { server.off("error", reject); resolve(); });
  });
  fs.chmodSync(socketPath, 0o600);
  return server;
}
