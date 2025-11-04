"""
Systematic dataset builder for the WeatherAI writer LLM.

It sweeps places × variable bundles × time modes, calls your MCP server
(describe → resolve → plan → execute), then creates JSONL with:
  - system: guardrails prompt
  - input:  { place, time_mode, plan, execute_result, timestamp_utc }
  - output: schema-valid object (deterministic writer; no LLM)

Usage (run from repo root):
  python tools/data_generation/make_dataset_full.py \
    --mcp http://127.0.0.1:8787 \
    --out data/train_full.jsonl \
    --max 2500 --shuffle 1
"""
import argparse, json, os, random, time, sys
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import requests as rq

DEFAULT_PLACES = [
    "Tokyo","Kyoto","Osaka","Sapporo","Seoul","Bangkok","Singapore","Kuala Lumpur",
    "Jakarta","Manila","Hanoi","Ho Chi Minh City","Taipei","Hong Kong","Beijing","Shanghai",
    "New Delhi","Mumbai","Bengaluru","Chennai","Kolkata","Hyderabad","Kathmandu",
    "London","Paris","Berlin","Rome","Madrid","Barcelona","Lisbon","Amsterdam",
    "Cairo","Casablanca","Lagos","Accra","Nairobi","Addis Ababa",
    "New York","Boston","Chicago","Miami","Atlanta","Houston","Dallas","Seattle",
    "San Francisco","Los Angeles","Vancouver","Toronto","Mexico City",
    "Bogota","Quito","Lima","Santiago","Buenos Aires","Sao Paulo","Rio de Janeiro",
    "Sydney","Melbourne","Brisbane","Perth","Wellington","Auckland",
    "India","China","USA","Brazil","Canada","Australia","Indonesia","Japan","United Kingdom","France","Germany","Italy","Spain","Kenya","Ethiopia","Morocco","South Africa","Norway","Mexico","Argentina","Chile","Russia","Saudi Arabia","Egypt","Nigeria"
]

VARIABLE_BUNDLES = [
    ["temperature"], ["temperature","typical"], ["air temp","daily average"],
    ["winds"], ["wind speed","gusts"], ["winds","clouds","rainfall"],
    ["precipitation"], ["rain","snow"], ["rainfall","intensity"],
    ["humidity"], ["relative humidity","dew point"],
    ["cloud cover"], ["clouds","sunshine"], ["visibility","fog"],
    ["soil moisture"], ["soil moisture","temperature"],
    ["solar radiation"], ["shortwave radiation"],
    ["pressure"], ["sea level pressure","mslp"],
    ["temperature in Fahrenheit","wind in knots"],
    ["air quality","PM2.5"], ["sea ice","extent"]
]

TIME_MODES = ["forecast","historical","current"]

SYSTEM_PROMPT = (
  "You are the Weather MCP Writer. Never invent numbers. "
  "Only use provided MCP JSON to produce a response matching agent/schema/response_schema.json. "
  "Include citations and limitations; keep language concise."
)

def ts_utc() -> str:
    return datetime.now(timezone.utc).isoformat()

def post_json(base: str, path: str, payload: Dict[str, Any], retries: int = 4, backoff: float = 1.2) -> Dict[str, Any]:
    err = None
    for k in range(retries):
        try:
            r = rq.post(f"{base}{path}", json=payload, timeout=180)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            err = e
            sleep = backoff ** k
            print(f"[retry] {path} attempt {k+1}/{retries} -> {e} (sleep {sleep:.1f}s)", flush=True)
            time.sleep(sleep)
    raise RuntimeError(f"Failed POST {path}: {err}")

def writer_from_execute(place: str, time_mode: str, plan: Dict[str,Any], ex: Dict[str,Any]) -> Dict[str,Any]:
    vars_planned = [it.get("canonical") for it in plan.get("items", []) if it.get("canonical")]
    title = f"{place} — " + (", ".join([v for v in vars_planned if v][:3]) + ("…" if len(vars_planned)>3 else ""))
    key_numbers: List[str] = []
    def fmt(x, unit):
        if x is None: return "NA"
        try: return f"{float(x):.1f} {unit}" if unit else f"{float(x):.1f}"
        except: return "NA"
    if ex.get("climatologies"):
        for c in ex["climatologies"][:2]:
            u = c.get("unit","")
            lt = c.get("blocks",{}).get("long_term",{})
            if lt.get("mean") is not None: key_numbers.append(f"{c['variable']} long-term mean: {fmt(lt['mean'], u)}")
            if lt.get("p10") is not None and lt.get("p90") is not None: key_numbers.append(f"{c['variable']} p10–p90: {fmt(lt['p10'], u)}–{fmt(lt['p90'], u)}")
            seas = c.get("blocks",{}).get("seasonal",{})
            if seas.get("mean"):
                vals = [v for v in seas["mean"] if v is not None]
                if vals: key_numbers.append(f"{c['variable']} seasonal mean range: {fmt(min(vals), u)}–{fmt(max(vals), u)}")
            break
    elif ex.get("series"):
        for s in ex["series"][:2]:
            u = s.get("unit","")
            vals = [v for v in s.get("values",[]) if v is not None]
            if vals:
                key_numbers.append(f"{s['variable']} first: {fmt(vals[0], u)}")
                key_numbers.append(f"{s['variable']} mean: {fmt(sum(vals)/len(vals), u)}")
    if ex.get("aggregates"):
        for a in ex["aggregates"][:1]:
            u = a.get("unit","")
            means = [v for v in a.get("aggregation",{}).get("mean",[]) if v is not None]
            if means: key_numbers.append(f"{a['variable']} diurnal mean range: {fmt(min(means), u)}–{fmt(max(means), u)}")
    if ex.get("climatologies"):
        answer = ("Typical conditions summarized across long-term mean & spread, seasonal (monthly), diurnal (local hour), and spatial bands.")
    elif ex.get("aggregates"):
        answer = "Regional conditions summarized as mean ± IQR across an adaptive grid."
    elif ex.get("series"):
        answer = "Point conditions summarized from hourly/current series."
    else:
        answer = "Requested variables were not available; see limitations."
    method = (f"Open-Meteo first. Planned variables: {', '.join([v for v in vars_planned if v])}. "
              f"Regions use adaptive grid → mean ± IQR. Historical uses a recent full year of hourly archive.")
    citations = list(ex.get("citations", [])) + [f"Query timestamp: {ts_utc()}"]
    limitations = ex.get("limitations", []) or ["Model output; station validation not applied."]
    suggested = ["Compare forecast vs historical","Add humidity/wind gusts","Try a different region"]
    return {"title": title,"answer": answer,"key_numbers": key_numbers[:8],"figures": [],"method": method,"citations": citations,"limitations": limitations,"suggested_followups": suggested[:5]}

