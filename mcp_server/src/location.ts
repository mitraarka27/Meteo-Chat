/**
 * location.ts
 * Geocoding & timezone helpers with caching + polite rate limiting.
 */
import { fetchJSONWithCache, RateLimiter } from "./utils";

export type ResolvedLocation = {
  display_name: string;
  lat: number;
  lon: number;
  bbox: [number, number, number, number]; // [south, west, north, east]
  area_km2: number;
};

const RL = new RateLimiter(1100); // ~1 rps for Nominatim
const NOM_BASE = "https://nominatim.openstreetmap.org";

export async function resolveLocation(query: string): Promise<ResolvedLocation> {
  const url = `${NOM_BASE}/search?format=json&q=${encodeURIComponent(query)}&limit=1`;
  const j: any[] = await fetchJSONWithCache(url, {
    ttlMs: 24 * 60 * 60 * 1000, // 1 day cache
    rl: RL,
    rlKey: "nominatim",
    headers: { "User-Agent": "WeatherAI/0.2 (demo contact: example@example.com)" }
  });
  if (!j?.length) throw new Error("place_not_found");
  const it = j[0];
  const bboxRaw = it.boundingbox.map((x: string) => parseFloat(x));
  const [south, north, west, east] = bboxRaw;
  const area_km2 = Math.max(1, Math.abs(east - west) * Math.abs(north - south) * 111 * 111);
  return {
    display_name: it.display_name,
    lat: parseFloat(it.lat),
    lon: parseFloat(it.lon),
    bbox: [south, west, north, east],
    area_km2
  };
}

export async function getTimezone(lat: number, lon: number): Promise<{ tz: string }> {
  const url = `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&current=temperature_2m&timezone=auto`;
  const j: any = await fetchJSONWithCache(url, { ttlMs: 6 * 60 * 60 * 1000, rl: RL, rlKey: "open-meteo" });
  return { tz: j?.timezone || "UTC" };
}