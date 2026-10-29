# Select Subject — GIMP 3 plug-in (Photoshop-style)

One-click "select the main subject" for **GIMP 3.x** (Windows **and** Linux),
using the **BRIA
RMBG-2.0** AI model (the same class of model Adobe Photoshop's *Select
Subject* relies on). It composites the **visible layer stack**, runs the
model, and returns a selection — non-destructive, exactly like Photoshop.

**Works with both vanilla GIMP and PhotoGIMP.** PhotoGIMP is a config-only
patch for GIMP 3.0+ (same binary, same plug-in API, same menu system), so
this plug-in runs identically under both.

## What it does
1. Duplicates the image and **flattens only the visible layers** (a copy —
   your document is untouched).
2. Runs **BRIA RMBG-2.0** on the composite via a **short-lived local
   daemon** (it exits right after each selection, releasing the model's
   RAM).
3. Converts the alpha mask back into a **GIMP selection** on the original
   image.

**Speed:** ~25–40 s per 1080p image on CPU: ~15–25 s to load the model
into a fresh daemon, then ~10–15 s to segment + matte. Because the daemon
is short-lived, every run pays the model load (warm loads after the first
are faster than a cold start after a reboot). A rare case is fast: if the
previous selection *failed* and the daemon is still warm, a retry reuses
it. Inference is **CPU by default** (onnxruntime CPU) — no GPU needed.
GPU acceleration is supported when your `onnxruntime` build provides a
GPU provider — the daemon picks it up automatically (always with CPU
fallback): **AMD Radeon** on Windows via the `onnxruntime-directml`
build (see *Install (one-click)* and *GPU inference on AMD (Windows —
DirectML)*), AMD on Linux via `onnxruntime-rocm` (*Install (Linux)*),
NVIDIA via `onnxruntime-gpu`.

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
>
> **AMD Radeon GPU (Windows):** run `install.ps1 -Amd` instead of
> `install.bat` — same steps, but it installs the `onnxruntime-directml`
> build and verifies `DmlExecutionProvider` before finishing (see *GPU
> inference on AMD (Windows — DirectML)* below).

## Install (Linux)

Use the bundled script (Ubuntu/Debian, Arch, Fedora, …):

```bash
./setup-ml-venv.sh            # CPU inference (default)
./setup-ml-venv.sh --rocm     # AMD GPU inference (ROCm, see below)
```

It creates the venv at `~/GIMP/select-subject-env` (override with
`SELECT_SUBJECT_HOME`), installs the ML stack, and prints the
onnxruntime version + available execution providers so you can see what
got installed. Then copy the plug-in into GIMP's config dir:

```bash
mkdir -p ~/.config/GIMP/3.2/plug-ins/select-subject
cp select-subject.py select-subject-daemon.py select-subject-worker.py \
   ~/.config/GIMP/3.2/plug-ins/select-subject/
```

**Restart GIMP** → **Select → Select Subject**. The ~1 GB model downloads
automatically **on first run only** — the plug-in checks rembg's cache
first and skips the download when the model is already there (no skip
flag needed). Cache: `~/.rembg/models/bria-rmbg/` (override with
`REMBG_HOME`).

### GPU inference on AMD (Linux — ROCm)

`--rocm` installs `onnxruntime-rocm` (AMD's ROCm GPU build of onnxruntime,
from PyPI) instead of the CPU build. Requirements (tested on Arch with
ROCm 7.2, CPython 3.14, onnxruntime-rocm 1.22.2.post3):

- **Linux only** (the wheels are `manylinux x86_64`);
- **CPython 3.11–3.14** — onnxruntime-rocm 1.22.x ships `cp310`–`cp314`
  manylinux wheels only (no source distro); the script picks the
  newest of 3.14 → 3.11 it finds;
