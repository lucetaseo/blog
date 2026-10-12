#!/bin/bash
# 네이버 블로그 글쓰기 도우미 — 맥에서 더블클릭으로 실행
# 사용법: ./시작하기.command              (브라우저도 엽니다)
#         ./시작하기.command --background (자동 실행용)
cd "$(dirname "$0")" || exit 1

pause_exit() { read -r -p "  엔터를 누르면 창을 닫습니다." _; exit "${1:-1}"; }

echo
echo "  =============================================="
echo "    네이버 블로그 글쓰기 도우미를 준비합니다"
echo "  =============================================="
echo

ok_python() { "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; }

find_python() {
  for c in python3.13 python3.12 python3.11 python3.10 \
           /opt/homebrew/bin/python3 /usr/local/bin/python3 \
           /Library/Frameworks/Python.framework/Versions/3.*/bin/python3 python3; do
    if command -v "$c" >/dev/null 2>&1 && ok_python "$c"; then echo "$c"; return 0; fi
  done
  return 1
}

# ---- 1. 파이썬 (3.10 이상) ----
PY="$(find_python)"
if [ -z "$PY" ] && command -v brew >/dev/null 2>&1; then
  echo "  [1/3] 파이썬을 설치합니다 (Homebrew). 몇 분 걸릴 수 있어요..."
  brew install python@3.12 && PY="$(find_python)"
fi
if [ -z "$PY" ]; then
  echo "  파이썬 3.10 이상이 필요합니다."
  echo "  잠시 뒤 열리는 페이지에서 'Download Python' 을 눌러 설치한 뒤, 이 파일을 다시 실행하세요."
  open "https://www.python.org/downloads/macos/"
  pause_exit 1
fi
echo "  [1/3] 파이썬 확인 완료 ($("$PY" --version))"

# ---- 2. 필요한 프로그램 (처음 한 번, 또는 업데이트 후) ----
if [ ! -x .venv/bin/python ]; then
  echo "  [2/3] 처음 실행이라 필요한 프로그램을 설치합니다. 1~3분 걸려요..."
  "$PY" -m venv .venv || pause_exit 1
fi
if ! cmp -s requirements.txt .venv/installed.txt; then
  if ! .venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt; then
    echo "  설치 중 문제가 생겼습니다. 인터넷 연결을 확인하고 다시 실행해 주세요."
    pause_exit 1
  fi
  cp requirements.txt .venv/installed.txt
fi
echo "  [2/3] 프로그램 준비 완료"

# ---- 3. 실행 ----
echo "  [3/3] 도우미를 켭니다. 잠시 뒤 브라우저가 열려요."
if [ "$1" != "--background" ]; then
  (sleep 3 && open "http://localhost:${PORT:-8000}") &
fi
exec .venv/bin/python -m app.main
