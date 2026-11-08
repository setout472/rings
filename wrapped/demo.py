"""手写的示例数据：一个有具体生活轨迹的人，而不是随机撒点。

三条原则：

1. **有情节**。三年里有一条能讲出来的时间线：解封后的第一次远行、一次只拍了 29 张的出差、
   春节带家人去三亚、换手机丢掉的一段时间戳。
2. **有沉默**。真实相册不是均匀分布的，2022 年春天有 79 天空白。这份空白是整个报告里最像人的地方。
3. **有脏数据**。重复导入、山谷里的 GPS 漂移、相机照片没有定位——真实相册一定有这些，
   而且正好用来演示清洗逻辑真的在干活。

数据全部是编的，不对应任何真实的人。
"""

from __future__ import annotations

import colorsys
import csv
import os
import random
from datetime import datetime, timedelta

HOME = ("上海", 31.2304, 121.4737)

CITY_POS = {
    "上海": (31.2304, 121.4737), "三亚": (18.2528, 109.5119),
    "成都": (30.5728, 104.0668), "大理": (25.6065, 100.2676),
    "北京": (39.9042, 116.4074), "东京": (35.6762, 139.6503),
    "西安": (34.3416, 108.9398), "杭州": (30.2741, 120.1551),
    "大阪": (34.6937, 135.5023), "京都": (35.0116, 135.7681),
    "奈良": (34.6851, 135.8048), "箱根": (35.2324, 139.1069),
    "哈尔滨": (45.8038, 126.5350), "青岛": (36.0671, 120.3826),
    "乌鲁木齐": (43.8256, 87.6168), "喀什": (39.4677, 75.9938),
    "香港": (22.3193, 114.1694), "昆明": (25.0389, 102.7183),
    "丽江": (26.8721, 100.2299), "都江堰": (31.0077, 103.6377),
    "乐山": (29.5521, 103.7652), "乌镇": (30.7450, 120.4870),
    "九寨沟": (33.2600, 103.9180),
}

# 日常生活的拍摄密度：(起, 止, 当天拍照的概率, 每天张数范围)
# 2022-03-14 到 2022-05-31 整天没有安排 —— 那 79 天没按过快门
HOME_PERIODS = [
    ("2022-01-01", "2022-03-13", 0.55, (1, 6)),
    ("2022-06-01", "2022-12-31", 0.50, (1, 5)),
    ("2023-01-01", "2023-12-31", 0.48, (1, 5)),
    ("2024-01-01", "2024-12-31", 0.46, (1, 6)),
]

# 每天的张数是手写的，不是随机数：到达日少、中间多、离开日回落
TRIPS = [
    {"route": ["昆明", "大理", "丽江"], "start": "2022-08-06",
     "per_day": [32, 45, 61, 52, 47, 58, 41, 30], "note": "解封后的第一次远行"},
    {"route": ["杭州", "乌镇"], "start": "2022-11-12",
     "per_day": [26, 21], "note": "周末"},
    {"route": ["哈尔滨"], "start": "2023-01-20",
     "per_day": [24, 37, 44, 33, 20], "note": "春节去看冰雕"},
    {"route": ["北京"], "start": "2023-03-06",
     "per_day": [9, 14, 6], "note": "出差，只在会场和酒店附近拍了几张"},
    {"route": ["东京", "箱根"], "start": "2023-05-01",
     "per_day": [41, 53, 68, 62, 51, 58, 48, 36], "note": "第一次去日本"},
    {"route": ["青岛"], "start": "2023-08-19",
     "per_day": [19, 16], "note": "带了相机"},
    {"route": ["成都", "九寨沟"], "start": "2023-10-01",
     "per_day": [29, 40, 52, 44, 34, 25], "note": "国庆"},
    {"route": ["三亚"], "start": "2024-02-08",
     "per_day": [27, 34, 39, 36, 31, 23], "note": "带爸妈过年"},
    {"route": ["大阪", "京都", "奈良"], "start": "2024-07-06",
     "per_day": [37, 48, 57, 52, 44, 40, 29], "note": "年假"},
    {"route": ["乌鲁木齐", "喀什"], "start": "2024-10-01",
     "per_day": [31, 43, 55, 65, 60, 47, 37, 26], "note": "国庆，走了南疆"},
    {"route": ["香港"], "start": "2024-12-20",
     "per_day": [25, 31, 37, 20], "note": "年末"},
]