- the **system ROCm 7.x runtime** (provides `libamdhip64`, `librocblas`,
  `libhipblas`, `libMIOpen`, `libhiprtc`, `libamd_comgr`,
  `libhsa-runtime64`, …). On Arch:

  ```bash
  sudo pacman -S rocm-hip-sdk rocblas hipblas hipfft rocsolver rocrand
  sudo usermod -aG render,video "$USER"   # log out and back in after
  rocm-smi                                # sanity check
  ```

  Other distros: install the ROCm 7.x SDK/runtime packages for your
  distro, or AMD's `rocm` tarball (extracted so the libraries land in
  `/opt/rocm/lib`).

The setup script bakes the runtime environment into the venv's
`python`/`python3` launchers — `LD_LIBRARY_PATH` pointing at
`/opt/rocm/lib` (plus the `migraphx`/`hip` sub-dirs when present) and
`HSA_OVERRIDE_GFX_VERSION=11.0.0` — so no extra shell setup is needed
when GIMP spawns the daemon. The override matters on **RDNA3** cards
(RX 7000 series, e.g. 7900 XTX): without it those cards can silently
fall back to CPU.

The plug-in detects the ROCm provider automatically (it checks for
`ROCMExecutionProvider` explicitly, which rembg's own auto-detect misses)
and always falls back to CPU. The daemon log line
`active providers: ...` shows what actually got used; `rocm-smi` should
show GPU utilization while a selection runs.

**NVIDIA:** install `onnxruntime-gpu` into the venv instead; the plug-in
picks CUDA up the same way. **No supported GPU?** CPU inference is the
reliable default and needs none of the above.

### GPU inference on AMD (Windows — DirectML)

DirectML is Microsoft's cross-vendor GPU stack: any DirectX-12 GPU — AMD
Radeon, Intel Arc, … — runs onnxruntime through it, so no vendor driver
stack or ROCm install is required.

- **Windows 10/11 x64** + a current AMD Adrenalin GPU driver (WDDM,
  DirectX 12).
- Build/refresh the venv with the AMD build:

      setup-ml-venv.bat --amd            (alias: --dml)

  This removes the CPU `onnxruntime`, installs
  `onnxruntime-directml==1.24.4`, and verifies that
  `DmlExecutionProvider` is available before finishing.
- No further setup: the daemon detects `DmlExecutionProvider`
  automatically and always falls back to CPU if anything errors.
  Confirm in the daemon log line `active providers: ...` (it should read
  `DmlExecutionProvider, CPUExecutionProvider`), and watch GPU utilization
  in the AMD Adrenalin overlay while a selection runs.

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
| `select-subject-daemon.py` | Short-lived ML daemon (one segment, then exits; TCP loopback, line-JSON) |
| `select-subject-worker.py` | One-shot ML fallback (no daemon) |
| `install.ps1` / `install.bat` | Standalone installer |
| `uninstall.ps1` / `uninstall.bat` | One-click uninstaller |
| `portable.ps1` | Portable bundle builder |
| `setup-ml-venv.sh` / `setup-ml-venv.bat` | ML venv setup (Linux: `--rocm` flag for AMD GPU; Windows: `--amd`/`--dml` flag for AMD Radeon via DirectML, CPU default) |
| `requirements.txt` | Exact ML package pins (CPU build — GPU: swap in `onnxruntime-directml` (AMD/Windows) or `onnxruntime-rocm` (AMD/Linux), as noted in the file) |

## Notes & troubleshooting
- **Each run takes ~15–25 s to load the model** — the daemon is
  short-lived (it exits right after the selection so the ~6 GB of model
  RAM is released). Orphaned daemons backstop-exit after 5 min idle or
  2 h total.
- **Model check:** on every daemon start the plug-in checks rembg's cache
  for the model and logs `model already downloaded: ... (skipping
  download)` or `downloading bria-rmbg.onnx (one-time, ~1 GB)` — so the
  ~1 GB fetch happens exactly once per machine.
- **Which GPU/CPU is actually in use?** The daemon log prints
  `active providers: ...` at startup (e.g. `ROCMExecutionProvider,
  CPUExecutionProvider`, `DmlExecutionProvider, CPUExecutionProvider`,
  or plain `CPUExecutionProvider`).
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
