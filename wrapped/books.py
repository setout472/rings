"""阅读/观影数据适配器：读 CSV → 归一化 → 统计。

设计上刻意「容忍脏输入」：豆瓣导出、手动表格、Notion 导出，列名和格式都不一样。
所以这里做三件事：列名模糊匹配、评分多格式解析、缺列降级（没有大众评分就不算口味偏差）。
"""

from __future__ import annotations

import csv
import re
from collections import Counter
from datetime import datetime

ALIASES = {
    "title": ["标题", "名称", "书名", "片名", "电影名", "剧名", "title", "name"],
    "my_rating": ["我的评分", "评分", "打分", "星级", "rating", "star", "my_rating"],
    "avg_rating": ["大众评分", "豆瓣评分", "平均分", "均分", "avg_rating", "average"],
    "date": ["日期", "标记日期", "观看日期", "看过日期", "时间", "date", "watched"],
    "tags": ["标签", "类型", "分类", "题材", "tags", "genre"],
    "year": ["年份", "出版年", "上映年份", "发行年", "year"],
    "creator": ["作者", "导演", "主演", "creator", "author", "director"],
}

_SPLIT = re.compile(r"[,，/|、;；]+")


def _pick(row: dict, field: str) -> str:
    for key in ALIASES[field]:
        for col in row:
            if col is None:
                continue
            if col.strip().lower() == key.lower():
                v = row[col]
                return (v or "").strip() if isinstance(v, str) else ("" if v is None else str(v).strip())
    return ""


def parse_rating(raw: str) -> float | None:
    """支持 4 / 4.5 / 4星 / ★★★★☆ / 8.6（十分制）。"""
    if not raw:
        return None
    raw = raw.strip().replace("．", ".").replace("。", ".")
    if "★" in raw or "☆" in raw:
        return float(raw.count("★")) if raw.count("★") else None
    m = re.search(r"\d+(?:\.\d+)?", raw)
    if not m:
        return None
    val = float(m.group())
    if val > 5:          # 十分制转换
        val = val / 2.0
    return round(min(5.0, max(0.0, val)), 2)


def parse_date(raw: str) -> datetime | None:
    if not raw:
        return None
    s = raw.strip().replace("年", "-").replace("月", "-").replace("日", "")
    s = s.replace("/", "-").replace(".", "-")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y-%m"):
        try:
            return datetime.strptime(s[:len(fmt) + 2].strip(), fmt)
        except ValueError:
            continue
    m = re.match(r"(20\d{2}|19\d{2})-(\d{1,2})", s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), 1)
        except ValueError:
            return None
    return None


def load_csv(path: str) -> list[dict]:
    records: list[dict] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            title = _pick(row, "title")
            if not title:
                continue
            tags_raw = _pick(row, "tags")
            tags = [t.strip() for t in _SPLIT.split(tags_raw) if t.strip()] if tags_raw else []
            year_raw = _pick(row, "year")
            ym = re.search(r"(19|20)\d{2}", year_raw)
            records.append({
                "title": title,
                "my_rating": parse_rating(_pick(row, "my_rating")),
                "avg_rating": parse_rating(_pick(row, "avg_rating")),
                "date": parse_date(_pick(row, "date")),
                "tags": tags,
                "year": int(ym.group()) if ym else None,
                "creator": _pick(row, "creator"),
            })
    records = [r for r in records if r["date"] is not None]
    records.sort(key=lambda r: r["date"])
    return records


def _streaks(dates: list[datetime]) -> tuple[int, int]:
    """返回 (最长连续天数, 最长空窗天数)。"""
    if not dates:
        return 0, 0
    days = sorted({d.date() for d in dates})
    longest = cur = 1
    gap = 0
    for a, b in zip(days, days[1:]):
        delta = (b - a).days
        cur = cur + 1 if delta == 1 else 1
        longest = max(longest, cur)
        gap = max(gap, delta - 1)
    return longest, gap


def build_payload(records: list[dict], label: str = "") -> dict:
    if not records:
        raise ValueError("没有可用记录：请检查 CSV 里是否有「标题」和可解析的「日期」列")

    n = len(records)
    years = sorted({r["date"].year for r in records})
    months = Counter(r["date"].month for r in records)
    ratings = [r["my_rating"] for r in records if r["my_rating"] is not None]
    deltas = [r["my_rating"] - r["avg_rating"] for r in records
              if r["my_rating"] is not None and r["avg_rating"] is not None]

    tag_counter = Counter()
    for r in records:
        for t in r["tags"]:
            tag_counter[t] += 1

    creator_counter = Counter(r["creator"] for r in records if r["creator"])

    rated = [r for r in records if r["my_rating"] is not None]
    best = max(rated, key=lambda r: (r["my_rating"], r["date"])) if rated else None
    worst = min(rated, key=lambda r: (r["my_rating"], r["date"])) if rated else None

    # 与大众口味分歧最大的那一部（只在同时有两个评分时算）
    divergent = None
    both = [r for r in records if r["my_rating"] is not None and r["avg_rating"] is not None]
    if both:
        divergent = max(both, key=lambda r: abs(r["my_rating"] - r["avg_rating"]))

    longest, gap = _streaks([r["date"] for r in records])
    avg = round(sum(ratings) / len(ratings), 2) if ratings else None
    delta = round(sum(deltas) / len(deltas), 2) if deltas else None

    # 评分分布：0.5 星一档
    hist = [0] * 10
    for v in ratings:
        hist[min(9, max(0, int(v * 2)))] += 1

    return {
        "label": label,
        "n": n,
        "first": records[0]["date"].strftime("%Y-%m-%d"),
        "last": records[-1]["date"].strftime("%Y-%m-%d"),
        "years": years,
        "months": [months.get(m, 0) for m in range(1, 13)],
        "avg": avg,
        "delta": delta,
        "rated_count": len(ratings),
        "hist": hist,
        "tags": [{"name": t, "n": c} for t, c in tag_counter.most_common(10)],
        "creators": [{"name": c, "n": k} for c, k in creator_counter.most_common(5) if k > 1],
        "best": best,
        "worst": worst,
        "divergent": divergent,
        "longest_streak": longest,
        "longest_gap": gap,
        "release_years": sorted({r["year"] for r in records if r["year"]}),
    }
