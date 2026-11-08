"""共享视觉层：两个报告共用的设计变量、排版与卡片组件。

设计原则（写下来，是为了之后能解释为什么这么做）：
  1. 深色背景 + 单一强调色：数据本身很花，界面必须安静
  2. 数字用等宽数字（tabular-nums）+ 超大字号：让人一眼看到"量"
  3. 卡片间距 > 卡片内边距，留白优先于装饰
  4. 只有一个滚动方向，不做横向滚动陷阱
  5. 所有动画都尊重 prefers-reduced-motion
"""

BASE_CSS = r"""
:root{
  --bg:#0a0b0d;
  --panel:#12151a;
  --panel-2:#171b21;
  --line:#232830;
  --ink:#e9edf2;
  --ink-2:#b7c0cd;
  --muted:#7e8794;
  --accent:#5eead4;
  --accent-soft:rgba(94,234,212,.12);
  --warn:#fbbf24;
  --radius:18px;
  --maxw:1080px;
  --font: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
          "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans SC", sans-serif;
  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0; background:var(--bg); color:var(--ink);
  font-family:var(--font); font-size:16px; line-height:1.65;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:var(--maxw); margin:0 auto; padding:0 24px}
.kicker{
  font-family:var(--mono); font-size:12px; letter-spacing:.22em;
  text-transform:uppercase; color:var(--accent);
}
.num{font-variant-numeric:tabular-nums; font-weight:800; letter-spacing:-.035em; line-height:1}
.muted{color:var(--muted)}
.divider{height:1px; background:var(--line); border:0; margin:0}

.reveal{opacity:0; transform:translateY(18px);
  transition:opacity .7s cubic-bezier(.2,.7,.3,1), transform .7s cubic-bezier(.2,.7,.3,1)}
.reveal.in{opacity:1; transform:none}

@media (prefers-reduced-motion: reduce){
  .reveal{opacity:1; transform:none; transition:none}
  *{animation-duration:.001ms !important; transition-duration:.001ms !important}
}
"""
