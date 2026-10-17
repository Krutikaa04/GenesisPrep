"""Local web interface for the salvage tool (opt-in; the command line is unchanged).

    python -m deadbits.webui [--port 8765] [--no-browser] [--samples-dir DIR] [--workdir DIR]

The page is a front end for exactly the code path the CLI uses: files are copied into a private session folder
(`<workdir>/<session>/in`, by default under the system temp folder), `deadbits.cli.run` writes `<workdir>/<session>/out` (per-file JSON plus report.json) and
the browser shows, and offers for download, those very files. The server binds to 127.0.0.1 only, serves no
third-party content, validates the Host/Origin of every request and removes its session folders on exit.
"""
import argparse
import base64
import contextlib
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import time
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from . import cli
from .engine import MAX_INPUT_BYTES
from .version import VERSION
from .webui_assets import APP_CSS, APP_JS, INDEX_HTML

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_UPLOAD_BYTES = min(MAX_INPUT_BYTES, 64 * 1024 * 1024)
MAX_BYTES_WINDOW = 4096
MAX_BODY_JSON = 1 << 20
STALE_SECONDS = 24 * 3600
SESSION_RE = re.compile(r"^s-[0-9a-f]{12}$")
MUTATIONS = {
    "truncate_50": ("cut-in-half", "cut in half"),
    "flip_middle": ("flipped-byte", "one byte flipped in the middle"),
    "zero_block": ("zeroed-block", "a 32-byte block zeroed"),
}
_WINDOWS_BAD = re.compile(r'[<>:"|?*\x00-\x1f]')
ROOT = Path(__file__).resolve().parent.parent


def default_samples_dir() -> Path:
    return ROOT / "samples" / "official" / "samples"


def default_workdir() -> Path:
    """Session copies live in the system temp folder: the project folder may be synced to a cloud drive."""
    return Path(tempfile.gettempdir()) / "deadbits-ui"


def safe_name(raw: str):
    """A single, filesystem-safe file name. Returns (name, was_changed) or (None, False) when unusable."""
    original = raw or ""
    name = original.replace("\\", "/").split("/")[-1].strip()
    name = _WINDOWS_BAD.sub("_", name).rstrip(" .")
    if not name or name in (".", "..") or len(name.encode("utf-8", "replace")) > 200:
        return None, False
    return name, name != original


