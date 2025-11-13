/**
 * location.ts
 * Robust geocoding & timezone helpers using Open-Meteo Geocoding.
 * Removes all Nominatim dependencies (403 issues) and adds caching.
 */

// mcp_server/src/location.ts

import type { Request, Response } from "express";
import { z } from "zod";
import { fetch } from "undici";

const OpenMeteoGeoSchema = z.object({
  results: z
    .array(
      z.object({
        id: z.number().optional(),
        name: z.string(),
        country: z.string().optional(),
        country_code: z.string().optional(),
        admin1: z.string().optional(),
        latitude: z.number(),
        longitude: z.number(),
        elevation: z.number().optional(),
        population: z.number().optional(),
        timezone: z.string().optional(),
        feature_code: z.string().optional(),
      })
    )
    .optional(),
});

type GeoResult = z.infer<typeof OpenMeteoGeoSchema>["results"][number];

// ---- helpers ---------------------------------------------------------------

function looksLikeLatLon(q: string) {
  const m = q.match(
    /^\s*(-?\d+(\.\d+)?)\s*,\s*(-?\d+(\.\d+)?)\s*$/ // lat, lon
  );
  if (!m) return null;
  const lat = Number(m[1]);
  const lon = Number(m[3]);
  if (Number.isNaN(lat) || Number.isNaN(lon)) return null;
  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
  return { lat, lon };
}

function buildLabel(r: GeoResult): string {
  const parts = [r.name];
  if (r.admin1) parts.push(r.admin1);
  if (r.country) parts.push(r.country);
  return parts.join(", ");
}

function scoreCandidate(query: string, r: GeoResult): number {
  const qParts = query
    .split(",")
    .map((s) => s.trim().toLowerCase())
    .filter((s) => s.length > 0);

  const nameHint = qParts[0] ?? "";
  const regionHints = qParts.slice(1); // e.g. ["or", "usa"]

  const admin1 = (r.admin1 ?? "").toLowerCase();
  const country = (r.country ?? "").toLowerCase();
  const ccode = (r.country_code ?? "").toLowerCase();
  const name = (r.name ?? "").toLowerCase();

  let score = 0;

  // exact city-name match gets a small boost
  if (name === nameHint) score += 3;

  for (const hRaw of regionHints) {
    const h = hRaw.toLowerCase();

    // country code like "US", "IN"
    if (h.length <= 3 && ccode === h.toUpperCase()) score += 10;

    // state/region like "oregon", "ma"
    if (admin1.includes(h)) score += 8;

    // country name like "united states", "india"
    if (country.includes(h)) score += 6;
  }

  // Capital / major places
  if (r.feature_code && r.feature_code.startsWith("PPL")) {
    score += 1;
  }

  // Population as gentle tiebreaker
  if (r.population && r.population > 0) {
    score += Math.log10(r.population + 1);
  }

  return score;
}

// ---- main handler ----------------------------------------------------------

export async function resolveLocation(req: Request, res: Response) {
  try {
    const raw = (req.body?.query ?? "").toString().trim();
    if (!raw) {
      return res.status(400).json({ error: "Missing 'query' string" });
    }

    // 1) Direct lat,lon support
    const coord = looksLikeLatLon(raw);
    if (coord) {
      const location = {
        name: raw,
        latitude: coord.lat,
        longitude: coord.lon,
        label: raw,
      };
      return res.json({
        query: raw,
        location,
        candidates: [location],
      });
    }

    // 2) Name-based geocoding via Open-Meteo
    const url = new URL("https://geocoding-api.open-meteo.com/v1/search");
    url.searchParams.set("name", raw);
    url.searchParams.set("count", "10");
    url.searchParams.set("language", "en");
    url.searchParams.set("format", "json");

    const resp = await fetch(url);
    if (!resp.ok) {
      const text = await resp.text();
      return res
        .status(502)
        .json({ error: "Geocoding upstream error", status: resp.status, body: text });
    }

    const json = await resp.json();
    const parsed = OpenMeteoGeoSchema.parse(json);
    const results = parsed.results ?? [];

    if (results.length === 0) {
      return res
        .status(404)
        .json({ error: `No locations found for query '${raw}'` });
    }

    // 3) Score + pick best candidate
    const scored = results
      .map((r) => ({ r, score: scoreCandidate(raw, r) }))
      .sort((a, b) => b.score - a.score);

    const best = scored[0].r;

    const location = {
      id: best.id,
      name: best.name,
      admin1: best.admin1,
      country: best.country,
      country_code: best.country_code,
      latitude: best.latitude,
      longitude: best.longitude,
      elevation: best.elevation,
      population: best.population,
      timezone: best.timezone,
      label: buildLabel(best),
    };

    return res.json({
      query: raw,
      location,
      candidates: scored.map(({ r }) => ({
        id: r.id,
        name: r.name,
        admin1: r.admin1,
        country: r.country,
        country_code: r.country_code,
        latitude: r.latitude,
        longitude: r.longitude,
        elevation: r.elevation,
        population: r.population,
        timezone: r.timezone,
        feature_code: r.feature_code,
        label: buildLabel(r),
      })),
    });
  } catch (err: any) {
    console.error("[resolveLocation] Error:", err);
    return res.status(500).json({ error: "Internal location resolver error" });
  }
}