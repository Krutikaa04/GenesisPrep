"""The local web interface must be a thin, safe front end for the exact CLI code path."""
import http.client
import json
import re
import tempfile
import threading
import unittest
import zipfile
import io
from pathlib import Path
from unittest.mock import patch

from helpers import SAMPLES
from deadbits import cli, webui


class WebUi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.server = webui.make_server(0, SAMPLES, Path(cls.temp.name) / "work")
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server.app.close()
        cls.temp.cleanup()

    def call(self, method, path, body=None, headers=None, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        hdrs = {"Host": host or "127.0.0.1:%d" % self.port}
        hdrs.update(headers or {})
        conn.request(method, path, body=body, headers=hdrs)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, resp, data

    def json(self, method, path, payload=None, **kw):
        body = None if payload is None else json.dumps(payload).encode()
        status, resp, data = self.call(method, path, body, {"Content-Type": "application/json"} if body else None, **kw)
        return status, json.loads(data.decode("utf-8"))

    def session(self):
        status, doc = self.json("POST", "/api/sessions")
        self.assertEqual(status, 201)
        return doc["id"]

    def add_samples(self, sid, names, mutate=""):
        return self.json("POST", "/api/sessions/%s/samples" % sid, {"names": names, "mutate": mutate})

    # --- static page ---------------------------------------------------------------------------------------
    def test_page_assets_are_served_with_restrictive_headers_and_no_external_references(self):
        for path, ctype in (("/", "text/html"), ("/app.css", "text/css"), ("/app.js", "text/javascript")):
            status, resp, data = self.call("GET", path)
            self.assertEqual(status, 200, path)
            self.assertTrue(resp.getheader("Content-Type").startswith(ctype), path)
            self.assertIn("default-src 'none'", resp.getheader("Content-Security-Policy"))
            self.assertEqual(resp.getheader("X-Content-Type-Options"), "nosniff")
            self.assertEqual(resp.getheader("Cache-Control"), "no-store")
            text = data.decode("utf-8")
            self.assertEqual(re.findall(r"(?:src|href)=[\"']https?://", text), [], path)
            self.assertNotIn("url(http", text)
            self.assertNotIn("@import", text)
            # the only absolute URL anywhere is the SVG XML namespace
            self.assertEqual(set(re.findall(r"https?://[^\s'\"<>)]+", text)) - {"http://www.w3.org/2000/svg"}, set(), path)

    def test_ping_is_a_cheap_liveness_check_that_still_enforces_the_host_rule(self):
        status, doc = self.json("GET", "/api/ping")
        self.assertEqual((status, doc["ok"]), (200, True))
        self.assertEqual(self.call("GET", "/api/ping", host="evil.example")[0], 403)
        # the page polls it, shows a friendly message instead of the browser's "Failed to fetch",
        # and tells an unreadable local file apart from a stopped program
        self.assertIn("/api/ping", webui.APP_JS)
        self.assertIn("is not running any more", webui.APP_JS)
        self.assertIn("from your disk", webui.APP_JS)

    def test_unknown_paths_and_methods(self):
        self.assertEqual(self.call("GET", "/nope")[0], 404)
        self.assertEqual(self.call("GET", "/api/sessions/s-000000000000/files")[0], 404)
        self.assertEqual(self.call("POST", "/api/other")[0], 404)

    # --- request validation --------------------------------------------------------------------------------
    def test_requests_for_other_hosts_or_origins_are_refused(self):
        self.assertEqual(self.call("GET", "/api/info", host="evil.example")[0], 403)
        self.assertEqual(self.call("GET", "/api/info", host="127.0.0.1:1")[0], 403)
        self.assertEqual(self.call("POST", "/api/sessions", headers={"Origin": "http://evil.example"})[0], 403)
        ok = "http://127.0.0.1:%d" % self.port
        self.assertEqual(self.call("POST", "/api/sessions", headers={"Origin": ok})[0], 201)
        self.assertEqual(self.call("GET", "/api/info", host="localhost:%d" % self.port)[0], 200)

    def test_server_binds_to_loopback_only(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_info_lists_kit_samples_with_hints_and_never_nested_folders(self):
        status, info = self.json("GET", "/api/info")
        names = [s["name"] for s in info["samples"]]
        self.assertEqual(status, 200)
        self.assertIn("s01.dat", names)
        self.assertNotIn("nested", names)
        hint = {s["name"]: s["hint"] for s in info["samples"]}
        self.assertIn("Municipal library", hint["s01.dat"])
        self.assertEqual(hint["s25_random.bin"], "")

    # --- the core promise: same engine, same bytes as the command line --------------------------------------
    def test_session_output_is_byte_identical_to_the_cli(self):
        sid = self.session()
        status, added = self.add_samples(sid, [p.name for p in sorted(SAMPLES.iterdir()) if p.is_file()])
        self.assertEqual(status, 201)
        upload = b"LB98\x02"      # also exercise the raw upload path with a damaged file
        status, _, data = self.call("POST", "/api/sessions/%s/files?name=my%%20broken.dat" % sid, upload,
                                    {"Content-Type": "application/octet-stream"})
        self.assertEqual(status, 201)
        self.assertEqual(json.loads(data)["name"], "my broken.dat")
        status, result = self.json("POST", "/api/sessions/%s/run" % sid)
        self.assertEqual(status, 200)
        session = self.server.app.get(sid)
        with tempfile.TemporaryDirectory() as expected:
            with patch("sys.stderr", new=io.StringIO()):
                report = cli.run(session.inp, Path(expected))
            self.assertEqual(result["report"], report)
            produced = sorted(p.name for p in session.out.iterdir())
            self.assertEqual(produced, sorted(p.name for p in Path(expected).iterdir()))
            for name in produced:
                self.assertEqual((session.out / name).read_bytes(), (Path(expected) / name).read_bytes(), name)
            for entry in result["files"]:
                self.assertEqual(entry["doc"], json.loads((Path(expected) / (entry["name"] + ".json")).read_text("utf-8")))
            status, _, blob = self.call("GET", "/api/sessions/%s/results.zip" % sid)
            self.assertEqual(status, 200)
            with zipfile.ZipFile(io.BytesIO(blob)) as archive:
                self.assertEqual(sorted(archive.namelist()), produced)
                for name in produced:
                    self.assertEqual(archive.read(name), (Path(expected) / name).read_bytes(), name)
            status, _, raw = self.call("GET", "/api/sessions/%s/out/report.json" % sid)
            self.assertEqual((status, raw), (200, (Path(expected) / "report.json").read_bytes()))
        self.assertTrue(result["location"].endswith("out"))
        self.assertEqual(len(result["reportSha256"]), 64)

    def test_running_again_after_removing_a_file_leaves_no_stale_output(self):
        sid = self.session()
        self.add_samples(sid, ["s01.dat", "s02.dat"])
        self.json("POST", "/api/sessions/%s/run" % sid)
        self.assertEqual(self.json("DELETE", "/api/sessions/%s/files/s02.dat" % sid)[0], 200)
        status, result = self.json("POST", "/api/sessions/%s/run" % sid)
        self.assertEqual([f["name"] for f in result["files"]], ["s01.dat"])
        self.assertEqual(sorted(p.name for p in self.server.app.get(sid).out.iterdir()), ["report.json", "s01.dat.json"])
        self.assertEqual(self.json("DELETE", "/api/sessions/%s/files/s02.dat" % sid)[0], 404)

    def test_damage_demo_renames_copies_and_damages_exactly_as_documented(self):
        sid = self.session()
        original = (SAMPLES / "s01.dat").read_bytes()
        _, added = self.add_samples(sid, ["s01.dat"], "")
        _, cut = self.add_samples(sid, ["s01.dat"], "truncate_50")
        _, flip = self.add_samples(sid, ["s01.dat"], "flip_middle")
        _, zero = self.add_samples(sid, ["s01.dat"], "zero_block")
        names = [x["added"][0]["name"] for x in (added, cut, flip, zero)]
        self.assertEqual(names, ["s01.dat", "s01.cut-in-half.dat", "s01.flipped-byte.dat", "s01.zeroed-block.dat"])
        inp = self.server.app.get(sid).inp
        self.assertEqual((inp / names[0]).read_bytes(), original)
        self.assertEqual((inp / names[1]).read_bytes(), original[: len(original) // 2])
        flipped = bytearray(original)
        flipped[len(original) // 2] ^= 0xFF
        self.assertEqual((inp / names[2]).read_bytes(), bytes(flipped))
        middle = (len(original) - 32) // 2
        self.assertEqual((inp / names[3]).read_bytes()[middle:middle + 32], bytes(32))
        self.assertTrue(all(x["added"][0]["note"] for x in (cut, flip, zero)))
        self.assertEqual(self.add_samples(sid, ["s01.dat"], "shred")[0], 400)

    def test_same_name_twice_is_kept_not_overwritten(self):
        sid = self.session()
        for _ in range(3):
            self.call("POST", "/api/sessions/%s/files?name=a.bin" % sid, b"x", {"Content-Type": "application/octet-stream"})
        names = [r["name"] for r in self.json("GET", "/api/sessions/%s/files" % sid)[1]["files"]]
        self.assertEqual(names, ["a (2).bin", "a (3).bin", "a.bin"])

    # --- hostile input -------------------------------------------------------------------------------------
    def test_unsafe_names_are_neutralised(self):
        sid = self.session()
        post = lambda name: self.call("POST", "/api/sessions/%s/files?name=%s" % (sid, name), b"x",
                                      {"Content-Type": "application/octet-stream"})
        status, _, data = post("..%2F..%2Fevil.txt")
        self.assertEqual((status, json.loads(data)["name"]), (201, "evil.txt"))
        status, _, data = post("C%3A%5Cwin%5Cdrive%3Aname%3F.dat")
        self.assertEqual(status, 201)
        self.assertEqual(json.loads(data)["name"], "drive_name_.dat")
        for bad in ("", "..", ".", "%2F", "a" * 300):
            self.assertEqual(post(bad)[0], 400, bad)
        self.assertEqual(sorted(p.name for p in self.server.app.get(sid).inp.iterdir()), ["drive_name_.dat", "evil.txt"])
        self.assertFalse((self.server.app.workdir / "evil.txt").exists())

    def test_sample_names_must_come_from_the_kit_listing(self):
        sid = self.session()
        for name in ("../s01.dat", "nested", "s99.dat", "..\\s01.dat"):
            self.assertEqual(self.add_samples(sid, [name])[0], 404, name)
        self.assertEqual(self.json("POST", "/api/sessions/%s/samples" % sid, {"names": "s01.dat"})[0], 400)
        self.assertEqual(self.json("POST", "/api/sessions/%s/samples" % sid, {"names": [1]})[0], 400)

    def test_result_and_byte_endpoints_cannot_leave_the_session(self):
        sid = self.session()
        self.add_samples(sid, ["s01.dat"])
        self.json("POST", "/api/sessions/%s/run" % sid)
        for path in ("out/..%2F..%2Fx", "out/..%2Fin%2Fs01.dat", "out/in", "bytes/..%2Fout%2Freport.json", "bytes/report.json"):
            self.assertEqual(self.call("GET", "/api/sessions/%s/%s" % (sid, path))[0], 404, path)

    def test_oversized_upload_is_refused_without_reading_it(self):
        sid = self.session()
        with patch.object(webui, "MAX_UPLOAD_BYTES", 10):
            status, _, data = self.call("POST", "/api/sessions/%s/files?name=big.bin" % sid, b"x" * 11,
                                        {"Content-Type": "application/octet-stream"})
        self.assertEqual(status, 413)
        self.assertEqual(list(self.server.app.get(sid).inp.iterdir()), [])

    def test_byte_windows_are_bounded_and_hostile_numbers_rejected(self):
        sid = self.session()
        self.add_samples(sid, ["s01.dat"])
        raw = (SAMPLES / "s01.dat").read_bytes()
        status, doc = self.json("GET", "/api/sessions/%s/bytes/s01.dat?offset=16&length=32" % sid)
        import base64
        self.assertEqual((status, base64.b64decode(doc["base64"]), doc["size"]), (200, raw[16:48], len(raw)))
        _, doc = self.json("GET", "/api/sessions/%s/bytes/s01.dat?offset=0&length=99999999" % sid)
        self.assertEqual(len(base64.b64decode(doc["base64"])), min(len(raw), webui.MAX_BYTES_WINDOW))
        _, doc = self.json("GET", "/api/sessions/%s/bytes/s01.dat?offset=%d" % (sid, len(raw) + 50))
        self.assertEqual(doc["base64"], "")
        self.assertEqual(self.call("GET", "/api/sessions/%s/bytes/s01.dat?offset=abc" % sid)[0], 400)

    def test_ending_a_session_removes_its_folder(self):
        sid = self.session()
        folder = self.server.app.get(sid).dir
        self.assertTrue(folder.is_dir())
        self.assertEqual(self.json("DELETE", "/api/sessions/%s" % sid), (200, {"ended": True}))
        self.assertFalse(folder.exists())
        self.assertEqual(self.json("DELETE", "/api/sessions/%s" % sid), (200, {"ended": False}))
        self.assertEqual(self.call("POST", "/api/sessions/%s/run" % sid)[0], 404)

    def test_hostile_content_survives_as_data_and_never_breaks_the_run(self):
        sid = self.session()
        evil = b"<script>alert(1)</script>\r\n\x00\xff" * 50
        self.call("POST", "/api/sessions/%s/files?name=%%26lt%%3Bimg%%20onerror%%3D1%%27.txt" % sid, evil, {"Content-Type": "application/octet-stream"})
        status, result = self.json("POST", "/api/sessions/%s/run" % sid)
        self.assertEqual(status, 200)
        self.assertEqual(result["files"][0]["doc"]["source_file"], "&lt;img onerror=1'.txt")
        # the page builds all dynamic content with textContent/createTextNode, never innerHTML
        self.assertNotIn("innerHTML", webui.APP_JS)
        self.assertNotIn("insertAdjacentHTML", webui.APP_JS)
        self.assertNotIn("document.write", webui.APP_JS)
        self.assertNotIn("eval(", webui.APP_JS)


class Helpers(unittest.TestCase):
    def test_safe_name(self):
        self.assertEqual(webui.safe_name("a/b/c.dat"), ("c.dat", True))
        self.assertEqual(webui.safe_name("plain.dat"), ("plain.dat", False))
        self.assertEqual(webui.safe_name("x:y.dat")[0], "x_y.dat")
        self.assertEqual(webui.safe_name("trailing. ")[0], "trailing")
        self.assertEqual(webui.safe_name("..")[0], None)
        self.assertEqual(webui.safe_name("")[0], None)

    def test_mutations_are_deterministic(self):
        data = bytes(range(100))
        self.assertEqual(webui.mutate(data, "truncate_50"), data[:50])
        self.assertEqual(webui.mutate(b"", "flip_middle"), b"")
        self.assertEqual(webui.mutate(b"", "zero_block"), b"")
        self.assertEqual(webui.mutate(b"\x01\x02", "zero_block"), b"\x00\x00")
        self.assertEqual(webui.mutate(data, "unknown"), data)

    def test_default_workdir_is_not_inside_the_project(self):
        self.assertNotIn(webui.ROOT.resolve(), webui.default_workdir().resolve().parents)

    def test_stale_session_folders_are_removed_on_start(self):
        with tempfile.TemporaryDirectory() as temp:
            old = Path(temp) / "s-0123456789ab"
            keep = Path(temp) / "mine"
            old.mkdir()
            keep.mkdir()
            import os
            os.utime(old, (1, 1))
            webui.App(SAMPLES, Path(temp))
            self.assertFalse(old.exists())
            self.assertTrue(keep.exists())


if __name__ == "__main__":
    unittest.main()
