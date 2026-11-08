"""构建前端需要的静态产物。

前端要跑在浏览器里，但城市表和报告模板的唯一事实来源在 Python 这边。
所以每次改完 geo.py 或 render.py，跑一次 `python -m wrapped webbuild` 重新生成，
而不是手抄一份到 JS 里——两份数据迟早会分叉。
"""

from __future__ import annotations

import json
import os
from datetime import datetime

from . import __version__, clean, geo, render, scan, thumbs, trips
from .util import scrub


def _write(path: str, text: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def build_cities(path: str) -> str:
    data = [[name, lat, lon] for name, lat, lon in geo.CITIES]
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # 用 IIFE 挂到全局，这样 Node 里也能 require 进来做对拍
    return _write(path, "/* 由 wrapped/geo.py 生成，不要手改。python -m wrapped webbuild */\n"
                        "(function(g){g.RingsCities=" + body + ";})"
                        "(typeof window!=='undefined'?window:globalThis);\n")


def build_sample(csv_path: str, out_path: str, budget: int = 36) -> str | None:
    """把示例数据算成一份 payload，供报告页 ?demo=1 直接加载。

    这样访客不装任何东西也能看到完整报告——连地图和缩略图都在。
    """
    if not os.path.exists(csv_path):
        return None

    photos = scan.load_records_csv(csv_path)
    raw = clean.source_stats(photos)
    tz = clean.annotate_utc(photos)
    photos, dup = clean.dedupe(photos)
    photos, drift = clean.filter_drift(photos)

    payload = trips.build_payload(photos)
    made = thumbs.attach_thumbs(payload["years"][0]["trips"], budget=budget)

    with_gps = sum(1 for p in photos if p.lat is not None)
    meta = {
        "total": raw["total"],
        "with_gps": with_gps,
        "gps_ratio": round(with_gps / raw["total"], 3) if raw["total"] else 0.0,
        "by_source": raw["by_source"],
        "drift_removed": drift["drift_removed"],
        "duplicates_removed": dup["duplicates_removed"],
        "timezone_corrected": tz["timezone_corrected"],
        "thumbs": made,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "version": __version__ + "-demo",
    }

    data = scrub(payload)
    data["meta"] = meta
    return _write(out_path, json.dumps(data, ensure_ascii=False, separators=(",", ":")))


def build_all(web_dir: str = "web") -> list[str]:
    web_dir = os.path.abspath(web_dir)
    root = os.path.dirname(web_dir)

    outs = [
        build_cities(os.path.join(web_dir, "js", "cities.js")),
        render.render_web_report(os.path.join(web_dir, "report.html")),
    ]
    sample = build_sample(os.path.join(root, "demo", "photos.csv"),
                          os.path.join(web_dir, "sample.json"))
    if sample:
        outs.append(sample)
    return outs
