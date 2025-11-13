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
 *  - Keep this file tiny: only routing + validation + error handling.
 */

import { createServer } from "node:http";
import { z } from "zod";

import { describeCapabilities } from "./capabilities";
import { resolveLocation, getTimezone } from "./location";
import { planQuery } from "./planner";
import { executePlan } from "./executor";

/* ------------------------------ Utilities ------------------------------ */

const JsonBody = async (req: any): Promise<any> =>
  await new Promise((res, rej) => {
    let d = "";
    req.on("data", (c: any) => (d += c));
    req.on("end", () => {
      try {
        res(d ? JSON.parse(d) : {});
      } catch (e) {
        rej(e);
      }
    });
  });

const sendJSON = (res: any, code: number, payload: any) => {
  res.writeHead(code, { "content-type": "application/json" });
  return res.end(JSON.stringify(payload));
};

/* ------------------------------ Route Map ------------------------------ */

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

/* ------------------------------ HTTP Server ------------------------------ */

createServer(async (req, res) => {
  try {
    const url = req.url;

    // Reject anything except known POST routes
    if (req.method !== "POST" || !url || !(url in RouteMap)) {
      return sendJSON(res, 404, { error: { code: "not_found" } });
    }

    // Parse JSON body
    const body = await JsonBody(req);

    // Process route
    const result = await RouteMap[url](body);

    return sendJSON(res, 200, result);

  } catch (err: any) {
    // Standardized surface error
    const msg = err?.message || String(err);
    return sendJSON(res, 400, { error: { message: msg } });
  }
}).listen(8787, "127.0.0.1", () => {
  console.log("✅ MCP server listening on http://127.0.0.1:8787");
});
