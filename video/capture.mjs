/*
 * capture.mjs —— 用 CDP 驱动真实浏览器，逐帧抓图。
 *
 * 关键设计：**画面里的运动由「帧序号」驱动，不由墙钟驱动。**
 * 抓一帧要 100~200ms，如果按真实时间滚动，成片里会快得离谱。
 * 所以每一帧只把滚动位置推进 1/N，抓多慢都不影响成片速度。
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const BASE = 'http://127.0.0.1:8931';

const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, cur, i, arr) => {
    if (cur.startsWith('--')) acc.push([cur.slice(2), arr[i + 1]]);
    return acc;
  }, [])
);

const shotsPath = args.shots;
const outDir = args.out;
const FPS = Number(args.fps || 8);
const W = Number(args.width || 1440);
const H = Number(args.height || 900);

const shots = JSON.parse(fs.readFileSync(shotsPath, 'utf8'));
fs.mkdirSync(outDir, { recursive: true });

const PROFILE = path.resolve(path.dirname(outDir), '.chrome');

// 每次重开都从干净的 profile 开始，避免 SingletonLock 让新实例直接退出
fs.rmSync(PROFILE, { recursive: true, force: true });

function freePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const p = srv.address().port;
      srv.close(() => resolve(p));
    });
  });
}

/* ------------------------- CDP 最小客户端 ------------------------- */

let ws;
let seq = 0;
const pending = new Map();

function send(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++seq;
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });
}

async function evaluate(expression) {
  const r = await send('Runtime.evaluate', {
    expression: `(function(){${expression}})()`,
    returnByValue: true,
    awaitPromise: true,
  });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.text + ' :: ' + expression);
  return r.result && r.result.value;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitFor(expression, timeoutMs = 15000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try {
      if (await evaluate(`return !!(${expression})`)) return true;
    } catch (e) { /* 页面还在跳转 */ }
    await sleep(120);
  }
  throw new Error('waitFor 超时: ' + expression);
}

async function shot(file) {
  const r = await send('Page.captureScreenshot', { format: 'jpeg', quality: 82 });
  fs.writeFileSync(file, Buffer.from(r.data, 'base64'));
}

/* ------------------------- 启动浏览器 ------------------------- */

let chrome = null;

async function launch() {
  const port = await freePort();
  chrome = spawn(CHROME, [
    '--headless=new',
    '--no-sandbox',
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check',
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${PROFILE}`,
    `--window-size=${W},${H}`,
    'about:blank',
  ], { stdio: ['ignore', 'ignore', process.env.RINGS_DEBUG ? 'inherit' : 'ignore'] });

  chrome.on('exit', (code) => {
    if (process.env.RINGS_DEBUG) console.error(`  chrome 退出，code=${code}`);
  });
  return port;
}

async function connect() {
  const port = await launch();

  let lastErr = '';
  for (let i = 0; i < 80; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      const page = list.find((t) => t.type === 'page');
      if (page) {
        ws = new WebSocket(page.webSocketDebuggerUrl);
        await new Promise((res, rej) => {
          ws.onopen = res;
          ws.onerror = rej;
        });
        ws.onmessage = (e) => {
          const msg = JSON.parse(e.data);
          if (msg.id && pending.has(msg.id)) {
            const { resolve, reject } = pending.get(msg.id);
            pending.delete(msg.id);
            if (msg.error) reject(new Error(msg.error.message));
            else resolve(msg.result);
          }
        };
        console.log(`  CDP 已连接（端口 ${port}）`);
        return;
      }
      lastErr = '没有 page 目标';
    } catch (e) { lastErr = e.message; }
    await sleep(250);
  }
  throw new Error('连不上 Chrome（' + lastErr + '）');
}

/* ------------------------- 页面准备 ------------------------- */

// 一个假光标：没有它，点击在视频里显得像变魔术
const CURSOR = `
(function(){
  if (window.__cur) return;
  var d = document.createElement('div');
  d.id = '__cur';
  d.style.cssText = 'position:fixed;left:0;top:0;width:16px;height:16px;margin:-8px 0 0 -8px;' +
    'border-radius:50%;background:rgba(94,234,212,.95);box-shadow:0 0 0 7px rgba(94,234,212,.16),' +
    '0 2px 10px rgba(0,0,0,.5);z-index:2147483647;pointer-events:none;' +
    'transition:transform .45s cubic-bezier(.2,.7,.3,1);transform:translate(-100px,-100px)';
  document.documentElement.appendChild(d);
  window.__cur = d;
})();
`;

async function moveCursorTo(selector) {
  const pos = await evaluate(`
    var el = document.querySelector(${JSON.stringify(selector)});
    if (!el) return null;
    var r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2, ok: r.top > 20 && r.bottom < window.innerHeight - 20 };
  `);
  if (!pos) return;
  await evaluate(`
    var d = document.getElementById('__cur');
    if (d) d.style.transform = 'translate(${pos.x}px,${pos.y}px)';
  `);
  await sleep(450);
}

const CLEAN_CSS = `
  (function(){
    var s = document.getElementById('__clean');
    if (!s) { s = document.createElement('style'); s.id = '__clean'; }
    s.textContent =
      'html{scrollbar-width:none!important}' +
      '::-webkit-scrollbar{width:0!important;height:0!important;display:none!important}' +
      '*{scroll-behavior:auto!important;transition:none!important;animation:none!important}';
    (document.head || document.documentElement).appendChild(s);
  })();
`;

async function prepare(prep) {
  const [kind, mod] = prep.split('#');

  if (kind === 'landing') {
    await send('Page.navigate', { url: `${BASE}/index.html` });
    await waitFor('document.querySelector(".hero h1")');
  } else if (kind === 'app') {
    await send('Page.navigate', { url: `${BASE}/web/app.html` });
    await waitFor('document.querySelector(".drop")');
  } else if (kind === 'report') {
    const year = mod ? parseInt(mod, 10) : 0;
    await send('Page.navigate', { url: `${BASE}/web/report.html?demo=1` });
    await waitFor('document.querySelector(".statgrid") && document.querySelector(".statgrid").children.length > 0');
    // 地图库是异步加载的，它加载完会重绘一次、把视图重置回全图。
    // 不等它就先点行程，缩放会被随后的重绘吃掉。
    try {
      await waitFor('window.L && document.querySelector("#map .leaflet-container")', 12000);
    } catch (e) { /* 没网就走 SVG 简图，继续 */ }
    await evaluate(CURSOR);
    if (year > 0) {      await moveCursorTo(`#years button[data-i="${year}"]`);
      await evaluate(`document.querySelector('#years button[data-i="${year}"]').click();`);
      await sleep(700);
    }
    if (prep.includes('click_trip')) {
      // 按标题文字找目标行程，别赌列表顺序——旁白点了新疆，画面就得是新疆
      const extra = prep.split('+')[1] || '';
      const target = extra.includes(':') ? extra.split(':')[1] : '喀什';
      const idx = await evaluate(`
        var cards = Array.prototype.slice.call(document.querySelectorAll('.trip'));
        for (var i = 0; i < cards.length; i++) {
          if ((cards[i].textContent || '').indexOf(${JSON.stringify(target)}) >= 0) return i;
        }
        return -1;
      `);
      if (idx >= 0) {
        await evaluate(`
          var c = document.querySelectorAll('.trip')[${idx}];
          window.scrollTo(0, c.getBoundingClientRect().top + window.scrollY - 220);
        `);
        await sleep(300);
        await evaluate(`
          var c = document.querySelectorAll('.trip')[${idx}];
          var r = c.getBoundingClientRect();
          var d = document.getElementById('__cur');
          if (d) d.style.transform = 'translate(' + (r.width * 0.5) + 'px,' + (r.top + 40) + 'px)';
        `);
        await sleep(500);
        await evaluate(`document.querySelectorAll('.trip')[${idx}].click();`);
        await sleep(1500);          // 等地图缩放动画结束
        if (process.env.RINGS_DEBUG) {
          const url = await evaluate(`
            var t = document.querySelector('.leaflet-tile');
            return t ? t.src : 'none';
          `);
          console.log('    tile:', url);
        }
      }
    }
  }

  // 导航之后统一收口：藏滚动条、关动效、装上假光标
  await evaluate(CLEAN_CSS);
  await evaluate(CURSOR);
  await sleep(300);
}

