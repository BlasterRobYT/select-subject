<#
  uninstall.ps1 -- removes the "Select Subject" GIMP plug-in (Windows)

  What it removes (and nothing else):
    1. The plug-in folder from every GIMP 3.x config dir
       (%APPDATA%\GIMP\<3.x>\plug-ins\select-subject\)
    2. The ML runtime venv at %USERPROFILE%\GIMP\select-subject-env\
       (only that folder -- the rest of your GIMP folder is left alone)
    3. The BRIA RMBG-2.0 model (~980 MB) at %LOCALAPPDATA%\rembg\models\bria-rmbg\
    4. Small log/state files in your Temp folder

  What it does NOT touch: GIMP itself, your images, any other plug-ins,
  the registry (nothing was written to it), or any other rembg model.

  Usage:
    double-click uninstall.bat
    or:  powershell -NoProfile -ExecutionPolicy Bypass -File .\uninstall.ps1
    -Force   skips the Y/N confirmation (for advanced users)

  Note: if you built a PORTABLE version, just delete its folder
  (e.g. select-subject-portable-windows) -- it is fully self-contained.
#>
param([switch]$Force)

$ErrorActionPreference = "Stop"

$pluginDirs = @()
$venvDir    = "$env:USERPROFILE\GIMP\select-subject-env"
$modelDir   = "$env:LOCALAPPDATA\rembg\models\bria-rmbg"
$stateFile  = "$env:TEMP\select_subject_daemon.json"
$logFile    = "$env:TEMP\select_subject_daemon.log"

# ---- locate installed plug-in folders (all GIMP 3.x config versions) ----
$gimpApp = "$env:APPDATA\GIMP"
if (Test-Path $gimpApp) {
    foreach ($verdir in (Get-ChildItem $gimpApp -Directory -ErrorAction SilentlyContinue)) {
        if ($verdir.BaseName -notmatch '^3\.[0-9]+') { continue }
        $p = Join-Path $verdir.FullName "plug-ins\select-subject"
        if (Test-Path $p) { $pluginDirs += $p }
    }
}

# ---- nothing installed? bail out politely -------------------------------
if (-not $pluginDirs -and -not (Test-Path $venvDir) -and -not (Test-Path $modelDir)) {
    Write-Host "Nothing to do -- Select Subject doesn't appear to be installed."
    Write-Host "(Checked plug-in folders, the venv, and the model cache.)"
    exit 0
}

# ---- show the user what will be removed ---------------------------------
function SizeMB($p) {
    if (-not (Test-Path $p)) { return 0 }
    $b = (Get-ChildItem $p -Recurse -File -ErrorAction SilentlyContinue |
          Measure-Object Length -Sum).Sum
    [math]::Round($b / 1MB, 1)
}

Write-Host ""
Write-Host "Select Subject will remove:" -ForegroundColor Cyan
foreach ($p in $pluginDirs) { Write-Host ("  [plug-in] " + $p) }
if (Test-Path $venvDir)  { Write-Host ("  [ML runtime] " + $venvDir + "  (~" + (SizeMB $venvDir) + " MB)") }
if (Test-Path $modelDir) { Write-Host ("  [model] " + $modelDir + "  (~" + (SizeMB $modelDir) + " MB)") }
Write-Host "  [logs]      $stateFile"
Write-Host "               $logFile"
Write-Host ""
Write-Host "Your GIMP install, images, and other plug-ins are NOT touched." -ForegroundColor Green

if (-not $Force) {
    $ans = Read-Host "Remove all of the above? (Y/N)"
    if ($ans -notmatch '^[Yy]') { Write-Host "Cancelled -- nothing was removed."; exit 0 }
}

# ---- 1. stop the ML daemon (only if it is running) -----------------------
$daemon = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
          Where-Object { $_.CommandLine -like '*select-subject-daemon.py*' }
if ($daemon) {
    foreach ($d in $daemon) {
        Write-Host ("Stopping ML daemon (pid " + $d.ProcessId + ")...")
        Stop-Process -Id $d.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
} else {
    Write-Host "ML daemon is not running."
}

# ---- 2. remove plug-in folders ------------------------------------------
foreach ($p in $pluginDirs) {
    Remove-Item $p -Recurse -Force
    Write-Host ("Removed: " + $p) -ForegroundColor Green
}

# ---- 3. remove venv ------------------------------------------------------
if (Test-Path $venvDir) {
    try {
        Remove-Item $venvDir -Recurse -Force
        Write-Host ("Removed: " + $venvDir) -ForegroundColor Green
    } catch {
        Write-Host ("Could not remove $venvDir : " + $_.Exception.Message) -ForegroundColor Yellow
        Write-Host "Close any window using it (GIMP, terminals), then re-run."
    }
}

# ---- 4. remove model ------------------------------------------------------
if (Test-Path $modelDir) {
    try {
        Remove-Item $modelDir -Recurse -Force
        Write-Host ("Removed: " + $modelDir) -ForegroundColor Green
    } catch {
        Write-Host ("Could not remove $modelDir : " + $_.Exception.Message) -ForegroundColor Yellow
        Write-Host "Restart your PC if the model file is locked, then re-run."
    }
}

# ---- 5. logs / state ------------------------------------------------------
foreach ($f in @($stateFile, $logFile)) {
    if (Test-Path $f) { Remove-Item $f -Force; Write-Host ("Removed: " + $f) }
}

Write-Host ""
Write-Host "================= UNINSTALL COMPLETE =================" -ForegroundColor Green
Write-Host "  Restart GIMP and 'Image > Select Subject' will be gone."
Write-Host "  (If it was a portable build, just delete that folder too.)"
Write-Host "===============================================" -ForegroundColor Green
