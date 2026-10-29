#!/usr/bin/env bash
# setup-ml-venv.sh -- create (or update) the ML venv for the select-subject
# GIMP plugin. Linux (tested on Arch).
#
#   ./setup-ml-venv.sh            CPU inference (default onnxruntime)
#   ./setup-ml-venv.sh --rocm     AMD GPU inference (onnxruntime-rocm)
#
# The venv lands in ~/GIMP/select-subject-env (override: SELECT_SUBJECT_HOME).
#
# --rocm prerequisites (system-wide, NOT installed by this script):
#   * A ROCm 7.x runtime stack for your distro. On Arch (tested):
#         sudo pacman -S rocm-hip-sdk rocblas hipblas hipfft rocsolver rocrand
#     (provides libamdhip64, librocblas, libMIOpen, libhipblas, libhipfft,
#               librocsolver, libamd_comgr, libhsa-runtime64, ...)
#   * RDNA GPU group membership (log out and back in afterwards):
#         sudo usermod -aG render,video "$USER"
#   * Sanity-check the GPU stack:   rocm-smi
#   * RDNA3 cards (RX 7000 series, e.g. 7900 XTX): the script bakes
#                HSA_OVERRIDE_GFX_VERSION=11.0.0 into the venv so those
#     cards do not fall back to CPU.
set -euo pipefail

ROCM=0
[[ "${1:-}" == "--rocm" ]] && ROCM=1

VENV="${SELECT_SUBJECT_HOME:-$HOME/GIMP/select-subject-env}"

# onnxruntime-rocm 1.22.x ships a cp314 wheel; prefer the newest CPython
# that has one (3.14 -> 3.13 -> 3.12 -> 3.11) so the install actually works.
if [[ $ROCM == 1 ]]; then
    PY="python3.14"
    command -v "$PY" >/dev/null 2>&1 || PY="python3.13"
    command -v "$PY" >/dev/null 2>&1 || PY="python3.12"
    command -v "$PY" >/dev/null 2>&1 || PY="python3.11"
else
    PY="python3"
fi

if ! command -v "$PY" >/dev/null 2>&1; then
    echo "error: $PY not found." >&2
    if [[ $ROCM == 1 ]]; then
        echo "The --rocm build needs a CPython with a cp wheel for " >&2
        echo "onnxruntime-rocm (3.11-3.14; the 1.22.x cp314 wheel is the " >&2
        echo "safest). On Arch:  sudo pacman -S python3.14" >&2
    fi
    exit 1
fi

echo ">> creating venv at $VENV (using $PY: $(\"$PY\" --version 2>&1))"
"$PY" -m venv "$VENV"
VPY="$VENV/bin/python"
"$VPY" -m pip install --upgrade pip >/dev/null

if [[ $ROCM == 1 ]]; then
    echo ">> installing rembg + onnxruntime-rocm (AMD GPU build)"
    "$VPY" -m pip install rembg
    # rembg pulls the CPU onnxruntime wheel by default; the ROCm build is a
    # separate wheel that shares the same onnxruntime package, so drop the
    # CPU one first and install the GPU build in its place.
    "$VPY" -m pip uninstall -y onnxruntime >/dev/null 2>&1 || true
    "$VPY" -m pip install "onnxruntime-rocm"
else
    echo ">> installing rembg + CPU onnxruntime"
    "$VPY" -m pip install "rembg[cpu]"
fi

if [[ $ROCM == 1 ]]; then
    # Bake the ROCm runtime environment into the venv so the daemon
    # (spawned by GIMP, outside any shell) finds the ROCm shared libraries
    # and the RDNA3 override without extra setup: wrap the venv's
    # 'python'/'python3' launchers, keeping the real interpreter
    # (e.g. python3.14) untouched.
    PYVER="$("$VPY" -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
    INTERP="python${PYVER}"
    LIBDIRS=""
    for d in /opt/rocm/lib /opt/rocm/lib/migraphx/lib /opt/rocm/hip/lib \
             /usr/local/lib /usr/lib; do
        [[ -d "$d" ]] && LIBDIRS="${LIBDIRS:+$LIBDIRS:}$d"
    done
    if [[ -z "$LIBDIRS" ]]; then
        echo "warning: no system ROCm lib dir found (/opt/rocm/lib, ...)." >&2
        echo "         The ROCMExecutionProvider will not load without them." >&2
    fi
    for L in python python3; do
        cat > "$VENV/bin/$L" <<EOF
#!/bin/sh
# select-subject venv: prepend ROCm runtime libs, set RDNA3 override
export LD_LIBRARY_PATH="$LIBDIRS\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
export HSA_OVERRIDE_GFX_VERSION="\${HSA_OVERRIDE_GFX_VERSION:-11.0.0}"
exec "\$(dirname -- "\$0")/$INTERP" "\$@"
EOF
        chmod +x "$VENV/bin/$L"
    done
    echo ">> wrapped $VENV/bin/python{,3} (LD_LIBRARY_PATH=$LIBDIRS)"
    echo "   HSA_OVERRIDE_GFX_VERSION defaults to 11.0.0"
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
