#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
select-subject ML worker  (runs OUTSIDE GIMP, inside the ML venv)

Usage:
    python select-subject-worker.py <input_image> <output_mask_png>

Reads an image, runs BRIA RMBG-2.0 subject segmentation (rembg), and writes the
subject's ALPHA channel out as a grayscale (L-mode) PNG.  White = subject,
black = background, with soft anti-aliased edges.  GIMP uses that grayscale
image as a channel/selection mask (luminance-based), so this is exactly the
format the GIMP plugin needs.

The model (bria-rmbg) is checked for in rembg's cache at startup and
downloaded automatically on first run (one time, ~1 GB) -- no manual
skip flag needed.
"""
import os
import sys
import time


def _segment_kwargs():
    """Extra remove() kwargs (see the daemon for the rationale).

    Alpha matting refines the raw RMBG-2.0 edge into a tighter, cleaner
    selection -- default ON; set SELECT_SUBJECT_MATTING=0 to disable.
    """
    if os.environ.get("SELECT_SUBJECT_MATTING", "1").strip().lower() in (
            "0", "off", "false", "no"):
        return {}
    return {
        "post_process_mask": True,
        "alpha_matting": True,
        "alpha_matting_foreground_threshold": 240,
        "alpha_matting_background_threshold": 10,
        "alpha_matting_erode_size": 10,
    }


def _pick_providers():
    """GPU execution-provider list if a GPU onnxruntime build is installed,
    else None (rembg picks CPU).  Same logic as the daemon -- duplicated
    here because dashed module names can't be imported directly.  MIGraphX
    is checked first; rembg's auto-detect misses 'MIGraphXExecutionProvider'
    and would fall back to CPU on AMD's current GPU wheels.
    """
    try:
        import onnxruntime as ort
    except Exception:
        return None
    avail = set(ort.get_available_providers())
    for ep in ("MIGraphXExecutionProvider", "ROCMExecutionProvider",
               "CUDAExecutionProvider"):
        if ep in avail:
            return [ep, "CPUExecutionProvider"]
    return None


def _ensure_model():
    """Check whether the bria-rmbg model was already downloaded.

    Returns (path, downloaded).  Missing model is fetched once here
    (sha256-verified, progress on stderr); a cached model causes no
    network traffic.
    """
    from rembg.sessions.bria_rmbg import BriaRmBgSession as M
    existing = M.resolve_existing("bria-rmbg.onnx")
    if existing is not None:
        return existing, False
    print("select-subject: model not cached - downloading bria-rmbg.onnx "
          "(one-time, ~1 GB)", file=sys.stderr)
    return M.download_models(), True


def main():
    if len(sys.argv) != 3:
        print("usage: select-subject-worker.py <input_image> <output_mask_png>",
              file=sys.stderr)
        return 2

    input_path = sys.argv[1]
    output_path = sys.argv[2]

    t0 = time.time()

    # Lazy imports so the usage error path doesn't need the heavy deps.
    from PIL import Image
    from rembg import remove, new_session

    model_path, downloaded = _ensure_model()
    print("model: %s (%s)"
          % (model_path, "downloaded now" if downloaded
             else "already downloaded"), file=sys.stderr)
    providers = _pick_providers()
    if providers:
        print("requesting providers: %s" % ", ".join(providers),
              file=sys.stderr)

    inp = Image.open(input_path).convert("RGB")

    t1 = time.time()
    print("model+inference start ...", file=sys.stderr)
    # Build the session explicitly (same provider logic as the daemon)
    # and run inference with it.
    session = new_session("bria-rmbg", providers=providers)
    # remove() -> RGBA PIL image: subject opaque, background transparent.
    out = remove(inp, session=session, **_segment_kwargs())
    print("inference done in %.1fs (input %dx%d)"
          % (time.time() - t1, inp.width, inp.height), file=sys.stderr)

    # The alpha channel IS the mask: 255 = subject, 0 = background.
    alpha = out.getchannel("A") if hasattr(out, "getchannel") else out.split()[-1]
    alpha.save(output_path)

    print("wrote mask %s (%dx%d) in %.1fs total"
          % (output_path, alpha.width, alpha.height, time.time() - t0),
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
