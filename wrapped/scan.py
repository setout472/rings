"""扫描照片目录，抽取时间与 GPS。

三级降级策略（真实相册里三种情况都会遇到）：

1. EXIF DateTimeOriginal + GPS      -> 最好，标记为 exif
2. 文件名里的时间戳（IMG_20240501_123456）-> 有 GPS 也可能没有，标记为 filename
3. 文件修改时间                      -> 最后的兜底，标记为 mtime（不可信）

明确记录每张照片的来源，最后在报告里如实披露 —— 数据可信度是产品的一部分。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime

from . import geo

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".heic", ".heif"}

# IMG_20240501_123456 / PXL_20240501_123456789 / 2024-05-01 12.34.56
_NAME_DT = re.compile(r"(20\d{2})[^0-9]?(0[1-9]|1[0-2])[^0-9]?(0[1-9]|[12]\d|3[01])[^0-9]?(\d{2})[^0-9]?(\d{2})[^0-9]?(\d{2})")

_EXIF_DT_ORIGINAL = 36867
_EXIF_DT = 306
_EXIF_GPS_IFD = 0x8825
_EXIF_EXIF_IFD = 0x8769
_EXIF_MAKE = 271
_EXIF_MODEL = 272
_GPS_LAT_REF, _GPS_LAT = 1, 2
_GPS_LON_REF, _GPS_LON = 3, 4


@dataclass
class Photo:
    path: str
    dt: datetime          # 本地时间（EXIF 记录的是拍摄地当地时间，不带时区）
    lat: float | None
    lon: float | None
    source: str           # exif / filename / mtime
    camera: str = ""

    def to_json(self) -> dict:
        d = asdict(self)
        d["dt"] = self.dt.isoformat(timespec="seconds")
        return d


def _to_float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _dms_to_deg(dms, ref) -> float | None:
    """把 EXIF 的 (度, 分, 秒) + 半球引用 转成十进制度。"""
    if not dms or len(dms) < 3:
        return None
    try:
        d, m, s = (float(x) for x in dms)
    except (TypeError, ValueError):
        return None
    val = d + m / 60.0 + s / 3600.0
    if isinstance(ref, bytes):
        ref = ref.decode("ascii", "ignore")
    if isinstance(ref, str) and ref.strip().upper() in ("S", "W"):
        val = -val
    return val if -180 <= val <= 180 else None


def _read_exif(path: str) -> dict:
    """读出 (datetime, lat, lon, camera)，缺失的字段为 None。"""
    out = {"dt": None, "lat": None, "lon": None, "camera": ""}
    try:
        from PIL import Image
    except ImportError:
        return out

    try:
        with Image.open(path) as im:
            exif = im.getexif()
            if not exif:
                return out

            raw_dt = None
            try:
                raw_dt = exif.get_ifd(_EXIF_EXIF_IFD).get(_EXIF_DT_ORIGINAL)
            except Exception:
                pass
            if not raw_dt:
                raw_dt = exif.get(_EXIF_DT)
            if raw_dt:
                if isinstance(raw_dt, bytes):
                    raw_dt = raw_dt.decode("ascii", "ignore")
                raw_dt = str(raw_dt).strip().replace("-", ":", 2)
                try:
                    out["dt"] = datetime.strptime(raw_dt[:19], "%Y:%m:%d %H:%M:%S")
                except ValueError:
                    pass

            make = exif.get(_EXIF_MAKE) or ""
            model = exif.get(_EXIF_MODEL) or ""
            out["camera"] = " ".join(
                str(x).strip() for x in (make, model) if x
            ).strip()

            try:
                gps = exif.get_ifd(_EXIF_GPS_IFD)
            except Exception:
                gps = {}
            if gps:
                lat = _dms_to_deg(gps.get(_GPS_LAT), gps.get(_GPS_LAT_REF))
                lon = _dms_to_deg(gps.get(_GPS_LON), gps.get(_GPS_LON_REF))
                # 0,0 是常见的无效 GPS（设备未定位时的占位符）
                if lat is not None and lon is not None and not (abs(lat) < 0.01 and abs(lon) < 0.01):
                    out["lat"], out["lon"] = lat, lon
    except Exception:
        pass
    return out


def _dt_from_name(name: str) -> datetime | None:
    m = _NAME_DT.search(name)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                        int(m.group(4)), int(m.group(5)), int(m.group(6)))
    except ValueError:
        return None


def scan_photos(root: str, limit: int | None = None) -> list[Photo]:
    """递归扫描目录，返回按时间排序的照片列表。"""
    photos: list[Photo] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in IMAGE_EXTS:
                continue
            full = os.path.join(dirpath, fn)
            ex = _read_exif(full)

            if ex["dt"] is not None:
                dt, source = ex["dt"], "exif"
            else:
                dt, source = _dt_from_name(fn), "filename"
                if dt is None:
                    try:
                        dt = datetime.fromtimestamp(os.path.getmtime(full))
                    except OSError:
                        continue
                    source = "mtime"

            photos.append(Photo(full, dt, ex["lat"], ex["lon"], source, ex["camera"]))
            if limit and len(photos) >= limit:
                photos.sort(key=lambda p: p.dt)
                return photos

    photos.sort(key=lambda p: p.dt)
    return photos


def load_records_csv(path: str) -> list[Photo]:
    """从 CSV 读记录（演示 / 手动补录用）。

    列：path, datetime, lat, lon，可选 source（exif / filename / mtime）。
    没有 source 就按 csv 记，报告里的数据可信度会如实反映。
    """
    import csv

    out: list[Photo] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            raw = (row.get("datetime") or "").strip()
            if not raw:
                continue
            dt = None
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(raw[:19], fmt)
                    break
                except ValueError:
                    continue
            if dt is None:
                continue
            lat = _to_float(row.get("lat"))
            lon = _to_float(row.get("lon"))
            if lat is not None and lon is not None and abs(lat) < 0.01 and abs(lon) < 0.01:
                lat = lon = None
            source = (row.get("source") or "csv").strip() or "csv"
            out.append(Photo(row.get("path", ""), dt, lat, lon, source))
    out.sort(key=lambda p: p.dt)
    return out
