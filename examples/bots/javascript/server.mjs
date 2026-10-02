// Minimal dependency-free Node.js participant bot. Run with: BOT_TOKEN=... node server.mjs
import { createServer } from "node:http";

const token = process.env.BOT_TOKEN ?? "replace-me";
const port = Number(process.env.PORT ?? 8001);

function send(response, status, body) {
  response.writeHead(status, { "content-type": "application/json" });
  response.end(JSON.stringify(body));
}

function authorized(request) {
  return request.headers.authorization === `Bearer ${token}`;
}

async function jsonBody(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > 64 * 1024) throw new Error("request too large");
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

createServer(async (request, response) => {
  try {
    if (request.method === "GET" && request.url === "/v1/health") {
      send(response, 200, { protocol: "poker-bot.v1", status: "ready" });
      return;
    }
    if (!authorized(request)) {
      send(response, 401, { error: "invalid bearer token" });
      return;
    }
    const body = await jsonBody(request);
    if (request.method === "POST" && request.url === "/v1/verify") {
      send(response, 200, { protocol: "poker-bot.v1", challenge: body.challenge });
      return;
    }
    if (request.method === "POST" && request.url === "/v1/action") {
      const allowed = new Set(body.legal_actions.map((item) => item.action));
      const action = allowed.has("check") ? "check" : allowed.has("call") ? "call" : "fold";
      send(response, 200, {
        protocol: "poker-bot.v1",
        tournament_id: body.tournament_id,
        table_id: body.table_id,
        hand_id: body.hand_id,
        decision_id: body.decision_id,
        table_version: body.table_version,
        action,
        amount_to: null,
      });
      return;
    }
    send(response, 404, { error: "not found" });
  } catch {
    send(response, 400, { error: "invalid request" });
  }
}).listen(port, "0.0.0.0", () => {
  console.log(`Poker bot listening on port ${port}`);
});
