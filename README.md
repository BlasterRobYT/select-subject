# Select Subject — GIMP 3 plug-in (Photoshop-style)

One-click "select the main subject" for **GIMP 3.x** (Windows **and** Linux),
using the **BRIA
RMBG-2.0** AI model (the same class of model Adobe Photoshop's *Select
Subject* relies on). It composites the **visible layer stack**, runs the
model, and returns a selection — non-destructive, exactly like Photoshop.

**Works with both vanilla GIMP and PhotoGIMP.** PhotoGIMP is a config-only
patch for GIMP 3.0+ (same binary, same plug-in API, same menu system), so
so this plug-in runs identically under both.

## What it does
1. Duplicates the image and **flattens only the visible layers** (a copy —
   your document is untouched).
2. Runs **BRIA RMBG-2.0** on the composite via a **persistent daemon**
   (the model stays in RAM, so repeated runs are fast).
3. Converts the alpha mask back into a **GIMP selection** on the original
   image.

**Speed:** ~25 s cold (first run, model load) → **~12 s per 1080p image**
afterwards. Inference is **CPU-only** (onnxruntime CPU) — no GPU needed,
but no GPU acceleration either.

## Requirements
- **Windows x64 or Linux x64** (Ubuntu/Debian, Arch, Fedora, …)
- **GIMP 3.0 or newer** — vanilla GIMP or PhotoGIMP. *(GIMP 2.10 is not
  supported: it uses a different, legacy plug-in API.)*
- ~1 GB free disk (the model is ~980 MB)

