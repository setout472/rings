"""生成「阅读/观影 Wrapped」：竖向滚动叙事，单文件 HTML。

这个报告的卖点不是图表，是**节奏**：
一整屏只讲一件事，滚一下换一个画面，让人愿意从头看到尾。
这是纯产品设计能力，代码量反而比足迹地图小。
"""

from __future__ import annotations

import html
import json
from datetime import datetime

from .theme import BASE_CSS

CSS = r"""
:root{
  --bg:#0b0910; --panel:#141019; --panel-2:#1a1522; --line:#2a2233;
  --ink:#f2ecf7; --ink-2:#c6b9d4; --muted:#8c7f9b;
  --accent:#f0abfc; --accent-soft:rgba(240,171,252,.12);
}
.progress{position:fixed; top:0; left:0; height:2px; z-index:50; width:100%;
  background:rgba(255,255,255,.06)}
.progress i{display:block; height:100%; width:0;
  background:linear-gradient(90deg,#a78bfa,#f0abfc); transition:width .1s linear}

.ch{min-height:100vh; min-height:100svh; display:flex; align-items:center;
  padding:96px 24px; position:relative}
.ch .inner{max-width:860px; margin:0 auto; width:100%}
.ch .k{font-family:var(--mono); font-size:12px; letter-spacing:.22em;
  text-transform:uppercase; color:var(--accent); opacity:.85; margin-bottom:28px}
.ch h2{font-size:clamp(28px,4.6vw,52px); line-height:1.2; margin:0 0 18px;
  letter-spacing:-.035em; font-weight:800}
.ch p.lede{font-size:clamp(16px,1.9vw,20px); color:var(--ink-2); margin:0; max-width:56ch}
.ch .tiny{font-size:14px; color:var(--muted); margin-top:26px}

.giant{font-size:clamp(72px,17vw,190px); font-weight:800; letter-spacing:-.055em;
  line-height:.92; margin:0; font-variant-numeric:tabular-nums}
.giant .unit{font-size:.2em; font-weight:600; color:var(--muted);
  letter-spacing:0; margin-left:.15em; display:inline-block; transform:translateY(-.55em)}

.hero{text-align:left; background:
  radial-gradient(90% 60% at 12% 8%, rgba(167,139,250,.16), transparent 62%),
  radial-gradient(70% 50% at 88% 92%, rgba(240,171,252,.12), transparent 60%)}
.hero .scroll{position:absolute; bottom:38px; left:50%; transform:translateX(-50%);
  font-size:12px; letter-spacing:.2em; color:var(--muted); font-family:var(--mono);
  animation:bob 2.4s ease-in-out infinite}
@keyframes bob{0%,100%{transform:translate(-50%,0)} 50%{transform:translate(-50%,7px)}}

.months{display:flex; align-items:flex-end; gap:6px; height:220px; margin:38px 0 10px}
.months .m{flex:1; display:flex; flex-direction:column; justify-content:flex-end;
  align-items:center; gap:8px; height:100%}
.months .b{width:100%; border-radius:5px 5px 2px 2px; background:#33293f; min-height:3px;
  transition:background .4s}
.months .m.on .b{background:linear-gradient(180deg,#f0abfc,#a78bfa)}
.months .lb{font-size:11px; color:var(--muted); font-family:var(--mono)}
.months .m.on .lb{color:var(--accent)}

.hist{display:flex; align-items:flex-end; gap:5px; height:150px; margin:34px 0 12px}
.hist .h{flex:1; background:#33293f; border-radius:3px; position:relative; min-height:2px}
.hist .h.on{background:linear-gradient(180deg,#f0abfc,#a78bfa)}
.hist-axis{display:flex; justify-content:space-between; font-size:11px;
  color:var(--muted); font-family:var(--mono)}

.tagbars{display:flex; flex-direction:column; gap:13px; margin-top:34px}
.tag-row{display:grid; grid-template-columns:120px 1fr 44px; gap:14px; align-items:center}
.tag-row .nm{font-size:15px; color:var(--ink-2); overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
.tag-row .tr{height:6px; background:#241d2f; border-radius:99px; overflow:hidden}
.tag-row .tf{height:100%; border-radius:99px; background:linear-gradient(90deg,#a78bfa,#f0abfc)}
.tag-row .nn{text-align:right; font-size:13px; color:var(--muted); font-variant-numeric:tabular-nums}

.duo{display:grid; grid-template-columns:1fr 1fr; gap:18px; margin-top:34px}
.card{background:var(--panel); border:1px solid var(--line); border-radius:20px; padding:26px 24px}
.card .tag{font-size:11px; letter-spacing:.18em; font-family:var(--mono);
  color:var(--accent); text-transform:uppercase; margin-bottom:14px}
.card .name{font-size:clamp(20px,2.6vw,28px); font-weight:800; letter-spacing:-.02em; line-height:1.25}
.card .sub{margin-top:10px; font-size:14px; color:var(--muted)}
.card .stars{margin-top:14px; color:var(--accent); letter-spacing:2px; font-size:15px}

.tri{display:grid; grid-template-columns:repeat(3,1fr); gap:18px; margin-top:36px}
.tri .cell{background:var(--panel-2); border:1px solid var(--line); border-radius:18px; padding:22px}
.tri .v{font-size:clamp(30px,4.4vw,46px); font-weight:800; letter-spacing:-.04em;
  font-variant-numeric:tabular-nums}
.tri .v small{font-size:14px; color:var(--muted); font-weight:600; margin-left:4px; letter-spacing:0}
.tri .k{font-size:13px; color:var(--muted); margin-top:8px}

.outro{text-align:center; background:
  radial-gradient(80% 60% at 50% 40%, rgba(240,171,252,.13), transparent 65%)}
.outro h2{font-size:clamp(34px,6vw,64px)}
.outro .sig{margin-top:40px; font-size:13px; color:var(--muted); font-family:var(--mono); letter-spacing:.08em}

@media (max-width:760px){
  .duo,.tri{grid-template-columns:1fr}
  .months{height:170px}
  .ch{padding:72px 20px}
}
"""


