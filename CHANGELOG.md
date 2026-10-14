# Changelog

All notable changes to **Select Subject** are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- **Linux support (Windows + Linux):** the plug-in now documents and supports
  a standard Linux install (venv at `~/GIMP/select-subject-env`, plug-in
  files in `~/.config/GIMP/<ver>/plug-ins/select-subject/`). The daemon and
  process-spawn code paths were already portable (`os.name`-guarded
  `creationflags`); this closes the last Windows-only assumption.
- **`setup-ml-venv.sh` / `setup-ml-venv.bat`:** venv setup scripts for both
  platforms. The Linux script takes a **`--rocm` flag** that installs
  `onnxruntime-migraphx` (AMD's GPU build, from PyPI) instead of the CPU
  build; it requires CPython 3.11–3.13 (AMD wheel constraint) and refuses
  to fall back silently.
- **AMD GPU inference (ROCm / MIGraphX):** the daemon and worker now detect
  `MIGraphXExecutionProvider` explicitly (rembg's built-in auto-detect only
  looks for `ROCMExecutionProvider` and would silently fall back to CPU on
  AMD's current wheels), request it with a CPU fallback, and log
  `active providers: ...` at startup so you can verify GPU use. NVIDIA
  (`CUDAExecutionProvider`) is picked up by the same logic.
- **Model auto-detection:** the daemon/worker check rembg's cache
  (`BriaRmBgSession.resolve_existing`) before touching the network and log
  `model already downloaded: ... (skipping download)` vs
  `downloading bria-rmbg.onnx (one-time, ~1 GB)` — the ~1 GB fetch happens
  exactly once per machine, no manual skip flag needed.
- **GIMP 3 progress bar:** `Gimp.progress_init/set_text/update/end` drives
  a real progress bar in GIMP while the selection runs (no terminal output
  to watch).

### Changed
- **ML venv discovery is cross-platform:** `Scripts\python.exe` on Windows,
  `bin/python3` (falling back to `bin/python`) on Linux. Removed the
  hardcoded developer-only Windows path; the `~/GIMP/select-subject-env`
  standard location is now used identically on both platforms.
- The worker now builds its rembg session explicitly (same provider logic
  as the daemon) instead of letting `remove()` create one inline, so GPU
  provider selection is identical on both code paths.

### Fixed
- **Crash on the mask-compositing step:** a reversed `Gegl.Buffer.copy`
  wrote tiles into the wrong drawable (removed temp layer), tripping
  `gimp_plug_in_handle_tile_put` and making GIMP kill the plug-in's child
  process. Source/destination are now in the correct order; verified with a
  full headless GIMP 3.2 repro on a 1080p image.

## [1.0.0] - 2026-10-14

### Added
- **GIMP 3 "Select Subject" plug-in** — AI subject selection in the spirit of
  Adobe Photoshop's *Select Subject*.
  - Composites the full visible layer stack (blended, like Photoshop) before
    segmenting — layers, opacity, and masks all respected.
  - Uses **BRIA RMBG-2.0** segmentation via a persistent local daemon, so the
    ~1 GB model is loaded once and reused for fast follow-up selections.
  - Non-destructive: result is a normal GIMP selection; original image
    untouched.
  - Menu: **Select → Select Subject** (top-level *Select* menu; registered
    with GIMP 3's `add_menu_path("<Image>/Select")` menu path).
- **Standalone installer** (`install.bat` → `install.ps1`):
  - Detects GIMP 3.x (registry + PATH), rejects GIMP 2.x.
  - Creates the ML venv with GIMP's bundled Python, installs pinned
    requirements, downloads the BRIA model, copies the plug-in into every
    GIMP 3.x config version dir, verifies the ML stack.
- **Portable build** (`portable.ps1`):
  - Self-contained bundle (`runtime/` venv + `models/` + launcher `.bat`)
    that runs with no system install — USB-drive friendly.
  - Verifies with a real 256×256 inference test.
- **One-click uninstaller** (`uninstall.bat` → `uninstall.ps1`):
  - Shows exactly what it will remove, asks for confirmation, then removes
    the plug-in folder, the ML venv, the model, and log/state files.
  - Safe: touches nothing else (no registry, no GIMP, no images);
    `-Force` skips the prompt.
- **Security notes** in the README: VirusTotal scanning link and guidance
  for verifying downloads before running anything.
- **Alpha matting** (on by default) — refines the raw mask into tighter,
  cleaner edges (measured: 0.47% → 0.34% soft-edge pixels on a 1080p test
  image, identical coverage). Disable with `SELECT_SUBJECT_MATTING=0`.
- `requirements.txt` with exact pins (rembg 2.0.85, onnxruntime 1.31.0
  CPU, numpy 2.5.4, pillow 12.3.0, scipy 1.18.1, scikit-image 0.26.0,
  pymatting 1.1.16, pooch 1.9.0).
- `README.md` with install/portable/PhotoGIMP/speed documentation.
- MIT `LICENSE`.

### Notes
- Works identically with **vanilla GIMP** and **PhotoGIMP** (both are GIMP
  3.0+; PhotoGIMP is a config-only patch — the installer handles its versioned
  config directory automatically).
- No visible console windows during operation (daemon/worker launched hidden).
- onnxruntime is CPU-only: expect ~25 s cold start (model load) and ~12 s per
  1080p image afterwards; matting adds negligible time on clean renders.

[1.0.0]: https://github.com/BlasterRobYT/select-subject/releases/tag/1.0.0
