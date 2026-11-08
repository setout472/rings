"""缩略图生成：把选中的照片压成 base64 内嵌进 HTML。

为什么内嵌而不是引用路径：
    - 报告变成**单个文件**，发微信 / 发邮件 / 丢 GitHub Pages 都能直接看
    - 不会因为移动了相册目录而碎图
代价是文件变大，所以每张压到 360px 宽、JPEG q72（约 15–25KB），总量做硬性上限。
"""

from __future__ import annotations

import base64
import io

MAX_WIDTH = 360
QUALITY = 72


def make_thumb(path: str, max_width: int = MAX_WIDTH, quality: int = QUALITY) -> str | None:
    """返回 data URI；失败返回 None（前端会用占位色块兜底）。"""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return None
    try:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            w, h = im.size
            if w > max_width:
                im = im.resize((max_width, max(1, int(h * max_width / w))), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=quality, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return None


def attach_thumbs(trips: list[dict], budget: int = 40, enabled: bool = True) -> int:
    """给行程挂缩略图，总量控制在 budget 张以内。返回实际生成张数。

    分配方式是**轮流发**而不是"先把最近的行程喂满"：
    否则预算会被最近几次旅行吃光，早年的行程全是光秃秃的文字行，
    滚动下来视觉上断层。
    """
    if not enabled:
        for t in trips:
            t.pop("_paths", None)
        return 0

    pools = {}
    for t in trips:
        pools[id(t)] = list(t.pop("_paths", []) or [])

    order = sorted(trips, key=lambda x: x["start"], reverse=True)
    for t in trips:
        t["thumbs"] = []

    made = 0
    while made < budget:
        progressed = False
        for t in order:
            if made >= budget:
                break
            pool = pools[id(t)]
            if not pool:
                continue
            data = make_thumb(pool.pop(0))
            progressed = True
            if data:
                t["thumbs"].append(data)
                made += 1
        if not progressed:
            break
    return made
