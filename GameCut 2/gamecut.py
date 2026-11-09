#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GameCut 2 — คัดช็อตเด็ดจากฟุตเทจเกมยาวๆ ให้เหลือคลิปไฮไลต์สั้นๆ (เช่น 1 ชั่วโมง → 1–2 นาที)

วิธีหาช็อตเด็ด (ไม่ต้องใช้ AI หนักๆ จึงเร็ว):
  • ความเคลื่อนไหวของภาพ (ฉากต่อสู้ / แอคชั่น / กล้องหมุนเร็ว)
  • ความดังของเสียงเกม และจังหวะที่เสียงดังขึ้นกะทันหัน (ระเบิด / ตีบอส)
  • ข้ามจอดำ (โหลด) ภาพค้าง (pause / เมนู) และฉากนิ่งๆ อัตโนมัติ
  • กระจายช็อตให้ทั่วทั้งไฟล์ ไม่กองอยู่ฉากเดียว

รัน:   python3 gamecut.py          (เปิดหน้าแอพในเบราว์เซอร์ให้อัตโนมัติ)
ต้องมี: ffmpeg และ numpy
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import mimetypes
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    import numpy as np
except ImportError:  # pragma: no cover
    print("\n❌ ไม่พบ numpy — เปิดแอพผ่าน start.command (Mac) หรือ start.bat (Windows) เพื่อให้ติดตั้งให้อัตโนมัติ\n")
    sys.exit(1)

VERSION = "2.0.1"
APP_DIR = Path(__file__).resolve().parent
PORT = int(os.environ.get("GAMECUT_PORT", "8765"))
IS_MAC = platform.system() == "Darwin"
IS_WIN = platform.system() == "Windows"

_local_ff = APP_DIR / "ffmpeg" / "bin"          # ffmpeg ที่ดาวน์โหลดมาไว้ในโฟลเดอร์แอพ (Windows)
if _local_ff.is_dir():
    os.environ["PATH"] = str(_local_ff) + os.pathsep + os.environ.get("PATH", "")
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa
        pass

ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
ffprobe_bin = shutil.which("ffprobe") or "ffprobe"

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".flv", ".ts", ".mts", ".m2ts"}
STD_FPS = [23.976, 24, 25, 29.97, 30, 48, 50, 59.94, 60, 90, 100, 119.88, 120, 144, 165, 240]
FPS_F = 5                     # วิเคราะห์ภาพ 5 เฟรมต่อวินาที
AN_W, AN_H = 64, 36           # ขนาดภาพที่ใช้วิเคราะห์
ANALYSIS_VER = "a2"
FRAMES = {"1080x1920": (1080, 1920), "1080x1080": (1080, 1080)}

DEFAULT_SETTINGS = {
    # คัดช็อต
    "target_len": 90.0,     # ความยาวคลิปไฮไลต์ต่อ 1 ไฟล์ฟุตเทจ (วินาที)
    "shot_min": 2.5,        # ช็อตสั้นสุด (วินาที)
    "shot_max": 6.0,        # ช็อตยาวสุด (วินาที) — ฉากที่มันส์ต่อเนื่องจะได้ช็อตยาวขึ้น
    "spread": "mid",        # low | mid | high — กระจายช็อตให้ทั่วไฟล์มากน้อยแค่ไหน
    "order": "chrono",      # chrono = ตามเวลาในเกม | score = มันส์สุดขึ้นก่อน
    "skip_head": 0.0,       # ข้ามต้นไฟล์ (วินาที)
    "skip_tail": 0.0,       # ข้ามท้ายไฟล์ (วินาที)
    # ทำให้ภาพชัดขึ้น
    "enhance": "off",       # off | light | medium | strong
    "upscale": "none",      # none | 1080 | 1440 | 2160
    # รูปแบบภาพ
    "frame": "original",    # original | 1080x1920 (Reel) | 1080x1080
    "reframe": "crop",      # crop | blur | fit
    "crop_pos": 0.5,
    "blur_zoom": 1.0,
    # ส่งออก
    "audio": False,         # เก็บเสียงเกมไว้ในไฟล์ (ปกติปิด — ภาพอย่างเดียว)
    "codec": "h264",        # h264 (.mp4) | prores (.mov — ใหญ่แต่ตัดต่อลื่น)
    "export_shots": True,   # ไฟล์แยกทุกช็อต
    "export_reel": True,    # คลิปไฮไลต์รวมต่อไฟล์
    "fill": False,          # False = เอาเฉพาะช็อตที่มันส์กว่าค่าเฉลี่ย (อาจสั้นกว่าเป้า) | True = เติมให้ครบเป้า
    "combine": True,        # รวมไฮไลต์ทุกไฟล์เป็นคลิปเดียว
}


# ───────────────────────────── utils ─────────────────────────────

def log(*a):
    print("[GameCut]", *a, flush=True)


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)


def parse_rate(s) -> float:
    try:
        s = str(s)
        if "/" in s:
            n, d = s.split("/")
            return float(n) / float(d) if float(d) else 0.0
        return float(s)
    except Exception:  # noqa
        return 0.0


def snap_fps(f: float) -> float:
    if not f or f <= 0:
        return 30.0
    best = min(STD_FPS, key=lambda x: abs(x - f))
    return float(best) if abs(best - f) / best < 0.03 else float(round(f))


def fmt_tc(sec: float) -> str:
    sec = max(0.0, sec)
    m, s = divmod(sec, 60)
    h, m = divmod(int(m), 60)
    return f"{h}:{m:02d}:{s:04.1f}" if h else f"{int(m)}:{s:04.1f}"


def tc_name(sec: float) -> str:
    sec = int(max(0, sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}h{m:02d}m{s:02d}s" if h else f"{m:02d}m{s:02d}s"


def slug(text: str, n: int = 40) -> str:
    t = re.sub(r"[^A-Za-z0-9ก-๙]+", "-", text).strip("-")
    return t[:n].rstrip("-") or "clip"


def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def file_key(path: str, extra: str = "") -> str:
    try:
        st = os.stat(path)
        raw = f"{path}|{st.st_size}|{st.st_mtime}|{extra}"
    except OSError:
        raw = f"{path}|{extra}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def ev(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def probe(path: str) -> dict:
    r = run([ffprobe_bin, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)])
    try:
        d = json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        d = {}
    streams = d.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"
              and not (s.get("disposition") or {}).get("attached_pic")), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    dur = float((d.get("format") or {}).get("duration") or 0) or float((v or a or {}).get("duration") or 0)
    info = {"path": str(path), "name": Path(path).name, "duration": dur,
            "has_video": v is not None, "has_audio": a is not None}
    if v:
        r_fps = parse_rate(v.get("r_frame_rate", "0"))
        a_fps = parse_rate(v.get("avg_frame_rate", "0"))
        fps = r_fps if 10 < r_fps <= 240 else a_fps
        w, h = int(v.get("width") or 1920), int(v.get("height") or 1080)
        rot = 0
        for sd in v.get("side_data_list") or []:
            rot = int(sd.get("rotation", 0) or 0)
        if abs(rot) in (90, 270):
            w, h = h, w
        info.update(width=w, height=h, fps=snap_fps(fps), vcodec=v.get("codec_name"),
                    vbitrate=int(v.get("bit_rate") or (d.get("format") or {}).get("bit_rate") or 0))
    return info


