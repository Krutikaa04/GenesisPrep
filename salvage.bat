@echo off
set PYTHONPATH=%~dp0;%PYTHONPATH%
python -m deadbits.cli %*
exit /b 0
