/**
 * location.ts
 * Robust geocoding & timezone helpers using Open-Meteo Geocoding.
 * Keeps the old ResolvedLocation interface so the rest of MCP stays unchanged.
 */

import { fetchJSONWithCache, RateLimiter } from "./utils";

export type ResolvedLocation = {
  display_name: string;
  lat: number;
  lon: number;
  bbox: [number, number, number, number]; // [south, west, north, east]
  area_km2: number;
};

// Open-Meteo endpoints do NOT need rate limiting, but keep RL for uniformity.
const RL = new RateLimiter(200); // very gentle, 0.2s spacing

// --- helpers ----------------------------------------------------------

/** Detect "lat, lon" input like "37.8, -122.4". */
function looksLikeLatLon(q: string): { lat: number; lon: number } | null {
  const m = q.match(/^\s*(-?\d+(\.\d+)?)\s*,\s*(-?\d+(\.\d+)?)\s*$/);
  if (!m) return null;
  const lat = Number(m[1]);
  const lon = Number(m[3]);
  if (Number.isNaN(lat) || Number.isNaN(lon)) return null;
  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
  return { lat, lon };
}

type GeoResult = {
  id?: number;
  name: string;
  country?: string;
  country_code?: string;
  admin1?: string;
  latitude: number;
  longitude: number;
  elevation?: number;
  population?: number;
  timezone?: string;
  feature_code?: string;
};

/** Human-readable label like "Salem, Oregon, United States" */
function buildLabel(it: GeoResult): string {
  const parts: string[] = [];
  if (it.name) parts.push(it.name);
  if (it.admin1) parts.push(it.admin1);
  if (it.country) parts.push(it.country);
  return parts.join(", ");
}

/**
 * Score candidates using user-provided hints after the first comma.
 * e.g. "Salem, OR, USA" → nameHint="salem", regionHints=["or", "usa"].
 */
function scoreCandidate(query: string, it: GeoResult): number {
  const qParts = query
    .split(",")
    .map((s) => s.trim().toLowerCase())
    .filter((s) => s.length > 0);

  const nameHint = qParts[0] ?? "";
  const regionHints = qParts.slice(1); // e.g. ["or", "usa"]

  const admin1 = (it.admin1 ?? "").toLowerCase();
  const country = (it.country ?? "").toLowerCase();
  const ccode = (it.country_code ?? "").toLowerCase();
  const name = (it.name ?? "").toLowerCase();

  let score = 0;

  // city-name match
  if (name === nameHint) score += 3;

  for (const hRaw of regionHints) {
    const h = hRaw.toLowerCase();

    // country code like "US", "IN", "DE"
    if (h.length <= 3 && ccode === h.toUpperCase()) score += 10;

    // state/region like "oregon", "ma", "bavaria"
    if (admin1.includes(h)) score += 8;

    // country name like "united states", "india"
    if (country.includes(h)) score += 6;
  }

  // Major populated places
  if (it.feature_code && it.feature_code.startsWith("PPL")) {
    score += 1;
  }

  // Population as tie-breaker
  if (it.population && it.population > 0) {
    score += Math.log10(it.population + 1);
  }

  return score;
}

// --- main resolver ----------------------------------------------------

/**
 * Resolve a place name → coordinates using Open-Meteo Geocoding API.
 * Returns structure identical to old Nominatim-based version so
 * the rest of MCP stays unchanged.
 *
 * Supports:
 *   - "Salem"
 *   - "Salem, OR"
 *   - "Salem, Oregon, USA"
 *   - "44.9429, -123.0351" (lat,lon anywhere on globe)
 */
export async function resolveLocation(query: string): Promise<ResolvedLocation> {
  const q = (query || "").trim();
  if (!q) {
    throw new Error("empty_query");
  }

  // 1) Direct lat,lon support, no geocoding needed.
  const coord = looksLikeLatLon(q);
  if (coord) {
    const { lat, lon } = coord;

    const south = lat - 0.05;
    const north = lat + 0.05;
    const west = lon - 0.05;
    const east = lon + 0.05;

    const area_km2 =
      Math.max(1, Math.abs(east - west) * Math.abs(north - south) * 111 * 111);

    return {
      display_name: q,
      lat,
      lon,
      bbox: [south, west, north, east],
      area_km2,
    };
  }

  // 2) Name-based geocoding via Open-Meteo (ask for multiple, then score).
  const url =
    `https://geocoding-api.open-meteo.com/v1/search` +
    `?name=${encodeURIComponent(q)}` +
    `&count=10&language=en&format=json`;

  const j: any = await fetchJSONWithCache(url, {
    ttlMs: 24 * 60 * 60 * 1000, // 1 day cache
    rl: RL,
    rlKey: "openmeteo_geocode",
  });

  if (!j?.results || j.results.length === 0) {
    throw new Error("place_not_found");
  }

  const results: GeoResult[] = j.results;

  // 3) Score candidates and pick best one using user hints.
  const scored = results
    .map((it) => ({ it, score: scoreCandidate(q, it) }))
    .sort((a, b) => b.score - a.score);

  const best = scored[0].it;

  const lat = best.latitude;
  const lon = best.longitude;

  // Same tight bbox logic as original version.
  const south = lat - 0.05;
  const north = lat + 0.05;
  const west = lon - 0.05;
  const east = lon + 0.05;

  const area_km2 =
    Math.max(1, Math.abs(east - west) * Math.abs(north - south) * 111 * 111);

  const display_name = buildLabel(best) || q;

  return {
    display_name,
    lat,
    lon,
    bbox: [south, west, north, east],
    area_km2,
  };
}

/**
 * Timezone lookup using Open-Meteo.
 */
export async function getTimezone(
  lat: number,
  lon: number
): Promise<{ tz: string }> {
  const url =
    `https://api.open-meteo.com/v1/forecast` +
    `?latitude=${lat}&longitude=${lon}` +
    `&current=temperature_2m&timezone=auto`;

  const j: any = await fetchJSONWithCache(url, {
    ttlMs: 6 * 60 * 60 * 1000,
    rl: RL,
    rlKey: "openmeteo_tz",
  });

  return { tz: j?.timezone || "UTC" };
}