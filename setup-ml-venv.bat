@echo off
rem setup-ml-venv.bat -- create (or update) the ML venv for the select-subject
rem GIMP plugin (Windows, CPU inference).
rem
rem The venv lands in %USERPROFILE%\GIMP\select-subject-env
rem (override: SELECT_SUBJECT_HOME).
setlocal
set VENV=%SELECT_SUBJECT_HOME%
if "%VENV%"=="" set VENV=%USERPROFILE%\GIMP\select-subject-env

echo ^>^> creating venv at %VENV%
python -m venv "%VENV%" || goto :err
set VPY=%VENV%\Scripts\python.exe

"%VPY%" -m pip install --upgrade pip || goto :err
echo ^>^> installing rembg + CPU onnxruntime
"%VPY%" -m pip install "rembg[cpu]" || goto :err
echo ^>^> verifying
"%VPY%" -c "import onnxruntime as ort; print('onnxruntime', ort.__version__, ort.get_available_providers())" || goto :err
echo ^>^> done: %VENV%
echo    next: restart GIMP and pick Select ^> Select Subject.
exit /b 0

:err
echo failed.
exit /b 1
