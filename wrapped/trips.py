"""出行事件识别与年度汇总。

核心问题：「旅行」到底是什么？
不是「离开家」，而是「离开家足够远、且停留足够久」。
一个去隔壁城市当天来回的出差，和一次去成都的五天休假，在产品上应该区分对待。

参数（都能改，写清楚原因）：
    AWAY_KM      = 100   超过 100km 才算「离巢」，避开城际通勤
    GAP_HOURS    = 48    两次「离家照片」间隔超过 48h 就切成两段行程
    MIN_PHOTOS   = 3     少于 3 张照片的行程不成立（可能只是一张路上随手拍）
    MIN_MAX_KM   = 150   行程最远点至少要 150km
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from . import geo
from .scan import Photo

AWAY_KM = 100.0
GAP_HOURS = 48.0
MIN_PHOTOS = 3
MIN_MAX_KM = 150.0


def _utc(p: Photo):
    return getattr(p, "utc", p.dt)


def detect_home(gps_photos: list[Photo]) -> tuple[float, float] | None:
    """用「照片最密集的 0.2° 网格」近似常住地，再用该网格内的点求均值。"""
    if not gps_photos:
        return None
    cells: dict[tuple[float, float], list[Photo]] = {}
    for p in gps_photos:
        key = (round(p.lat * 5) / 5, round(p.lon * 5) / 5)
        cells.setdefault(key, []).append(p)
    best = max(cells.values(), key=len)
    clat = sum(p.lat for p in best) / len(best)
    clon = sum(p.lon for p in best) / len(best)
    near = [p for p in gps_photos if geo.haversine(p.lat, p.lon, clat, clon) <= 30.0]
    if not near:
        near = best
    return (sum(p.lat for p in near) / len(near), sum(p.lon for p in near) / len(near))


def _sample(points: list[tuple[float, float]], cap: int = 120) -> list[list[float]]:
    if len(points) <= cap:
        return [[round(a, 5), round(b, 5)] for a, b in points]
    step = len(points) / cap
    picked = [points[int(i * step)] for i in range(cap)]
    picked[-1] = points[-1]
    return [[round(a, 5), round(b, 5)] for a, b in picked]


def segment_trips(photos: list[Photo], home: tuple[float, float],
                  away_km: float = AWAY_KM, gap_hours: float = GAP_HOURS,
                  min_photos: int = MIN_PHOTOS, min_max_km: float = MIN_MAX_KM) -> list[list[Photo]]:
    """把照片按「离家 + 时间连续」切成一段段行程。"""
    gps = sorted([p for p in photos if p.lat is not None], key=_utc)
    away: list[Photo] = []
    dists: dict[int, float] = {}
    for p in gps:
        d = geo.haversine(home[0], home[1], p.lat, p.lon)
        dists[id(p)] = d
        if d > away_km:
            away.append(p)

    runs: list[list[Photo]] = []
    for p in away:
        if runs and (_utc(p) - _utc(runs[-1][-1])).total_seconds() / 3600.0 <= gap_hours:
            runs[-1].append(p)
        else:
            runs.append([p])

    keep: list[list[Photo]] = []
    for run in runs:
        if len(run) < min_photos:
            continue
        if max(dists[id(p)] for p in run) < min_max_km:
            continue
        keep.append(run)
    return keep


def _trip_json(run: list[Photo], idx: int, dists: dict[int, float]) -> dict:
    # 展示用当地日期：用 UTC 会把日本行程的前一天算成出发日
    start, end = run[0].dt, run[-1].dt
    days = max(1, (end.date() - start.date()).days + 1)
    city_counter = Counter()
    for p in run:
        name, _ = geo.nearest_city(p.lat, p.lon)
        if name != geo.UNKNOWN_CITY:
            city_counter[name] += 1
    cities = [c for c, _ in city_counter.most_common(4)]
    max_km = max(dists.get(id(p), 0.0) for p in run)
    lats = [p.lat for p in run]
    lons = [p.lon for p in run]
    title = " · ".join(cities[:2]) if cities else "一段没有名字的旅程"
    ordered = sorted(run, key=lambda x: x.dt)
    step = max(1, len(ordered) // 8)
    picked = ordered[::step][:8]
    return {
        "id": idx,
        "start": start.strftime("%Y-%m-%d"),
        "end": end.strftime("%Y-%m-%d"),
        "days": days,
        "photos": len(run),
        "cities": cities,
        "title": title,
        "max_km": round(max_km, 1),
        "center": [round(sum(lats) / len(lats), 4), round(sum(lons) / len(lons), 4)],
        "poly": _sample([(p.lat, p.lon) for p in run]),
        "thumbs": [],
        "_paths": [p.path for p in picked if p.path],
        "_year": start.year,
        "_month": start.month,
    }


def _longest_streak(days: set) -> int:
    if not days:
        return 0
    ordered = sorted(days)
    best = cur = 1
    for prev, now in zip(ordered, ordered[1:]):
        cur = cur + 1 if (now - prev).days == 1 else 1
        best = max(best, cur)
    return best


def _calendar(day_counts: Counter, start: date, end: date) -> dict:
    """把每天的拍照数铺成 7 行 × N 列的日历（周一为每周第一天）。"""
    grid_start = start - timedelta(days=start.weekday())
    grid_end = end + timedelta(days=(6 - end.weekday()))
    weeks: list[list[int | None]] = []
    cur = grid_start
    while cur <= grid_end:
        week: list[int | None] = []
        for i in range(7):
            d = cur + timedelta(days=i)
            week.append(None if (d < start or d > end) else day_counts.get(d, 0))
        weeks.append(week)
        cur += timedelta(days=7)
    return {"from": grid_start.isoformat(), "weeks": weeks}


def _quiet_gap(days: list[date]) -> dict:
    """最长的一段「没按快门」——比任何数字都更像一个人的生活。"""
    best, qf, qt = 0, None, None
    for a, b in zip(days, days[1:]):
        gap = (b - a).days - 1
        if gap > best:
            best, qf, qt = gap, a.isoformat(), b.isoformat()
    return {"days": best, "from": qf, "to": qt}


def build_year_block(year_label: str, photos: list[Photo], home: tuple[float, float],
                     dists: dict[int, float], trips: list[dict], year: int | None,
                     home_city: str = "") -> dict:
    """单个年度（或「全部」）的统计块。

    城市统计**排除常住地**：用户想知道的是「我去过哪」，
    而不是「我在家拍了多少张」——后者会把榜单压成一根柱子。
    """
    gps = [p for p in photos if p.lat is not None]
    cities = Counter()
    for p in gps:
        name, _ = geo.nearest_city(p.lat, p.lon)
        if name != geo.UNKNOWN_CITY and name != home_city:
            cities[name] += 1

    north = max(gps, key=lambda p: p.lat) if gps else None
    south = min(gps, key=lambda p: p.lat) if gps else None
    max_km = max((dists.get(id(p), 0.0) for p in gps), default=0.0)
    furthest = max(gps, key=lambda p: dists.get(id(p), 0.0)) if gps else None

    day_counts = Counter(p.dt.date() for p in photos)
    if year is not None:
        cal_start, cal_end = date(year, 1, 1), date(year, 12, 31)
    else:
        last = max(day_counts) if day_counts else date.today()
        cal_start, cal_end = last - timedelta(days=364), last

    # 「活跃天数」和「最长沉默」必须和日历图用同一个时间窗，
    # 否则「全部」视图会出现「这 365 天里你有 535 天按了快门」这种自相矛盾
    window_counts = Counter({d: c for d, c in day_counts.items() if cal_start <= d <= cal_end})
    active = sorted(window_counts)

    return {
        "label": year_label,
        "year": year,
        "stats": {
            "photos": len(photos),
            "trips": len(trips),
            "cities": len(cities),
            "max_km": round(max_km, 0),
            "away_days": sum(t["days"] for t in trips),
            "active_days": len(active),
            "longest_streak": _longest_streak(set(active)),
            "span_days": (cal_end - cal_start).days + 1,
            "cal": _calendar(window_counts, cal_start, cal_end),
            "quiet": _quiet_gap(active),
            "north": (geo.nearest_city(north.lat, north.lon)[0] if north else "—"),
            "south": (geo.nearest_city(south.lat, south.lon)[0] if south else "—"),
            "furthest_city": (geo.nearest_city(furthest.lat, furthest.lon)[0] if furthest else "—"),
            "top_cities": [{"name": c, "n": n} for c, n in cities.most_common(8)],
        },
        "trips": sorted(trips, key=lambda t: t["start"], reverse=True),
    }


def build_payload(photos: list[Photo], *, home: tuple[float, float] | None = None) -> dict:
    """把清洗后的照片整理成报告需要的完整 payload。"""
    gps = [p for p in photos if p.lat is not None]
    if home is None:
        home = detect_home(gps)
    if home is None:
        raise ValueError("没有任何带 GPS 的照片，无法生成足迹报告")

    dists = {id(p): geo.haversine(home[0], home[1], p.lat, p.lon) for p in gps}
    runs = segment_trips(photos, home)
    trips = [_trip_json(run, i, dists) for i, run in enumerate(runs)]

    home_city, _ = geo.nearest_city(home[0], home[1])

    years = sorted({p.dt.year for p in photos}, reverse=True)
    blocks = []
    for y in years:
        yp = [p for p in photos if p.dt.year == y]
        blocks.append(build_year_block(str(y), yp, home, dists,
                                       [t for t in trips if t["_year"] == y], y, home_city))
    blocks.insert(0, build_year_block("全部", photos, home, dists, trips, None, home_city))

    return {
        "home": {"lat": round(home[0], 4), "lon": round(home[1], 4), "city": home_city},
        "years": blocks,
    }