def _stars(v: float | None) -> str:
    if v is None:
        return ""
    full = int(round(v))
    return "★" * full + "☆" * max(0, 5 - full)


def _fmt(v, nd=0) -> str:
    if v is None:
        return "—"
    return f"{v:,.{nd}f}"


def _section(kicker: str, inner: str, cls: str = "") -> str:
    return (f'<section class="ch {cls}"><div class="inner reveal">'
            f'<div class="k">{kicker}</div>{inner}</div></section>')


def render_wrapped(payload: dict, out_path: str, label: str | None = None) -> str:
    p = payload
    e = html.escape
    label = label or p.get("label") or ""
    if not label:
        ys = p["years"]
        label = str(ys[0]) if len(ys) == 1 else f"{ys[0]}–{ys[-1]}"

    months = p["months"]
    peak_month = months.index(max(months)) + 1 if any(months) else None
    parts: list[str] = []

    # 01 封面
    parts.append(_section(
        f"{e(label)} · 年度阅读/观影报告",
        f'<p class="giant">{_fmt(p["n"])}<span class="unit">部</span></p>'
        f'<h2 style="margin-top:26px">你在 {e(label)} 里，<br>做出了 {_fmt(p["n"])} 次「看别人人生」的选择。</h2>'
        f'<p class="lede">从 {e(p["first"])} 到 {e(p["last"])}，下面是这些数字背后的你。</p>',
        "hero"))

    # 02 节奏
    mx = max(months) or 1
    bars = "".join(
        f'<div class="m {"on" if (peak_month and i + 1 == peak_month) else ""}">'
        f'<div class="b" style="height:{max(2, round(v / mx * 100))}%"></div>'
        f'<div class="lb">{i + 1}</div></div>'
        for i, v in enumerate(months))
    peak_txt = (f'最集中的是 <b>{peak_month} 月</b>，一个月就有 {max(months)} 部。'
                if peak_month else "这一年的分布很均匀。")
    parts.append(_section(
        "01 / 节奏",
        f'<h2>你的「看片季」在 {peak_month or "—"} 月。</h2>'
        f'<div class="months">{bars}</div>'
        f'<p class="lede">{peak_txt}</p>'))

    # 03 评分
    hist = p["hist"]
    hmax = max(hist) or 1
    hbars = "".join(
        f'<div class="h {"on" if (p["avg"] and abs((i + 1) / 2 - p["avg"]) < 0.25) else ""}"'
        f' style="height:{max(2, round(v / hmax * 100))}%"></div>' for i, v in enumerate(hist))
    delta = p["delta"]
    if delta is None:
        delta_txt = "这份数据里没有大众评分，所以不知道你和大家的口味差多少。"
    elif delta > 0.10:
        delta_txt = f"你比大众平均<b>宽容 {delta:.2f} 分</b>——你更愿意给人机会。"
    elif delta < -0.10:
        delta_txt = f"你比大众平均<b>苛刻 {abs(delta):.2f} 分</b>——你有自己的标准。"
    else:
        delta_txt = "你和大众的口味几乎完全一致，这不常见。"
    avg_html = (f'<p class="giant">{p["avg"]:.2f}<span class="unit">/ 5 星</span></p>'
                if p["avg"] is not None else '<p class="giant">—</p>')
    parts.append(_section(
        "02 / 品味标准",
        f'{avg_html}<h2 style="margin-top:24px">你给出的每一次评分，<br>加起来就是这个数。</h2>'
        f'<div class="hist">{hbars}</div>'
        f'<div class="hist-axis"><span>0.5★</span><span>3★</span><span>5★</span></div>'
        f'<p class="lede" style="margin-top:30px">{delta_txt}</p>'))

    # 04 口味
    tags = p["tags"]
    if tags:
        tmax = tags[0]["n"] or 1
        rows = "".join(
            f'<div class="tag-row"><span class="nm">{e(t["name"])}</span>'
            f'<div class="tr"><div class="tf" style="width:{max(3, round(t["n"] / tmax * 100))}%"></div></div>'
            f'<span class="nn">{t["n"]}</span></div>' for t in tags[:8])
        parts.append(_section(
            "03 / 口味",
            f'<h2>你反复回到的，是这些。</h2>'
            f'<p class="lede">排名第一的是「{e(tags[0]["name"])}」，出现了 {tags[0]["n"]} 次。</p>'
            f'<div class="tagbars">{rows}</div>'))

    # 05 两个极端
    best, worst = p["best"], p["worst"]
    if best or worst:
        def card(tag: str, r: dict | None) -> str:
            if not r:
                return f'<div class="card"><div class="tag">{tag}</div><div class="name">没有数据</div></div>'
            sub = []
            if r.get("creator"):
                sub.append(e(r["creator"]))
            if r.get("year"):
                sub.append(str(r["year"]))
            if r.get("avg_rating"):
                sub.append(f'大众 {r["avg_rating"]:.1f} 星')
            return (f'<div class="card"><div class="tag">{tag}</div>'
                    f'<div class="name">{e(r["title"])}</div>'
                    f'<div class="sub">{" · ".join(sub) or "—"}</div>'
                    f'<div class="stars">{_stars(r.get("my_rating"))}</div></div>')
        parts.append(_section(
            "04 / 两个极端",
            '<h2>最爱的那一部，<br>和最后悔的那一部。</h2>'
            f'<div class="duo">{card("给得最高", best)}{card("给得最低", worst)}</div>'))

    # 06 习惯
    creator_note = ""
    if p["creators"]:
        c = p["creators"][0]
        creator_note = f'<div class="cell"><div class="v">{c["n"]}<small>部</small></div>' \
                       f'<div class="k">反复看了 {e(c["name"])} 的作品</div></div>'
    rated_note = ("你标记了 " + str(p["n"]) + " 部，每一部都给了分。"
                  if p["rated_count"] == p["n"]
                  else "你标记了 " + str(p["n"]) + " 部，其中 " + str(p["rated_count"]) + " 部给了分。")
    parts.append(_section(
        "05 / 习惯",
        '<h2>数字之外，还有些细节。</h2>'
        f'<div class="tri">'
        f'<div class="cell"><div class="v">{p["longest_streak"]}<small>天</small></div>'
        f'<div class="k">最长连续观看</div></div>'
        f'<div class="cell"><div class="v">{p["longest_gap"]}<small>天</small></div>'
        f'<div class="k">最长的一次空窗</div></div>'
        f'{creator_note}</div>'
        f'<p class="lede" style="margin-top:34px">记录本身就是一种自我观察。{rated_note}</p>'))

    # 07 结尾
    parts.append(_section(
        "·",
        '<h2>明年的这个时候，<br>再看一遍。</h2>'
        f'<p class="lede" style="margin:0 auto">数据会积累，口味会变，而你会有证据。</p>'
        f'<div class="sig">{e(label)} · {p["n"]} 部 · 由 wrapped 生成</div>',
        "outro"))

    # 给每一屏一个锚点：既是深链接（#ch3 可以直接分享到第三屏），也方便分段截图
    body = "".join(
        part.replace('<section class="ch', f'<section id="ch{i + 1}" class="ch', 1)
        for i, part in enumerate(parts))
    js = r"""
(function(){
  var bar = document.querySelector('.progress i');
  function onScroll(){
    var h = document.documentElement.scrollHeight - window.innerHeight;
    bar.style.width = (h > 0 ? (window.scrollY / h * 100) : 0) + '%';
  }
  window.addEventListener('scroll', onScroll, {passive:true}); onScroll();

  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if(reduce){ document.querySelectorAll('.reveal').forEach(function(n){ n.classList.add('in'); }); return; }
  var io = new IntersectionObserver(function(es){
    es.forEach(function(e){ if(e.isIntersecting){ e.target.classList.add('in'); io.unobserve(e.target); } });
  }, {threshold:.15});
  document.querySelectorAll('.reveal').forEach(function(n){ io.observe(n); });
})();
"""

    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(label)} · 年度报告</title>
<style>{BASE_CSS}{CSS}</style>
</head>
<body>
<div class="progress"><i></i></div>
<main>{body}</main>
<script>{js}</script>
</body>
</html>"""

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(page)
    return out_path
