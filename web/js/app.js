/*
 * app.js —— 把「一堆照片」变成「一份能看的报告」。
 *
 * 流程：拖入 → 逐个解析 EXIF → 交给引擎 → 补缩略图 → 存起来 → 跳到报告页。
 *
 * 全部在浏览器里完成。没有 fetch 到任何服务器，也不会有任何字节离开这台机器。
 */
(function () {
  'use strict';

  var MAX_FILES = 8000;
  var THUMB_BUDGET = 36;
  var THUMB_WIDTH = 240;
  var STORAGE_KEY = 'rings.payload';

  var $ = function (id) { return document.getElementById(id); };

  /* ---------------- 工具 ---------------- */

  function tick() { return new Promise(function (r) { setTimeout(r, 0); }); }

  function isImage(f) {
    if (!f) return false;
    if (f.type && /^image\//.test(f.type)) return true;
    return /\.(jpe?g|png|tiff?|webp|heic|heif)$/i.test(f.name || '');
  }

  // EXIF 时间丢了（微信导出、截图、部分相机），退化成从文件名里捞
  function fromFilename(name) {
    var m = /(20\d{2})[^0-9]?(0[1-9]|1[0-2])[^0-9]?(0[1-9]|[12]\d|3[01])[^0-9]?(\d{2})[^0-9]?(\d{2})[^0-9]?(\d{2})/.exec(name);
    if (!m) return null;
    var y = +m[1], mo = +m[2], d = +m[3], h = +m[4], mi = +m[5], s = +m[6];
    if (mo < 1 || mo > 12 || d < 1 || d > 31 || h > 23 || mi > 59 || s > 59) return null;
    return new Date(y, mo - 1, d, h, mi, s);
  }

  function scrub(obj) {
    if (Array.isArray(obj)) return obj.map(scrub);
    if (obj && typeof obj === 'object') {
      var out = {};
      Object.keys(obj).forEach(function (k) {
        if (k.charAt(0) === '_') return;      // 内部字段（File 句柄等）不能进序列化
        out[k] = scrub(obj[k]);
      });
      return out;
    }
    return obj;
  }

  function setProgress(p, text) {
    $('pBar').style.width = Math.max(0, Math.min(1, p)) * 100 + '%';
    if (text) $('pLog').textContent = text;
  }

  function fail(title, msg) {
    $('progress').hidden = true;
    $('stage').hidden = true;
    $('eTitle').textContent = title;
    $('eMsg').textContent = msg;
    $('error').hidden = false;
  }

  /* ---------------- 读文件 ---------------- */

  // 拖进来的是文件夹时，要自己递归 —— 浏览器只给 File 列表，不给目录结构
  function walkEntry(entry, out) {
    return new Promise(function (resolve) {
      if (!entry) return resolve();
      if (entry.isFile) {
        entry.file(function (f) { if (isImage(f)) out.push(f); resolve(); }, function () { resolve(); });
      } else if (entry.isDirectory) {
        var reader = entry.createReader();
        var readBatch = function () {
          reader.readEntries(function (batch) {
            if (!batch.length) return resolve();
            Promise.all(batch.map(function (e) { return walkEntry(e, out); })).then(readBatch);
          }, function () { resolve(); });
        };
        readBatch();
      } else {
        resolve();
      }
    });
  }

  function filesFromDataTransfer(dt) {
    var entries = [];
    if (dt.items && dt.items.length) {
      for (var i = 0; i < dt.items.length; i++) {
        var it = dt.items[i];
        var e = it.webkitGetAsEntry && it.webkitGetAsEntry();
        if (e) entries.push(e);
      }
    }
    if (!entries.length) return Promise.resolve(Array.prototype.slice.call(dt.files || []));
    var out = [];
    return Promise.all(entries.map(function (e) { return walkEntry(e, out); })).then(function () { return out; });
  }

  /* ---------------- 缩略图 ---------------- */

  function makeThumb(file) {
    return new Promise(function (resolve) {
      if (!window.createImageBitmap) return resolve(null);
      createImageBitmap(file).then(function (bmp) {
        var scale = Math.min(1, THUMB_WIDTH / bmp.width);
        var c = document.createElement('canvas');
        c.width = Math.max(1, Math.round(bmp.width * scale));
        c.height = Math.max(1, Math.round(bmp.height * scale));
        c.getContext('2d').drawImage(bmp, 0, 0, c.width, c.height);
        if (bmp.close) bmp.close();
        resolve(c.toDataURL('image/jpeg', 0.72));
      }).catch(function () { resolve(null); });
    });
  }

  // 轮流发图，而不是把预算全给小费最近几次旅行 —— 否则早年行程全是光秃秃的文字行
  async function attachThumbs(trips, budget) {
    var pools = trips.map(function (t) { return (t._photos || []).slice(); });
    trips.forEach(function (t) { t.thumbs = []; });

    var order = trips.map(function (_, i) { return i; })
      .sort(function (a, b) { return trips[a].start < trips[b].start ? 1 : -1; });

    var made = 0;
    var guard = 0;
    while (made < budget && guard++ < 60) {
      var progressed = false;
      for (var k = 0; k < order.length && made < budget; k++) {
        var i = order[k];
        var pool = pools[i];
        if (!pool.length) continue;
        progressed = true;
        var p = pool.shift();
        var url = await makeThumb(p.file);
        if (url) { trips[i].thumbs.push(url); made++; }
        if (made % 4 === 0) await tick();
      }
      if (!progressed) break;
    }
    return made;
  }

  /* ---------------- 主流程 ---------------- */

  async function build(fileList) {
    var files = Array.prototype.slice.call(fileList).filter(isImage);
    if (!files.length) {
      return fail('没有找到图片', '这个文件夹里没有可识别的图片文件。支持 JPEG、PNG、TIFF、WebP。');
    }
    var truncated = files.length > MAX_FILES;
    if (truncated) files = files.slice(0, MAX_FILES);

    $('stage').hidden = true;
    $('error').hidden = true;
    $('progress').hidden = false;
    $('pTitle').textContent = '正在读取 ' + files.length.toLocaleString() + ' 张照片…';
    setProgress(0.02, '准备中…');

    var photos = [];
    var srcCount = { exif: 0, filename: 0, mtime: 0 };

    for (var i = 0; i < files.length; i++) {
      var f = files[i];
      var ex = null;
      try {
        var buf = await f.arrayBuffer();
        ex = window.RingsEXIF ? window.RingsEXIF.parse(buf) : null;
      } catch (e) { ex = null; }

      var dt = ex && ex.date;
      var src = 'exif';
      if (!dt) { dt = fromFilename(f.name); src = 'filename'; }
      if (!dt) { dt = new Date(f.lastModified || Date.now()); src = 'mtime'; }

      photos.push({
        dt: dt,
        lat: ex ? ex.lat : null,
        lon: ex ? ex.lon : null,
        src: src,
        file: f,
      });
      srcCount[src]++;

      if (i % 40 === 0 || i === files.length - 1) {
        setProgress(0.02 + (i + 1) / files.length * 0.76,
          '已解析 ' + (i + 1).toLocaleString() + ' / ' + files.length.toLocaleString());
        await tick();
      }
    }

    $('pTitle').textContent = '正在识别行程…';
    setProgress(0.82, '清洗 · 聚类 · 统计');
    await tick();

    var result;
    try {
      result = window.RingsEngine.run(photos);
    } catch (e) {
      if (e && e.code === 'NO_GPS') {
        return fail('这些照片没有定位信息',
          '找到了 ' + photos.length.toLocaleString() + ' 张照片，但没有一张带 GPS 坐标。' +
          '常见原因：拍照时关了定位；或者这些照片是从微信、社交软件另存出来的——它们会把 EXIF 抹掉。');
      }
      return fail('解析出错了', '处理过程中出现异常：' + (e && e.message ? e.message : '未知错误'));
    }

    $('pTitle').textContent = '正在生成报告…';
    setProgress(0.9, '准备缩略图');
    await tick();

    var budget = THUMB_BUDGET;
    var made = await attachThumbs(result.payload.years[0].trips, budget);

    var payload = result.payload;
    payload.meta = Object.assign({}, result.meta, {
      thumbs: made,
      truncated: truncated,
      generated_at: new Date().toLocaleString('zh-CN', { hour12: false }).replace(/\//g, '-'),
      version: 'web',
    });

    var json = JSON.stringify(scrub(payload));

    // sessionStorage 大约 5MB 上限；超了就砍掉缩略图，别让整份报告存不进去
    if (json.length > 4.4 * 1024 * 1024) {
      payload.years.forEach(function (b) {
        b.trips.forEach(function (t) { t.thumbs = []; });
      });
      payload.meta.thumbs = 0;
      json = JSON.stringify(payload);
    }

    try { sessionStorage.setItem(STORAGE_KEY, json); } catch (e) { /* file:// 会禁掉 */ }
    try { window.name = 'rings:' + json; } catch (e) {}

    setProgress(1, '完成，正在打开报告…');
    location.href = 'report.html';
  }

  /* ---------------- 事件绑定 ---------------- */

  var drop = $('drop');

  ['dragenter', 'dragover'].forEach(function (ev) {
    document.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add('over'); });
  });
  ['dragleave', 'drop'].forEach(function (ev) {
    document.addEventListener(ev, function (e) {
      e.preventDefault();
      if (ev === 'dragleave' && e.target !== drop && !drop.contains(e.target)) return;
      drop.classList.remove('over');
    });
  });

  document.addEventListener('drop', function (e) {
    e.preventDefault();
    drop.classList.remove('over');
    filesFromDataTransfer(e.dataTransfer).then(function (files) {
      if (!files.length) return fail('没有拿到文件', '拖进来的是文件夹还是文件？可以试试「选择文件夹」。');
      build(files);
    });
  });

  $('pickDir').addEventListener('change', function (e) {
    if (e.target.files && e.target.files.length) build(e.target.files);
  });
  $('pickFiles').addEventListener('change', function (e) {
    if (e.target.files && e.target.files.length) build(e.target.files);
  });
  $('retry').addEventListener('click', function () { location.reload(); });

  // 供无头测试使用：?test=1 时把 fixtures 当作用户选的文件跑一遍
  if (/[?&]test=1/.test(location.search)) {
    document.title = 'TEST-MODE';
    var names = ['le_gps.jpg', 'be_gps.jpg', 'gps_zero.jpg', 'no_exif.jpg'];
    Promise.all(names.map(function (n) {
      return fetch('fixtures/' + n).then(function (r) { return r.blob(); })
        .then(function (b) { return new File([b], n, { type: 'image/jpeg' }); });
    })).then(function (files) {
      build(files);
    }).catch(function (e) {
      document.title = 'TEST-FETCH-FAILED';
    });
  }
})();
