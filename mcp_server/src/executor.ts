/**
 * executor.ts
 * -----------
 * Executes a plan:
 *  - Point: single OM call
 *  - Region: adaptive grid sampling + mean ± IQR by UTC hour
 *  - Historical ("typical"): now supports multi-year windows (1y normal / 10y deep)
 * Caching and polite 1 req/s rate limiting included.
 */

import { adaptiveGrid, summarizeHourUTC, climateBlocks } from "./aggregator";
import { fetchJSONWithCache, MemoryCache, RateLimiter } from "./utils";

type Geometry =
  | { type: "Point"; lat: number; lon: number }
  | { type: "BBox"; bbox: [number, number, number, number] };

type PlanItem = { requested: string; canonical?: string; unit?: string; provider?: string };

type Plan = {
  place_geometry: Geometry;
  time_mode: "current" | "forecast" | "historical" | "climate";
  items: PlanItem[];
  options?: { historical_depth?: "normal" | "deep"; historical_years?: number };
  meta?: { historical_window?: { start: string; end: string; years: number } };
};

const RL = new RateLimiter(1000); // 1 req/s (polite)
const OM_CACHE = new MemoryCache<any>(60_000); // 1 min default (overridden per call)

// Helpers to build URLs
function urlForecast(lat: number, lon: number, hourlyVars: string[], tz = "auto") {
  const u = new URL("https://api.open-meteo.com/v1/forecast");
  u.searchParams.set("latitude", String(lat));
  u.searchParams.set("longitude", String(lon));
  if (hourlyVars.length) u.searchParams.set("hourly", hourlyVars.join(","));
  u.searchParams.set("timezone", tz);
  return u.toString();
}

function urlArchive(
  lat: number,
  lon: number,
  hourlyVars: string[],
  start: string,
  end: string,
  tz = "auto"
) {
  const u = new URL("https://archive-api.open-meteo.com/v1/era5");
  u.searchParams.set("latitude", String(lat));
  u.searchParams.set("longitude", String(lon));
  if (hourlyVars.length) u.searchParams.set("hourly", hourlyVars.join(","));
  u.searchParams.set("start_date", start);
  u.searchParams.set("end_date", end);
  u.searchParams.set("timezone", tz);
  return u.toString();
}

async function getOMPoint(
  lat: number,
  lon: number,
  hourlyVars: string[],
  mode: "forecast" | "historical",
  range?: { start: string; end: string }
) {
  const tz = "auto";
  const rangeKey =
    mode === "historical" && range ? `:${range.start}->${range.end}` : "";
  const key = `${mode}:${lat.toFixed(3)},${lon.toFixed(3)}:${hourlyVars
    .slice()
    .sort()
    .join(",")}:${tz}${rangeKey}`;

  const cacheHit = OM_CACHE.get(key);
  if (cacheHit) return cacheHit;

  const url =
    mode === "forecast"
      ? urlForecast(lat, lon, hourlyVars, tz)
      : urlArchive(
          lat,
          lon,
          hourlyVars,
          range?.start ??
            new Date(new Date().getUTCFullYear() - 1, 0, 1)
              .toISOString()
              .slice(0, 10),
          range?.end ??
            new Date(new Date().getUTCFullYear() - 1, 11, 31)
              .toISOString()
              .slice(0, 10),
          tz
        );

  const json = await fetchJSONWithCache(url, {
    ttlMs: mode === "forecast" ? 60_000 : 24 * 60 * 60 * 1000,
    headers: { "User-Agent": "WeatherAI-MCP/0.3 (demo)" },
    rl: RL,
    rlKey: "open-meteo"
  });
  OM_CACHE.set(key, json, mode === "forecast" ? 60_000 : 24 * 60 * 60 * 1000);
  return json;
}

