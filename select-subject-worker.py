#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
select-subject ML worker  (runs OUTSIDE GIMP, inside the ML venv)

Usage:
    python select-subject-worker.py <input_image> <output_mask_png>

Reads an image, runs a U2-Net subject segmentation (rembg), and writes the
subject's ALPHA channel out as a grayscale (L-mode) PNG.  White = subject,
black = background, with soft anti-aliased edges.  GIMP uses that grayscale
image as a channel/selection mask (luminance-based), so this is exactly the
format the GIMP plugin needs.

The model (u2net) is auto-downloaded on first run to rembg's pooch cache.
"""
import sys
import time


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
    from rembg import remove

    inp = Image.open(input_path).convert("RGB")

    t1 = time.time()
    print("model+inference start ...", file=sys.stderr)
    # remove() -> RGBA PIL image: subject opaque, background transparent.
    out = remove(inp)
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