def mutate(data: bytes, kind: str) -> bytes:
    """Deliberate, reproducible damage for the resilience demo (same ideas as tools/make_variants.py)."""
    if kind == "truncate_50":
        return data[: len(data) // 2]
    out = bytearray(data)
    if kind == "flip_middle" and out:
        out[len(out) // 2] ^= 0xFF
    elif kind == "zero_block" and out:
        length = min(32, len(out))
        start = max(0, (len(out) - length) // 2)
        out[start:start + length] = bytes(length)
    return bytes(out)


def read_hints(samples_dir: Path) -> dict:
    """Context hints from the organizer kit's HINTS.md table (the kit's folder above samples/ or beside it)."""
    for candidate in (samples_dir.parent / "HINTS.md", samples_dir / "HINTS.md"):
        try:
            text = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        hints = {}
        for line in text.splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) == 2 and cells[0] not in ("file", "---") and not set(cells[0]) <= set("-"):
                hints[cells[0]] = "" if cells[1] == "(none)" else cells[1]
        return hints
    return {}


class Session:
    def __init__(self, root: Path):
        self.id = "s-" + secrets.token_hex(6)
        self.dir = root / self.id
        self.inp = self.dir / "in"
        self.out = self.dir / "out"
        self.inp.mkdir(parents=True)
        self.out.mkdir()
        self.lock = threading.Lock()
        self.notes = {}   # staged name -> human note (e.g. which damage was applied)

    def staged(self):
        rows = []
        for entry in sorted(os.scandir(self.inp), key=lambda e: e.name):
            if entry.is_file(follow_symlinks=False):
                rows.append({"name": entry.name, "size": entry.stat().st_size, "note": self.notes.get(entry.name, "")})
        return rows

    def unique(self, name: str) -> str:
        if not (self.inp / name).exists():
            return name
        stem, dot, ext = name.rpartition(".")
        if not dot or not stem:
            stem, ext = name, ""
        else:
            ext = "." + ext
        n = 2
        while (self.inp / ("%s (%d)%s" % (stem, n, ext))).exists():
            n += 1
        return "%s (%d)%s" % (stem, n, ext)

    def add(self, name: str, data: bytes, note: str = ""):
        final = self.unique(name)
        (self.inp / final).write_bytes(data)
        if note:
            self.notes[final] = note
        return final

    def remove_tree(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class App:
    """State shared by all requests: kit samples, session registry, and the working folder."""

    def __init__(self, samples_dir: Path, workdir: Path):
        self.samples_dir = Path(samples_dir)
        self.workdir = Path(workdir)
        self.sessions = {}
        self.lock = threading.Lock()
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.clean_stale()

    def clean_stale(self):
        cutoff = time.time() - STALE_SECONDS
        for entry in os.scandir(self.workdir):
            if SESSION_RE.match(entry.name) and entry.is_dir(follow_symlinks=False):
                try:
                    if entry.stat().st_mtime < cutoff:
                        shutil.rmtree(entry.path, ignore_errors=True)
                except OSError:
                    pass

    def new_session(self) -> Session:
        session = Session(self.workdir)
        with self.lock:
            self.sessions[session.id] = session
        return session

    def get(self, sid: str):
        with self.lock:
            return self.sessions.get(sid)

    def drop(self, sid: str):
        with self.lock:
            session = self.sessions.pop(sid, None)
        if session:
            session.remove_tree()
        return session is not None

    def close(self):
        with self.lock:
            sessions, self.sessions = list(self.sessions.values()), {}
        for session in sessions:
            session.remove_tree()

    def samples(self):
        hints = read_hints(self.samples_dir)
        rows = []
        try:
            entries = sorted(os.scandir(self.samples_dir), key=lambda e: e.name)
        except OSError:
            return rows
        for entry in entries:
            if entry.is_file(follow_symlinks=False):
                rows.append({"name": entry.name, "size": entry.stat().st_size, "hint": hints.get(entry.name, "")})
        return rows

    def sample_bytes(self, name: str):
        for row in self.samples():     # names come from the listing, never from the request path
            if row["name"] == name:
                return (self.samples_dir / name).read_bytes()
        return None


def run_session(session: Session) -> dict:
    """Run the CLI's own recovery on the session folder and package what it wrote."""
    for child in session.out.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink()
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        report = cli.run(session.inp, session.out)
    files = []
    for row in report["files"]:
        doc = None
        target = session.out / (row["file"] + ".json")
        try:
            doc = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = None
        try:
            size = (session.inp / row["file"]).stat().st_size
        except OSError:
            size = 0
        files.append({"name": row["file"], "size": size, "doc": doc, "note": session.notes.get(row["file"], "")})
    report_bytes = (session.out / "report.json").read_bytes()
    return {"report": report, "files": files, "stderr": stderr.getvalue().splitlines(),
            "reportSha256": hashlib.sha256(report_bytes).hexdigest(),
            "location": str(session.out)}


def build_zip(session: Session) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for entry in sorted(os.scandir(session.out), key=lambda e: e.name):
            if entry.is_file(follow_symlinks=False):
                info = zipfile.ZipInfo(entry.name, (2000, 1, 1, 0, 0, 0))   # fixed time: reproducible archive
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, Path(entry.path).read_bytes())
    return buffer.getvalue()


CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def make_handler(app: App, port_holder: list):
    class Handler(BaseHTTPRequestHandler):
        server_version = "DeadBitsUI/" + VERSION
        protocol_version = "HTTP/1.1"
        verbose = False

        # --- plumbing -------------------------------------------------------------------------------------
        def log_message(self, fmt, *args):
            if self.verbose:
                sys.stderr.write("webui: " + fmt % args + "\n")

        def _headers(self, status, ctype, length, extra=None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            if self.close_connection:
                self.send_header("Connection", "close")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", CSP)
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()

        def _send(self, status, body: bytes, ctype, extra=None):
            self._headers(status, ctype, len(body), extra)
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, payload, status=200):
            self._send(status, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

        def _error(self, status, message):
            self._json({"error": message}, status)

        def _host_ok(self):
            hosts = {"127.0.0.1:%d" % port_holder[0], "localhost:%d" % port_holder[0]}
            if (self.headers.get("Host") or "").lower() not in hosts:
                return False
            origin = self.headers.get("Origin")
            return origin is None or origin.lower() in {"http://" + h for h in hosts}

        def _body(self, limit):
            raw = self.headers.get("Content-Length")
            if raw is None or not raw.isdigit():
                self._error(411, "Content-Length is required")
                return None
            length = int(raw)
            if length > limit:
                self.close_connection = True
                self._error(413, "That file is larger than the %d MiB the interface accepts" % (limit >> 20))
                return None
            data = self.rfile.read(length)
            if len(data) != length:
                self._error(400, "Upload was cut short")
                return None
            return data

        def _route(self):
            parts = urlsplit(self.path)
            segments = [unquote(s) for s in parts.path.split("/") if s]
            query = {k: v[-1] for k, v in parse_qs(parts.query, keep_blank_values=True).items()}
            return segments, query

        # --- dispatch -------------------------------------------------------------------------------------
        def _guard(self):
            if not self._host_ok():
                self._error(403, "Requests must come from this computer")
                return False
            return True

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            if not self._guard():
                return
            segments, query = self._route()
            try:
                if not segments:
                    return self._send(200, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
                if segments == ["app.css"]:
                    return self._send(200, APP_CSS.encode("utf-8"), "text/css; charset=utf-8")
                if segments == ["app.js"]:
                    return self._send(200, APP_JS.encode("utf-8"), "text/javascript; charset=utf-8")
                if segments == ["api", "ping"]:
                    return self._json({"ok": True, "version": VERSION})
                if segments == ["api", "info"]:
                    return self._json({"version": VERSION, "samples": app.samples(),
                                       "maxUploadBytes": MAX_UPLOAD_BYTES,
                                       "mutations": [{"id": k, "label": v[1]} for k, v in MUTATIONS.items()]})
                if len(segments) >= 4 and segments[:2] == ["api", "sessions"]:
                    session = app.get(segments[2])
                    if session is None:
                        return self._error(404, "That session has ended")
                    return self._session_get(session, segments[3:], query)
                self._error(404, "Not found")
            except Exception as exc:   # never let a handler bug kill the connection thread silently
                self._error(500, "Unexpected error: %s" % type(exc).__name__)

        def do_POST(self):
            if not self._guard():
                return
            segments, query = self._route()
            try:
                if segments == ["api", "sessions"]:
                    return self._json({"id": app.new_session().id}, 201)
                if len(segments) >= 4 and segments[:2] == ["api", "sessions"]:
                    session = app.get(segments[2])
                    if session is None:
                        return self._error(404, "That session has ended")
                    return self._session_post(session, segments[3:], query)
                self._error(404, "Not found")
            except Exception as exc:
                self._error(500, "Unexpected error: %s" % type(exc).__name__)

        def do_DELETE(self):
            if not self._guard():
                return
            segments, _ = self._route()
            try:
                if len(segments) == 3 and segments[:2] == ["api", "sessions"]:
                    return self._json({"ended": app.drop(segments[2])})
                if len(segments) == 5 and segments[:2] == ["api", "sessions"] and segments[3] == "files":
                    session = app.get(segments[2])
                    if session is None:
                        return self._error(404, "That session has ended")
                    with session.lock:
                        match = [r for r in session.staged() if r["name"] == segments[4]]
                        if not match:
                            return self._error(404, "That file is not in the list")
                        (session.inp / match[0]["name"]).unlink()
                        session.notes.pop(match[0]["name"], None)
                    return self._json({"removed": segments[4]})
                self._error(404, "Not found")
            except Exception as exc:
                self._error(500, "Unexpected error: %s" % type(exc).__name__)

        # --- session routes -------------------------------------------------------------------------------
        def _session_get(self, session, rest, query):
            if rest == ["files"]:
                return self._json({"files": session.staged()})
            if rest == ["results.zip"]:
                return self._send(200, build_zip(session), "application/zip",
                                  {"Content-Disposition": 'attachment; filename="salvage-results.zip"'})
            if len(rest) == 2 and rest[0] == "out":
                names = {e.name for e in os.scandir(session.out) if e.is_file(follow_symlinks=False)}
                if rest[1] not in names:
                    return self._error(404, "No such result file")
                body = (session.out / rest[1]).read_bytes()
                ascii_name = rest[1].encode("ascii", "replace").decode("ascii").replace('"', "_")
                return self._send(200, body, "application/json; charset=utf-8",
                                  {"Content-Disposition": 'attachment; filename="%s"' % ascii_name})
            if len(rest) == 2 and rest[0] == "bytes":
                staged = {r["name"] for r in session.staged()}
                if rest[1] not in staged:
                    return self._error(404, "No such file")
                try:
                    offset = max(0, int(query.get("offset", "0")))
                    length = max(1, min(MAX_BYTES_WINDOW, int(query.get("length", "256"))))
                except ValueError:
                    return self._error(400, "offset and length must be numbers")
                path = session.inp / rest[1]
                size = path.stat().st_size
                with open(path, "rb") as stream:
                    stream.seek(offset)
                    chunk = stream.read(length)
                return self._json({"offset": offset, "size": size,
                                   "base64": base64.b64encode(chunk).decode("ascii")})
            self._error(404, "Not found")

        def _session_post(self, session, rest, query):
            if rest == ["files"]:
                name, changed = safe_name(query.get("name", ""))
                if name is None:
                    return self._error(400, "That file name cannot be used")
                kind = query.get("mutate", "")
                if kind and kind not in MUTATIONS:
                    return self._error(400, "Unknown damage option")
                data = self._body(MAX_UPLOAD_BYTES)
                if data is None:
                    return
                return self._json(self._stage(session, name, data, kind, changed), 201)
            if rest == ["samples"]:
                body = self._body(MAX_BODY_JSON)
                if body is None:
                    return
                try:
                    request = json.loads(body.decode("utf-8"))
                    names = request["names"]
                    kind = request.get("mutate", "")
                    if not isinstance(names, list) or len(names) > 200 or any(not isinstance(n, str) for n in names):
                        raise ValueError
                    if kind and kind not in MUTATIONS:
                        raise ValueError
                except (ValueError, KeyError, UnicodeDecodeError):
                    return self._error(400, "Bad request")
                added = []
                for sample in names:
                    data = app.sample_bytes(sample)
                    if data is None:
                        return self._error(404, "Unknown sample")
                    added.append(self._stage(session, sample, data, kind, False))
                return self._json({"added": added}, 201)
            if rest == ["run"]:
                with session.lock:
                    return self._json(run_session(session))
            self._error(404, "Not found")

        def _stage(self, session, name, data, kind, renamed):
            note = ""
            if kind:
                stem, dot, ext = name.rpartition(".")
                tag = MUTATIONS[kind][0]
                name = ("%s.%s.%s" % (stem, tag, ext)) if dot and stem else "%s.%s" % (name, tag)
                data = mutate(data, kind)
                note = "Damaged on purpose for this demo: %s." % MUTATIONS[kind][1]
            with session.lock:
                final = session.add(name, data, note)
            return {"name": final, "size": len(data), "note": note, "renamed": bool(renamed or final != name)}

    return Handler


def make_server(port=DEFAULT_PORT, samples_dir=None, workdir=None, verbose=False):
    """Create (not start) the server. `server.app` owns the session folders; call `server.app.close()` to clean up."""
    app = App(samples_dir or default_samples_dir(), workdir or default_workdir())
    port_holder = [port]
    handler = make_handler(app, port_holder)
    handler.verbose = verbose
    server = ThreadingHTTPServer((HOST, port), handler)
    server.daemon_threads = True
    port_holder[0] = server.server_address[1]
    server.app = app
    return server


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m deadbits.webui", description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="port on 127.0.0.1 (default %(default)s)")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    parser.add_argument("--samples-dir", type=Path, help="kit samples offered as examples")
    parser.add_argument("--workdir", type=Path, help="private folder for session copies (default: system temp folder)")
    parser.add_argument("--verbose", action="store_true", help="log requests to stderr")
    args = parser.parse_args(argv)
    try:
        server = make_server(args.port, args.samples_dir, args.workdir, args.verbose)
    except OSError as exc:
        print("webui: cannot start on port %d: %s" % (args.port, exc.strerror or type(exc).__name__), file=sys.stderr)
        return 1
    url = "http://%s:%d/" % (HOST, server.server_address[1])
    print("DeadBits Salvage is running at %s  (Ctrl+C to stop)" % url)
    print("Everything stays on this computer. Working folder: %s" % server.app.workdir)
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.app.close()
        print("Stopped. Session copies removed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
