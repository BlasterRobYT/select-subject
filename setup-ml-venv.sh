#!/usr/bin/env bash
# setup-ml-venv.sh -- create (or update) the ML venv for the select-subject
# GIMP plugin. Linux (tested on Arch).
#
#   ./setup-ml-venv.sh            CPU inference (default onnxruntime)
#   ./setup-ml-venv.sh --rocm     AMD GPU inference (onnxruntime-migraphx)
#
# The venv lands in ~/GIMP/select-subject-env (override: SELECT_SUBJECT_HOME).
#
# --rocm prerequisites (system-wide, NOT installed by this script):
#   * ROCm 7.x libraries:        sudo pacman -S rocm-hip-sdk rocm-opencl-sdk
#   * GPU group membership:      sudo usermod -aG render,video "$USER"
#                                (log out and back in afterwards)
#   * RDNA3 cards (RX 7000, e.g. 7900 XTX) that fall back to CPU:
#                                export HSA_OVERRIDE_GFX_VERSION=11.0.0
#   * Verify the GPU stack:      rocm-smi
set -euo pipefail

ROCM=0
[[ "${1:-}" == "--rocm" ]] && ROCM=1

VENV="${SELECT_SUBJECT_HOME:-$HOME/GIMP/select-subject-env}"

# AMD's onnxruntime-migraphx wheels ship for CPython 3.11-3.13 only
# (cp310/cp311/cp312/cp313), so the ROCm path uses python3.12 when
# available and refuses anything else.
if [[ $ROCM == 1 ]]; then
    PY="python3.12"
    command -v "$PY" >/dev/null 2>&1 || PY="python3.13"
    command -v "$PY" >/dev/null 2>&1 || PY="python3.11"
else
    PY="python3"
fi

if ! command -v "$PY" >/dev/null 2>&1; then
    echo "error: $PY not found." >&2
    if [[ $ROCM == 1 ]]; then
        echo "The --rocm build needs CPython 3.11-3.13 (AMD's wheels only" >&2
        echo "ship cp310-cp313). On Arch:  sudo pacman -S python3.12" >&2
    fi
    exit 1
fi

echo ">> creating venv at $VENV (using $PY: $("$PY" --version 2>&1))"
"$PY" -m venv "$VENV"
VPY="$VENV/bin/python"
"$VPY" -m pip install --upgrade pip

if [[ $ROCM == 1 ]]; then
    echo ">> installing rembg + onnxruntime-migraphx (AMD GPU build)"
    "$VPY" -m pip install rembg
    "$VPY" -m pip install "onnxruntime-migraphx==1.27.1"
else
    echo ">> installing rembg + CPU onnxruntime"
    "$VPY" -m pip install "rembg[cpu]"
fi

echo ">> verifying"
"$VPY" - <<'EOF'
import onnxruntime as ort
import rembg
print("onnxruntime %s  providers=%s"
      % (ort.__version__, ort.get_available_providers()))
print("rembg %s" % getattr(rembg, "__version__", "?"))
EOF

echo ">> done: $VENV"
echo "   next: restart GIMP and pick Select > Select Subject."
