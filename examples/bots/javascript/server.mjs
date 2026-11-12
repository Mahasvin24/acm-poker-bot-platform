// Minimal dependency-free Node.js participant bot. Run with: BOT_TOKEN=... node server.mjs
import { createServer } from "node:http";
import { chooseAction } from "./strategy.mjs";

const token = process.env.BOT_TOKEN ?? "replace-me";
const games = new Map(); // State is isolated by match_id.
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
      send(response, 200, { protocol: "poker-bot.v2", status: "ready" });
      return;
    }
    if (!authorized(request)) {
      send(response, 401, { error: "invalid bearer token" });
      return;
    }
    const body = await jsonBody(request);
    if (request.method === "POST" && request.url === "/v1/verify") {
      send(response, 200, { protocol: "poker-bot.v2", challenge: body.challenge });
      return;
    }
    if (request.method === "POST" &&
        ["/v1/game/start", "/v1/game/end"].includes(request.url)) {
      if (body.protocol !== "poker-bot.v2" ||
          typeof body.match_id !== "string" || !body.match_id ||
          typeof body.entrant_id !== "string" || !body.entrant_id) {
        send(response, 400, { error: "invalid game notification" });
        return;
      }
      if (request.url === "/v1/game/start") {
        // Duplicate starts must not erase accumulated state.
        if (!games.has(body.match_id)) games.set(body.match_id, {});
      } else {
        games.delete(body.match_id);
      }
      send(response, 200, {
        protocol: "poker-bot.v2", match_id: body.match_id, entrant_id: body.entrant_id,
      });
      return;
    }
    if (request.method === "POST" && request.url === "/v1/action") {
      // Recover when the bot restarts or misses the start notification.
      if (!games.has(body.match_id)) games.set(body.match_id, {});
      const { action, amount_to } = chooseAction(body);
      send(response, 200, {
        protocol: "poker-bot.v2",
        match_id: body.match_id,
        table_id: body.table_id,
        hand_id: body.hand_id,
        decision_id: body.decision_id,
        table_version: body.table_version,
        action,
        amount_to,
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
