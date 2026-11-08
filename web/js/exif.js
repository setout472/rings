/*
 * exif.js —— 手写的 JPEG EXIF 解析器。
 *
 * 只做三件事：读拍摄时间、读 GPS 坐标、读相机型号。不引第三方库，因为：
 *   1. 整个产品卖的就是「不上传、无依赖」，前端引一个 200KB 的解析库有点讽刺
 *   2. 需要的字段就这几个，硬编码比通用库更可控
 *
 * 结构：JPEG 的 APP1 段（FFE1）里装着 "Exif\0\0" + 一个 TIFF 文件。
 * TIFF 里是 IFD 链：IFD0 有两个指针，0x8769 指向 Exif 子 IFD（放拍摄时间），
 * 0x8825 指向 GPS IFD（放经纬度）。
 *
 * 任何一步不合法都返回空对象，不抛异常 —— 相册里总有几张坏图，
 * 为了一张坏图让整个扫描失败是不可接受的。
 */
(function (global) {
  'use strict';

  var TYPE_SIZE = { 1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8 };

  function findTiffStart(dv) {
    var len = dv.byteLength;
    if (len < 4 || dv.getUint16(0) !== 0xFFD8) return -1;   // 不是 JPEG
    var off = 2;
    while (off + 4 <= len) {
      if (dv.getUint8(off) !== 0xFF) { off++; continue; }
      var marker = dv.getUint8(off + 1);
      // 无长度的标记
      if (marker === 0xD8 || marker === 0x01 || (marker >= 0xD0 && marker <= 0xD7)) {
        off += 2;
        continue;
      }
      if (marker === 0xDA) break;                            // 图像数据开始，后面没有元数据了
      if (off + 4 > len) break;
      var size = dv.getUint16(off + 2);
      if (size < 2) break;
      if (marker === 0xE1 && off + 4 + 6 <= len) {
        var p = off + 4;
        if (dv.getUint32(p) === 0x45786966 && dv.getUint16(p + 4) === 0x0000) {
          return p + 6;                                      // 跳过 "Exif\0\0"
        }
      }
      off += 2 + size;
    }
    return -1;
  }

  function readIfd(dv, tiff, offset, le) {
    var out = {};
    if (offset <= 0 || tiff + offset + 2 > dv.byteLength) return out;
    var count = dv.getUint16(tiff + offset, le);
    if (count > 512) return out;                              // 明显不合理，放弃
    var base = tiff + offset + 2;
    for (var i = 0; i < count; i++) {
      var e = base + i * 12;
      if (e + 12 > dv.byteLength) break;
      var tag = dv.getUint16(e, le);
      var type = dv.getUint16(e + 2, le);
      var num = dv.getUint32(e + 4, le);
      var unit = TYPE_SIZE[type] || 1;
      var bytes = unit * num;
      var vOff = bytes <= 4 ? e + 8 : tiff + dv.getUint32(e + 8, le);
      if (vOff < 0 || vOff + Math.min(bytes, 4) > dv.byteLength) continue;
      out[tag] = { type: type, count: num, off: vOff };
    }
    return out;
  }

  function asciiAt(dv, ent) {
    if (!ent) return '';
    var s = '';
    var end = Math.min(ent.count, 64);
    for (var i = 0; i < end; i++) {
      var c = dv.getUint8(ent.off + i);
      if (c === 0) break;
      s += String.fromCharCode(c);
    }
    return s.trim();
  }

  function rationalAt(dv, ent, le, idx) {
    var o = ent.off + idx * 8;
    if (o + 8 > dv.byteLength) return 0;
    var n = dv.getUint32(o, le);
    var d = dv.getUint32(o + 4, le);
    return d ? n / d : 0;
  }

  function dmsToDeg(dv, ent, ref, le) {
    if (!ent || ent.count < 3) return null;
    var d = rationalAt(dv, ent, le, 0);
    var m = rationalAt(dv, ent, le, 1);
    var s = rationalAt(dv, ent, le, 2);
    var v = d + m / 60 + s / 3600;
    if (!isFinite(v) || v > 180) return null;
    if (ref === 'S' || ref === 'W') v = -v;
    return v;
  }

  function parseDate(str) {
    if (!str) return null;
    var m = /^(\d{4})[:\-](\d{2})[:\-](\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?/.exec(str);
    if (!m) return null;
    var y = +m[1], mo = +m[2], d = +m[3], h = +m[4], mi = +m[5], s = +(m[6] || 0);
    if (y < 1970 || y > 2100 || mo < 1 || mo > 12 || d < 1 || d > 31) return null;
    return new Date(y, mo - 1, d, h, mi, s);
  }

  function parse(buffer) {
    var res = { date: null, lat: null, lon: null, make: '', model: '', ok: false };
    try {
      var dv = new DataView(buffer);
      var tiff = findTiffStart(dv);
      if (tiff < 0) return res;

      var bom = dv.getUint16(tiff);
      var le;
      if (bom === 0x4949) le = true;          // "II" 小端
      else if (bom === 0x4D4D) le = false;    // "MM" 大端
      else return res;

      if (dv.getUint16(tiff + 2, le) !== 0x002A) return res;
      var ifd0Off = dv.getUint32(tiff + 4, le);
      var ifd0 = readIfd(dv, tiff, ifd0Off, le);

      res.make = asciiAt(dv, ifd0[0x010F]);
      res.model = asciiAt(dv, ifd0[0x0110]);

      // 拍摄时间：优先 Exif 子 IFD 的 DateTimeOriginal，其次 IFD0 的 DateTime
      var dateStr = '';
      if (ifd0[0x8769]) {
        var exifIfd = readIfd(dv, tiff, dv.getUint32(ifd0[0x8769].off, le), le);
        dateStr = asciiAt(dv, exifIfd[0x9003]) || asciiAt(dv, exifIfd[0x9004]);
      }
      if (!dateStr && ifd0[0x0132]) dateStr = asciiAt(dv, ifd0[0x0132]);
      if (!dateStr && ifd0[0x9003]) dateStr = asciiAt(dv, ifd0[0x9003]);  // 坏相机写在 IFD0
      res.date = parseDate(dateStr);

      // GPS
      if (ifd0[0x8825]) {
        var gps = readIfd(dv, tiff, dv.getUint32(ifd0[0x8825].off, le), le);
        var latRef = asciiAt(dv, gps[1]).toUpperCase();
        var lonRef = asciiAt(dv, gps[3]).toUpperCase();
        var lat = dmsToDeg(dv, gps[2], latRef, le);
        var lon = dmsToDeg(dv, gps[4], lonRef, le);
        if (lat !== null && lon !== null && !(Math.abs(lat) < 0.01 && Math.abs(lon) < 0.01)) {
          res.lat = lat;
          res.lon = lon;
        }
      }
      res.ok = !!(res.date || res.lat !== null);
      return res;
    } catch (e) {
      return res;
    }
  }

  global.RingsEXIF = { parse: parse };
})(typeof window !== 'undefined' ? window : globalThis);
