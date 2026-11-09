# -*- coding: utf-8 -*-
"""ตัวติดตั้ง/เปิดแอพ GameCut สำหรับ Windows (start.bat เรียกไฟล์นี้)
- ดาวน์โหลด ffmpeg มาไว้ในโฟลเดอร์แอพให้อัตโนมัติ (ไม่ต้องติดตั้งเอง)
- สร้าง Python environment ของแอพไว้ใน .venv-win (อยู่ในโฟลเดอร์แอพ ย้ายไป SSD ได้)
- ติดตั้งไลบรารีของแอพ (numpy) แล้วเปิดแอพ
"""
import hashlib
import io
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

APP = Path(__file__).resolve().parent
FF_DIR = APP / "ffmpeg" / "bin"
VENV = APP / ".venv-win"
EXE = ".exe" if os.name == "nt" else ""
VPY = VENV / ("Scripts" if os.name == "nt" else "bin") / ("python" + EXE)
REQ = APP / "requirements.txt"
FF_URLS = [
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
]

for s in (sys.stdout, sys.stderr):
    try:
        s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa
        pass


def say(*a):
    print(*a, flush=True)


def fail(msg):
    say("\n❌ " + msg + "\n")
    sys.exit(1)


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "GameCut-setup"})
    with urllib.request.urlopen(req, timeout=60) as r:
        total = int(r.headers.get("Content-Length") or 0)
        buf, got = io.BytesIO(), 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            buf.write(chunk)
            got += len(chunk)
            if total:
                pct = got * 100 // total
                bar = "█" * (pct // 4) + "░" * (25 - pct // 4)
                print(f"\r   {bar} {pct:3d}%  ({got >> 20}/{total >> 20} MB)", end="", flush=True)
        print()
        return buf.getvalue()


def ensure_ffmpeg():
    if (FF_DIR / ("ffmpeg" + EXE)).exists() and (FF_DIR / ("ffprobe" + EXE)).exists():
        return
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return
    say("⏳ ดาวน์โหลด ffmpeg (ประมาณ 90 MB ครั้งเดียว)…")
    last = None
    for url in FF_URLS:
        try:
            data = download(url)
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                FF_DIR.mkdir(parents=True, exist_ok=True)
                n = 0
                for name in z.namelist():
                    base = name.rsplit("/", 1)[-1].lower()
                    if base in ("ffmpeg.exe", "ffprobe.exe") and "/bin/" in name:
                        with z.open(name) as src, open(FF_DIR / base, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        n += 1
                if n == 2:
                    say("✅ ติดตั้ง ffmpeg แล้ว")
                    return
                last = "ไม่พบ ffmpeg.exe ในไฟล์ที่ดาวน์โหลด"
        except Exception as ex:  # noqa
            last = ex
            say(f"   ดาวน์โหลดจาก {url.split('/')[2]} ไม่สำเร็จ ({ex}) — ลองแหล่งอื่น…")
    fail("ติดตั้ง ffmpeg ไม่สำเร็จ: " + str(last) + "\n"
         "   ทางเลือก: เปิด Command Prompt แล้วพิมพ์  winget install Gyan.FFmpeg  จากนั้นเปิด start.bat ใหม่")


def req_hash() -> str:
    return hashlib.sha1(REQ.read_bytes()).hexdigest()[:12] if REQ.exists() else "none"


def venv_ok() -> bool:
    if not VPY.exists():
        return False
    try:
        r = subprocess.run([str(VPY), "-c", "import sys"], capture_output=True, timeout=30)
        return r.returncode == 0
    except Exception:  # noqa
        return False


def ensure_venv():
    marker = VENV / ".gamecut_ok"
    if venv_ok() and marker.exists() and marker.read_text().strip() == req_hash():
        return
    v = sys.version_info
    if not ((3, 10) <= v[:2] <= (3, 13)):
        say(f"⚠️  Python {v.major}.{v.minor} อาจยังไม่รองรับบางไลบรารี — แนะนำติดตั้ง Python 3.12")
    if not venv_ok():
        say("⏳ ติดตั้งครั้งแรก (ใช้เวลาสักครู่)…")
        if VENV.exists():
            shutil.rmtree(VENV, ignore_errors=True)
        r = subprocess.run([sys.executable, "-m", "venv", str(VENV)])
        if r.returncode != 0 or not VPY.exists():
            fail("สร้าง Python environment ไม่สำเร็จ")
    else:
        say("⏳ อัปเดตไลบรารี…")
    subprocess.run([str(VPY), "-m", "pip", "install", "--upgrade", "pip", "-q"])
    r = subprocess.run([str(VPY), "-m", "pip", "install", "-r", str(REQ)])
    if r.returncode != 0:
        fail("ติดตั้งไลบรารีไม่สำเร็จ — ตรวจอินเทอร์เน็ต แล้วเปิด start.bat ใหม่\n"
             "   (ถ้ายังไม่ได้ ลองติดตั้ง Python 3.12 จาก python.org)")
    marker.write_text(req_hash())
    say("✅ ติดตั้งเสร็จ")


def main():
    say("======================================")
    say("   🎮 GameCut — ตัดฟุตเทจเกมให้ลงเสียงพากย์")
    say("======================================")
    ensure_ffmpeg()
    ensure_venv()
    env = dict(os.environ)
    env["HF_HOME"] = str(APP / "models")       # เก็บโมเดล Whisper ไว้ในโฟลเดอร์แอพ
    env["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    env["PYTHONUTF8"] = "1"
    if FF_DIR.is_dir():
        env["PATH"] = str(FF_DIR) + os.pathsep + env.get("PATH", "")
    try:
        return subprocess.call([str(VPY), str(APP / "gamecut.py"), *sys.argv[1:]], env=env)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
