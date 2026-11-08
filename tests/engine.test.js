/*
 * 引擎对拍 —— node tests/engine.test.js
 *
 * 同一份 demo/photos.csv，Python 跑一遍（tests/gen_expected.py），
 * JS 跑一遍（web/js/engine.js），逐项比。
 *
 * 移植代码最容易出的错不是语法，是「有一处细节没对齐」：
 * 四舍五入、排序稳定性、相等时谁赢。这些只有对拍能抓出来。
 */
'use strict';

const fs = require('fs');
const path = require('path');

require('../web/js/cities.js');
require('../web/js/engine.js');
const ENGINE = globalThis.RingsEngine;

const ROOT = path.join(__dirname, '..');
const CSV = path.join(ROOT, 'demo', 'photos.csv');
const EXPECTED = path.join(__dirname, 'expected_demo.json');

if (!fs.existsSync(EXPECTED)) {
  console.error('缺少 tests/expected_demo.json，先跑：python tests/gen_expected.py');
  process.exit(2);
}

function parseCsvLine(line) {
  const out = [];
  let cur = '';
  let q = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (q) {
      if (c === '"' && line[i + 1] === '"') { cur += '"'; i++; }
      else if (c === '"') q = false;
      else cur += c;
    } else if (c === '"') q = true;
    else if (c === ',') { out.push(cur); cur = ''; }
    else cur += c;
  }
  out.push(cur);
  return out;
}

function parseDate(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?/.exec(s.trim());
  if (!m) return null;
  return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0));
}

const lines = fs.readFileSync(CSV, 'utf8').replace(/^\uFEFF/, '').trim().split(/\r?\n/);
const head = parseCsvLine(lines.shift()).map((h) => h.trim().toLowerCase());
const idx = {
  dt: head.indexOf('datetime'),
  lat: head.indexOf('lat'),
  lon: head.indexOf('lon'),
  src: head.indexOf('source'),
};

const photos = lines.map((line) => {
  const f = parseCsvLine(line);
  const dt = parseDate(f[idx.dt] || '');
  if (!dt) return null;
  const lat = f[idx.lat] ? parseFloat(f[idx.lat]) : NaN;
  const lon = f[idx.lon] ? parseFloat(f[idx.lon]) : NaN;
  const hasGps = isFinite(lat) && isFinite(lon) && !(Math.abs(lat) < 0.01 && Math.abs(lon) < 0.01);
  return {
    dt,
    lat: hasGps ? lat : null,
    lon: hasGps ? lon : null,
    src: (idx.src >= 0 ? f[idx.src] : '') || 'csv',
  };
}).filter(Boolean);

const expected = JSON.parse(fs.readFileSync(EXPECTED, 'utf8'));
const got = ENGINE.run(photos);

const problems = [];
function eq(label, a, b, tol) {
  if (tol) {
    if (Math.abs(a - b) > tol) problems.push(`${label}: 期望 ${b}，得到 ${a}`);
  } else if (a !== b) {
    problems.push(`${label}: 期望 ${JSON.stringify(b)}，得到 ${JSON.stringify(a)}`);
  }
}

// meta
for (const k of ['total', 'with_gps', 'drift_removed', 'duplicates_removed', 'timezone_corrected']) {
  eq(`meta.${k}`, got.meta[k], expected.meta[k]);
}

// 常住地
eq('home.city', got.payload.home.city, expected.home.city);
eq('home.lat', got.payload.home.lat, expected.home.lat, 0.001);
eq('home.lon', got.payload.home.lon, expected.home.lon, 0.001);

// 逐年
eq('years.length', got.payload.years.length, expected.years.length);
expected.years.forEach((want, i) => {
  const have = got.payload.years[i];
  if (!have) { problems.push(`years[${i}] 缺失`); return; }
  const tag = `years[${i}](${want.label})`;
  eq(`${tag}.photos`, have.stats.photos, want.photos);
  eq(`${tag}.trips`, have.stats.trips, want.trips);
  eq(`${tag}.cities`, have.stats.cities, want.cities);
  eq(`${tag}.active_days`, have.stats.active_days, want.active_days);
  eq(`${tag}.span_days`, have.stats.span_days, want.span_days);
  eq(`${tag}.quiet_days`, have.stats.quiet.days, want.quiet_days);
  eq(`${tag}.max_km`, have.stats.max_km, want.max_km, 1);

  eq(`${tag}.trip_list.length`, have.trips.length, want.trip_list.length);
  want.trip_list.forEach((wt, j) => {
    const ht = have.trips[j];
    if (!ht) { problems.push(`${tag}.trips[${j}] 缺失`); return; }
    const t2 = `${tag}.trips[${j}]`;
    eq(`${t2}.start`, ht.start, wt.start);
    eq(`${t2}.days`, ht.days, wt.days);
    eq(`${t2}.photos`, ht.photos, wt.photos);
    eq(`${t2}.title`, ht.title, wt.title);
    eq(`${t2}.max_km`, Math.round(ht.max_km), wt.max_km, 1);
  });
});

const total = 13 + expected.years.length * 7 +
  expected.years.reduce((s, y) => s + y.trip_list.length * 5, 0);

if (problems.length) {
  console.log(`FAIL  ${problems.length} 处不一致（共比对 ${total} 项）`);
  problems.slice(0, 25).forEach((p) => console.log('   ·', p));
  if (problems.length > 25) console.log(`   … 还有 ${problems.length - 25} 项`);
  process.exit(1);
}
console.log(`ok    JS 引擎与 Python 实现逐项一致（${total} 项）`);
console.log(`      照片 ${got.meta.total} · 出行 ${got.payload.years[0].stats.trips} · ` +
            `城市 ${got.payload.years[0].stats.cities} · 漂移剔除 ${got.meta.drift_removed} · ` +
            `重复合并 ${got.meta.duplicates_removed}`);
