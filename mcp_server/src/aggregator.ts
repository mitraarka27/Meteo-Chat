/**
 * aggregator.ts
 * -------------
 * Region sampling and statistical aggregations for hourly series.
 * - adaptiveGrid(bbox)
 * - summarizeHourUTC(times, rows)              → mean ± IQR by UTC hour
 * - climateBlocks(timesUTC, rows, utcOff, lat) → Long-term / Seasonal / Diurnal(local) / Spatial(lat bands)
 */

function quantile(arr: number[], p: number) {
  const a = arr.filter((x) => Number.isFinite(x)).sort((x, y) => x - y);
  if (!a.length) return NaN;
  const i = (a.length - 1) * p;
  const b = Math.floor(i);
  const f = i - b;
  return a[b] + ((a[b + 1] - a[b]) || 0) * f;
}

export function adaptiveGrid([minLat, minLon, maxLat, maxLon]: [number, number, number, number]) {
  // Area-based step (km^2) → step in degrees; cap N to keep it free-tier friendly.
  const dLat = Math.abs(maxLat - minLat), dLon = Math.abs(maxLon - minLon);
  const areaKm2 = dLat * dLon * 111 * 111;
  const step = areaKm2 > 2e6 ? 2.0 : areaKm2 > 5e4 ? 1.0 : 0.5;
  const pts: { lat: number; lon: number }[] = [];
  for (let lat = minLat; lat <= maxLat; lat += step) {
    for (let lon = minLon; lon <= maxLon; lon += step) {
      pts.push({ lat: +lat.toFixed(3), lon: +lon.toFixed(3) });
    }
  }
  return pts.slice(0, 150); // guardrail
}

export function summarizeHourUTC(times: string[], rows: number[][]) {
  // rows: per-sample point → array(time) of values
  const byHour: number[][] = Array.from({ length: 24 }, () => []);
  for (let t = 0; t < times.length; t++) {
    const hr = new Date(times[t]).getUTCHours();
    const vals = rows.map((r) => r[t]).filter((v) => Number.isFinite(v)) as number[];
    if (vals.length) byHour[hr].push(...vals);
  }
  const mean = byHour.map((a) => (a.length ? a.reduce((s, x) => s + x, 0) / a.length : null));
  const iqr = byHour.map((a) => (a.length ? quantile(a, 0.75) - quantile(a, 0.25) : null));
  return { by: "hour", index: [...Array(24).keys()], mean, iqr };
}

export function climateBlocks(
  timesUTC: string[],
  rows: number[][],
  utcOffsetsSec: number[],
  lats: number[]
) {
  // Flatten all values
  const all: number[] = [];
  for (let i = 0; i < rows.length; i++) for (let t = 0; t < rows[i].length; t++) {
    const v = rows[i][t]; if (Number.isFinite(v)) all.push(v);
  }
  const ltMean = all.length ? all.reduce((s, x) => s + x, 0) / all.length : null;
  const ltP10 = all.length ? quantile(all, 0.10) : null;
  const ltP90 = all.length ? quantile(all, 0.90) : null;
  const ltIQR = all.length ? quantile(all, 0.75) - quantile(all, 0.25) : null;

  // Seasonal (monthly) from UTC timestamps
  const byMonth: number[][] = Array.from({ length: 12 }, () => []);
  for (let t = 0; t < timesUTC.length; t++) {
    const m = new Date(timesUTC[t]).getUTCMonth();
    const vals = rows.map((r) => r[t]).filter(Number.isFinite) as number[];
    if (vals.length) byMonth[m].push(...vals);
  }
  const monthMean = byMonth.map((a) => (a.length ? a.reduce((s, x) => s + x, 0) / a.length : null));
  const monthIQR = byMonth.map((a) => (a.length ? quantile(a, 0.75) - quantile(a, 0.25) : null));
  const monthIdx = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

  // Diurnal (LOCAL hour) using per-point utc_offset_seconds
  const byHourLocal: number[][] = Array.from({ length: 24 }, () => []);
  for (let i = 0; i < rows.length; i++) {
    const off = utcOffsetsSec[i] || 0;
    for (let t = 0; t < timesUTC.length; t++) {
      const v = rows[i][t]; if (!Number.isFinite(v)) continue;
      const ts = new Date(new Date(timesUTC[t]).getTime() + off * 1000);
      const h = ts.getHours();
      byHourLocal[h].push(v);
    }
  }
  const hourMean = byHourLocal.map((a) => (a.length ? a.reduce((s, x) => s + x, 0) / a.length : null));
  const hourIQR = byHourLocal.map((a) => (a.length ? quantile(a, 0.75) - quantile(a, 0.25) : null));
  const hourIdx = [...Array(24).keys()];

  // Spatial (lat bands) — simple bands (°N), only for Northern Hemisphere focus; extend as needed
  const bands: [number, number][] = [[6,15],[15,24],[24,33],[33,42],[42,51],[51,60]];
  const bandVals: number[][] = bands.map(() => []);
  for (let i = 0; i < rows.length; i++) {
    const valid = rows[i].filter(Number.isFinite) as number[];
    if (!valid.length) continue;
    const vmean = valid.reduce((s, x) => s + x, 0) / valid.length;
    const lat = lats[i];
    for (let b = 0; b < bands.length; b++) {
      const [a, z] = bands[b];
      if (lat >= a && lat < z) { bandVals[b].push(vmean); break; }
    }
  }
  const bandMean = bandVals.map((a) => (a.length ? a.reduce((s, x) => s + x, 0) / a.length : null));
  const bandIQR = bandVals.map((a) => (a.length ? quantile(a, 0.75) - quantile(a, 0.25) : null));
  const bandIdx = bands.map(([a, b]) => `${a}–${b}°N`);

  return {
    long_term: { mean: ltMean, p10: ltP10, p90: ltP90, iqr: ltIQR },
    seasonal:  { by: "month" as const, index: monthIdx, mean: monthMean, iqr: monthIQR },
    diurnal:   { by: "hour_local" as const, index: hourIdx, mean: hourMean, iqr: hourIQR },
    spatial:   { by: "lat_band" as const, index: bandIdx, mean: bandMean, iqr: bandIQR }
  };
}