def validate_schema(payload: Dict[str,Any], schema_path: str) -> Optional[str]:
    try:
        import jsonschema
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
        jsonschema.validate(payload, schema)
        return None
    except Exception as e:
        return str(e)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mcp", default="http://127.0.0.1:8787")
    ap.add_argument("--out", default="data/train_full.jsonl")
    ap.add_argument("--max", type=int, default=1000)
    ap.add_argument("--shuffle", type=int, default=1)
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--sleep", type=float, default=0.05, help="sleep between combos")
    ap.add_argument("--validate", type=int, default=1)
    args = ap.parse_args()
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    random.seed(args.seed)

    combos = [(p, vb, tm) for p in DEFAULT_PLACES for vb in VARIABLE_BUNDLES for tm in TIME_MODES]
    if args.shuffle: random.shuffle(combos)
    combos = combos[:args.max]

    # Warm caps
    caps = post_json(args.mcp, "/describe_capabilities", {})

    # Pre-resolve unique places (cache on MCP; be polite to Nominatim)
    uniq_places = sorted(set(p for p,_,_ in combos))
    place_cache: Dict[str, Dict[str,Any]] = {}
    print(f"[geocode] resolving {len(uniq_places)} places…", flush=True)
    for i,p in enumerate(uniq_places,1):
        try:
            loc = post_json(args.mcp, "/resolve_location", {"query": p})
            place_cache[p] = loc
        except Exception as e:
            print(f"[geocode-skip] {p} -> {e}", flush=True)
        if i % 10 == 0:
            print(f"[geocode] {i}/{len(uniq_places)} done", flush=True)
        time.sleep(1.1)  # 1 rps for Nominatim

    schema_path = os.path.join("agent","schema","response_schema.json")
    wrote = 0
    with open(args.out, "w", encoding="utf-8") as w:
        for i, (place, vars_bundle, mode) in enumerate(combos, 1):
            try:
                loc = place_cache.get(place)
                if not loc:
                    # fallback single attempt if cache miss
                    loc = post_json(args.mcp, "/resolve_location", {"query": place})
                    place_cache[place] = loc
                    time.sleep(1.1)
                geom = {"type":"Point","lat":loc["lat"],"lon":loc["lon"]} if loc["area_km2"] < 5e4 else {"type":"BBox","bbox":loc["bbox"]}
                plan = post_json(args.mcp, "/plan_query", {"capabilities": caps,"place_geometry": geom,"time_mode": mode,"variables": vars_bundle})
                ex = post_json(args.mcp, "/execute_plan", {"plan": plan})
                rec_in = {"place": place,"time_mode": mode,"plan": plan,"execute_result": ex,"timestamp_utc": ts_utc()}
                rec_out = writer_from_execute(place, mode, plan, ex)
                if args.validate:
                    err = validate_schema(rec_out, schema_path)
                    if err: print(f"[warn schema] ex#{i} {place} {vars_bundle} {mode} -> {err}", flush=True)
                record = {"system": SYSTEM_PROMPT,"input": rec_in,"output": rec_out}
                w.write(json.dumps(record, ensure_ascii=False) + "\n")
                wrote += 1
                if i % 10 == 0:
                    print(f"[{i}/{len(combos)}] wrote={wrote} :: {place} | {vars_bundle} | {mode}", flush=True)
            except Exception as e:
                print(f"[skip {i}] {place} | {vars_bundle} | {mode} -> {e}", flush=True)
            time.sleep(args.sleep)
    print(f"✅ Done. Wrote {wrote} examples to {args.out}", flush=True)

if __name__ == "__main__":
    # unbuffered output
    sys.stdout.reconfigure(line_buffering=True)
    main()