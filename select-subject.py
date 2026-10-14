#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#    select-subject.py
#
#    GIMP 3 "Select Subject" plug-in.
#    Segments the main subject (BRIA RMBG via rembg) and turns the mask
#    into a GIMP selection -- mirroring Photoshop's "Select Subject".
#
#    Architecture:
#      * This file runs INSIDE GIMP (GIMP's bundled Python, GObject API).
#      * It composites ALL visible layers (duplicate + flatten on a copy),
#        snapshots the result to a temp PNG, and gets a grayscale mask
#        back from the ML stack (white = subject), which it applies as
#        the image selection.
#      * The heavy ML stack (rembg / onnxruntime / numpy / PIL) lives in a
#        separate venv.  A resident daemon (select-subject-daemon.py) in
#        that venv keeps the model in RAM so repeat runs are ~5-10s; the
#        one-shot worker (select-subject-worker.py) is the fallback.
#
#    Requirements:
#      * ML venv with rembg+onnxruntime (default path below; override with
#        the SELECT_SUBJECT_PY / SELECT_SUBJECT_WORKER environment variables).
#        First run downloads the ~1 GB bria-rmbg model to rembg's cache.
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp
gi.require_version('Gegl', '0.4')
from gi.repository import Gegl
gi.require_version('Gio', '2.0')
from gi.repository import Gio
from gi.repository import GObject
from gi.repository import GLib

import os
import sys
import time
import json
import socket
import traceback
import tempfile
import subprocess


def N_(message):
    return message


def _(message):
    return GLib.dgettext(None, message)


def log(msg):
    """Write a short trace line to GIMP's stderr (harmless)."""
    try:
        sys.stderr.write("select-subject: %s\n" % msg)
        sys.stderr.flush()
    except Exception:
        pass


def dbg(msg):
    log(msg)


# --- Debug: write ground-truth JSON when SELECT_SUBJECT_DEBUG is set --------
_DBG_PATH = os.environ.get("SELECT_SUBJECT_DEBUG", "")


def _dbg_write(status_name, image, error_text, tb):
    if not _DBG_PATH:
        return
    info = {"status": status_name, "error": error_text,
            "traceback": tb, "selection": None}
    try:
        if image is not None:
            res = Gimp.Selection.bounds(image)
            info["selection"] = list(res)
    except Exception:
        info["selection"] = "selection-query-error"
    try:
        with open(_DBG_PATH, "w", encoding="utf-8") as fh:
            json.dump(info, fh, indent=2)
    except Exception:
        pass


# --- ML runtime location (overridable via environment) -----------------------
# GIMP's own Python has no numpy/onnxruntime/rembg, so the model runs in a
# dedicated runtime (a CPython venv).  Cross-platform (Windows + Linux).
# Resolution order:
#   1. SELECT_SUBJECT_PY environment variable (explicit override).
#   2. $SELECT_SUBJECT_HOME/runtime/<venv-python>  (PORTABLE: the launcher
#      exports SELECT_SUBJECT_HOME = the portable root, so a plug-in copied
#      into GIMP's config dir finds the bundled runtime).
#   3. ~/GIMP/select-subject-env/<venv-python>  (STANDARD install location,
#      created by the installer on Windows; mirror it on Linux).
# <venv-python> is Scripts\python.exe on Windows, bin/python3 (or
# bin/python) on Linux.
def _portable_root():
    root = os.environ.get("SELECT_SUBJECT_HOME", "").strip()
    if root and os.path.isdir(root):
        return root
    return ""


def _venv_python_relpaths():
    """OS-appropriate interpreter paths, relative to the venv root."""
    if os.name == "nt":
        return [os.path.join("Scripts", "python.exe")]
    return [os.path.join("bin", "python3"),
            os.path.join("bin", "python")]


