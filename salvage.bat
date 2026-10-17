@echo off
setlocal DisableDelayedExpansion
set "PYTHONPATH=%~dp0;%PYTHONPATH%"
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" -m deadbits.cli %*
) else (
  python -m deadbits.cli %*
)
exit /b %ERRORLEVEL%
