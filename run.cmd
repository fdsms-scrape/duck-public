@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
exit /b %errorlevel%
