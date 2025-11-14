# apps/streamlit_app/app.py
"""
Meteo-Chat — professional UI (Quicksand theme), persistent results,
richer time-series summaries (bullets + quartiles), mode-aware sources,
sparse-variable (rain/snow) handling for plots + summaries,
local-LLM insight layer, form-only data fetch, dataset downloads, and sidebar chat.
"""

import os, sys, re, base64, io, requests
from pathlib import Path
import streamlit as st
import matplotlib.pyplot as plt
import pandas as pd
from datetime import datetime, timedelta
import html

# ---------- Setup ----------
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

st.set_page_config(page_title="Meteo-Chat", page_icon="🌤️", layout="centered")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Quicksand:wght@300;500;700&display=swap');
:root{ --bg1:#fff7f8; --bg2:#fff; --card:#ffffffcc; --stroke:#f2c6cf; --text:#2b2b2b;
       --muted:#6b7280; --accent:#ef5da8; --accent2:#f59e0b; --chip:#ffe4ed; --chipstroke:#ffd1e3;
       --sb-bg:#fffafc; --sb-border:#ffd7e6; }
html, body, [data-testid="stAppViewContainer"]{
  background: radial-gradient(1200px 800px at 10% 10%, var(--bg1) 0%, var(--bg2) 45%, #fff 100%) !important;
}
*, html, body, div, span, label, input, textarea, button, select {
  font-family: "Quicksand", system-ui, -apple-system, Segoe UI, Roboto, sans-serif !important;
  color: var(--text);
}
.stTabs [data-baseweb="tab-list"] { border-bottom: 1px solid var(--stroke); }
.stTabs [data-baseweb="tab"] { font-weight: 600; }
.stTabs [aria-selected="true"] { color: #b91c57 !important; }
.small{ font-size:.95rem; } .muted{ color:var(--muted)!important; }
.hero{ background:linear-gradient(180deg,#ffe8ee 0%,#fff5f7 100%);
       border:1px solid #ffd6e1; box-shadow:0 10px 28px rgba(239,93,168,.12);
       border-radius:20px; padding:26px 22px; margin-bottom:18px;}
.card{ background:var(--card); border:1px solid var(--stroke);
       border-radius:18px; padding:16px 16px;
       box-shadow:0 6px 20px rgba(239,93,168,.08); }
.stButton>button{ background:linear-gradient(90deg,var(--accent),#ff80b5);
  color:white; border:none; padding:12px 22px; border-radius:14px;
  font-weight:700; letter-spacing:.2px;}
.stButton>button:hover{ filter:brightness(1.02); }
.badge{ display:inline-block; padding:5px 10px; border-radius:999px;
        background:var(--chip); border:1px solid var(--chipstroke); color:#b91c57;
        margin-right:6px; font-size:.85rem; }

/* Sidebar theme */
section[data-testid="stSidebar"] > div {
  background: var(--sb-bg) !important;
  border-left: 1px solid var(--sb-border);
}
.sidebar-card {
  background: #ffffffcc; border:1px solid var(--sb-border); border-radius:16px; padding:12px;
  box-shadow:0 4px 14px rgba(239,93,168,.10);
}
.msg-user, .msg-assistant {
  border:1px solid var(--sb-border); border-radius:14px; padding:10px 12px; margin:8px 0;
  background:#fff;
}
.msg-user { background:#fff4f8; }
.msg-assistant { background:#fff; }

/* Download tab buttons */
.download-wrap .stDownloadButton > button {
  background:linear-gradient(90deg,var(--accent),#ff80b5);
  color:white; border:none; padding:10px 14px; border-radius:12px; font-weight:700;
}
.download-wrap .stDownloadButton { margin-bottom:8px; }
.footer{ margin-top:32px; padding-top:12px; opacity:.9;
         border-top:1px dashed var(--stroke); text-align:center; }
a, a:visited { color:#b91c57; text-decoration:none; }
a:hover { text-decoration:underline; }
</style>
""", unsafe_allow_html=True)

st.markdown(
    """
    <style>
    /* Match Streamlit top bar with your app background */
    header[data-testid="stHeader"] {
        background: #fff0f5 !important;   /* pick your app’s main pastel tone */
        color: #444 !important;
    }
    header [data-testid="stToolbar"] {
        background: transparent !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------- Services ----------
MCP = os.getenv("MCP_URL", "http://127.0.0.1:8787")
LLM_URL = os.getenv("LLM_URL", "http://127.0.0.1:8899/generate")

@st.cache_data(ttl=300)
def mcp_post(ep, payload, timeout=90):
    r = requests.post(f"{MCP}{ep}", json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()

# ---------- Session ----------
if "last_result" not in st.session_state:
    # (place_name, loc, plan, ex, time_mode, variables, user_q)
    st.session_state["last_result"] = None
if "chat" not in st.session_state:
    st.session_state["chat"] = []  # list of dicts: {"role":"user"/"assistant","content":str}

# ---------- Helpers ----------
def _fig_to_b64():
    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    buf.seek(0)
    out = base64.b64encode(buf.read()).decode("ascii")
    plt.close()
    return out

def openmeteo_doc_links(mode):
    base = "https://open-meteo.com/en/docs"
    hist = "https://open-meteo.com/en/docs/historical-weather-api"
    if mode == "historical":
        return [("Open-Meteo Historical API", hist), ("Open-Meteo", base)]
    elif mode == "forecast":
        return [("Open-Meteo Forecast API", base)]
    else:
        return [("Open-Meteo", base)]

def _format_duration(td: timedelta) -> str:
    total_hours = int(td.total_seconds() // 3600)
    months = total_hours // (24 * 30); rem_h = total_hours % (24 * 30)
    days = rem_h // 24; hours = rem_h % 24
    parts = []
    if months: parts.append(f"{months} month{'s' if months!=1 else ''}")
    if days: parts.append(f"{days} day{'s' if days!=1 else ''}")
    if hours or not parts: parts.append(f"{hours} hour{'s' if hours!=1 else ''}")
    if len(parts) == 1: return parts[0]
    if len(parts) == 2: return f"{parts[0]} and {parts[1]}"
    return f"{', '.join(parts[:-1])} and {parts[-1]}"

def is_sparse_series(s: pd.Series, thresh=0.05) -> bool:
    s = pd.to_numeric(s, errors="coerce").fillna(0)
    if len(s) == 0:
        return False
    return (s > 0).mean() <= thresh

def window_line(plan, ex):
    win = ex.get("window") or (plan.get("meta",{}) or {}).get("historical_window")
    if not win: return None
    try:
        s, e = datetime.fromisoformat(win["start"]), datetime.fromisoformat(win["end"])
        yrs = round((e - s).days / 365.25, 1)
        yrs_txt = f"{yrs:.1f} year{'s' if yrs != 1 else ''}"
    except Exception:
        yrs_txt = "—"
    return f"Data window: {win['start']} → {win['end']} (≈{yrs_txt})"

# ---------- Plotters ----------
def plot_time_series(title, unit, times, values, show_roll=False, win=24):
    t = pd.to_datetime(times) if times else pd.to_datetime([])
    s = pd.to_numeric(pd.Series(values), errors="coerce") if values else pd.Series([])
    sparse = is_sparse_series(s)
    if sparse:
        mask = s > 0
        t = t[mask]; s = s[mask]
    plt.figure(figsize=(9.5, 3.6))
    if show_roll and len(s) > win:
        rm = s.rolling(win, min_periods=max(3, win//4)).mean()
        rs = s.rolling(win, min_periods=max(3, win//4)).std()
        plt.fill_between(t, rm - rs, rm + rs, alpha=0.18, label="±1σ")
        plt.plot(t, rm, linewidth=1.8, label="Rolling mean")
        plt.plot(t, s, alpha=0.35, linewidth=0.9, label="Raw")
        plt.legend()
    else:
        plt.plot(t, s)
    plt.title(title + (" (non-zero events)" if sparse else ""))
    plt.xlabel("Time"); plt.ylabel(unit or ""); plt.xticks(rotation=15)
    return _fig_to_b64()

def plot_box(title, unit, times, values, group="hour"):
    df = pd.DataFrame({"t": pd.to_datetime(times),
                       "v": pd.to_numeric(values, errors="coerce")}).dropna()
    if df.empty:
        plt.figure(figsize=(9.5, 3.6)); plt.title(title + " (no data)")
        return _fig_to_b64()
    sparse = is_sparse_series(df["v"])
    if sparse:
        df = df[df["v"] > 0]
    if df.empty:
        plt.figure(figsize=(9.5, 3.6)); plt.title(title + " (no non-zero events)")
        return _fig_to_b64()
    df["g"] = df["t"].dt.hour if group == "hour" else df["t"].dt.month
    order = sorted(df["g"].unique())
    groups = [df.loc[df.g==g, "v"].values for g in order]
    labels = [f"{g:02d}" if group=="hour" else
              ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][g-1]
              for g in order]
    fig, ax = plt.subplots(figsize=(9.5, 3.6))
    bp = ax.boxplot(groups, labels=labels, patch_artist=True, showfliers=False,
                    medianprops=dict(color="#9c1749"))
    for p in bp["boxes"]:
        p.set_facecolor("#f6a3c5"); p.set_alpha(0.35); p.set_edgecolor("#b91c57")
    ax.set_ylabel(unit or "")
    ax.set_title(title + (" (non-zero events)" if sparse else "") +
                 (" (diurnal)" if group=="hour" else " (monthly)"))
    ax.set_xlabel("Hour (UTC)" if group=="hour" else "Month")
    return _fig_to_b64()

# ---------- LLM Bridge (concise + cleaned) ----------
def synthesize_form_question(place_name: str, mode_sel: str, variables: list, fc_days: int, hist_years: int) -> str:
    pretty_vars = ", ".join(variables) if variables else "weather"
    if mode_sel == "forecast":
        return f"{fc_days}-day {pretty_vars} outlook for {place_name}."
    elif mode_sel == "historical":
        return f"Historical {pretty_vars} summary for {place_name} over ~{hist_years} year(s)."
    else:
        return f"Current {pretty_vars} conditions in {place_name}."

def _compact_stats_line(var: str, unit: str, values: pd.Series) -> str:
    v = pd.to_numeric(values, errors="coerce").dropna()
    if v.empty:
        return ""
    mean, std = v.mean(), v.std()
    vmin, vmax = v.min(), v.max()
    line = f"- {var}: mean={mean:.2f}{unit}, std={std:.2f}{unit}, range={vmin:.2f}–{vmax:.2f}{unit}"
    # sparse hint
    nz_frac = (v > 0).mean() if len(v) else 0.0
    if nz_frac > 0 and nz_frac <= 0.20:
        line += f", nonzero%={100*nz_frac:.1f}"
    return line

# --- LLM output cleaner ---
_SENTENCE_END = re.compile(r'(?<=[.!?])\s+')

def clean_llm(raw: str) -> str:
    """Return only the assistant's concise reply after the last 'answer only' marker."""
    if not raw:
        return ""
    txt = raw.strip()

    # Keep only after the final answer marker
    match = re.split(r'(?i)(assistant\s*\(answer only\)\s*:|answer only\s*:)', txt)
    if len(match) > 1:
        txt = match[-1]

    # Drop internal commentary
    txt = re.sub(r"(?i)user asked.*", "", txt)
    txt = re.sub(r"(?i)assistant('?s)? response.*", "", txt)
    txt = re.sub(r"(?i)\b(note|disclaimer|source|context)\b.*", "", txt)
    txt = re.sub(r"(?:\s*#[\w\-]+)+\s*$", "", txt)
    txt = txt.strip()
    return txt

def build_llm_context(place_name, plan, ex):
    lines = [f"Place: {place_name}"]
    win = ex.get("window") or (plan.get("meta",{}) or {}).get("historical_window")
    if win:
        lines.append(f"Window: {win.get('start','?')} → {win.get('end','?')}")
    # variables + stats
    series = (ex.get("series") or [])[:12]
    vnames = [s.get("variable","") for s in series if s.get("variable")]
    if vnames:
        lines.append("Variables: " + ", ".join(vnames))
    for s in series:
        var = s.get("variable","")
        unit = s.get("unit","") or ""
        vals = pd.to_numeric(pd.Series(s.get("values", [])), errors="coerce")
        ln = _compact_stats_line(var, unit, vals)
        if ln: lines.append(ln)
    # a couple of recent samples for grounding
    for s in series[:3]:
        var = s.get("variable","")
        unit = s.get("unit","") or ""
        t = pd.to_datetime(s.get("times", []))
        v = pd.to_numeric(pd.Series(s.get("values", [])), errors="coerce")
        df = pd.DataFrame({"t": t, "v": v}).dropna()
        if len(df) >= 3:
            tail = df.tail(3)
            lines.append(f"- recent {var} samples: " +
                         ", ".join(f"{row.v:.2f}{unit}@{row.t:%m-%d %H:%M}" for _, row in tail.iterrows()))
    return "\n".join(lines)

def _clean_llm(text: str) -> str:
    if not text: return ""
    # Strip any echoed instructions / headers
    text = re.sub(r"(?is)^\\s*(you are|dataset context|context:|instructions?|assistant:|system:).*?\\n", "", text).strip()
    # Remove trailing meta blocks
    text = re.sub(r"(?is)\\n(?:source|limitations|note|summary structure|additional information).*", "", text).strip()
    # Collapse whitespace
    text = re.sub(r"\\n{3,}", "\\n\\n", text).strip()
    return text

def build_llm_prompt_for_summary(context: str, user_question: str):
    return (
        "You are Meteo-Chat. Use ONLY the dataset below. "
        "Answer in 2–4 conversational sentences with clear numbers + units. "
        "Do not include any preamble, system text, or the words USER/ASSISTANT. "
        "Do not repeat the context. No hashtags. No disclaimers.\n\n"
        f"{context}\n\n"
        f"Question: {user_question}\n"
        "Answer only:"
    )

def build_llm_prompt_for_chat(context: str, chat_history: list, user_msg: str):
    # Collect the last few turns of dialogue, formatted cleanly
    history_text = "\n".join(
        f"{m['role'].upper()}: {m['content'].strip()}"
        for m in chat_history[-4:]
    )

    return (
        "You are Meteo-Chat, a conversational weather assistant that knows only the dataset shown below. "
        "If the user asks something outside this dataset’s place, variables, or timeframe, say politely that "
        "you only know about this dataset. Otherwise, answer in 2–4 sentences with clear numbers + units. "
        "Do not include preamble or system text. Do not repeat the context. No hashtags.\n\n"
        f"DATASET CONTEXT:\n{context}\n\n"
        f"RECENT CHAT:\n{history_text}\n\n"
        f"USER: {user_msg}\n"
        "ASSISTANT (answer only):"
    )

def query_llm(prompt: str):
    """Query the LLM and clean out any echoed prompt, instructions, or hashtags."""
    try:
        r = requests.post(LLM_URL, json={"prompt": prompt}, timeout=45)
        r.raise_for_status()
        txt = r.json().get("text") or r.json().get("generated_text") or ""
        # remove everything before first plausible answer
        cleaned = re.split(r"(?i)\b(answer|assistant):", txt, maxsplit=1)
        if len(cleaned) > 2:
            txt = cleaned[2]
        # strip hashtags, disclaimers, trailing noise
        txt = re.sub(r"#\w+", "", txt)
        txt = re.sub(r"(?i)(please note|disclaimer|knowledge cutoff).*", "", txt)
        return txt.strip()
    except Exception as e:
        return f"[LLM error: {e}]"

# ---------- Data shaping for downloads ----------
def build_combined_df(series_list):
    frames = []
    for s in series_list:
        t = pd.to_datetime(s.get("times", []))
        v = pd.to_numeric(pd.Series(s.get("values", [])), errors="coerce")
        if len(t) == 0 or v.dropna().empty:
            continue
        df = pd.DataFrame({"time": t, s.get("variable","var"): v})
        frames.append(df.dropna())
    if not frames:
        return pd.DataFrame()
    out = frames[0]
    for df in frames[1:]:
        out = out.merge(df, on="time", how="outer")
    out = out.sort_values("time").reset_index(drop=True)
    return out

def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")

# ---------- HERO ----------
st.markdown("""
<div class="hero">
  <div style="display:flex;align-items:center;gap:14px;">
    <div style="font-size:28px;">🌤️</div>
    <div>
      <div style="font-size:28px;font-weight:700;letter-spacing:.2px;">
        Hi, I am <span style="color:#b91c57">Meteo-Chat</span>
      </div>
      <div class="small" style="margin-top:4px;opacity:.9;">
        I’m an AI-powered chatbot for quick, structured answers about the weather of any place.
      </div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# ---------- FORM (only entrypoint for data) ----------
st.markdown('<div class="small muted">🌸 Enter your query in the form below:</div>', unsafe_allow_html=True)
col1, col2, col3 = st.columns([1.15, .85, 1.0], gap="large")
with col1:
    place = st.text_input("Type Location", "Kyoto")
with col2:
    mode = st.select_slider("Choose Duration", ["historical", "current", "forecast"], value="current")
with col3:
    vars_text = st.text_input("Type Variable(s)", "temperature")

# Historical / Forecast duration controls
hist_years, fc_days = 1, 7
if mode == "historical":
    if st.checkbox("Customize historical duration", key="hist"):
        hist_years = st.slider("Years", 1, 30, 10)
if mode == "forecast":
    fc_days = st.slider("Days ahead", 1, 16, 7)

go_form = st.button("Submit", key="form_submit")

# ---------- Back-end interaction ----------

# ---------- Variable aliasing + capability filtering ----------

def resolve_variable_aliases(query_vars: list[str], mode: str) -> list[str]:
    """
    Map free-form user variable names to Open-Meteo canonical keys.
    Returns a deduplicated, order-preserving list of canonical names.
    """
    if not query_vars:
        return []

    # canonical map (lowercased keys)
    alias = {
        # Temperature
        "temp": "temperature_2m",
        "temperature": "temperature_2m",
        "air_temperature": "temperature_2m",
        "t2m": "temperature_2m",
        "apparent_temperature": "apparent_temperature",
        "feels_like": "apparent_temperature",
        # Dew point / humidity
        "dewpoint": "dew_point_2m",
        "dew_point": "dew_point_2m",
        "dew_point_temperature": "dew_point_2m",
        "humidity": "relative_humidity_2m",
        "relative_humidity": "relative_humidity_2m",
        "rh": "relative_humidity_2m",
        # Wind
        "wind": "wind_speed_10m",
        "winds": "wind_speed_10m",
        "wind_speed": "wind_speed_10m",
        "wind_speed_10m": "wind_speed_10m",
        "wind_dir": "wind_direction_10m",
        "wind_direction": "wind_direction_10m",
        "wind_gusts": "wind_gusts_10m",
        "wind_gust": "wind_gusts_10m",
        # Precipitation
        "precip": "precipitation",
        "precipitation": "precipitation",
        "rain": "rain",
        "snow": "snowfall",
        "snowfall": "snowfall",
        "snow_depth": "snow_depth",
        # Cloud / radiation
        "cloud": "cloud_cover",
        "clouds": "cloud_cover",
        "cloud_cover": "cloud_cover",
        "shortwave_radiation": "shortwave_radiation",
        "direct_radiation": "direct_radiation",
        "diffuse_radiation": "diffuse_radiation",
        "et0": "et0_fao_evapotranspiration",
        "evapotranspiration": "et0_fao_evapotranspiration",
        # Pressure
        "mslp": "pressure_msl",
        "sea_level_pressure": "pressure_msl",
        "surface_pressure": "surface_pressure",
        # Soil (multi-depth)
        "soil_surface_temperature": "soil_temperature_0cm",
        "soil_temperature_surface": "soil_temperature_0cm",
        "soil_temp_surface": "soil_temperature_0cm",
        "soil_temperature_0cm": "soil_temperature_0cm",
        "soil_temp_0cm": "soil_temperature_0cm",
        "soil_temperature_6cm": "soil_temperature_6cm",
        "soil_temp_6cm": "soil_temperature_6cm",
        "soil_temperature_18cm": "soil_temperature_18cm",
        "soil_temp_18cm": "soil_temperature_18cm",
        "soil_temperature_54cm": "soil_temperature_54cm",
        "soil_temp_54cm": "soil_temperature_54cm",
        "soil_moisture_0_1cm": "soil_moisture_0_to_1cm",
        "soil_moisture_0_1": "soil_moisture_0_to_1cm",
        "soil_moisture_1_3cm": "soil_moisture_1_to_3cm",
        "soil_moisture_3_9cm": "soil_moisture_3_to_9cm",
        "soil_moisture_9_27cm": "soil_moisture_9_to_27cm",
        "soil_moisture_27_81cm": "soil_moisture_27_to_81cm",
        # Solar geometry
        "sunrise": "sunrise",
        "sunset": "sunset",
        # Daily aggregates (if your MCP supports daily mode)
        "tmax": "temperature_2m_max",
        "tmin": "temperature_2m_min",
        "temperature_max": "temperature_2m_max",
        "temperature_min": "temperature_2m_min",
        # Others (add more as needed)
        "visibility": "visibility",
        "uv_index": "uv_index",
    }

    out = []
    seen = set()
    for v in query_vars:
        k = v.strip().lower()
        cand = alias.get(k, k)   # fall back to user key if unknown
        if cand not in seen:
            seen.add(cand)
            out.append(cand)
    return out


def _caps_supported_set(caps: dict, mode: str) -> set[str]:
    """
    Safely extract a set of supported variable names from /describe_capabilities.
    Handles:
      - { "variables": [ {id,label,...}, ... ] }
      - { "variables": { "forecast":[...], "historical":[...] } }
      - { "variables": ["temperature_2m", "precipitation", ...] }
    Returns all names in *lowercase*.
    """
    supp = set()
    vs = caps.get("variables", {})

    # -- dict-of-lists case: {"forecast":[...], "historical":[...]}
    if isinstance(vs, dict):
        if mode in vs:
            arr = vs[mode]
            if isinstance(arr, (list, tuple, set)):
                for v in arr:
                    if isinstance(v, dict):
                        name = (
                            v.get("id")
                            or v.get("name")
                            or v.get("variable")
                        )
                        if name:
                            supp.add(str(name))
                    elif isinstance(v, str):
                        supp.add(v)
        else:
            # union across all categories if no per-mode entry
            for arr in vs.values():
                if isinstance(arr, (list, tuple, set)):
                    for v in arr:
                        if isinstance(v, dict):
                            name = (
                                v.get("id")
                                or v.get("name")
                                or v.get("variable")
                            )
                            if name:
                                supp.add(str(name))
                        elif isinstance(v, str):
                            supp.add(v)

    # -- flat list case: [{"id":...}, ...] or ["temperature_2m", ...]
    elif isinstance(vs, (list, tuple, set)):
        for v in vs:
            if isinstance(v, dict):
                name = (
                    v.get("id")
                    or v.get("name")
                    or v.get("variable")
                )
                if name:
                    supp.add(str(name))
            elif isinstance(v, str):
                supp.add(v)

    # normalize to lowercase
    return {v.lower() for v in supp}

def mcp_post(path: str, payload: dict):
    url = f"http://127.0.0.1:8787{path}"
    r = requests.post(url, json=payload, timeout=20)
    if not r.ok:
        # Let callers handle r.json() if present
        try:
            msg = r.json().get("error", r.text)
        except Exception:
            msg = r.text
        raise RuntimeError(f"MCP error ({r.status_code}): {msg}")
    return r.json()

def filter_supported_variables(caps: dict, variables: list[str], mode: str) -> tuple[list[str], list[str]]:
    """
    Keep only variables supported by the capability set for the selected mode.
    Returns (kept, dropped).
    """
    supported = _caps_supported_set(caps, mode)
    if not supported:
        # If caps are empty/unknown, don't drop anything silently
        return variables, []

    kept, dropped = [], []
    for v in variables:
        if v in supported:
            kept.append(v)
        else:
            dropped.append(v)
    # Avoid empty requests: if everything got dropped, keep originals so user sees MCP error
    return (kept or variables), dropped

def run_query(use_place, mode_sel, vars_sel, opt):
    caps = mcp_post("/describe_capabilities", {})
    try:
        loc = mcp_post("/resolve_location", {"query": use_place})
    except RuntimeError as e:
        st.error(str(e))
        st.stop()
    geom = {"type":"Point","lat":loc["lat"],"lon":loc["lon"]}
    # vars_sel = resolve_variable_aliases(vars_sel)
    plan = mcp_post("/plan_query", {
        "capabilities": caps,
        "place_geometry": geom,
        "time_mode": mode_sel,
        "variables": vars_sel,
        "options": opt
    })
    ex = mcp_post("/execute_plan", {"plan": plan})
    return loc, plan, ex

def synthesize_question(place_name, mode_sel, variables):
    return synthesize_form_question(place_name, mode_sel, variables, fc_days, hist_years)

def drive_form():
    use_place = place
    time_mode = mode
    variables_raw = [v.strip() for v in vars_text.split(",") if v.strip()]

    # NEW: alias -> canonical
    variables_canon = resolve_variable_aliases(variables_raw, time_mode)

    opts = {}
    if time_mode == "historical": opts["historical_years"] = int(hist_years)
    if time_mode == "forecast":   opts["forecast_days"] = int(fc_days)

    with st.spinner("Fetching data from Open-Meteo…"):
        # NEW: get caps and filter to supported variables for this mode
        caps = mcp_post("/describe_capabilities", {})
        variables_final, dropped = filter_supported_variables(caps, variables_canon, time_mode)
        if dropped:
            st.warning(
                "Unsupported for this mode and skipped: " + ", ".join(dropped),
                icon="⚠️"
            )

        loc, plan, ex = run_query(use_place, time_mode, variables_final, opts)

        user_q = synthesize_question(use_place, time_mode, variables_final)
        st.session_state.last_result = (use_place, loc, plan, ex, time_mode, variables_final, user_q)

        # Reset sidebar chat with a short dataset-based greeting summary
        st.session_state.chat = []
        context = build_llm_context(use_place, plan, ex)
        prompt = build_llm_prompt_for_summary(context, user_q)
        llm_reply = query_llm(prompt)
        llm_reply = clean_llm(llm_reply)
        if llm_reply and not llm_reply.startswith("[LLM error"):
            st.session_state.chat.append({"role":"assistant", "content": llm_reply})

# ---------- Summaries ----------
def summarize_point_series(item, place_name: str, title_for_user: str):
    df = pd.DataFrame({
        "t": pd.to_datetime(item.get("times", [])),
        "v": pd.to_numeric(item.get("values", []), errors="coerce")
    }).dropna()
    if df.empty: return []

    unit = (item.get("unit") or "").strip()
    vals = df["v"].reset_index(drop=True)
    times = df["t"].reset_index(drop=True)
    n = len(vals)

    start_t, end_t = pd.to_datetime(times.iloc[0]), pd.to_datetime(times.iloc[-1])
    duration_text = _format_duration(end_t - start_t)

    sparse = is_sparse_series(vals)
    lines = [f"{title_for_user.capitalize()} over {place_name}",
             f"During: {start_t.strftime('%Y-%m-%d %H:%M')} → {end_t.strftime('%Y-%m-%d %H:%M')}"]

    if sparse:
        nz = vals[vals > 0]
        wet_fraction = (len(nz) / n * 100.0) if n else 0.0
        n_events = int(((vals > 0) & (vals.shift(1, fill_value=0) == 0)).sum())
        lines.append(f" Non-zero fraction: {wet_fraction:.1f}% of timesteps ({n_events} events)")
        if len(nz):
            lines.append(f" Mean event intensity: {nz.mean():.2f} {unit}")
            lines.append(f" Total accumulation: {nz.sum():.2f} {unit} over {duration_text}")

    vmin, vmax = float(vals.min()), float(vals.max())
    mean, std, med = float(vals.mean()), float(vals.std()), float(vals.median())
    q25, q75 = float(vals.quantile(0.25)), float(vals.quantile(0.75))
    cv = (std / mean * 100.0) if mean != 0 else 0.0
    trend = "→ flat"
    if n >= 2:
        if vals.iloc[-1] > vals.iloc[0]: trend = "↗ rising"
        elif vals.iloc[-1] < vals.iloc[0]: trend = "↘ falling"

    iqr_str = f"IQR {q25:.2f}–{q75:.2f} {unit}"
    is_precip_like = unit.lower().startswith("mm") or "precip" in (item.get("variable","").lower())
    if (q25 == 0.0 and q75 == 0.0) and is_precip_like:
        nz = vals[vals > 0]
        if len(nz) > 0:
            nz_q25, nz_q75 = float(nz.quantile(0.25)), float(nz.quantile(0.75))
            if nz_q75 > 0:
                iqr_str += f" (non-zero IQR ≈ {nz_q25:.2f}–{nz_q75:.2f} {unit})"

    lines.append(
        f" Overall: mean {mean:.2f} ± {std:.2f} {unit}, range {vmin:.2f}–{vmax:.2f} {unit}, "
        f"median {med:.2f} {unit}, {iqr_str}, variability {cv:.0f}%, trend {trend}"
    )

    splits = [int(n * i / 4) for i in range(5)]
    labels = ["Q1 (first quarter)", "Q2", "Q3", "Q4 (last quarter)"]
    for i in range(4):
        seg = vals.iloc[splits[i]:splits[i+1]]
        if seg.empty: continue
        seg_line = f"{labels[i]}: mean {seg.mean():.2f} {unit}, min {seg.min():.2f} {unit}, max {seg.max():.2f} {unit}"
        if is_precip_like:
            seg_line += f", total {seg.sum():.2f} {unit}"
        lines.append(f" {seg_line}")

    if is_precip_like:
        lines.append(f" Overall total: {vals[vals>0].sum():.2f} {unit} over {duration_text}")

    return lines

def summarize_box(times, values, group="hour"):
    df = pd.DataFrame({
        "t": pd.to_datetime(times),
        "v": pd.to_numeric(values, errors="coerce")
    }).dropna()
    if df.empty:
        return []

    df["g"] = df["t"].dt.hour if group == "hour" else df["t"].dt.month
    label_fn = (lambda g: f"{g:02d} UTC") if group == "hour" else \
               (lambda g: ["Jan","Feb","Mar","Apr","May","Jun","Jul",
                           "Aug","Sep","Oct","Nov","Dec"][g-1])

    out = []
    for g, sub in df.groupby("g"):
        s = sub["v"].dropna()
        if s.empty:
            continue
        nz = s[s > 0]
        frac = len(nz) / len(s) * 100.0
        mean_all, med_all = s.mean(), s.median()
        q25, q75 = s.quantile(0.25), s.quantile(0.75)
        nz_iqr = None
        if q25 == 0 and q75 == 0 and not nz.empty:
            nz_q25, nz_q75 = nz.quantile(0.25), nz.quantile(0.75)
            if nz_q75 > 0:
                nz_iqr = (nz_q25, nz_q75)
        line = f"{label_fn(g)} — non-zero freq {frac:.1f}%, mean {mean_all:.2f}, median {med_all:.2f}, IQR {q25:.2f}–{q75:.2f}"
        if nz_iqr:
            line += f" (non-zero IQR ≈ {nz_iqr[0]:.2f}–{nz_iqr[1]:.2f})"
        out.append(line)

    return out[:12]

# ---------- Results renderer ----------
def render_results():
    if not st.session_state.last_result:
        st.info("Submit a query above to see results.")
        return

    place_name, loc, plan, ex, time_mode, variables, user_q = st.session_state.last_result

    # Card + Tabs (Overview / Data)
    shown_vars = [it.get("canonical", it.get("requested","")) for it in plan.get("items",[])]
    st.markdown(
        f"<div class='card'><b>Location:</b> {place_name}<br/>"
        f"<b>Variables:</b> {', '.join(shown_vars[:12])}</div>",
        unsafe_allow_html=True
    )
    tabs = st.tabs(["Meteo-Chat Overview", "Data"])
    with tabs[0]:
        # Data window + coords
        wline = window_line(plan, ex)
        if wline: st.caption(wline)
        st.caption(f"Using location: lat={loc['lat']:.3f}, lon={loc['lon']:.3f}, area≈{int(loc['area_km2'])} km²")

        # Figures
        figs = []
        viz = st.select_slider("Plot type", ["Time series", "Box plot"], value="Time series")
        roll_band = False; roll_win = 24; box_group = "hour"
        if viz == "Time series":
            roll_band = st.checkbox("Show rolling mean ± std", value=False)
            if roll_band:
                roll_win = st.slider("Rolling window", 6, 72, 24)
        else:
            box_group = st.select_slider("Box grouping", ["hour", "month"], value="hour")

        # map canonical->user titles once
        canon2user = {}
        for it in plan.get("items", []):
            req = it.get("requested") or it.get("canonical")
            can = it.get("canonical") or req
            if req and can: canon2user[can] = req

        for s in (ex.get("series") or []):
            title = canon2user.get(s.get("variable",""), s.get("variable",""))
            if viz == "Time series":
                figs.append(plot_time_series(title, s.get("unit",""), s.get("times",[]), s.get("values",[]),
                                             show_roll=roll_band, win=roll_win))
            else:
                figs.append(plot_box(title, s.get("unit",""), s.get("times",[]), s.get("values",[]),
                                     group=("hour" if box_group=="hour" else "month")))

        if figs:
            st.markdown("<div class='card'><b>Figures</b></div>", unsafe_allow_html=True)
            for b64 in figs:
                img = base64.b64decode(b64)
                st.image(img, width='stretch')

        # Summary
        lines = []
        for s in (ex.get("series") or []):
            title = canon2user.get(s.get("variable",""), s.get("variable",""))
            if viz == "Time series":
                lines += (summarize_point_series(s, place_name, title) or [])
            else:
                items = summarize_box(s.get("times",[]), s.get("values",[]),
                                      group=("hour" if box_group=="hour" else "month"))
                if items:
                    lines.append(f"{title} — distribution highlights:")
                    lines += [f" {x}" for x in items]

        # Aggregates
        for a in (ex.get("aggregates") or []):
            agg = a.get("aggregation", {})
            mean = [m for m in agg.get("mean", []) if isinstance(m, (int,float))]
            hrs = agg.get("index", [])
            if mean:
                unit = a.get("unit", "")
                vmin, vmax = min(mean), max(mean)
                try:
                    i_min = hrs[mean.index(vmin)]
                    i_max = hrs[mean.index(vmax)]
                    lines.append(f"{a['variable']} (regional diurnal): mean range {vmin:.2f}–{vmax:.2f} {unit} (min @{i_min:02d} UTC, max @{i_max:02d} UTC)")
                except Exception:
                    lines.append(f"{a['variable']} (regional diurnal): mean range {vmin:.2f}–{vmax:.2f} {unit}")

        if lines:
            st.markdown("<div class='card'><b>Summary</b><ul>" +
                        "".join(f"<li>{ln}</li>" for ln in lines) +
                        "</ul></div>", unsafe_allow_html=True)

        # Method / Source / Limitations
        st.markdown("""
        <div class='card'><b>Method</b>
        <ul>
          <li>Maps your free-text variables to Open-Meteo canonical parameters (no hardcoded list).</li>
          <li>Selects current, forecast, or historical mode based on your inputs.</li>
          <li>For sparse variables (e.g., rain), figures switch to non-zero events and summaries report event frequency & totals.</li>
          <li>Time series can add rolling mean ± std; box plots summarize diurnal or monthly distributions.</li>
          <li>Unsupported variables are reported explicitly—never guessed.</li>
        </ul></div>
        """, unsafe_allow_html=True)

        links = openmeteo_doc_links(time_mode)
        citations = ex.get("citations") or []
        src_html = "<div class='card'><b>Source</b><br/>"
        for c in citations:
            src_html += f" {c}<br/>"
        for label, url in links:
            src_html += f" {label} — <a href='{url}' target='_blank'>{url}</a><br/>"
        src_html += "</div>"
        st.markdown(src_html, unsafe_allow_html=True)

        lims = (ex.get("limitations") or []) + [
            "Regional summaries may hide local extremes.",
            "Archive windows and grid sizes are tuned for speed on the free tier."
        ]
        st.markdown("<div class='card'><b>Limitations</b><ul>" +
                    "".join(f"<li>{ln}</li>" for ln in lims[:8]) +
                    "</ul></div>", unsafe_allow_html=True)

    with tabs[1]:
        st.markdown("<div class='download-wrap'>**Download data**</div>", unsafe_allow_html=True)
        series = ex.get("series") or []
        combined = build_combined_df(series)
        if not combined.empty:
            st.download_button(
                "Download combined CSV",
                data=df_to_csv_bytes(combined),
                file_name=f"{place_name.replace(' ','_')}_combined.csv",
                mime="text/csv",
                key="dl_combined"
            )
        for s in series:
            var = s.get("variable","series")
            t = pd.to_datetime(s.get("times", []))
            v = pd.to_numeric(pd.Series(s.get("values", [])), errors="coerce")
            df = pd.DataFrame({"time": t, var: v}).dropna()
            if df.empty: 
                continue
            st.download_button(
                f"Download {var} CSV",
                data=df_to_csv_bytes(df),
                file_name=f"{place_name.replace(' ','_')}_{var.replace(' ','_')}.csv",
                mime="text/csv",
                key=f"dl_{var}"
            )

## ---------- Sidebar Chat (dataset-scoped, styled) ----------
with st.sidebar:
    st.markdown("<h4>💬 Meteo-Chat</h4>", unsafe_allow_html=True)

    if st.session_state.last_result:
        place_name, loc, plan, ex, time_mode, variables, user_q = st.session_state.last_result
        context = build_llm_context(place_name, plan, ex)
    else:
        context = None

    # render chat bubbles
    for m in st.session_state.chat:
        bubble_color = "#fff0f5" if m["role"] == "user" else "#ffe6f0"
        align = "right" if m["role"] == "user" else "left"
        st.markdown(
            f"<div style='background:{bubble_color};padding:10px 14px;border-radius:12px;"
            f"margin:4px 0;text-align:{align};font-size:0.95rem;'>{html.escape(m['content'])}</div>",
            unsafe_allow_html=True
        )

    # input row
    user_msg = st.text_input(
        "Ask about this dataset",
        "",
        key="sidebar_chat_input",
        placeholder="Enter query here...",
        label_visibility="collapsed"
    )

    # icons side by side
    col_send, col_clear = st.columns([1, 1])
    with col_send:
        send_clicked = st.button("📨", help="Send message", use_container_width=True)
    with col_clear:
        clear_clicked = st.button("🧹", help="Clear chat", use_container_width=True)

    if clear_clicked:
        st.session_state.chat = []
        st.rerun()

    if send_clicked and user_msg.strip():
        msg = user_msg.strip()
        st.session_state.chat.append({"role": "user", "content": msg})
        prompt = build_llm_prompt_for_chat(context, st.session_state.chat, msg)
        reply = query_llm(prompt)
        reply = clean_llm(reply)
        st.session_state.chat.append({"role": "assistant", "content": reply})

        # Instead of touching widget state, just trigger refresh
        st.experimental_set_query_params(_=datetime.now().timestamp())
        st.rerun()

    # subtle style tweak for icon buttons
    st.markdown(
        """
        <style>
        div[data-testid="stHorizontalBlock"] button {
            margin-top: -6px !important;
            height: 2.2rem !important;
            font-size: 1.3rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

# ---------- Triggers ----------
if go_form:
    drive_form()

render_results()

# ---------- Bottom: Keywords Dictionary ----------
st.markdown("""
<div class="card" style="background:#fff5f7cc;">
<b>Keywords Dictionary</b><br/>
<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-top:8px;">
  <div><b>Historical</b><br/><span class="muted small">historical, history, climatology, climate, typical, long-term, seasonal, diurnal, past</span></div>
  <div><b>Current</b><br/><span class="muted small">now, current, present, today, live</span></div>
  <div><b>Forecast</b><br/><span class="muted small">forecast, outlook, next, tomorrow, 5-day, 7-day, week, 10-day, 16-day</span></div>
</div>
</div>
""", unsafe_allow_html=True)

# ---------- Footer ----------
st.markdown("""
<div class="footer">
  <span class="badge">Open-Meteo</span>
  <span class="badge">MCP Server</span>
  <div style="margin-top:6px" class="muted small">© Arka Mitra, 2025</div>
</div>
""", unsafe_allow_html=True)