# ───────────────────────────── job / state ─────────────────────────────

class Cancelled(Exception):
    pass


class Job:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self, kind=None):
        self.kind, self.running, self.stage, self.progress = kind, False, "", 0.0
        self.message, self.error, self.done, self.cancel, self.result = "", None, False, False, None

    def set(self, stage=None, progress=None, message=None):
        with self.lock:
            if stage is not None:
                self.stage = stage
            if progress is not None:
                self.progress = max(0.0, min(1.0, progress))
            if message is not None:
                self.message = message

    def snapshot(self):
        with self.lock:
            return {"kind": self.kind, "running": self.running, "stage": self.stage,
                    "progress": round(self.progress, 4), "message": self.message,
                    "error": self.error, "done": self.done, "result": self.result}


JOB = Job()
STATE_LOCK = threading.RLock()
STATE = {
    "sources": [],      # [{path,name,duration,fps,width,height,has_audio, analyzed, shots, rejected, graph}]
    "settings": dict(DEFAULT_SETTINGS),
    "output": "",
}
FEATURES = {}           # path -> dict ของ numpy arrays (ไม่ส่งไปหน้าเว็บ)


def out_dir() -> Path:
    o = STATE.get("output") or ""
    if not o:
        base = Path(STATE["sources"][0]["path"]).parent if STATE["sources"] else Path.home()
        o = str(base / "GameCut_Highlights")
        STATE["output"] = o
    p = Path(o).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_dir() -> Path:
    p = out_dir() / ".gamecut_cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ───────────────────────────── 1) วิเคราะห์ฟุตเทจ ─────────────────────────────

