/**
 * capabilities.ts
 * ----------------
 * Dynamic discovery + daily-cached capability index for Open-Meteo.
 * If metadata endpoint is insufficient, fall back to a versioned descriptor.
 *
 * Exposes:
 *  - describeCapabilities(): Promise<Capabilities>
 *
 * TODOs:
 *  - Implement metadata scraping/reading to expand variables & units.
 *  - Persist cache to disk (mcp_server/cache/) with a daily TTL.
 */
import { fetch } from "undici";

export type CapabilityVariable = {
  id: string;           // canonical parameter name, e.g., "temperature_2m"
  label: string;        // human-readable label
  unit?: string;        // canonical unit
  time_modes: ("historical" | "current" | "forecast" | "climate")[];
  aliases?: string[];   // fuzzy matches
};

export type Capabilities = {
  provider: "open-meteo";
  last_updated: string;
  variables: CapabilityVariable[];
};

let memCache: { value: Capabilities; expires: number } | null = null;
const DAY = 24 * 60 * 60 * 1000;

/** Seed descriptor: safe minimal set (extend at runtime) */
const seed: Capabilities = {
  provider: "open-meteo",
  last_updated: new Date().toISOString(),
  variables: [
    { id: "temperature_2m", label: "2 m air temperature", unit: "°C", time_modes: ["historical","current","forecast"], aliases: ["temperature","air temp","t2m"] },
    { id: "relative_humidity_2m", label: "2 m relative humidity", unit: "%", time_modes: ["historical","current","forecast"], aliases: ["humidity","rh"] },
    { id: "windspeed_10m", label: "10 m wind speed", unit: "m/s", time_modes: ["historical","current","forecast"], aliases: ["wind","winds","wind speed"] },
    { id: "windgusts_10m", label: "10 m wind gusts", unit: "m/s", time_modes: ["current","forecast"], aliases: ["gust","gusts","wind gusts"] },
    { id: "cloudcover", label: "Total cloud cover", unit: "%", time_modes: ["historical","current","forecast"], aliases: ["clouds","cloud cover"] },
    { id: "precipitation", label: "Precipitation", unit: "mm", time_modes: ["historical","current","forecast"], aliases: ["rain","rainfall","precip"] }
  ]
};

async function refreshFromOpenMeteo(): Promise<Capabilities> {
  // NOTE: Open-Meteo does not expose a single "catalog" endpoint.
  // Strategy: hit a harmless forecast query and infer supported fields.
  try {
    const url = "https://api.open-meteo.com/v1/forecast?latitude=0&longitude=0&hourly=temperature_2m,relative_humidity_2m,windspeed_10m,cloudcover,precipitation&timezone=auto";
    const r = await fetch(url);
    if (!r.ok) throw new Error("open-meteo-metadata-failed");
    // In a fuller impl, parse body to validate parameter presence/units.
    return { ...seed, last_updated: new Date().toISOString() };
  } catch {
    return seed;
  }
}

export async function describeCapabilities(): Promise<Capabilities> {
  if (memCache && Date.now() < memCache.expires) return memCache.value;
  const fresh = await refreshFromOpenMeteo();
  memCache = { value: fresh, expires: Date.now() + DAY };
  return fresh;
}