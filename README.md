# Select Subject — GIMP 3 plug-in (Photoshop-style)

One-click "select the main subject" for **GIMP 3.x**, using the **BRIA
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
- Windows x64
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

**Restart GIMP** and use **Image → Select Subject**.

> Tip: if the model was already downloaded (e.g. from a previous install),
> re-run with `-SkipModel` to skip the ~980 MB download.

## Portable version (no install, works off a USB drive)
1. Run **`portable.ps1`** (requires a standalone CPython 3.14 x64 on PATH,
   which it auto-detects). It builds a self-contained folder:
   `runtime\` (bundled Python + ML stack), `models\` (the ONNX model),
   `plug-ins\select-subject\`, a launcher `.bat`, and a README.
2. Copy the whole folder to any Windows x64 machine that has GIMP 3.x.
3. Double-click **`select-subject-portable-gimp.bat`** → GIMP opens with
   **Image → Select Subject**. No admin, no network, no install.

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
| `portable.ps1` | Portable bundle builder |
| `requirements.txt` | Exact ML package pins |

## Notes & troubleshooting
- **First run is slow** (model load ~14 s). That's one-time per daemon
  lifetime; the daemon idles up to 20 min then exits.
- **No console windows** should appear during normal use.
- **Daemon log:** `%TEMP%\select_subject_daemon.log` — check it if a
  selection is never produced.
- **Model location:** `%LOCALAPPDATA%\rembg\models\bria-rmbg\bria-rmbg.onnx`
  (standard) or `<portable>\models\` (portable). Override with `REMBG_HOME`.
- **Custom Python:** set `SELECT_SUBJECT_PY` to point the plug-in at a
  different `python.exe`.
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
