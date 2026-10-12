@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem PC를 켜고 로그인하면 도우미가 자동으로 켜지게 설정/해제합니다.
set "LNK=%AppData%\Microsoft\Windows\Start Menu\Programs\Startup\블로그 글쓰기 도우미.lnk"
set "TARGET=%~dp0시작하기.bat"
set "WORKDIR=%~dp0"

if exist "%LNK%" (
  echo  지금은 PC를 켤 때 도우미가 자동으로 켜지도록 설정되어 있습니다.
  choice /c YN /m "  자동 실행을 끌까요? (Y=끄기, N=그대로)"
  if errorlevel 2 exit /b 0
  del "%LNK%"
  echo  자동 실행을 껐습니다.
  pause
  exit /b 0
)

powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK); $s.TargetPath=$env:TARGET; $s.Arguments='--background'; $s.WorkingDirectory=$env:WORKDIR; $s.WindowStyle=7; $s.Save()"
if errorlevel 1 (
  echo  설정하지 못했습니다.
) else (
  echo  완료! 이제 PC를 켜면 도우미가 작업 표시줄에 최소화된 채로 자동으로 켜집니다.
  echo  끄려면 이 파일을 다시 실행하세요.
)
pause
