@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title 블로그 글쓰기 도우미

rem 사용법: 시작하기.bat              (브라우저도 엽니다)
rem         시작하기.bat --background (자동 실행용, 브라우저를 열지 않습니다)

echo.
echo  ==============================================
echo    네이버 블로그 글쓰기 도우미를 준비합니다
echo  ==============================================
echo.

rem ---- 1. 파이썬 찾기 (3.10 이상) ----
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY=py -3"
if not defined PY (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY call :find_installed_python

if not defined PY (
  echo  [1/3] 파이썬이 없어 설치합니다. 몇 분 걸릴 수 있어요...
  where winget >nul 2>&1
  if errorlevel 1 goto :manual_python
  winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
  call :find_installed_python
  if not defined PY goto :manual_python
)
echo  [1/3] 파이썬 확인 완료

rem ---- 2. 필요한 프로그램 설치 (처음 한 번, 또는 업데이트 후) ----
if not exist ".venv\Scripts\python.exe" (
  echo  [2/3] 처음 실행이라 필요한 프로그램을 설치합니다. 1~3분 걸려요...
  !PY! -m venv .venv
  if errorlevel 1 goto :fail
)
fc /b requirements.txt .venv\installed.txt >nul 2>&1
if errorlevel 1 (
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
  if errorlevel 1 goto :fail
  copy /y requirements.txt .venv\installed.txt >nul
)
echo  [2/3] 프로그램 준비 완료

rem ---- 3. 실행 ----
echo  [3/3] 도우미를 켭니다. 잠시 뒤 브라우저가 열려요.
if /i not "%~1"=="--background" (
  start "" /b cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:8000"
)
".venv\Scripts\python.exe" -m app.main
echo.
echo  도우미가 종료되었습니다.
if /i not "%~1"=="--background" pause
exit /b 0

:find_installed_python
rem winget/python.org 로 사용자 폴더에 설치된 파이썬 (PATH에 아직 안 잡혔을 때)
for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do (
  if not defined PY if exist "%%D\python.exe" set "PY="%%D\python.exe""
)
exit /b 0

:manual_python
echo.
echo  파이썬을 자동으로 설치하지 못했습니다.
echo  잠시 뒤 열리는 페이지에서 Python을 내려받아 설치하세요.
echo  설치 첫 화면에서 "Add python.exe to PATH" 를 꼭 체크하세요.
echo  설치가 끝나면 이 파일을 다시 실행하세요.
start "" https://www.python.org/downloads/
pause
exit /b 1

:fail
echo.
echo  설치 중 문제가 생겼습니다. 인터넷 연결을 확인하고 다시 실행해 주세요.
echo  계속 안 되면 이 창 내용을 캡처해서 담당자에게 보내 주세요.
pause
exit /b 1
