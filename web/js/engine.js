/*
 * engine.js —— 聚类与统计引擎，wrapped/trips.py + clean.py 的 JS 移植。
 *
 * 移植的不是「差不多」，是同一套常数和同一套判断顺序：
 * 这样可以用同一份数据跑两边，逐项对拍。行为不一致就是 bug。
 *
 * 输入：photos = [{ dt: Date(当地拍摄时间), lat: number|null, lon: number|null, src: string }]
 * 输出：和 Python 版完全同构的 payload，直接喂给报告页。
 */
(function (global) {
  'use strict';

  var CITIES = global.RingsCities || [];

  var AWAY_KM = 100;
  var GAP_HOURS = 48;
  var MIN_PHOTOS = 3;
  var MIN_MAX_KM = 150;

  var MAX_SPEED_KMH = 900;
  var MIN_DISTANCE_KM = 50;
  var NEIGHBOR_JUMP_KM = 3000;

  var UNKNOWN_CITY = '未知地区';
  var EARTH_R = 6371.0088;

  function pad2(n) { return (n < 10 ? '0' : '') + n; }
  function ymd(d) { return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()); }
  function startOfDay(d) { return new Date(d.getFullYear(), d.getMonth(), d.getDate()); }
  function addDays(d, n) { return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n); }
  function dayKey(d) { return ymd(d); }

  function haversine(lat1, lon1, lat2, lon2) {
    var p1 = lat1 * Math.PI / 180, p2 = lat2 * Math.PI / 180;
    var dphi = p2 - p1;
    var dlam = (lon2 - lon1) * Math.PI / 180;
    var a = Math.sin(dphi / 2) * Math.sin(dphi / 2) +
            Math.cos(p1) * Math.cos(p2) * Math.sin(dlam / 2) * Math.sin(dlam / 2);
    return 2 * EARTH_R * Math.asin(Math.min(1, Math.sqrt(a)));
  }

  function nearestCity(lat, lon, maxKm) {
    maxKm = maxKm || 150;
    var best = UNKNOWN_CITY, bestD = Infinity;
    for (var i = 0; i < CITIES.length; i++) {
      var d = haversine(lat, lon, CITIES[i][1], CITIES[i][2]);
      if (d < bestD) { bestD = d; best = CITIES[i][0]; }
    }
    return bestD > maxKm ? [UNKNOWN_CITY, bestD] : [best, bestD];
  }

  // 中国大陆统一按 UTC+8；其余地区按经度每 15° 一小时
  function tzOffsetHours(lat, lon) {
    if (lat !== null && lon >= 73 && lon <= 135.5 && lat >= 18 && lat <= 53.6) return 8;
    return Math.max(-12, Math.min(14, Math.round(lon / 15)));
  }

  function annotateUtc(photos) {
    var offsets = {};
    var counts = {};
    photos.forEach(function (p) {
      if (p.lon === null) return;
      var o = tzOffsetHours(p.lat, p.lon);
      counts[o] = (counts[o] || 0) + 1;
      offsets[o] = true;
    });
    var base = 0, best = -1;
    Object.keys(counts).forEach(function (k) {
      var o = parseInt(k, 10);
      if (counts[k] > best) { best = counts[k]; base = o; }
    });

    var corrected = 0;
    photos.forEach(function (p) {
      var off = p.lon === null ? base : tzOffsetHours(p.lat, p.lon);
      if (p.lon !== null && off !== base) corrected++;
      p.utc = new Date(p.dt.getTime() - off * 3600000);
    });
    return { timezone_corrected: corrected };
  }

  function dedupe(photos) {
    var seen = {};
    var kept = [];
    var removed = 0;
    photos.forEach(function (p) {
      var key = p.dt.getTime() + '|' +
        (p.lat === null ? 'n' : p.lat.toFixed(4)) + '|' +
        (p.lon === null ? 'n' : p.lon.toFixed(4));
      if (seen[key]) { removed++; return; }
      seen[key] = 1;
      kept.push(p);
    });
    return [kept, { duplicates_removed: removed }];
  }

  function filterDrift(photos) {
    var gps = photos.filter(function (p) { return p.lat !== null; });
    if (gps.length < 3) return [photos, { drift_removed: 0 }];

    var pts = gps.slice().sort(function (a, b) { return a.utc - b.utc; });
    var n = pts.length;
    var viol = new Array(n).fill(0);

    for (var i = 0; i < n - 1; i++) {
      var dtH = (pts[i + 1].utc - pts[i].utc) / 3600000;
      if (dtH <= 0) continue;
      var dist = haversine(pts[i].lat, pts[i].lon, pts[i + 1].lat, pts[i + 1].lon);
      if (dist > MIN_DISTANCE_KM && dist / dtH > MAX_SPEED_KMH) {
        viol[i]++; viol[i + 1]++;
      }
    }

    var bad = {};
    for (var j = 0; j < n; j++) if (viol[j] >= 2) bad[j] = true;

    // 跟前后邻居都相距几千公里：不依赖时间的判据
    for (var k = 1; k < n - 1; k++) {
      if (bad[k]) continue;
      var dPrev = haversine(pts[k - 1].lat, pts[k - 1].lon, pts[k].lat, pts[k].lon);
      var dNext = haversine(pts[k].lat, pts[k].lon, pts[k + 1].lat, pts[k + 1].lon);
      if (dPrev > NEIGHBOR_JUMP_KM && dNext > NEIGHBOR_JUMP_KM) bad[k] = true;
    }

    // 端点只有一个邻居，只拦极端情况
    [0, n - 1].forEach(function (idx) {
      if (bad[idx]) return;
      var nb = idx === 0 ? 1 : n - 2;
      var dtH2 = Math.abs(pts[nb].utc - pts[idx].utc) / 3600000;
      var dist2 = haversine(pts[idx].lat, pts[idx].lon, pts[nb].lat, pts[nb].lon);
      if (dtH2 > 0 && dist2 > MIN_DISTANCE_KM && dist2 / dtH2 > 3000) bad[idx] = true;
    });

    var removed = Object.keys(bad).length;
    if (!removed) return [photos, { drift_removed: 0 }];
    var drop = {};
    Object.keys(bad).forEach(function (i2) { drop[pts[+i2].__id] = true; });
    var kept = photos.filter(function (p) { return !drop[p.__id]; });
    return [kept, { drift_removed: removed }];
  }

  function detectHome(gps) {
    if (!gps.length) return null;
    var cells = {};
    var order = [];
    gps.forEach(function (p) {
      var key = (Math.round(p.lat * 5) / 5) + ',' + (Math.round(p.lon * 5) / 5);
      if (!cells[key]) { cells[key] = []; order.push(key); }
      cells[key].push(p);
    });
    var bestKey = order[0];
    order.forEach(function (k) { if (cells[k].length > cells[bestKey].length) bestKey = k; });
    var cell = cells[bestKey];
    var clat = cell.reduce(function (s, p) { return s + p.lat; }, 0) / cell.length;
    var clon = cell.reduce(function (s, p) { return s + p.lon; }, 0) / cell.length;

    var near = gps.filter(function (p) { return haversine(p.lat, p.lon, clat, clon) <= 30; });
    if (!near.length) near = cell;
    return [
      near.reduce(function (s, p) { return s + p.lat; }, 0) / near.length,
      near.reduce(function (s, p) { return s + p.lon; }, 0) / near.length,
    ];
  }

  function samplePoly(points, cap) {
    cap = cap || 120;
    if (points.length <= cap) return points.map(function (p) { return [+p[0].toFixed(5), +p[1].toFixed(5)]; });
    var step = points.length / cap;
    var out = [];
    for (var i = 0; i < cap; i++) out.push(points[Math.floor(i * step)]);
    out[cap - 1] = points[points.length - 1];
    return out.map(function (p) { return [+p[0].toFixed(5), +p[1].toFixed(5)]; });
  }

  function segmentTrips(photos, home) {
    var gps = photos.filter(function (p) { return p.lat !== null; })
      .sort(function (a, b) { return a.utc - b.utc; });

    var dists = {};
    var away = [];
    gps.forEach(function (p) {
      var d = haversine(home[0], home[1], p.lat, p.lon);
      dists[p.__id] = d;
      if (d > AWAY_KM) away.push(p);
    });

    var runs = [];
    away.forEach(function (p) {
      var last = runs[runs.length - 1];
      if (last && (p.utc - last[last.length - 1].utc) / 3600000 <= GAP_HOURS) last.push(p);
      else runs.push([p]);
    });

    return runs.filter(function (run) {
      if (run.length < MIN_PHOTOS) return false;
      return Math.max.apply(null, run.map(function (p) { return dists[p.__id]; })) >= MIN_MAX_KM;
    }).map(function (run) { return { run: run, dists: dists }; });
  }

  function tripJson(item, idx) {
    var run = item.run, dists = item.dists;
    var start = run[0].dt, end = run[run.length - 1].dt;
    var days = Math.max(1, Math.round((startOfDay(end) - startOfDay(start)) / 86400000) + 1);

    var cityCount = {};
    var cityOrder = [];
    run.forEach(function (p) {
      var c = nearestCity(p.lat, p.lon)[0];
      if (c === UNKNOWN_CITY) return;
      if (!cityCount[c]) { cityCount[c] = 0; cityOrder.push(c); }
      cityCount[c]++;
    });
    cityOrder.sort(function (a, b) { return cityCount[b] - cityCount[a]; });
    var cities = cityOrder.slice(0, 4);

    var maxKm = Math.max.apply(null, run.map(function (p) { return dists[p.__id] || 0; }));
    var latSum = 0, lonSum = 0;
    run.forEach(function (p) { latSum += p.lat; lonSum += p.lon; });

    var ordered = run.slice().sort(function (a, b) { return a.dt - b.dt; });
    var step = Math.max(1, Math.floor(ordered.length / 8));
    var picked = [];
    for (var i = 0; i < ordered.length && picked.length < 8; i += step) picked.push(ordered[i]);

    return {
      id: idx,
      start: ymd(start),
      end: ymd(end),
      days: days,
      photos: run.length,
      cities: cities,
      title: cities.length ? cities.slice(0, 2).join(' · ') : '一段没有名字的旅程',
      max_km: Math.round(maxKm * 10) / 10,
      center: [+(latSum / run.length).toFixed(4), +(lonSum / run.length).toFixed(4)],
      poly: samplePoly(run.map(function (p) { return [p.lat, p.lon]; })),
      thumbs: [],
      _year: start.getFullYear(),
      _month: start.getMonth() + 1,
      _photos: picked,
    };
  }

  function longestStreak(dayList) {
    if (!dayList.length) return 0;
    var best = 1, cur = 1;
    for (var i = 1; i < dayList.length; i++) {
      var gap = Math.round((dayList[i] - dayList[i - 1]) / 86400000);
      cur = gap === 1 ? cur + 1 : 1;
      if (cur > best) best = cur;
    }
    return best;
  }

  function calendar(dayMap, start, end) {
    var gridStart = addDays(start, -((start.getDay() + 6) % 7));
    var gridEnd = addDays(end, 6 - ((end.getDay() + 6) % 7));
    var weeks = [];
    var cur = gridStart;
    while (cur <= gridEnd) {
      var week = [];
      for (var i = 0; i < 7; i++) {
        var d = addDays(cur, i);
        if (d < start || d > end) week.push(null);
        else week.push(dayMap[dayKey(d)] || 0);
      }
      weeks.push(week);
      cur = addDays(cur, 7);
    }
    return { from: ymd(gridStart), weeks: weeks };
  }

  function quietGap(days) {
    var best = 0, from = null, to = null;
    for (var i = 1; i < days.length; i++) {
      var gap = Math.round((days[i] - days[i - 1]) / 86400000) - 1;
      if (gap > best) { best = gap; from = ymd(days[i - 1]); to = ymd(days[i]); }
    }
    return { days: best, from: from, to: to };
  }

  function buildYearBlock(label, photos, home, dists, trips, year, homeCity) {
    var gps = photos.filter(function (p) { return p.lat !== null; });

    var cityCount = {}, cityOrder = [];
    gps.forEach(function (p) {
      var c = nearestCity(p.lat, p.lon)[0];
      if (c === UNKNOWN_CITY || c === homeCity) return;
      if (!cityCount[c]) { cityCount[c] = 0; cityOrder.push(c); }
      cityCount[c]++;
    });
    cityOrder.sort(function (a, b) { return cityCount[b] - cityCount[a]; });

    var dayMap = {}, daySet = {};
    photos.forEach(function (p) {
      var k = dayKey(p.dt);
      dayMap[k] = (dayMap[k] || 0) + 1;
      daySet[k] = 1;
    });
    var allDays = Object.keys(daySet).sort();

    var calStart, calEnd;
    if (year !== null) {
      calStart = new Date(year, 0, 1);
      calEnd = new Date(year, 11, 31);
    } else {
      var lastKey = allDays[allDays.length - 1];
      var last = lastKey ? new Date(lastKey + 'T00:00:00') : new Date();
      calEnd = last;
      calStart = addDays(last, -364);
    }

    var active = allDays.map(function (k) { return new Date(k + 'T00:00:00'); })
      .filter(function (d) { return d >= calStart && d <= calEnd; });
    var windowMap = {};
    active.forEach(function (d) { windowMap[dayKey(d)] = dayMap[dayKey(d)]; });

    var maxKm = 0, north = null, south = null, furthest = null;
    gps.forEach(function (p) {
      var d = dists[p.__id] || 0;
      if (d > maxKm) { maxKm = d; furthest = p; }
      if (!north || p.lat > north.lat) north = p;
      if (!south || p.lat < south.lat) south = p;
    });

    return {
      label: label,
      year: year,
      stats: {
        photos: photos.length,
        trips: trips.length,
        cities: Object.keys(cityCount).length,
        max_km: Math.round(maxKm),
        away_days: trips.reduce(function (s, t) { return s + t.days; }, 0),
        active_days: active.length,
        longest_streak: longestStreak(active),
        span_days: Math.round((calEnd - calStart) / 86400000) + 1,
        cal: calendar(windowMap, calStart, calEnd),
        quiet: quietGap(active),
        north: north ? nearestCity(north.lat, north.lon)[0] : '—',
        south: south ? nearestCity(south.lat, south.lon)[0] : '—',
        furthest_city: furthest ? nearestCity(furthest.lat, furthest.lon)[0] : '—',
        top_cities: cityOrder.slice(0, 8).map(function (c) { return { name: c, n: cityCount[c] }; }),
      },
      trips: trips.slice().sort(function (a, b) { return a.start < b.start ? 1 : a.start > b.start ? -1 : 0; }),
    };
  }

  function run(rawPhotos, opts) {
    opts = opts || {};
    var photos = rawPhotos.map(function (p, i) {
      return { dt: p.dt, lat: p.lat, lon: p.lon, src: p.src || 'exif', __id: i };
    }).sort(function (a, b) { return a.dt - b.dt; });

    var total = photos.length;
    var bySource = {};
    photos.forEach(function (p) { bySource[p.src] = (bySource[p.src] || 0) + 1; });

    var tz = annotateUtc(photos);
    var dd = dedupe(photos);
    photos = dd[0];
    var fd = filterDrift(photos);
    photos = fd[0];

    var gps = photos.filter(function (p) { return p.lat !== null; });
    if (!gps.length) {
      var err = new Error('NO_GPS');
      err.code = 'NO_GPS';
      throw err;
    }

    var home = detectHome(gps);
    var homeCity = nearestCity(home[0], home[1])[0];

    var dists = {};
    gps.forEach(function (p) { dists[p.__id] = haversine(home[0], home[1], p.lat, p.lon); });

    var trips = segmentTrips(photos, home).map(function (item, i) { return tripJson(item, i); });

    var years = Array.from(new Set(photos.map(function (p) { return p.dt.getFullYear(); })))
      .sort(function (a, b) { return b - a; });

    var blocks = years.map(function (y) {
      return buildYearBlock(String(y), photos.filter(function (p) { return p.dt.getFullYear() === y; }),
        home, dists, trips.filter(function (t) { return t._year === y; }), y, homeCity);
    });
    blocks.unshift(buildYearBlock('全部', photos, home, dists, trips, null, homeCity));

    return {
      payload: {
        home: { lat: +home[0].toFixed(4), lon: +home[1].toFixed(4), city: homeCity },
        years: blocks,
      },
      meta: {
        total: total,
        with_gps: gps.length,
        gps_ratio: total ? +(gps.length / total).toFixed(3) : 0,
        by_source: bySource,
        drift_removed: fd[1].drift_removed,
        duplicates_removed: dd[1].duplicates_removed,
        timezone_corrected: tz.timezone_corrected,
        thumbs: 0,
      },
    };
  }

  global.RingsEngine = {
    run: run,
    haversine: haversine,
    nearestCity: nearestCity,
    tzOffsetHours: tzOffsetHours,
  };
})(typeof window !== 'undefined' ? window : globalThis);
