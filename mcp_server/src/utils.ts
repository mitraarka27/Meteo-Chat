/**
 * utils.ts
 * --------
 * In-memory cache, polite rate limiter, and a cached JSON fetch helper.
 * Keep it simple & process-local to stay free-tier friendly.
 */

type CacheEntry<T> = { v: T; exp: number };

export class MemoryCache<T = any> {
  private store = new Map<string, CacheEntry<T>>();
  constructor(private defaultTTLms = 60_000) {}

  get(k: string): T | undefined {
    const e = this.store.get(k);
    if (!e) return;
    if (Date.now() > e.exp) {
      this.store.delete(k);
      return;
    }
    return e.v;
  }

  set(k: string, v: T, ttlMs?: number) {
    this.store.set(k, { v, exp: Date.now() + (ttlMs ?? this.defaultTTLms) });
  }

  has(k: string) {
    const e = this.store.get(k);
    if (!e) return false;
    if (Date.now() > e.exp) {
      this.store.delete(k);
      return false;
    }
    return true;
  }
}

/** Simple domain-scoped rate limiter (min gap between calls). */
export class RateLimiter {
  private lastByKey = new Map<string, number>();
  constructor(private minGapMs = 1000) {}

  async wait(key = "default") {
    const now = Date.now();
    const last = this.lastByKey.get(key) ?? 0;
    const gap = now - last;
    const wait = Math.max(0, this.minGapMs - gap);
    if (wait > 0) await new Promise((r) => setTimeout(r, wait));
    this.lastByKey.set(key, Date.now());
  }
}

import { request as undici } from "undici";

/**
 * fetchJSONWithCache
 * - Uses MemoryCache
 * - Applies RateLimiter
 * - Returns parsed JSON
 */
export async function fetchJSONWithCache(
  url: string,
  opts: { ttlMs?: number; headers?: Record<string, string>; rl?: RateLimiter; rlKey?: string } = {}
) {
  const { ttlMs = 60_000, headers = {}, rl, rlKey = "default" } = opts;
  const key = `json:${url}`;
  if (!(globalThis as any).__WEA_CACHE__) (globalThis as any).__WEA_CACHE__ = new MemoryCache<any>(ttlMs);
  const cache = (globalThis as any).__WEA_CACHE__ as MemoryCache<any>;

  if (cache.has(key)) return cache.get(key);

  if (rl) await rl.wait(rlKey);
  const resp = await undici(url, { headers });
  // @ts-ignore undici's response shape
  const status = resp.status ?? resp.statusCode ?? 200;
  if (status >= 400) throw new Error(`fetch_failed ${status} ${url}`);
  // @ts-ignore undici's response shape
  const j = await (resp.body?.json ? resp.body.json() : resp.body);
  cache.set(key, j, ttlMs);
  return j;
}

/** Optional helper if you want it elsewhere later */
export function computeHistoricalWindow(years: number) {
  const end = new Date();
  const start = new Date(end);
  start.setUTCFullYear(end.getUTCFullYear() - years);
  const toISO = (d: Date) => d.toISOString().slice(0, 10);
  return { start: toISO(start), end: toISO(end), years };
}