def _default_venv_python():
    roots = []
    root = _portable_root()
    if root:
        roots.append(os.path.join(root, "runtime"))
    roots.append(os.path.join(os.path.expanduser("~"), "GIMP",
                              "select-subject-env"))
    candidates = [os.path.join(r, p) for r in roots
                  for p in _venv_python_relpaths()]
    for cand in candidates:
        if os.path.isfile(cand):
            return cand
    return candidates[0]


_VENV_PYTHON = os.environ.get("SELECT_SUBJECT_PY",
                              _default_venv_python())
# The worker script ships alongside this plug-in (same folder).
_ML_WORKER = os.environ.get(
    "SELECT_SUBJECT_WORKER",
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "select-subject-worker.py"))


def _model_env():
    """Environment for the ML subprocesses.

    PORTABLE: when SELECT_SUBJECT_HOME is set and its "models" folder
    exists, point REMBG_HOME at it so the bundled .onnx is used and nothing
    is downloaded.  STANDARD: leave REMBG_HOME alone so rembg uses its
    default LOCALAPPDATA/rembg cache (populated by the installer, or
    auto-downloaded on first run).  An explicitly-set REMBG_HOME always wins.
    """
    env = dict(os.environ)
    if "REMBG_HOME" not in env:
        root = _portable_root()
        if root:
            bundled = os.path.join(root, "models")
            if os.path.isdir(bundled):
                env["REMBG_HOME"] = bundled
    # Alpha matting (default ON: gives the tightest Photoshop-like edges on
    # clean renders; costs a little CPU).  Override with SELECT_SUBJECT_MATTING=0.
    env.setdefault("SELECT_SUBJECT_MATTING", "1")
    return env


# ---------------------------------------------------------------------------
# Persistent ML daemon
# ---------------------------------------------------------------------------
# Re-launching the ONNX model every click costs ~30 s.  A small daemon
# (select-subject-daemon.py) runs in the SAME venv, keeps the model resident
# in RAM, and answers line-delimited JSON requests over a loopback TCP
# socket.  The plug-in spawns it lazily on first use; the daemon writes a
# state file and self-terminates after 20 min idle / 2 h total, so nothing
# lingers after GIMP closes.
# ---------------------------------------------------------------------------
DAEMON_STATE = os.path.join(tempfile.gettempdir(),
                            "select_subject_daemon.json")


def _daemon_alive(state):
    """True if the daemon named by the state file answers a TCP ping.

    (NOT os.kill -- on Windows that is GenerateConsoleCtrlEvent and fails
    for detached/no-console processes, so it is useless as a liveness
    probe.  A round-trip ping to the daemon's port is the real question.)
    """
    try:
        port = int(state["port"])
    except Exception:
        return False
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=3)
        s.sendall((json.dumps({"cmd": "ping"}) + "\n").encode("utf-8"))
        buf = b""
        while not buf.endswith(b"\n"):
            c = s.recv(65536)
            if not c:
                break
            buf += c
        s.close()
        return bool(json.loads(buf.decode("utf-8")).get("ok"))
    except Exception:
        return False