## Install (one-click)
Double-click **`install.bat`** (or run
`powershell -ExecutionPolicy Bypass -File install.ps1`). It will:
1. Detect your GIMP 3.x (vanilla or PhotoGIMP) and its `python.exe`.
2. Create a private CPython venv at `%USERPROFILE%\GIMP\select-subject-env`.
3. Install the ML stack (`rembg`, `onnxruntime`, …) and download the model.
4. Copy the plug-in into **every** GIMP 3.x config dir
   (`%APPDATA%\GIMP\<ver>\plug-ins\select-subject\`), so it works regardless
   of which version PhotoGIMP's config patch targets.

**Restart GIMP** and use **Select → Select Subject**.

> Tip: if the model was already downloaded (e.g. from a previous install),
> re-run with `-SkipModel` to skip the ~980 MB download.

## Install (Linux)

No installer script is bundled for Linux — it's three steps (Ubuntu/Debian
shown; Arch/Fedora just swap the package manager):

```bash
# 1. GIMP 3 + a venv-capable CPython 3.10+
#    Ubuntu: sudo apt install gimp python3-venv
#    Arch:   sudo pacman -S gimp python
# 2. Create the ML venv in the standard location the plug-in looks for:
python3 -m venv ~/GIMP/select-subject-env
~/GIMP/select-subject-env/bin/pip install -r requirements.txt
# 3. Copy the three plug-in files into a subfolder of GIMP's config dir
#    (GIMP 3.2 shown):
mkdir -p ~/.config/GIMP/3.2/plug-ins/select-subject
cp select-subject.py select-subject-daemon.py select-subject-worker.py \
   ~/.config/GIMP/3.2/plug-ins/select-subject/
```

**Restart GIMP** → **Select → Select Subject**. The ~980 MB model downloads
automatically on first run to `~/.rembg/models/bria-rmbg/` (override with
`REMBG_HOME`).

**GPU (optional):** inference runs on CPU by default (onnxruntime CPU). With
an NVIDIA GPU, install `onnxruntime-gpu` in the venv instead and rembg
auto-detects CUDA. AMD cards need a ROCm build of onnxruntime
(distribution-dependent); CPU is the reliable default.

## Uninstall (one-click)
Double-click **`uninstall.bat`** (or run
`powershell -ExecutionPolicy Bypass -File uninstall.ps1`). It shows you
exactly what it will remove, asks for confirmation, then removes:
- the plug-in folder from every GIMP 3.x config dir,
- the ML venv at `%USERPROFILE%\GIMP\select-subject-env`,
- the BRIA model at `%LOCALAPPDATA%\rembg\models\bria-rmbg`,
- small log/state files in `%TEMP%`.

It **does not** touch GIMP itself, your images, other plug-ins, or the
registry (nothing was written there). Use `-Force` to skip the Y/N prompt.

> Portable build? Just delete its folder — it's fully self-contained.

## Security / scanning
This repo is open source — the `.ps1` installers are plain text, so the
safest "scan" is reading them. If you'd prefer a tool's verdict:
1. Download the file or zip from a **release** (not from a chat/forum link).
2. Upload it to **[VirusTotal](https://www.virustotal.com/guide/scan-file/)**
   — it scans with ~70 antivirus engines at once and shows each result.
3. GitHub also **scans every repository file with VirusTotal automatically**;
   the repo page will display a warning banner if anything ever matches.

Nothing in the installer phones home, writes to the registry, or asks for
admin rights. If a download ever looks modified (different name, added
files, a `.exe` you didn't expect), **don't run it** — report it and get the
file again from the GitHub releases page.

## Portable version (Windows; no install, works off a USB drive)
1. Run **`portable.ps1`** (requires a standalone CPython 3.14 x64 on PATH,
   which it auto-detects). It builds a self-contained folder:
   `runtime\` (bundled Python + ML stack), `models\` (the ONNX model),
   `plug-ins\select-subject\`, a launcher `.bat`, and a README.
2. Copy the whole folder to any Windows x64 machine that has GIMP 3.x.
3. Double-click **`select-subject-portable-gimp.bat`** → GIMP opens with
   **Select → Select Subject**. No admin, no network, no install.

The launcher sets `SELECT_SUBJECT_HOME` to the portable root; the plug-in
then finds the bundled `runtime\` Python and `models\` automatically.
Pass `-Zip` to also produce a distributable zip in `dist\`.

## How the two GIMP flavours are handled
PhotoGIMP does **not** ship its own binary — it installs the *same* GIMP 3
and applies a config/theme/shortcuts patch. Two practical differences,
both handled here:
- It can make GIMP read a **different versioned config dir** than the
  installed version. → The installer copies the plug-in into **all**
  `%APPDATA%\GIMP\3.*` dirs.
- It is **GIMP 3.0+ only**. → The installer detects the GIMP version and
  gives a clear error if only 2.10 is present.

The plug-in itself (`gi.repository.Gimp` GObject API) is identical for
both — no PhotoGIMP-specific code path exists.

## Files
| File | Role |
|---|---|
| `select-subject.py` | GIMP menu command; composites, talks to daemon |
| `select-subject-daemon.py` | Persistent ML daemon (TCP loopback, line-JSON) |
| `select-subject-worker.py` | One-shot ML fallback (no daemon) |
| `install.ps1` / `install.bat` | Standalone installer |
| `uninstall.ps1` / `uninstall.bat` | One-click uninstaller |
| `portable.ps1` | Portable bundle builder |
| `requirements.txt` | Exact ML package pins |

## Notes & troubleshooting
- **First run is slow** (model load ~14 s). That's one-time per daemon
  lifetime; the daemon idles up to 20 min then exits.
- **No console windows** should appear during normal use.
- **Daemon log:** `%TEMP%\select_subject_daemon.log` (Windows) or
  `/tmp/select_subject_daemon.log` (Linux) — check it if a selection is
  never produced.
- **Model location:** `%LOCALAPPDATA%\rembg\models\bria-rmbg\bria-rmbg.onnx`
  (Windows), `~/.rembg/models/bria-rmbg/bria-rmbg.onnx` (Linux), or
  `<portable>\models\` (portable). Override with `REMBG_HOME`.
- **Custom Python:** set `SELECT_SUBJECT_PY` to point the plug-in at a
  different Python interpreter (`python.exe` on Windows, `bin/python3`
  on Linux).
- The plug-in **never edits your layers** — it works on a flattened copy and
  returns only a selection.

## Development
```
gimp-console --batch-interpreter=plug-in-script-fu-eval -b 'gimp_image_list' 
```
The plug-in can be driven headless for E2E testing (see the project's test
harness). `SELECT_SUBJECT_DEBUG=<path>` makes it write a JSON result file.

## License
See `LICENSE`. The BRIA RMBG-2.0 model is distributed by BRIA AI under its
own license; it is downloaded automatically at install time.