def _read_audio(path: str, out: dict):
    """ความดังเสียงเกม (dB) ทุก 0.2 วิ"""
    try:
        proc = subprocess.Popen([ffmpeg_bin, "-v", "error", "-nostdin", "-i", path, "-vn", "-map", "0:a:0",
                                 "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        hop = 8000 // FPS_F
        vals, buf = [], b""
        while True:
            chunk = proc.stdout.read(1 << 16)
            if not chunk:
                break
            buf += chunk
            n = len(buf) // (hop * 2)
            if n:
                a = np.frombuffer(buf[: n * hop * 2], dtype=np.int16).astype(np.float32).reshape(n, hop) / 32768.0
                vals.append(20 * np.log10(np.sqrt((a * a).mean(axis=1)) + 1e-5))
                buf = buf[n * hop * 2:]
            if JOB.cancel:
                proc.kill()
                return
        proc.wait()
        out["audio"] = np.concatenate(vals) if vals else np.zeros(0, np.float32)
    except Exception as ex:  # noqa
        log("audio read failed:", ex)


def feature_cache(src: dict) -> Path:
    return cache_dir() / f"an_{file_key(src['path'], ANALYSIS_VER)}.npz"


def analyze_file(src: dict, report) -> dict:
    """สแกนไฟล์รอบเดียว → ความเคลื่อนไหว ความสว่าง สี รายละเอียดภาพ จุดตัดฉาก ความดังเสียง (ทุก 0.2 วิ)"""
    path, dur = src["path"], src["duration"]
    cf = feature_cache(src)
    if cf.exists():
        try:
            z = np.load(cf)
            return {k: z[k] for k in z.files}
        except Exception:  # noqa
            pass
    audio = {}
    at = None
    if src.get("has_audio"):
        at = threading.Thread(target=_read_audio, args=(path, audio), daemon=True)
        at.start()
    cmd = [ffmpeg_bin, "-v", "error", "-nostdin"]
    if IS_MAC:
        cmd += ["-hwaccel", "videotoolbox"]
    cmd += ["-i", path, "-map", "0:v:0", "-an", "-sn", "-dn",
            "-vf", f"fps={FPS_F},scale={AN_W}:{AN_H}:flags=area,format=rgb24", "-f", "rawvideo", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    fsz = AN_W * AN_H * 3
    per = 250
    motion, bright, sat, detail, hdiff = [], [], [], [], []
    prev_g, prev_h = None, None
    wts = np.array([0.299, 0.587, 0.114], np.float32)
    count = 0
    try:
        while True:
            raw = proc.stdout.read(fsz * per)
            if not raw:
                break
            n = len(raw) // fsz
            if n == 0:
                break
            rgb = np.frombuffer(raw[: n * fsz], dtype=np.uint8).reshape(n, AN_H, AN_W, 3).astype(np.float32) / 255.0
            g = rgb @ wts                                            # (n,H,W)
            mx, mn = rgb.max(axis=3), rgb.min(axis=3)
            sat.append(((mx - mn) / (mx + 1e-3)).mean(axis=(1, 2)))
            bright.append(g.mean(axis=(1, 2)))
            detail.append(np.abs(np.diff(g, axis=2)).mean(axis=(1, 2)) + np.abs(np.diff(g, axis=1)).mean(axis=(1, 2)))
            seq = np.concatenate([prev_g[None], g]) if prev_g is not None else np.concatenate([g[:1], g])
            motion.append(np.abs(np.diff(seq, axis=0)).mean(axis=(1, 2)))
            idx = np.minimum((g * 16).astype(np.int32), 15).reshape(n, -1)
            h = np.stack([np.bincount(r, minlength=16) for r in idx]).astype(np.float32) / (AN_W * AN_H)
            hseq = np.concatenate([prev_h[None], h]) if prev_h is not None else np.concatenate([h[:1], h])
            hdiff.append(0.5 * np.abs(np.diff(hseq, axis=0)).sum(axis=1))
            prev_g, prev_h = g[-1], h[-1]
            count += n
            if dur > 0:
                report(min(1.0, count / FPS_F / dur))
            if JOB.cancel:
                proc.kill()
                raise Cancelled()
    finally:
        proc.wait()
    if count == 0:
        raise RuntimeError(f"อ่านวิดีโอไม่ได้: {src['name']}")
    if at:
        at.join()
    feat = {k: np.concatenate(v).astype(np.float32) for k, v in
            (("motion", motion), ("bright", bright), ("sat", sat), ("detail", detail), ("hdiff", hdiff))}
    n = len(feat["motion"])
    a = audio.get("audio")
    if a is None or len(a) == 0:
        feat["audio"] = np.full(n, -90.0, np.float32)
        feat["has_audio"] = np.array([0])
    else:
        a = a[:n] if len(a) >= n else np.concatenate([a, np.full(n - len(a), a[-1])])
        feat["audio"] = a.astype(np.float32)
        feat["has_audio"] = np.array([1])
    feat["cut"] = ((feat["hdiff"] > 0.45) & (feat["motion"] > 0.06)).astype(np.uint8)
    np.savez_compressed(cf, **feat)
    return feat


def _movavg(x: np.ndarray, k: int) -> np.ndarray:
    if k <= 1 or len(x) == 0:
        return x.astype(np.float32)
    c = np.cumsum(np.concatenate([[0.0], x.astype(np.float64)]))
    n = len(x)
    lo = np.clip(np.arange(n) - k // 2, 0, n)
    hi = np.clip(np.arange(n) + (k - k // 2), 0, n)
    return ((c[hi] - c[lo]) / np.maximum(hi - lo, 1)).astype(np.float32)


def _rz(x: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """robust z-score (ใช้ค่ากลาง/MAD ของช่วงที่ใช้ได้ — ไม่โดนจอดำ/เมนูดึงค่า)"""
    v = x[valid] if valid.any() else x
    med = float(np.median(v))
    mad = float(np.median(np.abs(v - med))) * 1.4826 + 1e-6
    return np.clip((x - med) / mad, -3, 4).astype(np.float32)


def score_file(src: dict, feat: dict) -> dict:
    """คะแนนความมันส์ทุก 0.2 วิ + ช่วงที่ใช้ไม่ได้ (จอดำ ภาพค้าง ต้น/ท้ายไฟล์ที่ข้าม)"""
    S = STATE["settings"]
    m, b, a = feat["motion"], feat["bright"], feat["audio"]
    n = len(m)
    ms = _movavg(m, FPS_F)
    # จอโหลด = มืด "และ" แทบไม่ขยับ (ฉากกลางคืน/ถ้ำ/เกมผีที่มืดแต่มีการเคลื่อนไหว จะไม่ถูกตัดทิ้ง)
    black = (b < 0.05) & (ms < 0.006)
    # ภาพค้างจริง (pause / หน้าจอนิ่งสนิท) ต่อเนื่อง ~3 วิ — ฉากที่ขยับช้าๆ (เดินในเกมสยองขวัญ) ไม่นับ
    still = m < 0.0007
    frozen = _movavg(still.astype(np.float32), 3 * FPS_F) > 0.95
    bad = black | frozen
    t = np.arange(n) / FPS_F
    bad |= t < float(S["skip_head"])
    bad |= t > (src["duration"] - float(S["skip_tail"]))
    ok = ~bad
    mz = _rz(np.log(ms + 1e-4), ok)
    dz = _rz(feat["detail"], ok)
    sz = _rz(feat["sat"], ok)
    audio_ok = bool(int(feat["has_audio"][0])) and ok.any() and float(np.std(a[ok])) > 0.5
    if audio_ok:
        as_ = _movavg(a, FPS_F)
        az = _rz(as_, ok)
        pz = _rz(as_ - _movavg(as_, 20 * FPS_F), ok)                  # ดังขึ้นกะทันหันเทียบกับรอบๆ
        score = 0.42 * mz + 0.28 * az + 0.18 * pz + 0.06 * sz + 0.06 * dz
    else:
        score = 0.72 * mz + 0.16 * dz + 0.12 * sz
    score = np.where(bad, -6.0, score).astype(np.float32)
    return {"score": score, "bad": bad, "cut": feat["cut"].astype(bool), "n": n, "audio": audio_ok}


# ───────────────────────────── 2) คัดช็อต ─────────────────────────────

MIN_GAP = 2.0   # ช็อตห่างกันอย่างน้อย (วินาที) — กันได้ช็อตต่อเนื่องที่แทบเหมือนกัน


def _spread(src: dict):
    """การกระจายช็อตแบบ "หักคะแนน" ไม่ใช่ห้าม: ยิ่งใกล้ช็อตที่เลือกไปแล้ว คะแนนยิ่งลด
    → ฉากต่อสู้ยาวๆ ที่มันส์มากยังได้หลายช็อต แต่ฉากธรรมดาจะไม่ถูกเลือกซ้ำๆ ที่เดิม"""
    S = STATE["settings"]
    T = max(5.0, float(S["target_len"]))
    avg = (float(S["shot_min"]) + float(S["shot_max"])) / 2
    nshots = max(1.0, T / avg)
    w, k = {"low": (0.35, 6.0), "mid": (1.0, 3.0), "high": (2.2, 1.5)}.get(S["spread"], (1.0, 3.0))
    radius = max(4.0, src["duration"] / (nshots * k))
    return w, radius


def pick_shots(src: dict, sc: dict, keep: list = None, need: float = None, max_new: int = None) -> list:
    """เลือกช่วงที่มันส์ที่สุดทีละช็อต → ขยายช็อตตามความมันส์ต่อเนื่อง → เว้นระยะให้กระจายทั่วไฟล์"""
    S = STATE["settings"]
    score, bad, cut, n = sc["score"], sc["bad"], sc["cut"], sc["n"]
    a = max(2, int(round(float(S["shot_min"]) * FPS_F)))
    bmax = max(a, int(round(float(S["shot_max"]) * FPS_F)))
    keep = list(keep or [])
    T = float(S["target_len"]) if need is None else need + sum(x["end"] - x["start"] for x in keep)
    if n < a + 1:
        return keep
    smooth = _movavg(score, FPS_F)
    # คะแนนเฉลี่ยของทุกหน้าต่างยาว a เฟรม (หักคะแนนถ้ามีจุดตัดฉากอยู่กลางช็อต)
    c = np.cumsum(np.concatenate([[0.0], score.astype(np.float64)]))
    cc = np.cumsum(np.concatenate([[0], cut.astype(np.int64)]))
    win = (c[a:] - c[:-a]) / a                                   # index i = ช่วง [i, i+a)
    inner = cc[a:] - cc[:-a] - cut[: n - a + 1].astype(np.int64)  # จุดตัดที่อยู่ใน (i, i+a)
    win = win - 1.5 * inner
    blocked_base = bad.copy()
    for r in src.get("rejected", []):
        blocked_base[int(r[0] * FPS_F): int(math.ceil(r[1] * FPS_F))] = True
    w_pen, radius = _spread(src)
    centers = np.arange(len(win)) + a / 2.0
    rf = radius * FPS_F
    pen = np.zeros(len(win), np.float32)

    def add_penalty(x):
        c0 = (x["start"] + x["end"]) / 2 * FPS_F
        pen[:] += (w_pen * np.exp(-((centers - c0) / rf) ** 2)).astype(np.float32)

    picks = list(keep)
    for x in picks:
        add_penalty(x)
    added = 0
    total = sum(x["end"] - x["start"] for x in picks)
    gap = MIN_GAP
    while total < T - 0.3 and (max_new is None or added < max_new):
        blocked = blocked_base.copy()
        gf = int(gap * FPS_F)
        for x in picks:
            blocked[max(0, int(x["start"] * FPS_F) - gf): int(math.ceil(x["end"] * FPS_F)) + gf] = True
        cb = np.cumsum(np.concatenate([[0], blocked.astype(np.int64)]))
        free = (cb[a:] - cb[:-a]) == 0
        raw = np.where(free, win, -np.inf)
        cand = raw - pen
        i = int(np.argmax(cand))
        floor = -2.5 if S.get("fill") else -0.3          # -0.3 ≈ ธรรมดากว่าค่าเฉลี่ยของไฟล์ → ไม่เอา
        if not np.isfinite(cand[i]) or raw[i] < floor:
            if gap > 0.4:
                gap = 0.4                         # ที่ว่างหมดแล้ว → ยอมให้ช็อตชิดกันขึ้น
                continue
            break
        L, R = i, i + a
        thr = float(win[i]) - 1.0
        room = T - total
        while (R - L) < bmax and (R - L) / FPS_F < room:
            left = smooth[L - 1] if L > 0 and not blocked[L - 1] and not cut[L] else -np.inf
            right = smooth[R] if R < n and not blocked[R] and not cut[R] else -np.inf
            if max(left, right) < thr:
                break
            if right >= left:
                R += 1
            else:
                L -= 1
        peak = L + int(np.argmax(smooth[L:R]))
        st, en = L / FPS_F, min(R / FPS_F, src["duration"] - 0.05)
        shot = {"start": round(st, 2), "end": round(en, 2), "peak": round(peak / FPS_F, 2),
                "score": round(float(score[L:R].mean()), 3)}
        picks.append(shot)
        add_penalty(shot)
        total += en - st
        added += 1
    return picks


def order_shots(shots: list) -> list:
    if STATE["settings"]["order"] == "score":
        return sorted(shots, key=lambda x: -x["score"])
    return sorted(shots, key=lambda x: x["start"])


def finalize(src: dict):
    for k, x in enumerate(src["shots"]):
        x["id"] = k
        x["thumb"] = f"{file_key(src['path'])}_{x['peak']:.1f}.jpg"
    src["total"] = round(sum(x["end"] - x["start"] for x in src["shots"]), 1)


def graph_data(sc: dict, points: int = 600) -> dict:
    s, bad = sc["score"], sc["bad"]
    n = len(s)
    k = max(1, int(math.ceil(n / points)))
    m = (n + k - 1) // k
    pad = m * k - n
    sp = np.concatenate([_movavg(s, FPS_F), np.full(pad, -6.0)]).reshape(m, k).max(axis=1)
    bp = np.concatenate([bad, np.ones(pad, bool)]).reshape(m, k).mean(axis=1) > 0.6
    good = sp[~bp] if (~bp).any() else sp
    lo, hi = float(np.percentile(good, 5)), float(np.percentile(good, 99.5)) + 1e-6
    val = np.clip((sp - lo) / (hi - lo), 0, 1)
    val[bp] = 0
    return {"v": [round(float(x), 3) for x in val], "bad": [int(x) for x in bp], "step": k / FPS_F}


def repick(src: dict):
    feat = FEATURES.get(src["path"])
    if feat is None:
        return
    sc = score_file(src, feat)
    src["shots"] = order_shots(pick_shots(src, sc))
    finalize(src)
    src["graph"] = graph_data(sc)
    src["audio_used"] = sc["audio"]
    src["bad_pct"] = round(float(sc["bad"].mean()) * 100)


def make_thumb(src: dict, t: float, name: str):
    d = cache_dir() / "thumbs"
    d.mkdir(exist_ok=True)
    dst = d / name
    if not dst.exists():
        run([ffmpeg_bin, "-v", "error", "-nostdin", "-y", "-ss", f"{t:.2f}", "-i", src["path"],
             "-frames:v", "1", "-vf", "scale=360:-2", "-q:v", "5", str(dst)])
    return dst


def thumbs_for(src: dict):
    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(lambda x: make_thumb(src, x["peak"], x["thumb"]), src["shots"]))


def ensure_features(src: dict):
    if src["path"] not in FEATURES:
        cf = feature_cache(src)
        if cf.exists():
            try:
                z = np.load(cf)
                FEATURES[src["path"]] = {k: z[k] for k in z.files}
            except Exception:  # noqa
                return None
    return FEATURES.get(src["path"])


def do_analyze():
    srcs = STATE["sources"]
    if not srcs:
        raise RuntimeError("ยังไม่ได้เลือกฟุตเทจ")
    total = sum(s["duration"] for s in srcs) or 1
    done = 0.0
    for i, src in enumerate(srcs):
        JOB.set(stage=f"สแกนหาช็อตเด็ด ({i + 1}/{len(srcs)})", message=src["name"])

        def rep(f, base=done, d=src["duration"]):
            JOB.set(progress=0.9 * (base + f * d) / total)

        t0 = time.time()
        FEATURES[src["path"]] = analyze_file(src, rep)
        log(f"analyzed {src['name']} ({fmt_tc(src['duration'])}) in {time.time() - t0:.1f}s")
        src["analyzed"] = True
        src["rejected"] = []
        repick(src)
        done += src["duration"]
    JOB.set(stage="สร้างภาพตัวอย่าง", progress=0.93, message="")
    for s in srcs:
        thumbs_for(s)
    return {"files": len(srcs), "shots": sum(len(s["shots"]) for s in srcs)}


# ───────────────────────────── 3) ทำให้ภาพชัด + รูปแบบภาพ ─────────────────────────────

_FILTERS = None


def has_filter(name: str) -> bool:
    global _FILTERS
    if _FILTERS is None:
        r = run([ffmpeg_bin, "-hide_banner", "-filters"])
        _FILTERS = set(re.findall(r"^\s*[TSC.]{3}\s+(\w+)", r.stdout, re.M))
    return name in _FILTERS


def reframe_vf(sw, sh, W, H, mode, pos, zoom):
    if (sw, sh) == (W, H):
        return None
    if abs(sw / sh - W / H) <= 0.01:
        return f"scale={W}:{H}:flags=lanczos"
    pos = min(1.0, max(0.0, float(pos)))
    if mode == "fit":
        return (f"scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black")
    if mode == "blur":
        s = min(W / sw, H / sh) * max(1.0, float(zoom))
        fw, fh = ev(sw * s), ev(sh * s)
        bw, bh = ev(W / 6), ev(H / 6)
        return (f"split=2[bg][fg];[bg]scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},"
                f"boxblur=6:2,scale={W}:{H},eq=brightness=-0.08[bgb];[fg]scale={fw}:{fh}:flags=lanczos[fgs];"
                f"[bgb][fgs]overlay=x=({W}-w)*{pos:.4f}:y=({H}-h)/2")
    return (f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={W}:{H}:(iw-{W})*{pos:.4f}:(ih-{H})*{pos:.4f}")


def out_size(src: dict) -> tuple:
    S = STATE["settings"]
    if S["frame"] in FRAMES:
        return FRAMES[S["frame"]]
    w, h = src.get("width", 1920), src.get("height", 1080)
    up = S.get("upscale", "none")
    if up != "none":
        H = int(up)
        if h < H * 0.98:                       # ขยายเฉพาะไฟล์ที่เล็กกว่าเป้าหมาย
            return max(8, int(round(w * H / h / 8)) * 8), H   # 854×480 → 1920×1080 พอดี
    return ev(w), ev(h)


# pp = ลบรอยบล็อกจากการบีบอัด (ฟุตเทจบิตเรตต่ำ / โหลดจากเว็บ) — ได้ผลมากที่สุดกับไฟล์คุณภาพต่ำ
ENH = {
    "light":  {"pp": None, "dn": "hqdn3d=1.5:1.5:4:4", "cas": 0.35, "us": "5:5:0.6", "eq": None, "deband": False},
    "medium": {"pp": ("fspp=quality=4:qp=10", "deblock=filter=strong:block=8"),
               "dn": "hqdn3d=2.5:2:5:4", "cas": 0.55, "us": "5:5:0.9",
               "eq": "eq=contrast=1.03:saturation=1.08", "deband": False},
    "strong": {"pp": ("fspp=quality=5:qp=14", "deblock=filter=strong:block=8:alpha=0.15:beta=0.1"),
               "dn": "hqdn3d=3.5:3:7:6", "cas": 0.75, "us": "5:5:1.2",
               "eq": "eq=contrast=1.05:saturation=1.12", "deband": True},
}


def video_filter(src: dict, crop_pos=None) -> str:
    """ลด noise/แถบสี → ขยาย/จัดเฟรม → เพิ่มความคม → สี"""
    S = STATE["settings"]
    e = ENH.get(S["enhance"])
    W, H = out_size(src)
    sw, sh = src.get("width", W), src.get("height", H)
    parts = []
    if e:
        if e["pp"]:
            pp = e["pp"][0] if has_filter("fspp") else (e["pp"][1] if has_filter("deblock") else None)
            if pp:
                parts.append(pp)
        parts.append(e["dn"])
        if e["deband"] and has_filter("deband"):
            parts.append("deband=1thr=0.012:2thr=0.012:3thr=0.012:4thr=0.012:blur=1")
    rf = reframe_vf(sw, sh, W, H, S["reframe"], S["crop_pos"] if crop_pos is None else crop_pos, S["blur_zoom"])
    if rf:
        parts.append(rf)
    if e:
        parts.append(f"cas=strength={e['cas']}" if has_filter("cas") else f"unsharp={e['us']}")
        if e["eq"]:
            parts.append(e["eq"])
    parts.append("setsar=1")
    return ",".join(parts)


# ───────────────────────────── 4) ส่งออก ─────────────────────────────

_ENCODER = None
X264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p"]


def h264_args(W: int, H: int, fps: float):
    """ตัวเข้ารหัส H.264 ที่เร็วที่สุดของเครื่อง (การ์ดจอ) — ทดสอบครั้งเดียว"""
    global _ENCODER
    if _ENCODER is None:
        cands = ["h264_videotoolbox"] if IS_MAC else (["h264_nvenc", "h264_qsv", "h264_amf"] if IS_WIN else [])
        _ENCODER = "libx264"
        for c in cands:
            r = run([ffmpeg_bin, "-v", "error", "-nostdin", "-f", "lavfi", "-i", "color=c=gray:s=640x360:r=30:d=0.2",
                     "-c:v", c, "-f", "null", "-"])
            if r.returncode == 0:
                _ENCODER = c
                break
        log("video encoder:", _ENCODER)
    mbps = max(10, int(32 * (W * H) / (1920 * 1080) * math.sqrt(min(fps, 120) / 60)))
    enc = _ENCODER
    if enc == "h264_videotoolbox":
        return ["-c:v", enc, "-b:v", f"{mbps}M", "-maxrate", f"{int(mbps * 1.5)}M", "-bufsize", f"{mbps * 2}M",
                "-pix_fmt", "yuv420p", "-allow_sw", "1", "-profile:v", "high"]
    if enc == "h264_nvenc":
        return ["-c:v", enc, "-preset", "p5", "-rc", "vbr", "-cq", "18", "-b:v", f"{mbps}M",
                "-maxrate", f"{int(mbps * 1.5)}M", "-pix_fmt", "yuv420p"]
    if enc == "h264_qsv":
        return ["-c:v", enc, "-global_quality", "19", "-pix_fmt", "nv12"]
    if enc == "h264_amf":
        return ["-c:v", enc, "-quality", "quality", "-rc", "cqp", "-qp_i", "17", "-qp_p", "19", "-pix_fmt", "yuv420p"]
    return list(X264)


def video_args(W, H, fps):
    if STATE["settings"]["codec"] == "prores":
        return ["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le", "-vendor", "apl0"]
    return h264_args(W, H, fps)


def ext() -> str:
    return ".mov" if STATE["settings"]["codec"] == "prores" else ".mp4"


def render_shot(src: dict, shot: dict, dst: Path):
    S = STATE["settings"]
    L = shot["end"] - shot["start"]
    W, H = out_size(src)
    vf = video_filter(src, shot.get("crop_pos"))
    if S["audio"] and src.get("has_audio"):
        aud = ["-map", "0:a:0", "-af", f"afade=t=in:d=0.04,afade=t=out:st={max(0, L - 0.06):.3f}:d=0.06",
               "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-ac", "2"]
    else:
        aud = ["-an"]

    def cmd(venc):
        return [ffmpeg_bin, "-v", "error", "-nostdin", "-y", "-ss", f"{shot['start']:.3f}", "-i", src["path"],
                "-t", f"{L:.3f}", "-map", "0:v:0", "-vf", vf, *venc, *aud, "-movflags", "+faststart", str(dst)]
    va = video_args(W, H, src.get("fps", 60))
    r = run(cmd(va))
    if r.returncode != 0 and va[1] not in ("libx264", "prores_ks"):
        r = run(cmd(X264))
    if r.returncode != 0:
        raise RuntimeError(f"ตัดช็อตไม่สำเร็จ: {dst.name}\n{r.stderr[-400:]}")


def concat_copy(files: list, dst: Path):
    lst = dst.with_suffix(".concat.txt")
    lst.write_text("".join("file '" + str(Path(f).resolve()).replace("'", "'\\''") + "'\n" for f in files),
                   encoding="utf-8")
    r = run([ffmpeg_bin, "-v", "error", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
             "-c", "copy", "-movflags", "+faststart", str(dst)])
    lst.unlink(missing_ok=True)
    if r.returncode != 0:
        raise RuntimeError("รวมคลิปไม่สำเร็จ\n" + r.stderr[-400:])


def concat_reencode(files: list, dst: Path, W: int, H: int, fps: float, audio: bool):
    cmd = [ffmpeg_bin, "-v", "error", "-nostdin", "-y"]
    for f in files:
        cmd += ["-i", str(f)]
    flt = ""
    for i in range(len(files)):
        flt += (f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}[v{i}];")
        if audio:
            flt += f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}];"
    flt += "".join(f"[v{i}]" + (f"[a{i}]" if audio else "") for i in range(len(files)))
    flt += f"concat=n={len(files)}:v=1:a={1 if audio else 0}[v]" + ("[a]" if audio else "")
    out = ["-map", "[v]"] + (["-map", "[a]", "-c:a", "aac", "-b:a", "256k"] if audio else ["-an"])
    va = video_args(W, H, fps)
    # ใส่ filter ตรงๆ (ffmpeg 8 เลิกใช้ -filter_complex_script แล้ว)
    base = cmd + ["-filter_complex", flt, *out]
    r = run(base + [*va, "-movflags", "+faststart", str(dst)])
    if r.returncode != 0 and va[1] not in ("libx264", "prores_ks"):
        r = run(base + [*X264, "-movflags", "+faststart", str(dst)])
    if r.returncode != 0:
        raise RuntimeError("รวมไฮไลต์ทุกไฟล์ไม่สำเร็จ\n" + r.stderr[-400:])


def do_export(opts: dict):
    S = STATE["settings"]
    srcs = [s for s in STATE["sources"] if s.get("shots")]
    if not srcs:
        raise RuntimeError("ยังไม่มีช็อต — กดวิเคราะห์ก่อน")
    stamp = time.strftime("%Y%m%d-%H%M")
    tag = {"1080x1920": "_reel", "1080x1080": "_square"}.get(S["frame"], "")
    base = out_dir() / f"Highlights{tag}_{stamp}"
    k = 2
    while base.exists():
        base = out_dir() / f"Highlights{tag}_{stamp}_{k}"
        k += 1
    base.mkdir(parents=True)
    E = ext()
    jobs, per_file = [], []
    for fi, src in enumerate(STATE["sources"]):
        if not src.get("shots"):
            continue
        d = base / f"{fi + 1:02d}_{slug(Path(src['name']).stem, 30)}"
        sd = d / "shots"
        sd.mkdir(parents=True, exist_ok=True)
        files = []
        for k, x in enumerate(src["shots"]):
            f = sd / f"{k + 1:02d}_{tc_name(x['start'])}_{x['end'] - x['start']:.1f}s{E}"
            jobs.append((src, x, f))
            files.append(f)
        per_file.append((src, d, files))
    done = [0]
    lock = threading.Lock()

    def work(j):
        if JOB.cancel:
            return
        render_shot(*j)
        with lock:
            done[0] += 1
            JOB.set(stage=f"ตัดช็อต {done[0]}/{len(jobs)}" + ("  ✨ ทำให้ภาพชัด" if S["enhance"] != "off" else ""),
                    progress=0.85 * done[0] / len(jobs))

    with ThreadPoolExecutor(max_workers=3 if (IS_MAC or IS_WIN) else 2) as ex:
        list(ex.map(work, jobs))
    if JOB.cancel:
        raise Cancelled()

    highlights = []
    multi = S["combine"] and len(per_file) > 1
    JOB.set(stage="รวมเป็นคลิปไฮไลต์", progress=0.88)
    for src, d, files in per_file:
        if S["export_reel"] or multi:
            h = d / f"{slug(Path(src['name']).stem, 30)}_highlight{E}"
            concat_copy(files, h)
            highlights.append(h)
        with open(d / "shots.csv", "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["#", "file", "start", "end", "length_s", "score"])
            for k, x in enumerate(src["shots"]):
                w.writerow([k + 1, src["name"], fmt_tc(x["start"]), fmt_tc(x["end"]),
                            round(x["end"] - x["start"], 2), x["score"]])
    combined = None
    if multi:
        JOB.set(stage="รวมไฮไลต์ทุกไฟล์เป็นคลิปเดียว", progress=0.92)
        sizes = {out_size(src) for src, _, _ in per_file}
        fpss = [src.get("fps", 60) for src, _, _ in per_file]
        audio = bool(S["audio"]) and all(src.get("has_audio") for src, _, _ in per_file)
        combined = base / f"ALL_highlights{E}"
        if len(sizes) == 1 and len(set(fpss)) == 1 and audio == bool(S["audio"]):
            concat_copy(highlights, combined)
        else:
            W, H = max(sizes, key=lambda s: s[0] * s[1])
            concat_reencode(highlights, combined, W, H, min(60.0, max(set(fpss), key=fpss.count)), audio)
    if not S["export_shots"]:
        for _, d, files in per_file:
            for f in files:
                f.unlink(missing_ok=True)
            try:
                (d / "shots").rmdir()
            except OSError:
                pass
    if not S["export_reel"]:
        for h in highlights:
            h.unlink(missing_ok=True)
    total = sum(s.get("total", 0) for s in srcs)
    return {"folder": str(base), "shots": len(jobs), "files": len(per_file), "total": round(total, 1),
            "combined": str(combined) if combined else None}


def compare_image(src: dict, t: float) -> Path:
    """ภาพเทียบ ก่อน | หลัง (ครึ่งซ้าย = ต้นฉบับ, ครึ่งขวา = หลังทำให้ชัด) ที่ขนาดส่งออกจริง"""
    W, H = out_size(src)
    vf = video_filter(src)
    key = hashlib.sha1(f"{src['path']}|{t:.2f}|{vf}".encode()).hexdigest()[:16]
    d = cache_dir() / "compare"
    d.mkdir(exist_ok=True)
    dst = d / f"{key}.jpg"
    if not dst.exists():
        # ตัดบริเวณเดียวกันตรงกลางภาพจากทั้งสองแบบ ที่ขนาดส่งออกจริง (ซูม 100%) แล้ววางคู่กัน: ก่อน | หลัง
        cw = ev(min(W / 2, 800))
        ch = ev(min(H, cw * 9 / 8 if W >= H else cw * 16 / 9))
        cx, cy = ev((W - cw) / 2), ev((H - ch) / 2)
        rf = reframe_vf(src.get("width", W), src.get("height", H), W, H, STATE["settings"]["reframe"],
                        STATE["settings"]["crop_pos"], STATE["settings"]["blur_zoom"])
        # ต้นฉบับ: ขยายแบบธรรมดา (bicubic) ไม่มีการปรับใดๆ — ให้เห็นความต่างจริง
        before = (rf.replace("flags=lanczos", "flags=bicubic") + ",") if rf else ""
        flt = (f"[0:v]split=2[o][e];[o]{before}crop={cw}:{ch}:{cx}:{cy}[l];"
               f"[e]{vf},crop={cw}:{ch}:{cx}:{cy}[r];"
               f"[l][r]hstack=2,drawbox=x={cw - 2}:y=0:w=4:h={ch}:color=white@0.9:t=fill")
        r = run([ffmpeg_bin, "-v", "error", "-nostdin", "-y", "-ss", f"{t:.2f}", "-i", src["path"],
                 "-frames:v", "1", "-filter_complex", flt, "-q:v", "2", str(dst)])
        if r.returncode != 0:
            raise RuntimeError(r.stderr[-300:])
    return dst


def run_job(kind, fn, *args):
    if JOB.running:
        return False
    JOB.reset(kind)
    JOB.running = True

    def target():
        try:
            res = fn(*args)
            with JOB.lock:
                JOB.result, JOB.done, JOB.progress, JOB.stage = res, True, 1.0, "เสร็จแล้ว"
        except Cancelled:
            with JOB.lock:
                JOB.error = "ยกเลิกแล้ว"
        except Exception as ex:  # noqa
            traceback.print_exc()
            with JOB.lock:
                JOB.error = str(ex)
        finally:
            with JOB.lock:
                JOB.running = False

    threading.Thread(target=target, daemon=True).start()
    return True


# ───────────────────────────── file pickers ─────────────────────────────

def osa(script: str):
    r = run(["osascript", "-e", script])
    if r.returncode != 0:
        return None, "cancel" if "-128" in r.stderr else r.stderr.strip()
    return [l for l in r.stdout.splitlines() if l.strip()], None


VIDEO_FILTER = "Video|" + ";".join("*" + e for e in sorted(VIDEO_EXT))


def win_dialog(kind: str, title: str, filt: str = "", multi: bool = False):
    title = title.replace("'", "''")
    head = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;Add-Type -AssemblyName System.Windows.Forms;"
            "$o=New-Object System.Windows.Forms.Form -Property @{TopMost=$true;ShowInTaskbar=$false};")
    if kind == "folder":
        body = (f"$d=New-Object System.Windows.Forms.FolderBrowserDialog;$d.Description='{title}';"
                "$d.ShowNewFolderButton=$true;if($d.ShowDialog($o) -eq 'OK'){$d.SelectedPath}")
    else:
        body = (f"$d=New-Object System.Windows.Forms.OpenFileDialog;$d.Title='{title}';"
                f"$d.Filter='{filt}|All files|*.*';$d.Multiselect=${'true' if multi else 'false'};"
                "if($d.ShowDialog($o) -eq 'OK'){$d.FileNames -join \"`n\"}")
    r = run(["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command", head + body])
    lines = [l.strip() for l in (r.stdout or "").splitlines() if l.strip()]
    if r.returncode != 0 and not lines:
        return None, (r.stderr or "เปิดหน้าต่างเลือกไฟล์ไม่ได้").strip()[-300:]
    return (lines, None) if lines else (None, "cancel")


def pick(kind: str):
    if IS_WIN:
        table = {"footage_folder": ("folder", "เลือกโฟลเดอร์ฟุตเทจเกม", "", False),
                 "footage_files": ("file", "เลือกไฟล์ฟุตเทจ (เลือกได้หลายไฟล์)", VIDEO_FILTER, True),
                 "output": ("folder", "เลือกโฟลเดอร์สำหรับเก็บผลลัพธ์", "", False)}
        return win_dialog(*table[kind]) if kind in table else (None, "unknown")
    if not IS_MAC:
        return None, "เลือกไฟล์ผ่านหน้าต่างไม่ได้บนเครื่องนี้ — พิมพ์/วาง path แทน"
    if kind == "footage_folder":
        return osa('POSIX path of (choose folder with prompt "เลือกโฟลเดอร์ฟุตเทจเกม")')
    if kind == "footage_files":
        return osa('set fs to choose file with prompt "เลือกไฟล์ฟุตเทจ (เลือกได้หลายไฟล์)" with multiple selections allowed\n'
                   'set out to ""\nrepeat with f in fs\nset out to out & POSIX path of f & linefeed\nend repeat\nreturn out')
    if kind == "output":
        return osa('POSIX path of (choose folder with prompt "เลือกโฟลเดอร์สำหรับเก็บผลลัพธ์")')
    return None, "unknown"


def expand_footage(paths: list) -> list:
    out = []
    for p in paths:
        p = os.path.expanduser(str(p).strip().strip("'\""))
        if not p:
            continue
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs[:] = [x for x in dirs if not x.startswith(".") and not x.startswith("GameCut_")
                           and not x.startswith("Highlights")]
                for f in files:
                    if Path(f).suffix.lower() in VIDEO_EXT and not f.startswith("."):
                        out.append(os.path.join(root, f))
        elif os.path.isfile(p) and Path(p).suffix.lower() in VIDEO_EXT:
            out.append(p)
    res = list(dict.fromkeys(out))
    return sorted(res, key=lambda x: (str(Path(x).parent), natural_key(Path(x).name)))


# ───────────────────────────── HTTP server ─────────────────────────────

def public_state():
    with STATE_LOCK:
        return {"version": VERSION, "is_mac": IS_MAC, "is_win": IS_WIN, "ffmpeg": bool(shutil.which("ffmpeg")),
                "sources": STATE["sources"], "settings": STATE["settings"], "output": STATE["output"],
                "sizes": [list(out_size(s)) for s in STATE["sources"]], "busy": JOB.running}


def _src(i):
    srcs = STATE["sources"]
    i = int(i)
    if not (0 <= i < len(srcs)):
        raise KeyError("ไม่พบไฟล์")
    return srcs[i]


class Handler(BaseHTTPRequestHandler):
    server_version = "GameCut/" + VERSION

    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _file(self, path: Path, ctype=None):
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        size = path.stat().st_size
        ctype = ctype or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        if rng and (m := re.match(r"bytes=(\d*)-(\d*)", rng)):
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else min(size - 1, start + 8 * 1024 * 1024)
            else:
                start = max(0, size - int(m.group(2)))
            end = min(end, size - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        try:
            with open(path, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1024 * 512, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html"):
                return self._file(APP_DIR / "ui.html", "text/html; charset=utf-8")
            if u.path == "/api/state":
                return self._json(public_state())
            if u.path == "/api/job":
                return self._json(JOB.snapshot())
            if u.path.startswith("/thumb/"):
                name = os.path.basename(urllib.parse.unquote(u.path[7:]))
                return self._file(cache_dir() / "thumbs" / name, "image/jpeg")
            if u.path == "/media":
                with STATE_LOCK:
                    p = _src(q.get("i", ["0"])[0])["path"]
                return self._file(Path(p))
            if u.path == "/compare":
                with STATE_LOCK:
                    src = _src(q.get("i", ["0"])[0])
                    t = float(q.get("t", [str(src["duration"] * 0.3)])[0])
                return self._file(compare_image(src, t), "image/jpeg")
        except KeyError:
            return self.send_error(404)
        except Exception as ex:  # noqa
            traceback.print_exc()
            return self._json({"error": str(ex)}, 500)
        self.send_error(404)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except Exception:  # noqa
            return self._json({"error": "bad json"}, 400)
        try:
            return self.route(u.path, body)
        except KeyError as ex:
            return self._json({"error": str(ex)}, 404)
        except Exception as ex:  # noqa
            traceback.print_exc()
            return self._json({"error": str(ex)}, 500)

    def route(self, path, body):
        if path == "/api/pick":
            res, err = pick(body.get("kind", ""))
            return self._json({"paths": res or [], "error": err})
        if path == "/api/cancel":
            JOB.cancel = True
            return self._json({"ok": True})
        if JOB.running:
            return self._json({"error": "กำลังทำงานอยู่ รอให้เสร็จก่อน"}, 409)

        if path == "/api/sources":
            paths = expand_footage(body.get("paths", []))
            with STATE_LOCK:
                have = {s["path"] for s in STATE["sources"]}
                added = 0
                for p in paths:
                    if p in have:
                        continue
                    info = probe(p)
                    if info.get("has_video") and info["duration"] > 0:
                        info.update(analyzed=False, shots=[], rejected=[], total=0)
                        STATE["sources"].append(info)
                        added += 1
                STATE["sources"].sort(key=lambda s: (str(Path(s["path"]).parent), natural_key(s["name"])))
                out_dir()
                for s in STATE["sources"]:            # ไฟล์ที่เคยวิเคราะห์แล้ว (มีแคช) ใช้ได้ทันที
                    if not s["analyzed"] and ensure_features(s) is not None:
                        s["analyzed"] = True
                        repick(s)
                        thumbs_for(s)
            return self._json({"added": added, "found": len(paths), "state": public_state()})

        if path == "/api/remove_source":
            with STATE_LOCK:
                STATE["sources"].pop(int(body.get("i", -1)))
            return self._json(public_state())

        if path == "/api/config":
            with STATE_LOCK:
                if "output" in body:
                    STATE["output"] = os.path.expanduser(str(body["output"]).strip())
                for k, v in (body.get("settings") or {}).items():
                    if k in DEFAULT_SETTINGS:
                        d = DEFAULT_SETTINGS[k]
                        STATE["settings"][k] = bool(v) if isinstance(d, bool) else (str(v) if isinstance(d, str) else float(v))
                S = STATE["settings"]
                if S["shot_max"] < S["shot_min"]:
                    S["shot_max" if "shot_min" in (body.get("settings") or {}) else "shot_min"] = \
                        S["shot_min"] if "shot_min" in (body.get("settings") or {}) else S["shot_max"]
            return self._json(public_state())

        if path == "/api/analyze":
            return self._json({"started": run_job("analyze", do_analyze)})

        if path == "/api/repick":
            with STATE_LOCK:
                for s in STATE["sources"]:
                    if s.get("analyzed") and ensure_features(s) is not None:
                        if body.get("reset_rejected", True):
                            s["rejected"] = []
                        repick(s)
                        thumbs_for(s)
            return self._json(public_state())

        if path in ("/api/shot/remove", "/api/shot/replace", "/api/shot/len", "/api/shot/add"):
            with STATE_LOCK:
                src = _src(body.get("src", -1))
                feat = ensure_features(src)
                if feat is None:
                    return self._json({"error": "ไฟล์นี้ยังไม่ได้วิเคราะห์"}, 400)
                shots = list(src["shots"])
                if path == "/api/shot/add":
                    t = float(body["t"])
                    S = STATE["settings"]
                    L = (float(S["shot_min"]) + float(S["shot_max"])) / 2
                    st, en = max(0.0, t - L / 2), min(src["duration"] - 0.05, t + L / 2)
                    for x in shots:                    # ไม่ให้ซ้อนกับช็อตเดิม
                        if x["start"] < en and x["end"] > st:
                            if x["start"] <= t <= x["end"]:
                                return self._json({"error": "ตรงนี้มีช็อตอยู่แล้ว"}, 400)
                            if t < x["start"]:
                                en = x["start"]
                            else:
                                st = x["end"]
                    if en - st < 1.0:
                        return self._json({"error": "ช่วงนี้ว่างไม่พอสำหรับช็อตใหม่"}, 400)
                    sc = score_file(src, feat)
                    a = int(st * FPS_F)
                    b = max(a + 1, int(en * FPS_F))
                    shots.append({"start": round(st, 2), "end": round(en, 2), "peak": round(t, 2),
                                  "score": round(float(sc["score"][a:b].mean()), 3), "manual": True})
                else:
                    k = int(body.get("id", -1))
                    if not (0 <= k < len(shots)):
                        return self._json({"error": "ไม่พบช็อต"}, 404)
                    x = shots[k]
                    if path == "/api/shot/len":
                        d = float(body.get("delta", 0))
                        nxt = [y["start"] for y in shots if y is not x and y["start"] >= x["end"] - 1e-6]
                        lim = min(nxt + [src["duration"] - 0.05])
                        x["end"] = round(max(x["start"] + 1.0, min(lim, x["end"] + d)), 2)
                    else:
                        shots.pop(k)
                        src["rejected"].append([x["start"], x["end"]])
                        if path == "/api/shot/replace":
                            sc = score_file(src, feat)
                            shots = pick_shots(src, sc, keep=shots, need=x["end"] - x["start"], max_new=1)
                src["shots"] = order_shots(shots)
                finalize(src)
                thumbs_for(src)
            return self._json(public_state())

        if path == "/api/export":
            return self._json({"started": run_job("export", do_export, body)})

        if path == "/api/open":
            p = body.get("path") or STATE["output"]
            if p and os.path.exists(p):
                if IS_WIN:
                    os.startfile(p)  # type: ignore[attr-defined]
                elif IS_MAC:
                    subprocess.Popen(["open", p])
                elif shutil.which("xdg-open"):
                    subprocess.Popen(["xdg-open", p])
            return self._json({"ok": True})

        if path == "/api/reset_settings":
            with STATE_LOCK:
                STATE["settings"] = dict(DEFAULT_SETTINGS)
            return self._json(public_state())

        return self._json({"error": "not found"}, 404)


def main():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        print("\n❌ ไม่พบ ffmpeg — " + ("ดับเบิลคลิก start.bat เพื่อให้ติดตั้งให้อัตโนมัติ" if IS_WIN
                                    else "ติดตั้งก่อนด้วยคำสั่ง:  brew install ffmpeg") + "\n")
        sys.exit(1)
    port = PORT
    for _ in range(20):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            port += 1
    else:
        print("เปิดเซิร์ฟเวอร์ไม่ได้")
        sys.exit(1)
    url = f"http://localhost:{port}"
    print(f"\n🎮 GameCut {VERSION} — คัดช็อตเด็ด พร้อมใช้งานแล้ว →  {url}")
    print("   (ปิดหน้าต่างนี้ หรือกด Ctrl+C เพื่อปิดแอพ)\n")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nปิดแอพแล้ว")


if __name__ == "__main__":
    main()
