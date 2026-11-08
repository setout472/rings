"""清洗：GPS 漂移过滤 + 时间统一为 UTC。

两个真实存在、且几乎所有人都会踩的坑：

1. GPS 漂移：室内 / 地下 / 高楼之间，坐标会突然跳到几公里外再跳回来。
   判据是「相邻两张照片算出来的移动速度」——超过 900 km/h（亚音速客机巡航约 850）一律视为漂移。
   这个阈值同时保留了真实航班（北京→上海 2 小时属正常），只剔除物理上不可能的跳变。

2. 时区：EXIF 的 DateTimeOriginal 是**拍摄地当地时间**，不带时区。
   直接拿来排序，跨时区旅行时会出现「照片时间倒流」。
   有 GPS 时用经度粗推偏移量回算 UTC；没有 GPS 就只能保持当地时间并如实标注。
"""

from __future__ import annotations

from datetime import timedelta

from . import geo
from .scan import Photo

MAX_SPEED_KMH = 900.0
MIN_DISTANCE_KM = 50.0   # 小于这个位移量，速度再离谱也只是测量噪声，不判漂移
NEIGHBOR_JUMP_KM = 3000.0  # 与前后邻居都相距这么远的点，无论间隔多久都不可能是真的


def annotate_utc(photos: list[Photo]) -> dict:
    """给每张照片补上 UTC 时间（原地加属性），返回统计信息。

    统计的是「跨时区拍摄」的张数：以出现最多的时区偏移作为基准（通常就是常住地），
    其余照片才算真的跨了时区。
    """
    offsets = [geo.tz_offset_hours(p.lon, p.lat) for p in photos if p.lon is not None]
    base = max(set(offsets), key=offsets.count) if offsets else 0

    corrected = 0
    for p in photos:
        offset = geo.tz_offset_hours(p.lon, p.lat) if p.lon is not None else base
        if p.lon is not None and offset != base:
            corrected += 1
        p.utc = p.dt - timedelta(hours=offset)
    return {"timezone_corrected": corrected}


def filter_drift(photos: list[Photo], max_speed_kmh: float = MAX_SPEED_KMH) -> tuple[list[Photo], dict]:
    """剔除 GPS 漂移点。返回 (保留的照片, 统计)。

    判据是**两边都不合理**：一个点同时相对前后邻居都出现物理上不可能的速度，
    它才是那个孤立的错误点（前后两张都是真的，中间那张是设备抽风）。
    只与单边不合理的点通常是真实位移（例如落地后拍的第一张），保留。
    """
    gps = [p for p in photos if p.lat is not None]
    if len(gps) < 3:
        return photos, {"drift_removed": 0}

    pts = sorted(gps, key=lambda p: getattr(p, "utc", p.dt))
    n = len(pts)
    viol = [0] * n

    for i in range(n - 1):
        a, b = pts[i], pts[i + 1]
        dt_h = (getattr(b, "utc", b.dt) - getattr(a, "utc", a.dt)).total_seconds() / 3600.0
        if dt_h <= 0:
            continue
        dist = geo.haversine(a.lat, a.lon, b.lat, b.lon)
        # 距离门槛很关键：间隔几秒的两张照片天然会差几公里，
        # 单看速度会把正常的连拍判成漂移
        if dist > MIN_DISTANCE_KM and dist / dt_h > max_speed_kmh:
            viol[i] += 1
            viol[i + 1] += 1

    bad_idx = {i for i, c in enumerate(viol) if c >= 2}

    # 补一条不依赖时间的判据：如果一个点跟前后邻居都相距几千公里，
    # 那它一定是个孤立的错误点——间隔多久都不影响这个结论。
    # （只靠速度会漏掉「漂移点恰好落在两张相隔很久的照片之间」的情况）
    for i in range(1, n - 1):
        if i in bad_idx:
            continue
        d_prev = geo.haversine(pts[i - 1].lat, pts[i - 1].lon, pts[i].lat, pts[i].lon)
        d_next = geo.haversine(pts[i].lat, pts[i].lon, pts[i + 1].lat, pts[i + 1].lon)
        if d_prev > NEIGHBOR_JUMP_KM and d_next > NEIGHBOR_JUMP_KM:
            bad_idx.add(i)

    # 端点只有一个邻居：只有距离离谱到不可能是真实位移时才判脏
    for i in (0, n - 1):
        if i in bad_idx:
            continue
        j = 1 if i == 0 else n - 2
        dt_h = abs((getattr(pts[j], "utc", pts[j].dt) - getattr(pts[i], "utc", pts[i].dt)).total_seconds()) / 3600.0
        dist = geo.haversine(pts[i].lat, pts[i].lon, pts[j].lat, pts[j].lon)
        if dt_h > 0 and dist > MIN_DISTANCE_KM and dist / dt_h > 3000:
            bad_idx.add(i)

    bad = {id(pts[i]) for i in bad_idx}
    kept = [p for p in photos if id(p) not in bad]
    return kept, {"drift_removed": len(bad)}


def dedupe(photos: list[Photo]) -> tuple[list[Photo], dict]:
    """同一秒、同一坐标的重复记录（连拍 / 备份重复文件）合并。"""
    seen: set[tuple] = set()
    kept: list[Photo] = []
    removed = 0
    for p in photos:
        key = (p.dt, round(p.lat, 4) if p.lat is not None else None,
               round(p.lon, 4) if p.lon is not None else None)
        if key in seen:
            removed += 1
            continue
        seen.add(key)
        kept.append(p)
    return kept, {"duplicates_removed": removed}


def source_stats(photos: list[Photo]) -> dict:
    """数据可信度画像：每一张照片的时间/GPS 是从哪来的。"""
    total = len(photos)
    with_gps = sum(1 for p in photos if p.lat is not None)
    by_source: dict[str, int] = {}
    for p in photos:
        by_source[p.source] = by_source.get(p.source, 0) + 1
    return {
        "total": total,
        "with_gps": with_gps,
        "gps_ratio": round(with_gps / total, 3) if total else 0.0,
        "by_source": by_source,
    }
