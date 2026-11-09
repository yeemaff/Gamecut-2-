#!/bin/bash
# GameCut — ดับเบิลคลิกไฟล์นี้เพื่อเปิดแอพ (Mac)
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

echo "======================================"
echo "   🎮 GameCut — ตัดฟุตเทจเกมให้ลงเสียงพากย์"
echo "======================================"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo ""
  echo "❌ ยังไม่มี ffmpeg"
  echo "   ติดตั้งด้วยคำสั่งนี้ใน Terminal:   brew install ffmpeg"
  echo "   (ถ้ายังไม่มี Homebrew ดูวิธีติดตั้งที่ https://brew.sh)"
  read -r -p "กด Enter เพื่อปิด"
  exit 1
fi

PY=""
for c in python3.12 python3.11 python3.13 python3; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "❌ ยังไม่มี Python 3 — ติดตั้งด้วย:   brew install python"
  read -r -p "กด Enter เพื่อปิด"
  exit 1
fi

# (โฟลเดอร์ models ใช้ในเวอร์ชันเก่า ไม่จำเป็นแล้ว)
export HF_HOME="$PWD/models"

# ไดรฟ์ exFAT (SSD ที่ใช้ร่วมกับ Windows) จะสร้างไฟล์ ._ ที่ทำให้ Python พัง — ลบทิ้งก่อนทุกครั้ง
clean_dot() { [ -d .venv ] && find .venv -name '._*' -delete 2>/dev/null; }
clean_dot

# venv เสีย (เช่น ย้าย SSD ไปเสียบ Mac เครื่องอื่น) → สร้างใหม่
if [ -d ".venv" ] && ! ./.venv/bin/python -c "import sys" >/dev/null 2>&1; then
  echo "♻️  ตั้งค่าใหม่สำหรับเครื่องนี้…"
  rm -rf .venv
fi

if [ ! -d ".venv" ]; then
  echo "⏳ ติดตั้งครั้งแรก (ใช้เวลาสักครู่)…"
  if ! "$PY" -m venv .venv 2>/dev/null; then
    rm -rf .venv
    "$PY" -m venv --copies .venv || { echo "สร้าง venv ไม่สำเร็จ"; read -r -p "กด Enter"; exit 1; }
  fi
  ./.venv/bin/python -m pip install --upgrade pip -q
  ./.venv/bin/python -m pip install -r requirements.txt || { echo "ติดตั้งไลบรารีไม่สำเร็จ"; rm -rf .venv; read -r -p "กด Enter"; exit 1; }
  clean_dot
  shasum requirements.txt | cut -c1-12 > .venv/.gamecut_ok
  echo "✅ ติดตั้งเสร็จ"
fi

# อัปเดตแอพแล้ว requirements เปลี่ยน → ติดตั้งเพิ่มให้อัตโนมัติ
REQ_HASH="$(shasum requirements.txt | cut -c1-12)"
if [ "$(cat .venv/.gamecut_ok 2>/dev/null)" != "$REQ_HASH" ]; then
  echo "⏳ อัปเดตไลบรารีของแอพ…"
  ./.venv/bin/python -m pip install -r requirements.txt -q && echo "$REQ_HASH" > .venv/.gamecut_ok
  clean_dot
fi

./.venv/bin/python gamecut.py
