@echo off
rem Select Subject - GIMP 3 plug-in installer launcher
title Select Subject - Installer
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
echo.
pause
