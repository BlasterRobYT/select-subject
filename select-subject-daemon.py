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

Liveness / cleanup:
    * Writes <temp>/select_subject_daemon.json = {pid, port, model} once
      the model is loaded (that file is the discovery mechanism).
    * Exits on its own after IDLE_LIMIT seconds without a request, or
      after HARD_LIMIT seconds total, and removes the state file -- so
      nothing lingers after GIMP closes.
"""
import json
import os
import socket
import sys
import tempfile
import time

STATE = os.path.join(tempfile.gettempdir(), "select_subject_daemon.json")
IDLE_LIMIT = 20 * 60    # exit after 20 min idle
HARD_LIMIT = 2 * 3600   # exit after 2 h total


def log(msg):
    sys.stderr.write("select-subject-daemon: %s\n" % msg)
    sys.stderr.flush()


def main():
    t0 = time.time()
    from rembg import remove, new_session
    session = new_session("bria-rmbg")
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
            try:
                req = json.loads(conn.recv(65536).decode("utf-8"))
                cmd = req.get("cmd")
                if cmd == "ping":
                    resp = {"ok": True, "model": "bria-rmbg"}
                elif cmd == "segment":
                    t = time.time()
                    from PIL import Image
                    img = Image.open(req["in"]).convert("RGB")
                    out = remove(img, session=session)
                    alpha = out.split()[-1]   # grayscale: 255 = subject
                    alpha.save(req["out"])
                    resp = {"ok": True,
                            "seconds": round(time.time() - t, 1),
                            "wh": [img.width, img.height]}
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
            last = time.time()
    finally:
        try:
            srv.close()
        except OSError:
            pass
        try:
            os.remove(STATE)
        except OSError:
            pass


if __name__ == "__main__":
    main()