# 一天里什么时段会掏手机：中午和下午最多，深夜几乎没有
_HOURS = [8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22]
_WEIGHTS = [2, 3, 3, 6, 7, 6, 5, 5, 6, 6, 5, 5, 4, 3, 2]


def _gradient(path: str, hue: float, rng: random.Random) -> None:
    """生成一张柔和的竖向渐变图，当作占位照片。"""
    import numpy as np
    from PIL import Image

    h, w = 180, 270
    c1 = colorsys.hsv_to_rgb(hue, 0.55, 0.42)
    c2 = colorsys.hsv_to_rgb((hue + 0.08) % 1.0, 0.65, 0.72)
    ramp = np.linspace(0, 1, h)[:, None, None]
    base = np.array(c1).reshape(1, 1, 3) * (1 - ramp) + np.array(c2).reshape(1, 1, 3) * ramp
    img = np.repeat(base, w, axis=1)
    noise = np.random.default_rng(rng.randint(0, 10**6)).uniform(-0.02, 0.02, size=(h, w, 1))
    img = np.clip(img + noise, 0, 1)
    Image.fromarray((img * 255).astype("uint8")).save(path, "JPEG", quality=80)


def _jitter(lat: float, lon: float, km: float, rng: random.Random) -> tuple[float, float]:
    import math
    dlat = rng.uniform(-1, 1) * km / 111.0
    dlon = rng.uniform(-1, 1) * km / (111.0 * max(0.2, math.cos(math.radians(lat))))
    return lat + dlat, lon + dlon


def _time_on(day: datetime, rng: random.Random) -> str:
    hour = rng.choices(_HOURS, weights=_WEIGHTS, k=1)[0]
    return day.replace(hour=hour, minute=rng.randint(0, 59),
                       second=rng.randint(0, 59)).strftime("%Y-%m-%d %H:%M:%S")


def _row(path: str, dt: str, lat: float | None, lon: float | None, source: str = "csv") -> dict:
    return {
        "path": path,
        "datetime": dt,
        "lat": "" if lat is None else f"{lat:.6f}",
        "lon": "" if lon is None else f"{lon:.6f}",
        "source": source,
    }


