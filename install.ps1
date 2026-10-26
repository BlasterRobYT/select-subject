<#
  install.ps1 -- "Select Subject" GIMP plug-in installer (Windows)

  What it does:
    1. Detects a GIMP 3.x installation (vanilla GIMP or PhotoGIMP -- both
       are GIMP 3.0+ and share the same plug-in API).  GIMP 2.x is rejected
       (different plug-in API).
    2. Creates a dedicated CPython venv (via GIMP's bundled python.exe) at
       %USERPROFILE%\GIMP\select-subject-env with the ML stack (rembg /
       onnxruntime).
    3. Downloads the BRIA RMBG-2.0 ONNX model (~980 MB) into
       %LOCALAPPDATA%\rembg (skippable with -SkipModel if already present).
    4. Copies the plug-in into EVERY GIMP 3.x config version dir
       (%APPDATA%\GIMP\<ver>\plug-ins\select-subject\) so it works no matter
       which version PhotoGIMP's config patch targets.

  Usage (double-click .bat, or from PowerShell):
      powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
      powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -SkipModel
      powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Amd

  Idempotent: safe to re-run; it updates the plug-in files and fills any
  missing pieces without breaking a working install.
#>
param(
    [switch]$SkipModel,
    [switch]$Amd,
    [string]$VenvDir = "$env:USERPROFILE\GIMP\select-subject-env"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$REQ  = Join-Path $Root "requirements.txt"

function Write-Step($m) { Write-Host "" ; Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "    $m" -ForegroundColor Green }
function Write-Warn($m) { Write-Host "    $m" -ForegroundColor Yellow }

# ---------------------------------------------------------------- 1. GIMP 3.x
Write-Step "Locating GIMP 3.x (vanilla or PhotoGIMP)..."
$gimpRoots = @()
# Registry: HKLM\SOFTWARE\GIMP\3.2 (64-bit) and WOW6432Node
foreach ($hive in @(
    "HKLM:\SOFTWARE\GIMP",
    "HKLM:\SOFTWARE\WOW6432Node\GIMP")) {
    $k = Get-Item $hive -ErrorAction SilentlyContinue
    if ($k) {
        foreach ($sub in (Get-ChildItem $k -ErrorAction SilentlyContinue)) {
            $p = $sub.GetValue("Path")
            if ($p) { $gimpRoots += $p }
        }
    }
}
# Common install dirs (registry sometimes misses portable installs)
$gimpRoots += @(
    "C:\Program Files\GIMP 3",
    "C:\Program Files (x86)\GIMP 3",
    "D:\GIMP 3"
) | Where-Object { Test-Path (Join-Path $_ "bin\gimp-console.exe") }
$gimpRoots = $gimpRoots | Sort-Object -Unique

$found3 = $gimpRoots | Where-Object {
    Test-Path (Join-Path $_ "bin\python.exe")
}
$found2 = @("C:\Program Files\GIMP 2.10", "C:\Program Files (x86)\GIMP 2.10") |
    Where-Object { Test-Path (Join-Path $_ "bin\gimp.exe") }

if (-not $found3) {
    if ($found2) {
        Write-Warn "Only GIMP 2.x detected. This plug-in requires GIMP 3.0+."
        Write-Warn "(GIMP 2.10 uses a different plug-in API; PhotoGIMP is GIMP 3-only too.)"
        throw "Install GIMP 3.0+ (or PhotoGIMP, which is GIMP 3.0+) and re-run."
    }
    throw "No GIMP 3.x installation found (checked registry + common folders)."
}
$gimpPy = $null
foreach ($r in $found3) {
    $py = Join-Path $r "bin\python.exe"
    if (Test-Path $py) { $gimpPy = $py ; break }
}
$ver = & $gimpPy --version 2>&1
Write-Ok "GIMP python: $gimpPy ($ver)"

# ------------------------------------------------------------- 2. ML venv
Write-Step "Preparing ML runtime (venv) at $VenvDir ..."
if (-not (Test-Path $VenvDir)) {
    & $gimpPy -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
    Write-Ok "venv created"
} else {
    Write-Ok "venv already present"
}
$venvPy = Join-Path $VenvDir "Scripts\python.exe"
$venvPip = Join-Path $VenvDir "Scripts\pip.exe"
# Make sure pip exists (ensurepip fallback if the venv is missing it)
if (-not (Test-Path $venvPip)) {
    & $venvPy -m ensurepip --upgrade | Out-Null
}
& $venvPy -m pip install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) { throw "pip self-upgrade failed" }
Write-Step "Installing ML packages (rembg / onnxruntime / ...) ..."
& $venvPy -m pip install -r $REQ --quiet
if ($LASTEXITCODE -ne 0) { throw "ML install failed" }
if ($Amd) {
    Write-Step "Switching onnxruntime to the DirectML build (AMD Radeon GPU) ..."
    # onnxruntime-directml installs into the same site-packages\onnxruntime
    # tree as the CPU build -- last install wins the DLLs -- so remove every
    # variant first, then install the DirectML wheel.
    & $venvPy -m pip uninstall -y onnxruntime onnxruntime-gpu onnxruntime-directml
    if ($LASTEXITCODE -ne 0) { throw "Failed to remove CPU onnxruntime" }
    & $venvPy -m pip install "onnxruntime-directml==1.24.4" --quiet
    if ($LASTEXITCODE -ne 0) { throw "onnxruntime-directml install failed" }
    & $venvPy -c "import sys, onnxruntime as o; sys.exit(0 if 'DmlExecutionProvider' in o.get_available_providers() else 1)"
    if ($LASTEXITCODE -ne 0) { throw "DirectML build installed but DmlExecutionProvider missing" }
    Write-Ok "AMD Radeon (DirectML) GPU acceleration configured"
}
Write-Ok "ML packages installed"

# ---------------------------------------------------------------- 3. model
$modelDir = "$env:LOCALAPPDATA\rembg\models\bria-rmbg"
$modelF   = Join-Path $modelDir "bria-rmbg.onnx"
if ($SkipModel) {
    Write-Warn "-SkipModel: skipping model download"
} elseif (Test-Path $modelF) {
    Write-Ok "model already cached: $modelF"
} else {
    Write-Step "Downloading BRIA RMBG-2.0 model (~980 MB) ..."
    & $venvPy -c "from rembg.sessions import BriaRmBgSession as B; p=B.download_models(); print('model ok:', p)"
    if ($LASTEXITCODE -ne 0) { throw "model download failed" }
    Write-Ok "model downloaded to $modelF"
}

# ------------------------------------------------- 4. copy plug-in (all 3.x)
Write-Step "Installing plug-in into GIMP config dir(s) ..."
$gimpApp = "$env:APPDATA\GIMP"
$installed = 0
if (Test-Path $gimpApp) {
    foreach ($verdir in (Get-ChildItem $gimpApp -Directory -ErrorAction SilentlyContinue)) {
        # only GIMP 3.x version folders (e.g. 3.0, 3.2) -- skip 2.x
        if ($verdir.BaseName -notmatch '^3\.[0-9]+') { continue }
        $dest = Join-Path $verdir.FullName "plug-ins\select-subject"
        New-Item -ItemType Directory -Force -Path $dest | Out-Null
        Copy-Item (Join-Path $Root "select-subject.py")        $dest -Force
        Copy-Item (Join-Path $Root "select-subject-daemon.py")  $dest -Force
        Copy-Item (Join-Path $Root "select-subject-worker.py")  $dest -Force
        Write-Ok "copied to $dest"
        $installed++
    }
}
if ($installed -eq 0) {
    Write-Warn "No GIMP 3.x config version dir found yet -- GIMP hasn't been launched."
    Write-Warn "The plug-in will install on first launch; or launch GIMP once and re-run."
}

# --------------------------------------------------------------- 5. verify
Write-Step "Verification (ML stack imports in venv) ..."
& $venvPy -c "import rembg, onnxruntime, numpy, PIL; from rembg.sessions import BriaRmBgSession as B; print('rembg + onnxruntime', onnxruntime.get_version(), '| providers', onnxruntime.get_available_providers(), 'OK')"
if ($LASTEXITCODE -ne 0) { throw "verification failed" }

Write-Host ""
Write-Host "================= INSTALL COMPLETE =================" -ForegroundColor Green
Write-Host "  Restart GIMP (or PhotoGIMP), then:  Image > Select Subject"
Write-Host "  (First run takes ~25s to warm up; after that ~12s per 1080p image.)"
Write-Host "  Log: $env:TEMP\select_subject_daemon.log"
Write-Host "==============================================" -ForegroundColor Green
