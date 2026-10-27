@echo off
setlocal
cd /d "%~dp0"
title RDW Milieuverkenner

echo ========================================
echo        RDW Milieuverkenner
echo ========================================
echo.

where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  set "PYTHON=py -3"
) else (
  set "PYTHON=python"
)

if not exist ".venv\Scripts\python.exe" (
  echo Eenmalig een lokale Python-omgeving aanmaken ...
  %PYTHON% -m venv .venv
  if errorlevel 1 goto fout
)

echo Benodigde pakketten installeren/controleren ...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto fout

echo.
echo Streamlit start op http://localhost:8501
echo Sluit dit venster om de app te stoppen.
echo.
".venv\Scripts\python.exe" -m streamlit run app.py --server.address localhost
if errorlevel 1 goto fout
exit /b 0

:fout
echo.
echo Starten is mislukt. Controleer Python, netwerk en eventuele firewallrestricties.
pause
exit /b 1