def generate_demo(root: str, seed: int = 7) -> dict:
    rng = random.Random(seed)
    photos_dir = os.path.join(root, "photos")
    os.makedirs(photos_dir, exist_ok=True)

    pool: dict[str, list[str]] = {}
    for i, city in enumerate(CITY_POS):
        pool[city] = []
        for k in range(6):
            p = os.path.join(photos_dir, f"{i:02d}_{k}.jpg")
            if not os.path.exists(p):
                _gradient(p, (i * 0.137 + k * 0.013) % 1.0, rng)
            pool[city].append(p)

    plans = []
    for t in TRIPS:
        plans.append((datetime.strptime(t["start"], "%Y-%m-%d"), t))
    busy = {(start + timedelta(days=d)).date()
            for start, t in plans for d in range(len(t["per_day"]))}

    rows: list[dict] = []

    # ---------- 日常 ----------
    for a, b, prob, (lo, hi) in HOME_PERIODS:
        day = datetime.strptime(a, "%Y-%m-%d")
        end = datetime.strptime(b, "%Y-%m-%d")
        while day <= end:
            if day.date() not in busy and rng.random() < prob:
                for _ in range(rng.randint(lo, hi)):
                    la, lo_ = _jitter(HOME[1], HOME[2], 5.0, rng)
                    rows.append(_row(rng.choice(pool["上海"]), _time_on(day, rng), la, lo_))
            day += timedelta(days=1)

    # ---------- 出行 ----------
    for start, t in plans:
        route = t["route"]
        pts = [CITY_POS[c] for c in route]
        for d, n in enumerate(t["per_day"]):
            day = start + timedelta(days=d)
            f = 0.0 if len(t["per_day"]) <= 1 else d / (len(t["per_day"]) - 1)
            seg = min(len(pts) - 1, int(f * (len(pts) - 1)))
            local = f * (len(pts) - 1) - seg
            if seg < len(pts) - 1:
                la0, lo0 = pts[seg]
                la1, lo1 = pts[seg + 1]
                lat = la0 + (la1 - la0) * local
                lon = lo0 + (lo1 - lo0) * local
            else:
                lat, lon = pts[seg]

            # 同一天里走一条有惯性的路线，而不是每张独立抖动
            wa, wo = lat, lon
            for _ in range(n):
                wa = max(lat - 0.06, min(lat + 0.06, wa + rng.gauss(0, 0.006)))
                wo = max(lon - 0.06, min(lon + 0.06, wo + rng.gauss(0, 0.006)))
                rows.append(_row(rng.choice(pool[route[seg]]), _time_on(day, rng), wa, wo))

    # ---------- 故意埋的脏数据 ----------
    # 1) 备份重复导入：那天整个文件夹被复制了两遍
    dup_src = [r for r in rows if r["datetime"].startswith("2024-02-13")][:6]
    for r in dup_src:
        rows.extend(dict(r) for _ in range(6))

    # 2) 山谷里的 GPS 漂移：大理那几天信号差，坐标乱跳到几千公里外
    valley = [r for r in rows if "2022-08-0" in r["datetime"] and r["lat"]][:5]
    for r in valley:
        dt = datetime.strptime(r["datetime"], "%Y-%m-%d %H:%M:%S") + timedelta(minutes=2)
        rows.append(_row(r["path"], dt.strftime("%Y-%m-%d %H:%M:%S"),
                         rng.uniform(-30, 55), rng.uniform(-100, 130)))

    # 3) 相机拍的那批没有定位：青岛第二天全部无 GPS
    for r in rows:
        if r["datetime"].startswith("2023-08-20"):
            r["lat"] = r["lon"] = ""

    # 4) 换手机后没有 EXIF 时间，只能从文件名里捞
    by_day: dict[str, list[dict]] = {}
    for r in rows:
        if r["datetime"].startswith("2024-"):
            by_day.setdefault(r["datetime"][:10], []).append(r)
    for d in sorted(by_day):
        if len(by_day[d]) >= 5:
            for r in by_day[d]:
                r["source"] = "filename"
            break

    rows.sort(key=lambda r: r["datetime"])
    csv_path = os.path.join(root, "photos.csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["path", "datetime", "lat", "lon", "source"])
        w.writeheader()
        w.writerows(rows)

    books_csv = os.path.join(root, "books.csv")
    _write_books(books_csv)
    return {"photos_csv": csv_path, "books_csv": books_csv,
            "photos": len(rows), "trip_count": len(TRIPS)}


# ---------------------------------------------------------------------------
# 阅读/观影记录：47 条，2024 年
# 有集中刷剧的周末、有加班到没时间看的月份、有没打分就标"看过"的条目
# (日期, 标题, 我的评分 或 None, 大众评分, 标签, 创作者)
# ---------------------------------------------------------------------------
_BOOKS = [
    ("2024-01-01", "繁花", 4, 4.1, "国产剧/年代", "王家卫"),
    ("2024-01-03", "年会不能停", 4, 4.1, "喜剧/职场", "董润年"),
    ("2024-01-06", "海边的曼彻斯特", 4.5, 4.4, "剧情/家庭", "肯尼斯·洛纳根"),
    ("2024-01-07", "海边的曼彻斯特", 4.5, 4.4, "剧情/家庭", "肯尼斯·洛纳根"),
    ("2024-01-12", "漫长的季节", 5, 4.9, "悬疑/国产剧", "辛爽"),
    ("2024-01-13", "漫长的季节", 5, 4.9, "悬疑/国产剧", "辛爽"),
    ("2024-01-14", "宇宙探索编辑部", 4.5, 4.2, "科幻/荒诞", "孔大山"),
    ("2024-01-20", "看不见的城市", 5, 4.6, "文学/外国文学", "卡尔维诺"),
    ("2024-01-27", "球状闪电", 4, 4.2, "科幻/中国文学", "刘慈欣"),
    ("2024-02-02", "好东西", 4.5, 4.4, "喜剧/都市", "邵艺辉"),
    ("2024-02-10", "热辣滚烫", 3, 4.0, "喜剧/励志", "贾玲"),
    ("2024-02-11", "飞驰人生2", 2.5, 3.9, "喜剧/赛车", "韩寒"),
    ("2024-02-12", "第二十条", 3, 4.1, "剧情/现实", "张艺谋"),
    ("2024-02-13", "周处除三害", 4, 4.0, "犯罪/动作", "黄精甫"),
    ("2024-02-14", "花束般的恋爱", 4, 4.2, "爱情/日本电影", "土井裕泰"),
    ("2024-03-02", "沙丘2", 4.5, 4.2, "科幻/史诗", "维伦纽瓦"),
    ("2024-03-09", "奥本海默", 4.5, 4.3, "传记/历史", "诺兰"),
    ("2024-03-16", "坠落的审判", 4.5, 4.3, "剧情/法庭", "茹斯汀·特里耶"),
    ("2024-03-23", "你想活出怎样的人生", 4, 4.1, "动画/宫崎骏", "宫崎骏"),
    ("2024-03-30", "蜘蛛侠：纵横宇宙", 4.5, 4.5, "动画/超级英雄", "索尼"),
    ("2024-04-06", "我的阿勒泰", 5, 4.7, "国产剧/散文", "滕丛丛"),
    ("2024-04-13", "我的阿勒泰", 5, 4.7, "国产剧/散文", "滕丛丛"),
    ("2024-04-20", "平原上的摩西", 4, 4.1, "剧集/悬疑", "张大磊"),
    ("2024-04-27", "大象席地而坐", 4.5, 4.4, "剧情/华语电影", "胡波"),
    ("2024-05-04", "春江水暖", 4, 4.1, "剧情/家庭", "顾晓刚"),
    ("2024-05-11", "地球最后的夜晚", 2.5, 3.6, "剧情/华语电影", "毕赣"),
    ("2024-05-18", "牯岭街少年杀人事件", 5, 4.7, "剧情/华语电影", "杨德昌"),
    ("2024-05-25", "一一", 5, 4.7, "剧情/华语电影", "杨德昌"),
    ("2024-06-01", "我的天才女友", 4.5, 4.6, "剧集/文学改编", "萨维里奥·科斯坦佐"),
    ("2024-06-08", "继承之战", 4.5, 4.5, "剧集/商战", "HBO"),
    ("2024-06-15", "熊家餐馆", None, 4.3, "剧集/生活", "FX"),
    ("2024-07-06", "驾驶我的车", 4.5, 4.2, "剧情/文学改编", "滨口龙介"),
    ("2024-07-13", "燃烧", 4.5, 4.3, "悬疑/文学改编", "李沧东"),
    ("2024-07-20", "寄生虫", 4.5, 4.6, "剧情/悬疑", "奉俊昊"),
    ("2024-07-27", "椒麻堂会", 4.5, 4.4, "剧情/华语电影", "邱炯炯"),
    ("2024-08-03", "心灵奇旅", 4, 4.4, "动画/治愈", "彼特·道格特"),
    ("2024-08-10", "深海", 3, 3.9, "动画/国产", "田晓鹏"),
    ("2024-08-17", "雄狮少年", 4, 4.2, "动画/国产", "孙海鹏"),
    ("2024-08-24", "铃芽之旅", 3, 4.0, "动画/日本电影", "新海诚"),
    ("2024-09-07", "繁城之下", 4, 4.0, "悬疑/古装", "王铮"),
    ("2024-09-14", "心迷宫", 4.5, 4.3, "悬疑/犯罪", "忻钰坤"),
    ("2024-09-21", "暴裂无声", 4, 4.2, "悬疑/犯罪", "忻钰坤"),
    ("2024-10-02", "隐入尘烟", 4, 4.3, "剧情/华语电影", "李睿珺"),
    ("2024-10-03", "路边野餐", 4, 4.1, "剧情/华语电影", "毕赣"),
    ("2024-10-04", "南方车站的聚会", 3.5, 3.8, "犯罪/黑色电影", "刁亦男"),
    ("2024-10-05", "白日焰火", 3.5, 3.9, "悬疑/犯罪", "刁亦男"),
    ("2024-11-09", "宇宙探索编辑部", 4.5, 4.2, "科幻/荒诞", "孔大山"),
    ("2024-11-16", "但是还有书籍", 5, 4.7, "纪录片/文化", "罗颖鸾"),
    ("2024-11-23", "我在故宫修文物", 4.5, 4.6, "纪录片/文化", "叶君"),
    ("2024-12-07", "十三邀", None, 4.3, "访谈/文化", "许知远"),
    ("2024-12-14", "人生一串", 4, 4.3, "纪录片/美食", "陈英杰"),
    ("2024-12-21", "风味人间", 4.5, 4.5, "纪录片/美食", "陈晓卿"),
]


def _write_books(path: str) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["标题", "年份", "我的评分", "大众评分", "标签", "作者", "日期"])
        w.writeheader()
        for date, title, mine, avg, tags, creator in _BOOKS:
            w.writerow({
                "标题": title,
                "年份": "",
                "我的评分": "" if mine is None else mine,
                "大众评分": avg,
                "标签": tags,
                "作者": creator,
                "日期": date,
            })
