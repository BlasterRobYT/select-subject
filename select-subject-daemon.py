#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
select-subject-daemon.py  --  persistent ML worker (runs OUTSIDE GIMP).

Holds the BRIA RMBG subject-matting model loaded in RAM and serves
segmentation requests over a loopback TCP socket, so repeated "Select
Subject" invocations in GIMP take ~5-10s instead of ~30s (no model
reload).  The GIMP plug-in spawns this lazily on first use and talks to
it via the state file it writes next to itself.

Protocol (line-delimited JSON over TCP, 127.0.0.1):
    client -> {"cmd": "ping"}
    client -> {"cmd": "segment", "in": "<input.png>", "out": "<mask.png>"}
    server -> {"ok": true, "seconds": 7.9, "wh": [w, h]}
             or {"ok": false, "error": "..."}
    client -> {"cmd": "shutdown"}
    server -> {"ok": true}   (then the daemon exits immediately)

Liveness / cleanup:
    * Writes <temp>/select_subject_daemon.json = {pid, port, model} once
      the model is loaded (that file is the discovery mechanism).
    * The plug-in sends "shutdown" right after a successful segment so
      the multi-GB model RAM is released as soon as masking is done.
    * Backstops: exits on its own after IDLE_LIMIT seconds without a
      request, or after HARD_LIMIT seconds total, and removes the state
      file -- so nothing lingers after GIMP closes.
"""
import json
import os
import socket
import sys
import tempfile
import time

STATE = os.path.join(tempfile.gettempdir(), "select_subject_daemon.json")
IDLE_LIMIT = 5 * 60     # 5 min (backstop; the plug-in sends 'shutdown' after each segment)
HARD_LIMIT = 2 * 3600   # exit after 2 h total


def _segment_kwargs():
    """Extra remove() kwargs.

    Alpha matting (pymatting) refines the raw RMBG-2.0 alpha into a
    tighter, cleaner edge -- measured on the Grunlac test image it cut
    soft-edge pixels from 0.47% to 0.34% with identical coverage, and
    costs ~0 s extra on clean renders (matting is a no-op where the raw
    mask is already sharp).  Default ON; set SELECT_SUBJECT_MATTING=0 to
    disable.
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


def log(msg):
    sys.stderr.write("select-subject-daemon: %s\n" % msg)
    sys.stderr.flush()


def _pick_providers():
    """Return an explicit execution-provider list when a GPU build of
    onnxruntime is installed, else None (let rembg decide -- i.e. CPU).

    Priority order:
      * MIGraphX -- AMD's current GPU build on Linux (onnxruntime-migraphx);
        rembg's own auto-detect misses 'MIGraphXExecutionProvider' and would
        silently fall back to CPU on those wheels, so it is checked first.
      * DirectML -- any DirectX-12 GPU (AMD Radeon on Windows via the
        onnxruntime-directml build); rembg's auto-detect does not look for
        'DmlExecutionProvider' either.
      * then ROCm, then CUDA (NVIDIA), with CPU fallback.
    """
    try:
        import onnxruntime as ort
    except Exception:
        return None
    avail = set(ort.get_available_providers())
    for ep in ("MIGraphXExecutionProvider", "DmlExecutionProvider",
               "ROCMExecutionProvider", "CUDAExecutionProvider"):
        if ep in avail:
            return [ep, "CPUExecutionProvider"]
    return None


def _ensure_model():
    """Check whether the bria-rmbg model was already downloaded.

    Returns (path, downloaded).  When the model is missing from rembg's
    cache it is fetched once here (sha256-verified, progress on stderr);
    when it is present, no network traffic happens at all.
    """
    from rembg.sessions.bria_rmbg import BriaRmBgSession as M
    existing = M.resolve_existing("bria-rmbg.onnx")
    if existing is not None:
        return existing, False
    log("model not cached - downloading bria-rmbg.onnx (one-time, ~1 GB)")
    return M.download_models(), True


