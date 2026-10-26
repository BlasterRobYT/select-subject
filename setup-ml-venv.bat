@echo off
rem setup-ml-venv.bat -- create (or update) the ML venv for the select-subject
rem GIMP plugin (Windows).
rem
rem   setup-ml-venv.bat            CPU inference (default)
rem   setup-ml-venv.bat --amd      AMD Radeon GPU inference (DirectML; alias --dml)
rem
rem The venv lands in %USERPROFILE%\GIMP\select-subject-env
rem (override: SELECT_SUBJECT_HOME).
setlocal enabledelayedexpansion
set AMD=0
if /i "%~1"=="--amd" set AMD=1
if /i "%~1"=="--dml" set AMD=1
set VENV=%SELECT_SUBJECT_HOME%
if "%VENV%"=="" set VENV=%USERPROFILE%\GIMP\select-subject-env

echo ^>^> creating venv at %VENV%
python -m venv "%VENV%" || goto :err
set VPY=%VENV%\Scripts\python.exe

"%VPY%" -m pip install --upgrade pip || goto :err
rem onnxruntime-directml installs into the same site-packages\onnxruntime
rem tree as the CPU build -- last install wins the DLLs.  Remove every
rem onnxruntime variant first so the target build is authoritative.
"%VPY%" -m pip uninstall -y onnxruntime onnxruntime-gpu onnxruntime-directml >nul 2>&1
if !AMD!=="1" (
    echo ^>^> installing rembg + CPU onnxruntime
    "%VPY%" -m pip install "rembg[cpu]" || goto :err
) else (
    echo ^>^> installing rembg + onnxruntime-directml ^(AMD Radeon GPU build^)
    "%VPY%" -m pip install rembg || goto :err
    "%VPY%" -m pip install "onnxruntime-directml==1.24.4" || goto :err
)
echo ^>^> verifying
"%VPY%" -c "import onnxruntime as ort; print('onnxruntime', ort.__version__, ort.get_available_providers())" || goto :err
if !AMD!=="1" (
    "%VPY%" -c "import sys, onnxruntime as o; sys.exit(0 if 'DmlExecutionProvider' in o.get_available_providers() else 1)" || goto :err
    echo    DmlExecutionProvider OK -- AMD Radeon (DirectML) acceleration active.
)
echo ^>^> done: %VENV%
echo    next: restart GIMP and pick Select ^> Select Subject.
exit /b 0

:err
echo failed.
exit /b 1
