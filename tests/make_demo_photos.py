"""生成一批**带真实 EXIF** 的 JPEG，用来演示/录屏浏览器版。

    python tests/make_demo_photos.py            # 默认写到 demo_photos/
    python tests/make_demo_photos.py --out D:/tmp/shots

和 demo/photos 的区别：那批是给静态报告用的占位图，没有 EXIF；
这批每张都写入了拍摄时间和 GPS，所以把它们拖进 web/app.html 能真的跑出报告。

刻意留了一段 5 周的空白（2023 年春天），这样日历上会有一块明显的空缺——
录屏时讲「最长的一次沉默」就有东西可指。
"""

from __future__ import annotations

import argparse
import os
import random
from datetime import datetime, timedelta

from PIL import Image
from PIL.TiffImagePlugin import IFDRational

HOME = ("上海", 31.2304, 121.4737)

TRIPS = [
    # (城市, 经纬度, 起始日, 天数, 每天张数)
    ("成都", (30.5728, 104.0668), "2022-08-06", 4, 20),
    ("大理", (25.6065, 100.2676), "2022-11-12", 3, 18),
    ("东京", (35.6762, 139.6503), "2023-05-01", 5, 28),
    ("哈尔滨", (45.8038, 126.5350), "2023-10-03", 4, 20),
    ("三亚", (18.2528, 109.5119), "2024-02-09", 4, 18),
    ("乌鲁木齐", (43.8256, 87.6168), "2024-10-01", 6, 26),
]

# 刻意留出的一段空白：报告会把它算成「最长的一次沉默，83 天」
GAP = (datetime(2022, 3, 11), datetime(2022, 6, 1))


def _gradient(w: int, h: int, hue: float, rng: random.Random) -> Image.Image:
    import colorsys

    import numpy as np

    c1 = colorsys.hsv_to_rgb(hue, 0.5, 0.45)
    c2 = colorsys.hsv_to_rgb((hue + 0.09) % 1.0, 0.62, 0.75)
    ramp = np.linspace(0, 1, h)[:, None, None]
    base = np.array(c1).reshape(1, 1, 3) * (1 - ramp) + np.array(c2).reshape(1, 1, 3) * ramp
    img = np.repeat(base, w, axis=1)
    noise = np.random.default_rng(rng.randint(0, 10**6)).uniform(-0.02, 0.02, size=(h, w, 1))
    return Image.fromarray((np.clip(img + noise, 0, 1) * 255).astype("uint8"))


def _dms(v: float) -> tuple:
    v = abs(v)
    d = int(v)
    m = int((v - d) * 60)
    s = round(((v - d) * 60 - m) * 60, 2)
    return (IFDRational(d), IFDRational(m), IFDRational(s))


def _write_jpeg(path: str, when: datetime, lat: float, lon: float,
                hue: float, rng: random.Random) -> None:
    im = _gradient(180, 135, hue, rng)
    ex = im.getexif()
    stamp = when.strftime("%Y:%m:%d %H:%M:%S")
    ex[0x8769] = {36867: stamp, 36868: stamp}
    ex[0x8825] = {
        1: "N" if lat >= 0 else "S", 2: _dms(lat),
        3: "E" if lon >= 0 else "W", 4: _dms(lon),
    }
    ex[0x010F] = "Rings"
    ex[0x0110] = "Demo Camera"
    im.save(path, "JPEG", quality=78, exif=ex)


def _in_gap(d: datetime) -> bool:
    return GAP[0] <= d <= GAP[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="demo_photos")
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    os.makedirs(args.out, exist_ok=True)

    n = 0
    hue = 0.0

    def emit(when: datetime, lat: float, lon: float, tag: str) -> None:
        nonlocal n, hue
        if _in_gap(when):
            return
        hue = (hue + 0.017) % 1.0
        name = f"{when:%Y%m%d_%H%M%S}_{tag}_{n:04d}.jpg"
        _write_jpeg(os.path.join(args.out, name), when, lat, lon, hue, rng)
        n += 1

    # 日常：家附近
    day = datetime(2022, 1, 1)
    while day < datetime(2024, 12, 1):
        if not _in_gap(day) and rng.random() < 0.42:
            for _ in range(rng.randint(1, 4)):
                la = HOME[1] + rng.gauss(0, 0.012)
                lo = HOME[2] + rng.gauss(0, 0.012)
                emit(day.replace(hour=rng.randint(9, 21), minute=rng.randint(0, 59)),
                     la, lo, "home")
        day += timedelta(days=1)

    # 钉住空白两端：保证算出来的沉默正好是 83 天，录屏时才敢报这个数
    for edge, hour in ((datetime(2022, 3, 10, 20, 15), 20), (datetime(2022, 6, 2, 8, 40), 8)):
        emit(edge, HOME[1] + 0.004, HOME[2] - 0.003, "edge")

    # 出行：逐日推进，走一条有惯性的路线
    for city, (clat, clon), start, days, per_day in TRIPS:
        base = datetime.strptime(start, "%Y-%m-%d")
        for d in range(days):
            lat, lon = clat, clon
            wa, wo = lat, lon
            for _ in range(per_day):
                wa = max(lat - 0.05, min(lat + 0.05, wa + rng.gauss(0, 0.006)))
                wo = max(lon - 0.05, min(lon + 0.05, wo + rng.gauss(0, 0.006)))
                emit(base + timedelta(days=d, hours=rng.randint(7, 22),
                                      minutes=rng.randint(0, 59)), wa, wo, city)

    total = len([f for f in os.listdir(args.out) if f.endswith(".jpg")])
    size = sum(os.path.getsize(os.path.join(args.out, f)) for f in os.listdir(args.out)
               if f.endswith(".jpg"))
    print(f"{total} 张 -> {os.path.abspath(args.out)}  ({size / 1024 / 1024:.1f} MB)")
    print(f"空白区间：{GAP[0]:%Y-%m-%d} ~ {GAP[1]:%Y-%m-%d}")
    print("把这个文件夹拖进 web/app.html 即可。")


if __name__ == "__main__":
    main()
