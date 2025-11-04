/**
 * planner.ts
 * ----------
 * Maps free-text variable names to canonical Open-Meteo parameters,
 * infers time_mode (e.g., "typical" → "historical"), and assembles a plan.
 *
 * Input payload shape (loose):
 *  { capabilities, place_geometry, time_mode, variables, options? }
 *
 * Output plan:
 *  { place_geometry, time_mode, items[], citations[], options?, meta? }
 */
import { z } from "zod";
import { describeCapabilities } from "./capabilities";

const PlanIn = z.object({
  capabilities: z.any().optional(),
  place_geometry: z.object({
    type: z.enum(["Point", "BBox"]),
    lat: z.number().optional(),
    lon: z.number().optional(),
    bbox: z.tuple([z.number(), z.number(), z.number(), z.number()]).optional()
  }),
  time_mode: z.enum(["current", "forecast", "historical", "climate"]).default("forecast"),
  variables: z.array(z.string()).default([]),
  options: z
    .object({
      historical_depth: z.enum(["normal", "deep"]).optional(),
      historical_years: z.number().int().positive().max(50).optional()
    })
    .optional()
});

const CLIMATE_HINTS = ["typical", "climatology", "normal", "long-term"];

function score(a: string, b: string): number {
  const A = new Set(a.toLowerCase().split(/\W+/).filter(Boolean));
  const B = new Set(b.toLowerCase().split(/\W+/).filter(Boolean));
  let inter = 0;
  A.forEach((t) => {
    if (B.has(t)) inter++;
  });
  return inter / Math.max(1, Math.max(A.size, B.size));
}

export async function planQuery(raw: any) {
  const { place_geometry, time_mode, variables, options } = PlanIn.parse(raw);
  const caps = raw.capabilities || (await describeCapabilities());

  const joined = variables.join(" ").toLowerCase();
  const wantsClimate = CLIMATE_HINTS.some((k) => joined.includes(k));
  const chosenMode = wantsClimate ? "historical" : time_mode;

  const items = variables.map((req: string) => {
    let best: any = null,
      bestScore = 0;
    for (const v of caps.variables) {
      const s = Math.max(
        score(req, v.id),
        score(req, v.label),
        ...(v.aliases || []).map((a: string) => score(req, a))
      );
      if (s > bestScore) {
        bestScore = s;
        best = v;
      }
    }
    if (best && bestScore >= 0.33) {
      return {
        requested: req,
        canonical: best.id,
        unit: best.unit,
        provider: "open-meteo",
        time_mode: chosenMode
      };
    }
    return {
      requested: req,
      canonical: undefined,
      provider: undefined,
      time_mode: chosenMode,
      fallback_candidates: [
        { provider: "meteostat", capability_tag: "station-met" },
        { provider: "climateserv", capability_tag: "precip-land-only" },
        { provider: "nasa-power", capability_tag: "radiation" },
        { provider: "openaq", capability_tag: "air-quality" },
        { provider: "nsidc", capability_tag: "sea-ice" }
      ]
    };
  });

  // ---- historical depth (years) chosen here so UI can display it immediately
  const years =
    options?.historical_years ??
    (options?.historical_depth === "deep" ? 10 : 1);

  const plan: any = {
    place_geometry,
    time_mode: chosenMode,
    items,
    citations: ["Open-Meteo (capability discovery cache)"],
    options
  };

  if (chosenMode === "historical") {
    const end = new Date();
    const start = new Date(end);
    start.setUTCFullYear(end.getUTCFullYear() - years);
    const toISO = (d: Date) => d.toISOString().slice(0, 10);
    plan.meta = {
      historical_window: { start: toISO(start), end: toISO(end), years }
    };
  }

  return plan;
}