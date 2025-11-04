"""
generate_samples.py
-------------------
Small helper to produce synthetic 'input' payloads for testing the writer.
"""
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

Tip: start MCP in another terminal:
  cd mcp_server && npm i && npm run dev
"""

import argparse, json, os, random, time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

import requests as rq

# -----------------------------
# 1) Expanded PLACES (≈150)
# -----------------------------
DEFAULT_PLACES = [
    # --- Asia ---
    "Tokyo","Kyoto","Osaka","Sapporo","Seoul","Busan",
    "Beijing","Shanghai","Guangzhou","Hong Kong","Shenzhen",
    "Taipei","Kaohsiung","Bangkok","Chiang Mai","Singapore",
    "Kuala Lumpur","Jakarta","Surabaya","Manila","Cebu",
    "Hanoi","Ho Chi Minh City","Vientiane","Phnom Penh",
    "New Delhi","Mumbai","Bengaluru","Chennai","Kolkata",
    "Hyderabad","Ahmedabad","Lucknow","Dhaka","Chittagong",
    "Islamabad","Karachi","Lahore","Kathmandu","Thimphu",
    "Male","Colombo","Riyadh","Jeddah","Mecca","Medina",
    "Doha","Dubai","Abu Dhabi","Muscat","Tehran","Baghdad",
    "Kuwait City","Amman","Jerusalem","Beirut",
    # --- Europe ---
    "London","Manchester","Birmingham","Edinburgh","Dublin",
    "Paris","Lyon","Marseille","Berlin","Hamburg","Munich",
    "Frankfurt","Rome","Milan","Naples","Venice","Madrid",
    "Barcelona","Valencia","Lisbon","Porto","Brussels",
    "Amsterdam","Rotterdam","Copenhagen","Stockholm","Oslo",
    "Helsinki","Tallinn","Riga","Vilnius","Warsaw","Krakow",
    "Prague","Vienna","Budapest","Zurich","Geneva",
    "Moscow","Saint Petersburg","Kyiv","Bucharest",
    "Belgrade","Sarajevo","Sofia","Athens","Istanbul",
    # --- Africa ---
    "Cairo","Alexandria","Casablanca","Rabat","Marrakech",
    "Algiers","Tunis","Tripoli","Lagos","Abuja","Kano",
    "Accra","Kumasi","Dakar","Banjul","Freetown","Monrovia",
    "Nairobi","Mombasa","Addis Ababa","Khartoum","Dar es Salaam",
    "Cape Town","Johannesburg","Pretoria","Durban","Harare",
    "Lusaka","Kinshasa","Lubumbashi","Luanda","Maputo",
    # --- North America ---
    "New York","Boston","Philadelphia","Washington DC","Chicago",
    "Detroit","Miami","Atlanta","Houston","Dallas","Austin",
    "Denver","Phoenix","Seattle","San Francisco","Los Angeles",
    "San Diego","Portland","Vancouver","Toronto","Montreal",
    "Ottawa","Quebec City","Calgary","Edmonton","Winnipeg",
    "Mexico City","Guadalajara","Monterrey","Tijuana","Cancun",
    # --- South America ---
    "Bogota","Medellin","Cali","Quito","Guayaquil",
    "Lima","Cusco","La Paz","Santa Cruz","Santiago",
    "Valparaiso","Buenos Aires","Cordoba","Rosario",
    "Sao Paulo","Rio de Janeiro","Brasilia","Salvador",
    "Fortaleza","Recife","Caracas","Georgetown","Paramaribo",
    # --- Oceania ---
    "Sydney","Melbourne","Brisbane","Perth","Adelaide",
    "Canberra","Wellington","Auckland","Christchurch",
    "Suva","Noumea","Port Moresby","Honiara","Apia",
    # --- Regions / countries (bbox) ---
    "India","China","USA","Brazil","Russia","Canada","Australia",
    "Indonesia","Japan","South Korea","Saudi Arabia","South Africa",
    "Egypt","Nigeria","Argentina","Chile","Mexico","United Kingdom",
    "France","Germany","Italy","Spain","Norway","Kenya","Ethiopia","Morocco"
]

# ------------------------------------
# 2) Variable bundles (≈40, with aliases)
# ------------------------------------
VARIABLE_BUNDLES = [
    # Core weather
    ["temperature"], ["temperature","typical"], ["air temp","daily average"],
    ["winds"], ["wind speed","gusts"], ["winds","clouds","rainfall"],
    ["precipitation"], ["rain","snow"], ["rainfall","intensity"],
    ["humidity"], ["relative humidity","dew point"],
    ["cloud cover"], ["clouds","sunshine"], ["visibility","fog"],

    # Surface/subsurface
    ["soil moisture"], ["soil moisture","temperature"],
    ["soil temp","surface temperature"], ["evapotranspiration","ET"],

    # Energy/radiation
    ["solar radiation"], ["solar insolation","shortwave radiation"],
    ["longwave radiation","net radiation"],

    # Atmospheric structure
    ["pressure"], ["sea level pressure","mslp"],
    ["boundary layer height"], ["pblh","mixing layer"],

    # Severe weather
    ["storm","lightning"], ["hail","severe convection"],

    # Combined realistic mixes
    ["temperature","humidity","winds"],
    ["winds","clouds","precipitation","radiation"],
    ["soil moisture","precipitation","temperature"],
    ["winds","gusts","pblh"],
    ["humidity","clouds","visibility"],
    ["rainfall","soil moisture","evapotranspiration"],
    ["air temp","radiation","cloud cover"],

    # Unsupported to teach clean fallback behavior
    ["air quality","PM2.5"], ["ozone","pollution"], ["sea ice","extent"],
]

TIME_MODES = ["forecast","historical","current"]

SYSTEM_PROMPT = (
  "You are the Weather MCP Writer. Never invent numbers. "
  "Only use provided MCP JSON to produce a response matching agent/schema/response_schema.json. "
  "Include citations and limitations; keep language concise."
)

def ts_utc() -> str:
    return datetime.now(timezone.utc).isoformat()

def post_json(base: str, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    r = rq.post(f"{base}{path}", json=payload, timeout=180)
    r.raise_for_status()
    return r.json()

# -----------------------------
# Rule-based deterministic writer (no LLM)
# -----------------------------
def writer_from_execute(place: str, time_mode: str, plan: Dict[str,Any], ex: Dict[str,Any]) -> Dict[str,Any]:
    # Title
    vars_planned = [it.get("canonical") for it in plan.get("items", []) if it.get("canonical")]
    title = f"{place} — " + (", ".join([v for v in vars_planned if v][:3]) + ("…" if len(vars_planned)>3 else ""))

    # Key numbers (conservative)
    key_numbers: List[str] = []
    def fmt(x, unit):
        if x is None: return "NA"
        try: return f"{float(x):.1f} {unit}" if unit else f"{float(x):.1f}"
        except: return "NA"

    # Prefer climatologies → long-term & seasonal/diurnal ranges
    if ex.get("climatologies"):
        for c in ex["climatologies"][:2]:
            u = c.get("unit","")
            lt = c.get("blocks",{}).get("long_term",{})
            if lt.get("mean") is not None:
                key_numbers.append(f"{c['variable']} long-term mean: {fmt(lt['mean'], u)}")
            if lt.get("p10") is not None and lt.get("p90") is not None:
                key_numbers.append(f"{c['variable']} p10–p90: {fmt(lt['p10'], u)}–{fmt(lt['p90'], u)}")
            seas = c.get("blocks",{}).get("seasonal",{})
            if seas.get("mean"):
                import math
                vals = [v for v in seas["mean"] if v is not None]
                if vals:
                    key_numbers.append(f"{c['variable']} seasonal mean range: {fmt(min(vals), u)}–{fmt(max(vals), u)}")
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
            if means:
                key_numbers.append(f"{a['variable']} diurnal mean range: {fmt(min(means), u)}–{fmt(max(means), u)}")

    # Answer text (short)
    if ex.get("climatologies"):
        answer = ("Typical conditions summarized across long-term mean & spread, "
                  "seasonal (monthly), diurnal (local hour), and spatial bands.")
    elif ex.get("aggregates"):
        answer = "Regional conditions summarized as mean ± IQR across an adaptive grid."
    elif ex.get("series"):
        answer = "Point conditions summarized from hourly/current series."
    else:
        answer = "Requested variables were not available; see limitations."

    figures = []  # Keep empty here; Streamlit and tools can attach plots later.

    method = (
      f"Open-Meteo first. Planned variables: {', '.join([v for v in vars_planned if v])}. "
      f"Regions use adaptive grid → mean ± IQR. Historical mode computes lightweight climatology "
      f"from a recent full year of hourly archive."
    )

    citations = list(ex.get("citations", [])) + [f"Query timestamp: {ts_utc()}"]
    limitations = ex.get("limitations", []) or ["Model output; station validation not applied."]

    suggested = ["Switch between forecast/current/historical to compare.",
                 "Add humidity and wind gusts for heat/comfort context."]

    return {
        "title": title,
        "answer": answer,
        "key_numbers": key_numbers[:8],
        "figures": figures,
        "method": method,
        "citations": citations,
        "limitations": limitations,
        "suggested_followups": suggested[:5]
    }

# -----------------------------
# Optional schema validation
# -----------------------------
def validate_schema(payload: Dict[str,Any], schema_path: str) -> Optional[str]:
    try:
        import jsonschema
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
        jsonschema.validate(payload, schema)
        return None
    except Exception as e:
        return str(e)

# -----------------------------
# Main loop
# -----------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mcp", default="http://127.0.0.1:8787")
    ap.add_argument("--out", default="data/train_full.jsonl")
    ap.add_argument("--max", type=int, default=2500, help="cap total examples")
    ap.add_argument("--shuffle", type=int, default=1)
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--sleep", type=float, default=0.2)
    ap.add_argument("--validate", type=int, default=1, help="validate against agent/schema/response_schema.json")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    random.seed(args.seed)

    # Build Cartesian product
    combos = [(p, vb, tm) for p in DEFAULT_PLACES for vb in VARIABLE_BUNDLES for tm in TIME_MODES]
    if args.shuffle: random.shuffle(combos)
    combos = combos[:args.max]

    # warm up capabilities
    try:
        caps = post_json(args.mcp, "/describe_capabilities", {})
    except Exception as e:
        raise SystemExit(f"Failed to reach MCP: {e}")

    schema_path = os.path.join("agent","schema","response_schema.json")

    written = 0
    with open(args.out, "w", encoding="utf-8") as w:
        for i, (place, vars_bundle, mode) in enumerate(combos, 1):
            try:
                loc = post_json(args.mcp, "/resolve_location", {"query": place})
                geom = {"type":"Point","lat":loc["lat"],"lon":loc["lon"]} if loc["area_km2"] < 5e4 else {"type":"BBox","bbox":loc["bbox"]}

                plan = post_json(args.mcp, "/plan_query", {
                    "capabilities": caps,
                    "place_geometry": geom,
                    "time_mode": mode,
                    "variables": vars_bundle
                })

                ex = post_json(args.mcp, "/execute_plan", {"plan": plan})

                rec_in = {
                    "place": place,
                    "time_mode": mode,
                    "plan": plan,
                    "execute_result": ex,
                    "timestamp_utc": ts_utc()
                }
                rec_out = writer_from_execute(place, mode, plan, ex)

                if args.validate:
                    err = validate_schema(rec_out, schema_path)
                    if err:  # keep building, just log it
                        print(f"[warn schema] ex#{i} {place} {vars_bundle} {mode} -> {err}")

                record = {
                    "system": SYSTEM_PROMPT,
                    "input": rec_in,
                    "output": rec_out
                }
                w.write(json.dumps(record, ensure_ascii=False) + "\n")
                written += 1

                if i % 50 == 0:
                    print(f"[{i}/{len(combos)}] wrote={written} :: {place} | {vars_bundle} | {mode}")

            except Exception as e:
                print(f"[skip {i}] {place} | {vars_bundle} | {mode} -> {e}")
            time.sleep(args.sleep)

    print(f"✅ Done. Wrote {written} examples to {args.out}")

if __name__ == "__main__":
    main()