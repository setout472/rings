# 部署到 GitHub Pages

> ✅ **已部署：https://setout472.github.io/rings/**
> 仓库：https://github.com/setout472/rings （public，Pages 来源 `main` / 根目录）
>
> 下面是当时的步骤和验证清单，留作以后迁移或重建时参考。

全站是静态文件，没有构建步骤。做完大概 10 分钟。

## 先确认（已在本机验证过）

我用目录联接模拟了 `/仓库名/` 子路径，逐项检查过：

```
200  /ai-tansuo/index.html
200  /ai-tansuo/web/app.html
200  /ai-tansuo/web/report.html
200  /ai-tansuo/out/footprint.html
200  /ai-tansuo/out/reading.html
200  /ai-tansuo/web/sample.json
200  /ai-tansuo/web/js/exif.js
200  /ai-tansuo/out/preview_footprint.png
```

全站只用了**相对路径**，所以挂在 `/任意仓库名/` 下都不会碎。唯一的绝对地址是老地图瓦片
（Esri）和异步加载的 Leaflet，那两样本来就是外网资源。

## 步骤

```bash
git init
git add .
git commit -m "feat: 年轮 Rings —— 本地优先的照片年度报告"
git branch -M main
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

然后：

1. 仓库页 → **Settings** → 左侧 **Pages**
2. **Source** 选 `Deploy from a branch`
3. **Branch** 选 `main`，目录选 `/ (root)` → Save
4. 等 1–2 分钟，页面顶部会出现 `https://<用户名>.github.io/<仓库名>/`

## 必须提交的东西

别把它们写进 `.gitignore`，入口页会链接到它们：

| 路径 | 为什么必须提交 |
|---|---|
| `demo/` | `webbuild` 用它生成示例数据；也是「数据从哪来」的证据 |
| `out/` | 入口页的两份示例报告 + 预览图都在这里 |
| `web/sample.json` | `report.html?demo=1` 靠它 |
| `.nojekyll` | 空文件。防止 Jekyll 忽略以下划线开头的文件 |

## 部署后逐项验证

- [ ] `https://…/` 打开是入口页，截图能显示（不是裂图）
- [ ] 点「开始制作」能进 `web/app.html`
- [ ] 点「先看一份示例」能进 `report.html?demo=1`，并且**地图有瓦片、日历有格子**
- [ ] 入口页底部「示例报告」两张卡片能打开
- [ ] 手机上打开一次（重点看报告页的地图高度和日历横向滚动）
- [ ] 在 `app.html` 里真拖一个照片文件夹进去，能出报告

## 常见坑

**页面 404。** 九成是 Pages 的分支/目录选错了，或者刚推上去还没构建完（看 Actions 里的 `pages build and deployment`）。

**报告页空白。** 打开控制台看有没有 `failed to fetch sample.json`——说明 `sample.json` 没提交，或者被 `.gitignore` 挡了。

**地图是空白的一块。** Leaflet 是异步从 unpkg 加载的；如果对方网络访问不了 unpkg，地图会降级成 SVG 轨迹简图（这是设计好的兜底，不是 bug）。

**想放到已有仓库的子目录。** 不用改代码，整个目录搬过去即可，相对路径照样成立。

## 一个额外的宣传点

Pages 的域名是 `*.github.io`，在很多公司网络里能正常访问；如果你以后买了域名，
在 Pages 里填 Custom domain 就行，代码一行都不用改。