export async function executePlan({ plan }: { plan: Plan }) {
  const vars = plan.items
    .filter((i) => i.canonical && i.provider === "open-meteo")
    .map((i) => i.canonical!) as string[];

  const citations = new Set<string>();
  const limitations: string[] = [];

  const modeIsHistorical = plan.time_mode === "historical";
  citations.add(modeIsHistorical ? "Open-Meteo ERA5 (archive)" : "Open-Meteo Forecast");

  // Determine historical window (supports deep)
  const years =
    plan.options?.historical_years ??
    (plan.options?.historical_depth === "deep" ? 10 : 1);

  const endDate = new Date();
  const startDate = new Date(endDate);
  startDate.setUTCFullYear(endDate.getUTCFullYear() - years);
  const toISO = (d: Date) => d.toISOString().slice(0, 10);
  const HIST_RANGE = { start: toISO(startDate), end: toISO(endDate) };

  // -------- Point mode --------
  if (plan.place_geometry.type === "Point") {
    const { lat, lon } = plan.place_geometry;
    if (lat == null || lon == null) throw new Error("point_missing_latlon");

    const data = await getOMPoint(
      lat,
      lon,
      vars,
      modeIsHistorical ? "historical" : "forecast",
      modeIsHistorical ? HIST_RANGE : undefined
    );

    const hourly = data?.hourly || {};
    const times: string[] = hourly?.time || [];
    const series = vars.map((v) => ({
      variable: v,
      unit: plan.items.find((x) => x.canonical === v)?.unit,
      times,
      values: hourly?.[v] || [],
      provenance: {
        provider: "open-meteo",
        endpoint: modeIsHistorical ? "archive/hourly" : "forecast/hourly",
        proxy_used: false
      }
    }));

    const climatologies =
      modeIsHistorical && times.length
        ? vars.map((v) => {
            const row = [hourly?.[v] || []]; // single "point" row
            const blocks = climateBlocks(times, row, [data?.utc_offset_seconds ?? 0], [lat]);
            return {
              variable: v,
              unit: plan.items.find((x) => x.canonical === v)?.unit,
              blocks,
              provenance: { provider: "open-meteo", endpoint: "archive/hourly", proxy_used: false }
            };
          })
        : undefined;

    if (modeIsHistorical) {
      limitations.push(
        years > 1
          ? `Historical mode uses ~${years} years of hourly ERA5 archive (lightweight aggregation).`
          : "Historical mode uses a single recent full year (hourly) from archive (lightweight)."
      );
    } else {
      limitations.push("Point forecast reflects model grid; local effects may vary.");
    }

    return {
      mode: "point",
      series,
      ...(climatologies ? { climatologies } : {}),
      ...(modeIsHistorical ? { window: HIST_RANGE } : {}),
      citations: Array.from(citations),
      limitations
    };
  }

  // -------- Region mode --------
  const [minLat, minLon, maxLat, maxLon] = (plan.place_geometry as any).bbox!;
  const pts = adaptiveGrid([minLat, minLon, maxLat, maxLon]);

  const timesRef: { times: string[] | null } = { times: null };
  const rowsByVar: Record<string, number[][]> = {};
  const utcOffsets: number[] = [];
  const lats: number[] = [];

  for (const v of vars) rowsByVar[v] = [];

  for (let i = 0; i < pts.length; i++) {
    const p = pts[i];
    const resp = await getOMPoint(
      p.lat,
      p.lon,
      vars,
      modeIsHistorical ? "historical" : "forecast",
      modeIsHistorical ? HIST_RANGE : undefined
    );
    const hourly = resp?.hourly || {};
    if (!timesRef.times && hourly?.time) timesRef.times = hourly.time;

    for (const v of vars) rowsByVar[v].push(hourly?.[v] || []);
    utcOffsets.push(resp?.utc_offset_seconds ?? 0);
    lats.push(p.lat);
  }
  const times = (timesRef.times ?? []) as string[];

  const aggregates = vars.map((v) => ({
    variable: v,
    unit: plan.items.find((x) => x.canonical === v)?.unit,
    aggregation: summarizeHourUTC(times, rowsByVar[v]),
    provenance: {
      provider: "open-meteo",
      endpoint: modeIsHistorical ? "archive/hourly" : "forecast/hourly",
      proxy_used: false,
      notes: `N=${pts.length}`
    }
  }));

  const climatologies =
    modeIsHistorical && times.length
      ? vars.map((v) => ({
          variable: v,
          unit: plan.items.find((x) => x.canonical === v)?.unit,
          blocks: climateBlocks(times, rowsByVar[v], utcOffsets, lats),
          provenance: {
            provider: "open-meteo",
            endpoint: "archive/hourly",
            proxy_used: false,
            notes: `N=${pts.length}`
          }
        }))
      : undefined;

  if (modeIsHistorical) {
    limitations.push(
      years > 1
        ? `Historical mode uses ~${years} years of hourly ERA5 archive (lightweight aggregation).`
        : "Historical mode uses a single recent full year (hourly) from archive (lightweight)."
    );
  } else {
    limitations.push("Regional stats computed from an adaptive grid; may not reflect fine-scale extremes.");
  }

  return {
    mode: "region",
    aggregates,
    ...(climatologies ? { climatologies } : {}),
    ...(modeIsHistorical ? { window: HIST_RANGE } : {}),
    citations: Array.from(citations),
    limitations
  };
}