def _ensure_daemon(venv_python):
    """Return True if a live daemon is running (reused or freshly spawned)."""
    state_path = DAEMON_STATE
    # Reuse a live daemon if one exists.
    try:
        with open(state_path, "r", encoding="utf-8") as fh:
            st = json.load(fh)
        if _daemon_alive(st):
            return True
    except Exception:
        pass
    # Otherwise spawn a fresh one.
    daemon_py = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "select-subject-daemon.py")
    if not os.path.exists(daemon_py):
        return False
    log("spawning daemon: %s" % daemon_py)
    # Log the daemon's stderr so a crash during model-load is diagnosable.
    try:
        log_dir = tempfile.gettempdir()
        log_path = os.path.join(log_dir, "select_subject_daemon.log")
        log_fh = open(log_path, "ab", buffering=0)
    except Exception:
        log_fh = subprocess.DEVNULL
    try:
        flags = 0
        if os.name == "nt":
            # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP: fully detached,
            # survives the calling (GIMP batch) session terminating.
            flags = 0x00000008 | 0x00000200
        subprocess.Popen(
            [venv_python, daemon_py],
            stdout=subprocess.DEVNULL,
            stderr=log_fh,
            stdin=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
            env=_model_env(),
        )
        try:
            log_fh.close()
        except Exception:
            pass
    except Exception as e:
        dbg("daemon spawn failed: %r" % e)
        return False
    # Wait up to ~75 s for the model to load and the state file to appear.
    deadline = time.time() + 75
    while time.time() < deadline:
        try:
            with open(state_path, "r", encoding="utf-8") as fh:
                st = json.load(fh)
            if _daemon_alive(st):
                log("daemon ready pid=%s port=%s"
                    % (st.get("pid"), st.get("port")))
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _daemon_segment(in_png, out_png, timeout_s=300):
    """Send a segment request to the daemon; return (ok, error)."""
    try:
        with open(DAEMON_STATE, "r", encoding="utf-8") as fh:
            port = int(json.load(fh)["port"])
    except Exception as e:
        return False, "no daemon state: %r" % e
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=10)
    except Exception as e:
        return False, "cannot reach daemon port %s: %r" % (port, e)
    s.settimeout(timeout_s)
    try:
        s.sendall((json.dumps({"cmd": "segment",
                               "in": in_png, "out": out_png}) + "\n")
                  .encode("utf-8"))
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        resp = json.loads(buf.decode("utf-8"))
        if resp.get("ok"):
            log("daemon segment ok in %.1fs" % resp.get("seconds", -1))
            return True, None
        return False, resp.get("error", "unknown")
    except Exception as e:
        return False, "daemon error: %r" % e
    finally:
        try:
            s.close()
        except Exception:
            pass


