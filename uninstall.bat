@echo off
rem Select Subject - GIMP 3 plug-in uninstaller launcher
title Select Subject - Uninstaller
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1" %*
echo.
pause
