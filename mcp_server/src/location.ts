/**
 * location.ts
 * Robust geocoding & timezone helpers using Open-Meteo Geocoding.
 * Removes all Nominatim dependencies (403 issues) and adds caching.
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

/** 
 * Resolve a place name → coordinates using Open-Meteo Geocoding API.
 * Returns structure identical to old Nominatim version so rest of MCP stays unchanged.
 */
export async function resolveLocation(query: string): Promise<ResolvedLocation> {
  const url =
    `https://geocoding-api.open-meteo.com/v1/search` +
    `?name=${encodeURIComponent(query)}&count=1&language=en&format=json`;

  const j: any = await fetchJSONWithCache(url, {
    ttlMs: 24 * 60 * 60 * 1000,  // 1 day cache
    rl: RL,
    rlKey: "openmeteo_geocode"
  });

  if (!j?.results || j.results.length === 0) {
    throw new Error("place_not_found");
  }

  const it = j.results[0];

  // Open-Meteo provides no explicit bbox → approximate small bounding box
  const lat = it.latitude;
  const lon = it.longitude;

  // Create a tight +/- 0.05° bbox (~5–7 km)
  const south = lat - 0.05;
  const north = lat + 0.05;
  const west  = lon - 0.05;
  const east  = lon + 0.05;

  const area_km2 =
    Math.max(1, Math.abs(east - west) * Math.abs(north - south) * 111 * 111);

  return {
    display_name: `${it.name}${it.country ? ", " + it.country : ""}`,
    lat,
    lon,
    bbox: [south, west, north, east],
    area_km2
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
    rlKey: "openmeteo_tz"
  });

  return { tz: j?.timezone || "UTC" };
}