/* ------------------------- 主流程 ------------------------- */

async function main() {
  await connect();
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', {
    width: W, height: H, deviceScaleFactor: 1, mobile: false,
  });

  // 录屏要干净：藏滚动条、关掉一切过渡动画（否则帧与帧之间会抖）
  await send('Page.addScriptToEvaluateOnNewDocument', {
    source: `
      (function(){
        var s = document.createElement('style');
        s.textContent =
          'html{scrollbar-width:none!important}' +
          '::-webkit-scrollbar{width:0!important;height:0!important;display:none!important}' +
          '*{scroll-behavior:auto!important;transition:none!important;animation:none!important}';
        (document.head || document.documentElement).appendChild(s);
      })();
    `,
  });

  for (const s of shots) {
    const n = Math.max(1, Math.round(s.hold * FPS));
    process.stdout.write(`  ${s.id.padEnd(14)} ${n} 帧 … `);

    await prepare(s.prep);

    if (s.anchor) {
      await evaluate(`
        var el = document.querySelector(${JSON.stringify(s.anchor)});
        if (el) el.scrollIntoView({block:'center', behavior:'instant'});
      `);
      await sleep(250);
    }

    const info = await evaluate(`
      return {
        y: window.scrollY,
        max: document.documentElement.scrollHeight - window.innerHeight
      };
    `);
    const startY = info.y;
    const delta = Math.max(-info.max - startY, Math.min(info.max - startY, s.scroll || 0));

    // 点完就把光标挪到角落：固定定位的假光标滚动后会停在文字上，像一块污渍
    await evaluate(`
      var d = document.getElementById('__cur');
      if (d) d.style.transform = 'translate(${W - 90}px,${H - 60}px)';
    `);
    await sleep(120);

    if (Math.abs(delta) < 1) {
      // 静止镜头：抓一帧复制 N 份，省时间
      const first = path.join(outDir, `${s.id}_0000.jpg`);
      await shot(first);
      for (let i = 1; i < n; i++) {
        fs.copyFileSync(first, path.join(outDir, `${s.id}_${String(i).padStart(4, '0')}.jpg`));
      }
    } else {
      for (let i = 0; i < n; i++) {
        const y = startY + (delta * i) / (n - 1 || 1);
        await evaluate(`window.scrollTo(0, ${y.toFixed(2)});`);
        await shot(path.join(outDir, `${s.id}_${String(i).padStart(4, '0')}.jpg`));
      }
    }
    console.log('ok');
  }

  chrome.kill();
}

main().catch((e) => {
  console.error('\n抓帧失败：', e.message);
  try { chrome.kill(); } catch (_) {}
  process.exit(1);
});
