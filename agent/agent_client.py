"""
agent_client.py
---------------
Thin client that, when enabled, converts MCP JSON outputs (plan + execute_result)
into a schema-valid narrative. Keep low temperature and validate JSON before use.

This file deliberately contains only interfaces & TODOs.
"""
from typing import Dict, Any, List
from tools.visualization.plot_utils import plot_point_series, plot_region_aggregate

def figures_from_execute(ex: Dict[str, Any]) -> List[Dict[str, str]]:
    figs: List[Dict[str, str]] = []
    for s in ex.get("series", []) or []:
        img_b64 = plot_point_series(s["variable"], s.get("unit",""), s.get("times", []), s.get("values", []))
        figs.append({"variable": s["variable"], "caption": f"{s['variable']} time series", "img_b64": img_b64})
    for a in ex.get("aggregates", []) or []:
        agg = a.get("aggregation", {})
        img_b64 = plot_region_aggregate(a["variable"], a.get("unit",""), agg.get("index", []), agg.get("mean", []), agg.get("iqr", []))
        figs.append({"variable": a["variable"], "caption": f"{a['variable']} mean±IQR (region)", "img_b64": img_b64})
    # Climatology blocks are multi-panel; keep it simple for now.
    return figs

def assemble_schema_answer(plan: Dict[str, Any], ex: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deterministic schema-only writer (no LLM). Attach figures.
    """
    vars_planned = [it.get("canonical") for it in plan.get("items", []) if it.get("canonical")]
    title = f"Results — {', '.join([v for v in vars_planned if v][:3])}"
    figs = figures_from_execute(ex)
    answer = "Deterministic summary generated from Open-Meteo results."
    return {
        "title": title,
        "answer": answer,
        "key_numbers": [],
        "figures": figs[:4],  # cap to keep payload small
        "method": "Open-Meteo first; unit conversions applied if requested.",
        "citations": ex.get("citations", []),
        "limitations": ex.get("limitations", []),
        "suggested_followups": ["Compare with different time mode", "Add humidity/wind for heat stress"]
    }