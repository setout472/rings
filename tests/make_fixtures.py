"""生成带已知 EXIF 的测试图片，给 web/js/exif.js 做真值校验。

    python tests/make_fixtures.py

Pillow 只会写小端（II），所以大端（MM）的样本是手工拼字节的——这一段最容易出错，
每个块写完都断言长度，免得又出现「某个条目少 1 字节，后面整体错位」这种坑。
"""

import os
import struct

from PIL import Image
from PIL.TiffImagePlugin import IFDRational

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "web", "fixtures")


def build_tiff(be: bool, lat=(31.0, 13.0, 0.0), lon=(121.0, 28.0, 0.0),
               dt=b"2024:05:01 12:34:56\x00", latref=b"N", lonref=b"E") -> bytes:
    e = ">" if be else "<"

    def u16(v):
        return struct.pack(e + "H", v)

    def u32(v):
        return struct.pack(e + "I", v)

    def rat(v):
        return struct.pack(e + "II", int(round(v * 1000000)), 1000000)

    ifd0_off = 8
    exif_off = ifd0_off + 30
    dt_off = exif_off + 18
    gps_off = dt_off + len(dt)
    if gps_off % 2:
        gps_off += 1
    rat_off = gps_off + 54

    ifd0 = bytearray()
    ifd0 += u16(2)
    ifd0 += u16(0x8769) + u16(4) + u32(1) + u32(exif_off)
    ifd0 += u16(0x8825) + u16(4) + u32(1) + u32(gps_off)
    ifd0 += u32(0)
    assert len(ifd0) == 30, len(ifd0)

    exif = bytearray()
    exif += u16(1)
    exif += u16(0x9003) + u16(2) + u32(len(dt)) + u32(dt_off)
    exif += u32(0)
    assert len(exif) == 18, len(exif)

    gps = bytearray()
    gps += u16(4)
    # ASCII 值域固定占 4 字节，不足要补零 —— 少写 1 字节就会让后面全部错位
    gps += u16(1) + u16(2) + u32(2) + latref.ljust(4, b"\x00")
    gps += u16(2) + u16(5) + u32(3) + u32(rat_off)
    gps += u16(3) + u16(2) + u32(2) + lonref.ljust(4, b"\x00")
    gps += u16(4) + u16(5) + u32(3) + u32(rat_off + 24)
    gps += u32(0)
    assert len(gps) == 54, len(gps)

    body = bytearray()
    body += b"MM" if be else b"II"
    body += u16(0x2A) + u32(ifd0_off)
    body += ifd0
    body += exif
    body += dt
    if len(body) < gps_off:
        body += b"\x00" * (gps_off - len(body))
    assert len(body) == gps_off, (len(body), gps_off)
    body += gps
    assert len(body) == rat_off, (len(body), rat_off)
    for v in lat:
        body += rat(v)
    for v in lon:
        body += rat(v)
    return bytes(body)


def wrap_jpeg(tiff: bytes) -> bytes:
    app1 = b"Exif\x00\x00" + tiff
    return b"\xff\xd8" + b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 + b"\xff\xd9"


def main() -> None:
    os.makedirs(OUT, exist_ok=True)

    # 1) Pillow 写的小端 + GPS（真实相机路径）
    im = Image.new("RGB", (64, 48), (40, 90, 120))
    ex = im.getexif()
    ex[0x8769] = {36867: "2023:10:02 08:15:30"}
    ex[0x8825] = {1: "N", 2: (IFDRational(30), IFDRational(34), IFDRational(0)),
                  3: "E", 4: (IFDRational(104), IFDRational(3), IFDRational(0))}
    ex[0x010F] = "Apple"
    ex[0x0110] = "iPhone 15 Pro"
    im.save(os.path.join(OUT, "le_gps.jpg"), exif=ex)

    # 2) 手工大端 + GPS
    open(os.path.join(OUT, "be_gps.jpg"), "wb").write(wrap_jpeg(build_tiff(be=True)))

    # 3) 只有 GPS、时间为空
    open(os.path.join(OUT, "be_no_date.jpg"), "wb").write(
        wrap_jpeg(build_tiff(be=True, dt=b"\x00")))

    # 4) 南半球 + 西经
    open(os.path.join(OUT, "be_south_west.jpg"), "wb").write(
        wrap_jpeg(build_tiff(be=True, lat=(33.86, 51, 0), lon=(151.20, 12, 0),
                             latref=b"S", lonref=b"W")))

    # 5) 完全没有 EXIF
    Image.new("RGB", (40, 40), (10, 10, 10)).save(os.path.join(OUT, "no_exif.jpg"))

    # 6) 0,0 坐标（设备未定位时的占位符）
    ex0 = Image.new("RGB", (48, 32), (60, 20, 20)).getexif()
    ex0[0x8769] = {36867: "2023:10:02 08:15:30"}
    ex0[0x8825] = {1: "N", 2: (IFDRational(0), IFDRational(0), IFDRational(0)),
                   3: "E", 4: (IFDRational(0), IFDRational(0), IFDRational(0))}
    Image.new("RGB", (48, 32), (60, 20, 20)).save(os.path.join(OUT, "gps_zero.jpg"), exif=ex0)

    # 7) 截断文件
    blob = open(os.path.join(OUT, "le_gps.jpg"), "rb").read()
    open(os.path.join(OUT, "truncated.jpg"), "wb").write(blob[:40])

    print("fixtures ->", os.path.normpath(OUT))
    for name in sorted(os.listdir(OUT)):
        print("  ", name, os.path.getsize(os.path.join(OUT, name)), "bytes")


if __name__ == "__main__":
    main()
