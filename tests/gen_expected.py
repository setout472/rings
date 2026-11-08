"""把 Python 引擎在示例数据上的结果导出成 JSON，给 tests/engine.test.js 做对拍。

    python tests/gen_expected.py

两边跑同一份 demo/photos.csv，逐项比。数字不一致就是移植出了偏差。
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from wrapped import clean, scan, trips  # noqa: E402


def main() -> None:
    csv_path = os.path.join(ROOT, "demo", "photos.csv")
    photos = scan.load_records_csv(csv_path)

    raw = clean.source_stats(photos)
    tz = clean.annotate_utc(photos)
    photos, dup = clean.dedupe(photos)
    photos, drift = clean.filter_drift(photos)

    payload = trips.build_payload(photos)

    out = {
        "meta": {
            "total": raw["total"],
            "with_gps": sum(1 for p in photos if p.lat is not None),
            "drift_removed": drift["drift_removed"],
            "duplicates_removed": dup["duplicates_removed"],
            "timezone_corrected": tz["timezone_corrected"],
        },
        "home": payload["home"],
        "years": [],
    }

    for block in payload["years"]:
        s = block["stats"]
        out["years"].append({
            "label": block["label"],
            "photos": s["photos"],
            "trips": s["trips"],
            "cities": s["cities"],
            "active_days": s["active_days"],
            "span_days": s["span_days"],
            "quiet_days": s["quiet"]["days"],
            "max_km": int(s["max_km"]),
            "trip_list": [
                {"start": t["start"], "days": t["days"], "photos": t["photos"],
                 "title": t["title"], "max_km": int(t["max_km"])}
                for t in block["trips"]
            ],
        })

    path = os.path.join(ROOT, "tests", "expected_demo.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("wrote", path)
    print("  photos=%d trips=%d" % (out["meta"]["total"], len(out["years"][0]["trip_list"])))


if __name__ == "__main__":
    main()
