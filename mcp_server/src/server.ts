/**
 * Minimal HTTP server exposing MCP routes:
 *  - POST /describe_capabilities
 *  - POST /resolve_location
 *  - POST /plan_query
 *  - POST /execute_plan
 *
 * The server orchestrates calls to modules:
 *  capabilities.ts (discovery & cache)
 *  location.ts     (geocoding & timezone)
 *  planner.ts      (variable alias → canonical param mapping)
 *  executor.ts     (Open-Meteo calls, aggregation, unit transforms)
 *
 * Implementation notes:
 *  - Keep this module tiny: just routing + validation + error handling.
 */
import { createServer } from "node:http";
import { z } from "zod";
import { describeCapabilities } from "./capabilities";
import { resolveLocation, getTimezone } from "./location";
import { planQuery } from "./planner";
import { executePlan } from "./executor";

const JsonBody = async (req: any): Promise<any> =>
  await new Promise((res, rej) => {
    let d = "";
    req.on("data", (c: any) => (d += c));
    req.on("end", () => {
      try { res(d ? JSON.parse(d) : {}); } catch (e) { rej(e); }
    });
  });

const RouteMap: Record<string, (b: any) => Promise<any>> = {
  "/describe_capabilities": async () => await describeCapabilities(),
  "/resolve_location": async (b) => {
    const schema = z.object({ query: z.string().min(1) });
    const { query } = schema.parse(b);
    return await resolveLocation(query);
  },
  "/get_timezone": async (b) => {
    const schema = z.object({ lat: z.number(), lon: z.number() });
    const { lat, lon } = schema.parse(b);
    return await getTimezone(lat, lon);
  },
  "/plan_query": async (b) => await planQuery(b),
  "/execute_plan": async (b) => await executePlan(b)
};

createServer(async (req, res) => {
  try {
    if (req.method !== "POST" || !req.url || !(req.url in RouteMap)) {
      res.writeHead(404, { "content-type": "application/json" });
      return res.end(JSON.stringify({ error: { code: "not_found" } }));
    }
    const body = await JsonBody(req);
    const out = await RouteMap[req.url](body);
    res.writeHead(200, { "content-type": "application/json" });
    return res.end(JSON.stringify(out));
  } catch (e: any) {
    res.writeHead(400, { "content-type": "application/json" });
    return res.end(JSON.stringify({ error: { message: String(e?.message || e) } }));
  }
}).listen(8787, "127.0.0.1", () => {
  console.log("✅ MCP server listening on http://127.0.0.1:8787");
});