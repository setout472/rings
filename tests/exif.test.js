/*
 * EXIF 解析器真值测试 —— node tests/exif.test.js
 *
 * 测试图片是 Python 脚本生成的（web_make_fixtures.py）：
 * 小端由 Pillow 写、大端手工拼字节、外加无 EXIF / 0,0 坐标 / 截断文件三类坏图。
 * 期望值都是独立算出来的，不是从解析器输出抄的。
 */
'use strict';

const fs = require('fs');
const path = require('path');

require('../web/js/exif.js');
const EXIF = globalThis.RingsEXIF;

const DIR = path.join(__dirname, '..', 'web', 'fixtures');

function load(name) {
  const b = fs.readFileSync(path.join(DIR, name));
  return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);
}

function iso(d) {
  if (!d) return null;
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

const cases = [
  {
    file: 'le_gps.jpg',
    why: 'Pillow 写的小端 JPEG：Exif 子 IFD 时间 + GPS IFD',
    want: { lat: 30 + 34 / 60, lon: 104 + 3 / 60, date: '2023-10-02T08:15:30' },
  },
  {
    file: 'be_gps.jpg',
    why: '手工拼的大端（MM）TIFF —— 佳能/尼康常见',
    want: { lat: 31 + 13 / 60, lon: 121 + 28 / 60, date: '2024-05-01T12:34:56' },
  },
  {
    file: 'be_no_date.jpg',
    why: '只有 GPS、时间为空：坐标要保留，时间必须是 null',
    want: { lat: 31 + 13 / 60, lon: 121 + 28 / 60, date: null },
  },
  {
    file: 'be_south_west.jpg',
    why: '南半球 + 西经：S/W 必须取负',
    want: { lat: -(33.86 + 51 / 60), lon: -(151.2 + 12 / 60), date: '2024-05-01T12:34:56' },
  },
  {
    file: 'gps_zero.jpg',
    why: '0,0 是设备没定位时的占位符，必须当成没有 GPS',
    want: { lat: null, lon: null, date: '2023-10-02T08:15:30' },
  },
  {
    file: 'no_exif.jpg',
    why: '没有任何 EXIF 段',
    want: { lat: null, lon: null, date: null },
  },
  {
    file: 'truncated.jpg',
    why: '文件被截断：不能抛异常',
    want: { lat: null, lon: null, date: null },
  },
];

let pass = 0;
let fail = 0;

for (const c of cases) {
  let got;
  try {
    got = EXIF.parse(load(c.file));
  } catch (e) {
    console.log(`FAIL  ${c.file} — 抛异常了: ${e.message}`);
    fail++;
    continue;
  }
  const problems = [];
  for (const k of ['lat', 'lon']) {
    const want = c.want[k];
    const val = got[k];
    if (want === null) {
      if (val !== null) problems.push(`${k}: 期望 null，得到 ${val}`);
    } else if (val === null || Math.abs(val - want) > 1e-3) {
      problems.push(`${k}: 期望 ${want.toFixed(5)}，得到 ${val === null ? 'null' : val.toFixed(5)}`);
    }
  }
  const dateIso = iso(got.date);
  if (dateIso !== c.want.date) problems.push(`date: 期望 ${c.want.date}，得到 ${dateIso}`);

  if (problems.length) {
    console.log(`FAIL  ${c.file}`);
    console.log(`      ${c.why}`);
    problems.forEach((p) => console.log(`      · ${p}`));
    fail++;
  } else {
    console.log(`ok    ${c.file.padEnd(20)} ${c.why}`);
    pass++;
  }
}

// 随机字节能被吃掉而不炸
try {
  const junk = new Uint8Array(256).map((_, i) => (i * 37) & 0xff).buffer;
  EXIF.parse(junk);
  console.log('ok    random-bytes        随机字节不抛异常');
  pass++;
} catch (e) {
  console.log('FAIL  random-bytes — 抛了异常');
  fail++;
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