class SelectSubject(Gimp.PlugIn):
    """GIMP 3 plug-in: ML "Select Subject" for the active layer."""

    ## GimpPlugIn virtual methods ##

    def do_query_procedures(self):
        return ['select-subject']

    def do_create_procedure(self, name):
        Gegl.init(None)

        procedure = Gimp.ImageProcedure.new(self, name,
                                            Gimp.PDBProcType.PLUGIN,
                                            self.run, None)

        procedure.set_image_types("RGB*, GRAY*")
        procedure.set_sensitivity_mask(
            Gimp.ProcedureSensitivityMask.DRAWABLE)

        procedure.set_documentation(
            _("Select the main subject using an ML segmentation model."),
            _("Runs a U-2-Net subject segmentation on the active layer and "
              "replaces the current selection with the detected subject."),
            name)
        procedure.set_menu_label(_("_Select Subject..."))
        procedure.set_attribution("BlasterRob", "blasterrob@users.noreply.github.com", "2026")
        # GIMP 3 menu paths: <Prefix>/<label>/<label>...  The <Prefix>
        # selects the menu manager (one of <Image>, <Layers>, <Channels>,
        # <Paths>, <Colormap>, <Brushes>, <Dynamics>, <MyPaintBrushes>,
        # <Gradients>, <Palettes>, <Patterns>, <ToolPresets>, <Fonts>,
        # <Buffers>).  Path elements after the prefix are matched by
        # SUBMENU LABEL (mnemonic stripped), walking the menu tree from that
        # manager's root (see bundled foggify: "<Image>/Filters/Decor").
        # "<Image>/Select" targets the top-level "Select" menu of the image
        # menubar (image-menu.ui), so the item lands inside Select ->
        # "Select Subject...".  This proc acts on the active layer.
        procedure.add_menu_path("<Image>/Select")

        return procedure

    # ------------------------------------------------------------------ run
    def run(self, procedure, run_mode, image, drawables, config, data):
        if len(drawables) != 1:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error.new_literal(Gimp.PlugIn.error_quark(),
                                       _("Select Subject needs one active "
                                         "drawable."), 0))

        drawable = drawables[0]

        # -- Photoshop parity: segment the COMPOSITE of all visible layers,
        #    not just the active one.  duplicate() + flatten() do this on a
        #    throwaway copy; the original image is never touched.  Falls back
        #    to the active drawable if compositing fails for any reason.
        work = None
        try:
            work = image.duplicate()
            composite = work.flatten()
            if composite is not None:
                drawable = composite
                log("composited visible layers -> %s %dx%d"
                    % (composite.__class__.__name__,
                       composite.get_width(), composite.get_height()))
        except Exception as e:
            dbg("duplicate/flatten failed (%r); using active drawable" % e)
            work = None

        # -- sanity: ML venv present? --------------------------------------
        if not os.path.isfile(_VENV_PYTHON) or not os.path.isfile(_ML_WORKER):
            _dbg_write("CALLING_ERROR:venv-missing", image,
                       "venv/worker not found", None)
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error.new_literal(
                    Gimp.PlugIn.error_quark(),
                    _("Could not find the ML environment:\n%s\n%s\n\n"
                      "Set the SELECT_SUBJECT_PY and SELECT_SUBJECT_WORKER "
                      "environment variables to fix this.")
                    % (_VENV_PYTHON, _ML_WORKER), 0))

        # -- temp files -----------------------------------------------------
        stamp = time.strftime('%Y%m%d%H%M%S')
        base = "select_subject_%s_%d" % (stamp, os.getpid())
        temp_in = os.path.join(tempfile.gettempdir(), base + "_in.png")
        temp_out = os.path.join(tempfile.gettempdir(), base + "_out.png")

        try:
            # -- geometry ---------------------------------------------------
            layer_w = drawable.get_width()
            layer_h = drawable.get_height()
            off_ok, off_x, off_y = drawable.get_offsets()
            if not off_ok:
                off_x = off_y = 0
            image_w = image.get_width()
            image_h = image.get_height()

            # -- 1. snapshot the active layer to a real PNG -----------------
            # NOTE: Gegl.Buffer.save(path, roi) does NOT write a PNG — it
            # serializes the buffer in GIMP's internal GEGL cache format
            # (file starts with the 'GEGL' magic), which PIL cannot read.
            # The validated export path (see rt_probe.py) is: copy the
            # drawable's pixels into a temp single-layer image, then use
            # Gimp.file_save(), which dispatches to GIMP's real PNG exporter.
            layer_buf = drawable.get_buffer()
            layer_buf.flush()
            snap = Gimp.Image.new(layer_w, layer_h,
                                  Gimp.ImageType.RGBA_IMAGE)
            snap_layer = Gimp.Layer.new(snap, "select-subject-snap",
                                        layer_w, layer_h,
                                        Gimp.ImageType.RGBA_IMAGE,
                                        100.0, Gimp.LayerMode.NORMAL)
            snap.insert_layer(snap_layer, None, 0)
            src_roi = Gegl.Rectangle.new(0, 0, layer_w, layer_h)
            snap_layer.get_buffer().copy(src_roi, Gegl.AbyssPolicy.NONE,
                                         layer_buf, src_roi)
            snap_ok = Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, snap,
                                     Gio.File.new_for_path(temp_in), None)
            if not snap_ok or not os.path.isfile(temp_in):
                raise RuntimeError("Gimp.file_save could not write "
                                   "the layer snapshot to %s" % temp_in)

            # Diagnostic: what did save() actually write?
            in_size = os.path.getsize(temp_in) if os.path.isfile(temp_in) else -1
            in_magic = b""
            if in_size > 0:
                with open(temp_in, "rb") as fh:
                    in_magic = fh.read(16)

            # -- 2. run the model.  PREFER the resident daemon (model already
            #    in RAM, ~5-10s); if no daemon is available, fall back to the
            #    one-shot worker (reloads the model, ~30s). -----------------
            used_daemon = False
            if _ensure_daemon(_VENV_PYTHON):
                d_ok, d_err = _daemon_segment(temp_in, temp_out)
                used_daemon = d_ok
                if not d_ok:
                    dbg("daemon segment failed (%r); trying one-shot" % d_err)

            if not used_daemon:
                cmd = [_VENV_PYTHON, _ML_WORKER, temp_in, temp_out]
                # No console flash on the one-shot fallback either.
                if os.name == "nt":
                    _kw = {"creationflags": 0x00000008}  # CREATE_NO_WINDOW
                else:
                    _kw = {}
                proc = subprocess.run(cmd, capture_output=True, text=True,
                                      env=_model_env(), **_kw)
                if proc.returncode != 0 or not os.path.isfile(temp_out):
                    detail = (proc.stderr or proc.stdout or "").strip()
                    if len(detail) > 500:
                        detail = detail[-500:]
                    _dbg_write(
                        "WORKER_ERROR:in_size=%d:in_magic=%r" % (in_size, in_magic),
                        image, detail, None)
                    return procedure.new_return_values(
                        Gimp.PDBStatusType.EXECUTION_ERROR,
                        GLib.Error.new_literal(
                            Gimp.PlugIn.error_quark(),
                            _("Subject segmentation failed (exit %d).\n%s")
                            % (proc.returncode, detail), 0))

            # -- 3. load the mask (grayscale: white = subject) --------------
            # Use Gimp.file_load (validated in rt_probe.py) rather than
            # Gegl.Buffer.load, then copy the mask's pixels into the channel.
            mask_img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE,
                                      Gio.File.new_for_path(temp_out))
            mask_layers = mask_img.get_layers()
            if isinstance(mask_layers, tuple):
                mask_layers = mask_layers[0]
            mask_layer = mask_layers[0]
            mask_buf = mask_layer.get_buffer()
            mask_buf.flush()

            # -- 4. build a full-image-sized channel and copy the mask into
            #        it at the layer's offset -------------------------------
            channel = Gimp.Channel.new(image, "Select Subject mask",
                                       image_w, image_h,
                                       100.0, Gegl.Color.new("white"))
            # position is a REQUIRED arg in GIMP 3 (no default).
            image.insert_channel(channel, None, 0)

            ch_buf = channel.get_buffer()
            src_rect = Gegl.Rectangle.new(0, 0, layer_w, layer_h)
            dst_rect = Gegl.Rectangle.new(off_x, off_y, layer_w, layer_h)
            # copy() auto-converts between pixel formats (gray -> gray).
            mask_buf.copy(src_rect, Gegl.AbyssPolicy.NONE, ch_buf, dst_rect)
            ch_buf.flush()
            channel.update(0, 0, image_w, image_h)

            # -- 5. apply the channel as the selection (white = selected) ---
            Gimp.context_push()
            image.undo_group_start()
            image.select_item(Gimp.ChannelOps.REPLACE, channel)
            image.undo_group_end()
            Gimp.context_pop()

            # -- 6. tidy up: drop the helper channel + temp files -----------
            image.remove_channel(channel)
            Gimp.displays_flush()

            _dbg_write("SUCCESS", image, None, None)
            return procedure.new_return_values(
                Gimp.PDBStatusType.SUCCESS, GLib.Error())

        except Exception as e:  # noqa: BLE001 - report any failure to GIMP
            _dbg_write("EXECUTION_ERROR", image, str(e), traceback.format_exc())
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR,
                GLib.Error.new_literal(Gimp.PlugIn.error_quark(),
                                       _("Select Subject error: %s") % e, 0))
        finally:
            # Drop the throwaway composite image (and its flattened layer).
            if work is not None:
                try:
                    work.delete()
                except Exception:
                    pass
            for p in (temp_in, temp_out):
                try:
                    if os.path.isfile(p):
                        os.remove(p)
                except OSError:
                    pass


Gimp.main(SelectSubject.__gtype__, sys.argv)
