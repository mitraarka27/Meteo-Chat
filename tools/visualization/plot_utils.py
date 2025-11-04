"""
plot_utils.py
-------------
Generate tiny (<200 KB) PNG plots in base64 for:
- point time series (times, values)
- regional aggregates (index, mean, iqr)

No seaborn. Single-axis matplotlib only.
"""
from typing import Dict, Any, List, Optional
import io, base64
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

def _png_b64_from_fig(fig, max_kb: int = 200) -> str:
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    # compress if too big
    data = buf.getvalue()
    if len(data) > max_kb * 1024:
        # downscale using PIL
        im = Image.open(io.BytesIO(data)).convert("RGB")
        w, h = im.size
        scale = min(1.0, (max_kb * 1024) / len(data)) ** 0.5  # heuristic
        new = im.resize((max(200, int(w * scale)), max(120, int(h * scale))), Image.BILINEAR)
        out = io.BytesIO()
        new.save(out, format="PNG", optimize=True)
        data = out.getvalue()
    return base64.b64encode(data).decode("ascii")

def plot_point_series(variable: str, unit: str, times: List[str], values: List[Optional[float]]) -> str:
    x = np.array(pd_to_datetime(times))
    y = np.array([np.nan if v is None else v for v in values], dtype=float)
    fig, ax = plt.subplots(figsize=(6, 2.8))
    ax.plot(x, y)
    ax.set_title(f"{variable} ({unit})")
    ax.set_xlabel("time")
    ax.set_ylabel(unit)
    return _png_b64_from_fig(fig)

def plot_region_aggregate(variable: str, unit: str, index: List[int], mean: List[Optional[float]], iqr: List[Optional[float]]) -> str:
    x = np.array(index)
    m = np.array([np.nan if v is None else v for v in mean], dtype=float)
    q = np.array([0 if v is None else v for v in iqr], dtype=float)
    fig, ax = plt.subplots(figsize=(6, 2.8))
    ax.plot(x, m)
    ax.fill_between(x, m - q/2, m + q/2, alpha=0.2)
    ax.set_title(f"{variable} ({unit})")
    ax.set_xlabel("index")
    ax.set_ylabel(unit)
    return _png_b64_from_fig(fig)

# small helper (no pandas dependency)
def pd_to_datetime(times: List[str]):
    from datetime import datetime
    return [datetime.fromisoformat(t.replace("Z","")) for t in times]