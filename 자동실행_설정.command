#!/bin/bash
# 맥에 로그인하면 도우미가 자동으로 켜지게 설정/해제합니다.
cd "$(dirname "$0")" || exit 1
DIR="$(pwd)"
LABEL="com.blogdoumi.server"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

pause_exit() { read -r -p "  엔터를 누르면 창을 닫습니다." _; exit "${1:-0}"; }

if [ -f "$PLIST" ]; then
  read -r -p "  지금은 자동 실행이 켜져 있습니다. 끌까요? (y/N) " a
  if [ "$a" = "y" ] || [ "$a" = "Y" ]; then
    launchctl unload "$PLIST" 2>/dev/null
    rm -f "$PLIST"
    echo "  자동 실행을 껐습니다."
  fi
  pause_exit 0
fi

if [ ! -x .venv/bin/python ]; then
  echo "  먼저 '시작하기.command'를 한 번 실행해서 설치를 끝내 주세요."
  pause_exit 1
fi

case "$DIR" in
  "$HOME/Desktop"*|"$HOME/Documents"*|"$HOME/Downloads"*)
    echo "  ⚠ 이 폴더가 데스크탑/문서/다운로드 안에 있으면 맥 보안 정책 때문에 자동 실행이 막힐 수 있습니다."
    echo "    폴더를 홈 폴더(예: $HOME/블로그도우미)로 옮긴 뒤 다시 실행하는 것을 권장합니다."
    read -r -p "  그래도 계속할까요? (y/N) " a
    if [ "$a" != "y" ] && [ "$a" != "Y" ]; then exit 0; fi
    ;;
esac

mkdir -p "$HOME/Library/LaunchAgents" "$DIR/data"
{
  echo '<?xml version="1.0" encoding="UTF-8"?>'
  echo '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
  echo '<plist version="1.0"><dict>'
  echo "  <key>Label</key><string>$LABEL</string>"
  echo "  <key>ProgramArguments</key><array><string>$DIR/.venv/bin/python</string><string>-m</string><string>app.main</string></array>"
  echo "  <key>WorkingDirectory</key><string>$DIR</string>"
  echo "  <key>RunAtLoad</key><true/>"
  echo "  <key>KeepAlive</key><true/>"
  echo "  <key>StandardOutPath</key><string>$DIR/data/server.log</string>"
  echo "  <key>StandardErrorPath</key><string>$DIR/data/server.log</string>"
  echo '</dict></plist>'
} > "$PLIST"

if launchctl load "$PLIST"; then
  echo "  완료! 이제 맥에 로그인하면 도우미가 자동으로 켜집니다. (지금도 켜졌어요: http://localhost:8000)"
  echo "  끄려면 이 파일을 다시 실행하세요."
else
  echo "  설정하지 못했습니다."
fi
pause_exit 0
