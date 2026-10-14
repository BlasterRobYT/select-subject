<#
  portable.ps1 -- builds the portable "Select Subject" bundle

  Layout produced (self-contained; copy the whole folder to any machine/USB):
      <out>\
        runtime\                      bundled CPython venv (stdlib + pip + ML stack)
          Scripts\python.exe          <- the plug-in's SELECT_SUBJECT_HOME resolution
          Lib\site-packages\...       rembg/onnxruntime/... (CPU onnxruntime)
        models\bria-rmbg\bria-rmbg.onnx   (~980 MB, used via REMBG_HOME)
        plug-ins\select-subject\      the three plug-in .py files
        select-subject-portable-gimp.bat  launcher (sets env, opens GIMP)
        README-portable.txt

  Usage:
      powershell -NoProfile -ExecutionPolicy Bypass -File .\portable.ps1
      powershell -NoProfile -ExecutionPolicy Bypass -File .\portable.ps1 -Zip
      powershell -NoProfile -ExecutionPolicy Bypass -File .\portable.ps1 `
          -Base "C:\path\to\python-3.14.7-win32-x64" -Out "D:\ss-portable"

  Requires: a standalone CPython 3.14 x64 base install (python.org full
  installer folder, or the auto-detected bundled tool). ~1.5 GB free space.
  The CPU onnxruntime wheel is used (no GPU needed).
#>
param(
    [string]$Base,
    [string]$Out = "$env:USERPROFILE\GIMP\select-subject-portable",
    [switch]$Zip
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$REQ  = Join-Path $Root "requirements.txt"

function Write-Step($m) { Write-Host "" ; Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "    $m" -ForegroundColor Green }

# --------------------------------------------------- 1. locate CPython base
if (-not $Base) {
    $candidates = Get-ChildItem "$env:LOCALAPPDATA\hermes\tools" -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^python-3\.14\.7' } |
        Sort-Object Name -Descending
    if ($candidates) { $Base = $candidates[0].FullName }
}
if (-not $Base) {
    $envPy = (Get-Command python -ErrorAction SilentlyContinue).Source
    if ($envPy) { $Base = Split-Path -Parent $envPy }
}
if (-not $Base -or -not (Test-Path (Join-Path $Base "python.exe"))) {
    throw "No standalone CPython 3.14 x64 base found. Pass -Base <folder-with-python.exe>."
}
Write-Step "CPython base: $Base"
& (Join-Path $Base "python.exe") --version

# ------------------------------------------------------------ 2. clean tree
Write-Step "Preparing output: $Out"
$runtime = Join-Path $Out "runtime"
if (Test-Path $Out) { Remove-Item $Out -Recurse -Force }
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Out "models") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Out "plug-ins\select-subject") | Out-Null

# --------------------------------------------------- 3. copy base -> runtime
Write-Step "Copying CPython into runtime\ (155 MB) ..."
robocopy $Base $runtime /E /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed" }
Write-Ok "runtime\ in place"

# ------------------------------------------- 4. turn runtime into a venv
Write-Step "Creating venv inside runtime\ (pip + site-packages) ..."
& (Join-Path $runtime "python.exe") -m venv --upgrade-deps $runtime
if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
$venvPy = Join-Path $runtime "Scripts\python.exe"
Write-Ok "venv ready"

# ---------------------------------------------------- 5. install ML stack
Write-Step "Installing ML stack into the bundled venv ..."
& $venvPy -m pip install --quiet --upgrade pip
& $venvPy -m pip install --quiet -r $REQ
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
Write-Ok "ML stack installed (rembg/onnxruntime/numpy/...)"

# ---------------------------------------------------------------- 6. model
Write-Step "Placing the BRIA RMBG-2.0 model in models\ ..."
$srcModels = "$env:LOCALAPPDATA\rembg\models"
if (Test-Path (Join-Path $srcModels "bria-rmbg\bria-rmbg.onnx")) {
    robocopy $srcModels (Join-Path $Out "models") /E /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
    Write-Ok "model copied from local cache"
} else {
    $env:REMBG_HOME = Join-Path $Out "models"
    & $venvPy -c "from rembg.sessions import BriaRmBgSession as B; p=B.download_models(); print('model ok:', p)"
    if ($LASTEXITCODE -ne 0) { throw "model download failed" }
    Remove-Item Env:\REMBG_HOME
    Write-Ok "model downloaded into models\"
}

# ------------------------------------------------------------ 7. plug-in
Write-Step "Copying plug-in files ..."
foreach ($f in "select-subject.py","select-subject-daemon.py","select-subject-worker.py") {
    Copy-Item (Join-Path $Root $f) (Join-Path $Out "plug-ins\select-subject\$f") -Force
}
Write-Ok "plug-in copied"

# ------------------------------------------------------- 8. launcher .bat
$gimpExe = $null
foreach ($c in @(
    "C:\Program Files\GIMP 3\bin\gimp-3.2.exe",
    "C:\Program Files\GIMP 3\bin\gimp.exe",
    "C:\Program Files (x86)\GIMP 3\bin\gimp-3.2.exe")) {
    if (Test-Path $c) { $gimpExe = $c ; break }
}
# The plug-in must live in GIMP's config dir for GIMP to load it; the heavy
# runtime + model stay in the portable folder. Copy it into every GIMP 3.x
# config version dir (covers whatever version PhotoGIMP's config targets).
$gimpApp = "$env:APPDATA\GIMP"
$installedPlugin = 0
if (Test-Path $gimpApp) {
    foreach ($verdir in (Get-ChildItem $gimpApp -Directory -ErrorAction SilentlyContinue)) {
        if ($verdir.BaseName -notmatch '^3\.[0-9]+') { continue }
        $dest = Join-Path $verdir.FullName "plug-ins\select-subject"
        New-Item -ItemType Directory -Force -Path $dest | Out-Null
        Copy-Item (Join-Path $Root "select-subject.py")       $dest -Force
        Copy-Item (Join-Path $Root "select-subject-daemon.py") $dest -Force
        Copy-Item (Join-Path $Root "select-subject-worker.py") $dest -Force
        Write-Ok "plug-in installed to $dest"
        $installedPlugin++
    }
}
if ($installedPlugin -eq 0) {
    Write-Host "    (GIMP not launched yet -- launch GIMP once, then run the .bat, then re-run this script)" -ForegroundColor Yellow
}
if ($gimpExe) {
    Write-Step "Launcher: $gimpExe"
    $bat = @"
@echo off
rem Launch GIMP with the portable "Select Subject" plug-in enabled.
rem Requires GIMP 3.x installed (vanilla or PhotoGIMP).
set "SELECT_SUBJECT_HOME=%~dp0."
set "PYTHONUTF8=1"
start "" "$gimpExe" %*
"@
    Set-Content -Path (Join-Path $Out "select-subject-portable-gimp.bat") -Value $bat -Encoding ascii
    Write-Ok "launcher .bat written"
} else {
    Write-Host "    (no GIMP 3.x found here -- the plug-in still works with GIMP on the target machine)" -ForegroundColor Yellow
}

# ------------------------------------------------------------- 9. README
$readme = @"
SELECT SUBJECT - GIMP 3 (portable)
==================================
Everything is in this folder. To use it:

  1. Make sure GIMP 3.x (vanilla or PhotoGIMP) is installed on this machine.
  2. Double-click:  select-subject-portable-gimp.bat
     (opens GIMP with the plug-in's environment pointed at this folder)
  3. In GIMP:  Image > Select Subject

No installation, no admin rights, no network needed (model is bundled).
The first run takes ~25 s (model load); afterwards ~12 s per 1080p image
(CPU inference).  Nothing is written outside your GIMP settings except a
log in %TEMP%\select_subject_daemon.log.

To copy to another computer: copy the WHOLE folder.  It must be a machine
with GIMP 3.x; the bundled Python is for Windows x64 only.
"@
Set-Content -Path (Join-Path $Out "README-portable.txt") -Value $readme -Encoding ascii
Write-Ok "README written"

# ---------------------------------------------------------- 10. verify
Write-Step "Verification: model loads + runs inference from the portable folder ..."
$env:REMBG_HOME = Join-Path $Out "models"
$env:SELECT_SUBJECT_HOME = $Out
$verify = @'
import os
os.environ["REMBG_HOME"] = os.environ["SELECT_SUBJECT_HOME"] + "\\models"
import numpy as np
from PIL import Image
from rembg import remove, new_session
import io
s = new_session("bria-rmbg")
img = Image.fromarray((np.random.rand(256, 256, 3) * 255).astype("uint8"))
out = remove(img, session=s)
assert out.size == img.size
print("portable inference OK (256x256 test image) ->", out.size)
'@
& $venvPy -c $verify
if ($LASTEXITCODE -ne 0) { throw "portable verification failed" }
Remove-Item Env:\REMBG_HOME
Remove-Item Env:\SELECT_SUBJECT_HOME
$size = (Get-ChildItem $Out -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
Write-Ok ("portable bundle verified ({0:N0} MB)" -f $size)

# ------------------------------------------------------------- 11. optional zip
if ($Zip) {
    Write-Step "Creating dist zip (this can take a few minutes) ..."
    $zipPath = Join-Path (Join-Path $Root "dist") "select-subject-portable-windows.zip"
    New-Item -ItemType Directory -Force -Path (Join-Path $Root "dist") | Out-Null
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
    Compress-Archive -Path (Join-Path $Out "*") -DestinationPath $zipPath -CompressionLevel Optimal
    $zsize = (Get-Item $zipPath).Length / 1MB
    Write-Ok ("zip ready: {0} ({1:N0} MB)" -f $zipPath, $zsize)
}

Write-Host ""
Write-Host "================= PORTABLE BUILD COMPLETE =================" -ForegroundColor Green
Write-Host "  $Out" -ForegroundColor Green
Write-Host "  Run: $Out\select-subject-portable-gimp.bat" -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Green
