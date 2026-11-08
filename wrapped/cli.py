"""命令行入口。

    python -m wrapped demo
    python -m wrapped footprint --photos "D:/Pictures" --out out/footprint.html
    python -m wrapped footprint --csv demo/photos.csv --out out/footprint.html
    python -m wrapped reading  --csv demo/books.csv --out out/reading.html --label 2024
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

from . import __version__, books, clean, render, render_wrapped, scan, thumbs, trips, webbuild
from . import demo as demo_mod
from .util import scrub


def _ensure_dir(path: str) -> None:
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)


def build_footprint(photos_path: str | None, csv_path: str | None, out_path: str,
                    thumb_budget: int = 40, title: str = "我的照片足迹") -> str:
    if photos_path:
        photos = scan.scan_photos(photos_path)
    elif csv_path:
        photos = scan.load_records_csv(csv_path)
    else:
        raise SystemExit("需要 --photos 目录 或 --csv 文件")

    if not photos:
        raise SystemExit("没有读到任何照片记录")

    raw = clean.source_stats(photos)
    tz_stats = clean.annotate_utc(photos)
    photos, dup_stats = clean.dedupe(photos)
    photos, drift_stats = clean.filter_drift(photos)

    payload = trips.build_payload(photos)
    made = thumbs.attach_thumbs(payload["years"][0]["trips"], budget=thumb_budget)

    meta = {
        "total": raw["total"],
        "with_gps": sum(1 for p in photos if p.lat is not None),
        "gps_ratio": 0.0,
        "by_source": raw["by_source"],
        "drift_removed": drift_stats["drift_removed"],
        "duplicates_removed": dup_stats["duplicates_removed"],
        "timezone_corrected": tz_stats["timezone_corrected"],
        "thumbs": made,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "version": __version__,
    }
    meta["gps_ratio"] = round(meta["with_gps"] / raw["total"], 3) if raw["total"] else 0.0

    _ensure_dir(out_path)
    render.render_footprint(scrub(payload), meta, out_path, title=title)
    return out_path


def build_reading(csv_path: str, out_path: str, label: str | None = None) -> str:
    records = books.load_csv(csv_path)
    payload = books.build_payload(records, label=label or "")
    _ensure_dir(out_path)
    render_wrapped.render_wrapped(payload, out_path, label=label)
    return out_path


def _report(path: str) -> None:
    size = os.path.getsize(path)
    unit = f"{size / 1024:.0f} KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f} MB"
    print(f"  OK  {path}  ({unit})")


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(prog="wrapped", description="把个人数据变成年度叙事")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_fp = sub.add_parser("footprint", help="照片 -> 足迹地图")
    p_fp.add_argument("--photos", help="相册目录（递归扫描 EXIF）")
    p_fp.add_argument("--csv", help="照片记录 CSV（path,datetime,lat,lon）")
    p_fp.add_argument("--out", default="out/footprint.html")
    p_fp.add_argument("--thumbs", type=int, default=40, help="缩略图总数上限，0 = 关闭")
    p_fp.add_argument("--title", default="我的照片足迹")

    p_rd = sub.add_parser("reading", help="阅读/观影 CSV -> Wrapped")
    p_rd.add_argument("--csv", required=True)
    p_rd.add_argument("--out", default="out/reading.html")
    p_rd.add_argument("--label", default=None, help="标题里显示的时间范围，如 2024")

    p_dm = sub.add_parser("demo", help="生成演示数据并产出两份报告")
    p_dm.add_argument("--root", default="demo", help="演示数据目录")

    p_wb = sub.add_parser("webbuild", help="生成前端静态产物（cities.js / report.html）")
    p_wb.add_argument("--dir", default="web", help="前端目录")

    args = ap.parse_args(argv)

    print(f"wrapped v{__version__}")

    if args.cmd == "demo":
        info = demo_mod.generate_demo(args.root)
        print(f"  demo data: {info['photos']} photos, {info['trip_count']} trips")
        a = build_footprint(None, info["photos_csv"], "out/footprint.html", thumb_budget=36)
        _report(a)
        b = build_reading(info["books_csv"], "out/reading.html", label="2024")
        _report(b)
        return 0

    if args.cmd == "footprint":
        out = build_footprint(args.photos, args.csv, args.out,
                              thumb_budget=max(0, args.thumbs), title=args.title)
        _report(out)
        return 0

    if args.cmd == "reading":
        out = build_reading(args.csv, args.out, label=args.label)
        _report(out)
        return 0

    if args.cmd == "webbuild":
        for out in webbuild.build_all(args.dir):
            _report(out)
        return 0

    return 1
