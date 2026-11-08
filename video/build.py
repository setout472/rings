"""生成演示视频：配音 → 定时长 → 抓帧 → 合成。

    python video/build.py                 # 全流程
    python video/build.py --audio-only    # 只做配音和时长清单

设计上的关键取舍：**画面动作用「每帧推进一点」驱动，而不是按真实时间录**。
抓一帧要 100ms 左右，如果按墙钟滚动，抓出来的动作会快得离谱；
按帧推进的话，哪怕抓 10 分钟，成片里也是匀速的。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEO = os.path.join(ROOT, "video")
AUDIO = os.path.join(VIDEO, "audio")
FRAMES = os.path.join(VIDEO, "frames")
VENDOR = os.path.join(ROOT, "_vendor")

sys.path.insert(0, VENDOR)

VOICE = "zh-CN-XiaoxiaoNeural"

# 片头留白：直接开口说话会显得很赶，先静 0.6 秒再起
LEAD_IN = 0.6

# 每个镜头：id、旁白、在页面上做什么
#   prep  : 抓帧前执行一次（导航 / 点击 / 滚动到某个锚点）
#   scroll: 整段镜头里额外滚动的像素（负数=向上），用来制造微小的运动
SHOTS = [
    {
        "id": "01_gap",
        "say": "三千七百多张照片里，最难被算出来的，不是你去过哪儿。",
        "prep": "report#3",          # 2022 年
        "anchor": ".cal-wrap",
        "scroll": 90,
        "pad": 1.2,
    },
    {
        "id": "02_what",
        "say": "我做了个小工具，把相册变成一份年度报告——不用注册，不用上传，也不用装任何东西。",
        "prep": "landing",
        "anchor": None,
        # 只挪 40px：挪多了大标题会被顶部导航切掉
        "scroll": 40,
        "pad": 0.8,
    },
    {
        "id": "03_app",
        "say": "相册拖进去就行，照片在你自己的电脑上读出来，算完直接出报告，一张都不会上传。",
        "prep": "app",
        "anchor": None,
        "scroll": 0,
        "pad": 0.8,
    },
    {
        "id": "04_numbers",
        "say": "三千七百多张照片，最后变成这几个数字，这些不是我填的，是从每张照片的元数据里算出来的。",
        "prep": "report#0",
        "anchor": ".statgrid",
        "scroll": -40,
        "pad": 1.0,
    },
    {
        "id": "05_route",
        "say": "点开一次行程，地图会放大到那一次的路线，新疆那趟走得最远。",
        "prep": "report#1+click_trip",
        "anchor": ".mapcard",
        "scroll": 0,
        "pad": 1.0,
    },
    {
        "id": "06_silence",
        "say": "然后是这块空白，二〇二二年三月到六月，一张照片都没有，报告自己把它算成了一句话，最长的一次沉默，八十三天。",
        "prep": "report#3",
        "anchor": ".cal-wrap",
        "scroll": 40,
        "pad": 1.2,
    },
    {
        "id": "07_trust",
        "say": "页面底部还写着另一件事，多少张没有定位，多少张的时间不可信，剔掉了几个异常点。",
        "prep": "report#0",
        "anchor": ".quality",
        "scroll": 60,
        "pad": 1.0,
    },
    {
        "id": "08_close",
        "say": "一个不告诉你哪里可能错的报告，不值得信。全部，都在你自己的电脑上完成。",
        "prep": "report#0",
        "anchor": None,
        "scroll": 0,
        "pad": 1.6,
    },
]


def ffmpeg() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def tighten(src: str, dst: str, comma: float = 0.11, period: float = 0.24,
            min_sil: float = 0.16) -> float:
    """把 TTS 在标点后塞的长停顿压短，返回新时长。

    Edge TTS 每个标点后要停 300~600ms，句子一密就变成一顿一顿。
    分两档处理：短的（逗号级）压到 110ms，长的（句号级）保留 220ms——
    全压到 110ms 会变成不喘气，全保留又是原来的卡顿。
    """
    import numpy as np

    with wave.open(src) as w:
        sr = w.getframerate()
        d = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
    if not len(d):
        return 0.0

    hop = max(1, int(sr * 0.005))
    frames = len(d) // hop
    rms = np.sqrt((d[: frames * hop].reshape(frames, hop) ** 2).mean(axis=1))
    thr = max(50.0, float(rms.max()) * 0.04)
    quiet = rms < thr

    min_n = int(min_sil * sr)
    period_n = int(0.30 * sr)   # 原始停顿 ≥300ms 的按句末处理，保留更长的呼吸

    pieces = []
    i = 0
    while i < frames:
        if not quiet[i]:
            j = i
            while j < frames and not quiet[j]:
                j += 1
            pieces.append(d[i * hop: j * hop])
            i = j
        else:
            j = i
            while j < frames and quiet[j]:
                j += 1
            start, end = i * hop, j * hop
            seg = end - start
            if seg >= min_n:
                want = int((period if seg >= period_n else comma) * sr)
                c = (start + end) // 2
                pieces.append(d[max(0, c - want // 2): c + want // 2])
            else:
                pieces.append(d[start:end])
            i = j

    out = np.clip(np.concatenate(pieces), -32768, 32767).astype(np.int16) if pieces else d.astype(np.int16)
    with wave.open(dst, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(out.tobytes())
    return len(out) / float(sr)


def synth(shot: dict) -> tuple[str, float]:
    """合成一段配音，转成 48k 单声道 wav，压掉长停顿，返回 (文件名, 时长)。

    直接调库而不是 `python -m edge_tts`：子进程不会继承 sys.path 里的 _vendor，
    而且这样少一层进程启动。
    """
    import asyncio

    import edge_tts

    mp3 = os.path.join(AUDIO, shot["id"] + ".mp3")
    raw = os.path.join(AUDIO, shot["id"] + "_raw.wav")
    tight = os.path.join(AUDIO, shot["id"] + ".wav")

    async def _say():
        await edge_tts.Communicate(shot["say"], VOICE).save(mp3)

    asyncio.run(_say())

    subprocess.run(
        [ffmpeg(), "-y", "-loglevel", "error", "-i", mp3,
         "-ar", "48000", "-ac", "1", raw],
        check=True,
    )
    dur = tighten(raw, tight)
    return shot["id"] + ".wav", dur


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio-only", action="store_true")
    ap.add_argument("--reuse-audio", action="store_true", help="复用已有配音，不重新合成")
    ap.add_argument("--reuse-frames", action="store_true", help="复用已抓好的帧，不重新抓")
    ap.add_argument("--fps", type=int, default=8)
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=900)
    args = ap.parse_args()

    os.makedirs(AUDIO, exist_ok=True)
    os.makedirs(FRAMES, exist_ok=True)

    manifest = []
    total = 0.0
    for shot in SHOTS:
        wav = os.path.join(AUDIO, shot["id"] + ".wav")
        if args.reuse_audio and os.path.exists(wav):
            with wave.open(wav) as w:
                dur = w.getnframes() / float(w.getframerate())
            name = shot["id"] + ".wav"
        else:
            name, dur = synth(shot)
        hold = round(dur + shot["pad"], 2)
        total += hold
        manifest.append({**shot, "audio": name,
                         "audio_dur": round(dur, 2), "hold": hold})
        print(f"  {shot['id']:<14} 配音 {dur:5.2f}s  画面 {hold:5.2f}s")

    print(f"合计 {total:.1f}s（{total / 60:.2f} 分钟）")

    path = os.path.join(VIDEO, "shots.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)

    if args.audio_only:
        return

    if args.reuse_frames:
        print("→ 跳过抓帧（复用现有帧）")
    else:
        print("→ 抓帧")
        subprocess.run(
            ["node", os.path.join(VIDEO, "capture.mjs"),
             "--shots", path, "--out", FRAMES,
             "--fps", str(args.fps), "--width", str(args.width), "--height", str(args.height)],
            check=True, cwd=ROOT,
        )

    print("→ 合成")
    concat_frames(manifest, args.fps)
    concat_audio(manifest)
    mux(manifest)


def concat_frames(manifest: list[dict], fps: int) -> None:
    """把所有帧按各自时长写成 concat 清单。"""
    lines = []
    idx = 0

    first = os.path.join(FRAMES, manifest[0]["id"] + "_0000.jpg")
    for _ in range(int(round(LEAD_IN * fps))):
        lines.append(f"file '{first.replace(chr(92), '/')}'")
        lines.append(f"duration {LEAD_IN / max(1, int(round(LEAD_IN * fps))):.4f}")
        idx += 1

    for shot in manifest:
        name = shot["id"]
        n = int(round(shot["hold"] * fps))
        step = shot["hold"] / n
        for i in range(n):
            p = os.path.join(FRAMES, f"{name}_{i:04d}.jpg")
            if not os.path.exists(p):
                break
            lines.append(f"file '{p.replace(chr(92), '/')}'")
            lines.append(f"duration {step:.4f}")
            idx += 1

    # concat 分离器要求最后一张重复一次，否则最后一帧的时长会被忽略
    last_shot = manifest[-1]["id"]
    last_n = int(round(manifest[-1]["hold"] * fps))
    tail = os.path.join(FRAMES, f"{last_shot}_{last_n - 1:04d}.jpg")
    if os.path.exists(tail):
        lines.append(f"file '{tail.replace(chr(92), '/')}'")

    path = os.path.join(VIDEO, "frames.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  帧清单：{idx} 帧（含片头 {int(round(LEAD_IN * fps))} 帧）")


def concat_audio(manifest: list[dict]) -> None:
    """按画面时长拼音轨：每段配音后面补静音，保证与画面严格对齐。"""
    ff = ffmpeg()
    lead = os.path.join(AUDIO, "00_lead.wav")
    subprocess.run(
        [ff, "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "anullsrc=r=48000:cl=mono", "-t", str(LEAD_IN), lead],
        check=True,
    )

    parts = [lead]
    for i, shot in enumerate(manifest):
        wav = os.path.join(AUDIO, shot["audio"])
        gap = shot["hold"] - shot["audio_dur"]
        padded = os.path.join(AUDIO, f"{i:02d}_pad.wav")
        subprocess.run(
            [ff, "-y", "-loglevel", "error", "-i", wav,
             "-af", f"apad=pad_dur={max(0.02, gap):.3f}",
             "-ar", "48000", "-ac", "1", padded],
            check=True,
        )
        parts.append(padded)

    lst = os.path.join(VIDEO, "audio.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for p in parts:
            f.write(f"file '{p.replace(chr(92), '/')}'\n")
    subprocess.run(
        [ff, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", lst, "-c", "copy", os.path.join(VIDEO, "voice.wav")],
        check=True,
    )


def mux(manifest: list[dict]) -> None:
    ff = ffmpeg()
    out = os.path.join(VIDEO, "demo.mp4")
    subprocess.run(
        [ff, "-y", "-loglevel", "error",
         "-f", "concat", "-safe", "0", "-i", os.path.join(VIDEO, "frames.txt"),
         "-i", os.path.join(VIDEO, "voice.wav"),
         "-c:v", "libx264", "-preset", "slow", "-crf", "20",
         "-pix_fmt", "yuv420p", "-r", "25",
         "-c:a", "aac", "-b:a", "128k",
         "-shortest", out],
        check=True,
    )
    size = os.path.getsize(out) / 1024 / 1024
    print(f"  成片：{out}  ({size:.1f} MB)")


if __name__ == "__main__":
    main()