def main():
    t0 = time.time()
    from rembg import remove, new_session
    import onnxruntime as ort
    model_path, downloaded = _ensure_model()
    if downloaded:
        log("model downloaded to %s" % model_path)
    else:
        log("model already downloaded: %s (skipping download)" % model_path)
    providers = _pick_providers()
    if providers:
        log("requesting providers: %s" % ", ".join(providers))
    # onnxruntime's default memory arena pre-allocates and then HOLDS
    # several GB until process exit -- that is what this daemon pinned at
    # 8-13 GB resident.  The daemon is short-lived now (the plug-in sends
    # 'shutdown' right after each segment), but even a transient 13 GB
    # spike is unacceptable on a 32 GB machine, so disable the arena and
    # let ORT free per-tensor memory as it goes (~1-2 GB instead).
    sess_opts = ort.SessionOptions()
    # ORT >= 1.20 renamed enable_mem_arena -> enable_cpu_mem_arena;
    # set whichever attribute this build has.
    for _attr in ("enable_cpu_mem_arena", "enable_mem_arena"):
        if hasattr(sess_opts, _attr):
            setattr(sess_opts, _attr, False)
            break
    sess_opts.enable_mem_pattern = False
    session = new_session("bria-rmbg", providers=providers, sess_opts=sess_opts)
    try:
        log("active providers: %s"
            % ", ".join(session.inner_session.get_providers()))
    except Exception:
        pass
    load_s = time.time() - t0
    log("model loaded in %.1fs" % load_s)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))   # ephemeral port
    port = srv.getsockname()[1]
    srv.listen(8)
    with open(STATE, "w", encoding="utf-8") as fh:
        json.dump({"pid": os.getpid(), "port": port, "model": "bria-rmbg",
                   "load_s": round(load_s, 1)}, fh)
    log("ready pid=%d port=%d (state=%s)" % (os.getpid(), port, STATE))

    start = time.time()
    last = time.time()
    try:
        while True:
            if (time.time() - last > IDLE_LIMIT or
                    time.time() - start > HARD_LIMIT):
                log("exiting (idle/hard limit)")
                break
            srv.settimeout(1.0)
            try:
                conn, _addr = srv.accept()
            except socket.timeout:
                continue
            conn.settimeout(300)
            shutdown = False
            try:
                req = json.loads(conn.recv(65536).decode("utf-8"))
                cmd = req.get("cmd")
                if cmd == "ping":
                    resp = {"ok": True, "model": "bria-rmbg"}
                elif cmd == "segment":
                    t = time.time()
                    from PIL import Image
                    img = Image.open(req["in"]).convert("RGB")
                    out = remove(img, session=session, **_segment_kwargs())
                    alpha = out.split()[-1]   # grayscale: 255 = subject
                    alpha.save(req["out"])
                    resp = {"ok": True,
                            "seconds": round(time.time() - t, 1),
                            "wh": [img.width, img.height]}
                elif cmd == "shutdown":
                    # The plug-in calls this after a successful segment so
                    # the model RAM is released immediately, not after the
                    # idle timeout.
                    log("shutdown requested by plug-in; exiting")
                    resp = {"ok": True}
                    shutdown = True
                else:
                    resp = {"ok": False, "error": "unknown cmd %r" % cmd}
            except Exception as e:  # noqa: BLE001 - report back to client
                resp = {"ok": False, "error": repr(e)}
            try:
                conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass
            if shutdown:
                break
            last = time.time()
    finally:
        try:
            srv.close()
        except OSError:
            pass
        try:
            # Only remove the state file if it still names US: a faster
            # replacement daemon may have written its own state file by
            # the time we get here (rapid successive runs).  (Read, CLOSE,
            # then unlink -- Windows refuses to delete a file that still
            # has an open handle.)
            pid_in_state = -1
            with open(STATE, "r", encoding="utf-8") as fh:
                pid_in_state = int(json.load(fh).get("pid", -1))
            if pid_in_state == os.getpid():
                os.remove(STATE)
        except Exception:
            pass


if __name__ == "__main__":
    main()
