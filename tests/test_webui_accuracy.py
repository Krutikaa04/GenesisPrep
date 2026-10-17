"""Measured accuracy in the web interface: the right truth, the CLI's counting rules, honest limits."""
import json
import tempfile
import threading
import http.client
import unittest
from pathlib import Path

from helpers import SAMPLES, KIT
from deadbits import webui, webui_accuracy
from deadbits.engine import salvage_bytes
from deadbits.validation import reference
import evaluate as evaluator
from make_variants import variants

REFERENCE_FILES = ["s01.dat", "s04.dat", "s05.dat", "s08.dat", "s11.wks", "s18.cvt", "s20.000"]
OPTIONS = {"truncate_50": "truncate_50", "flip_middle": "single_byte_corrupt", "zero_block": "zero_block"}


def expected_for(name):
    return json.loads((KIT / "expected_outputs" / (name + ".json")).read_text("utf-8"))


class AccuracyApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.server = webui.make_server(0, SAMPLES, Path(cls.temp.name) / "work")
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

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
        return resp.status, data

    def json(self, method, path, payload=None, **kw):
        body = None if payload is None else json.dumps(payload).encode()
        status, data = self.call(method, path, body, {"Content-Type": "application/json"} if body else None, **kw)
        return status, json.loads(data.decode("utf-8"))

    def session(self):
        return self.json("POST", "/api/sessions")[1]["id"]

    def stage(self, sid, names, mutate=""):
        status, doc = self.json("POST", "/api/sessions/%s/samples" % sid, {"names": names, "mutate": mutate})
        self.assertEqual(status, 201)
        return [a["name"] for a in doc["added"]]

    def upload(self, sid, name, data):
        status, _ = self.call("POST", "/api/sessions/%s/files?name=%s" % (sid, name), data,
                              {"Content-Type": "application/octet-stream"})
        self.assertEqual(status, 201)

    def measure(self, sid):
        self.assertEqual(self.json("POST", "/api/sessions/%s/run" % sid)[0], 200)
        status, doc = self.json("GET", "/api/sessions/%s/accuracy" % sid)
        self.assertEqual(status, 200)
        return doc

    # --- independent truth -------------------------------------------------------------------------------
    def test_pristine_reference_files_score_exactly_as_the_organizer_comparison(self):
        sid = self.session()
        self.stage(sid, REFERENCE_FILES)
        result = self.measure(sid)
        for name in REFERENCE_FILES:
            item = result["files"][name]
            actual = salvage_bytes((SAMPLES / name).read_bytes(), name).to_dict()
            key = expected_for(name)
            self.assertEqual((item["basis"], item["available"]), ("organizer", True), name)
            self.assertEqual(item["counts"], reference.record_accuracy(actual, key).to_dict(), name)
            self.assertEqual(reference.compare(actual, key), [], name)       # what tools/compare_expected.py checks
            self.assertEqual(item["counts"]["measurements"]["accuracy"]["value"], 1.0, name)
            self.assertEqual(item["agreement"], {"status": True, "damage": True, "metadata": True}, name)
            self.assertEqual(item["falseVerified"], 0, name)
            self.assertEqual((item["fields"]["correct"], len(item["wrong"]), item["missing"], item["unexpected"]),
                             (item["fields"]["expected"], 0, [], []), name)
        group = result["summary"]["groups"]["organizer"]
        self.assertEqual((group["files"], group["expected"], group["correct"]), (7, 61, 61))

    def test_damaged_copies_agree_with_the_independent_evaluator(self):
        for option, variant_name in OPTIONS.items():
            for name in REFERENCE_FILES:
                data = (SAMPLES / name).read_bytes()
                damaged = {m: d for m, d, _ in variants(data)}[variant_name]
                self.assertEqual(webui.mutate(data, option), damaged, (name, option))   # same damage as the evaluator
                sid = self.session()
                staged = self.stage(sid, [name], option)[0]
                item = self.measure(sid)["files"][staged]
                actual = salvage_bytes(damaged, staged).to_dict()
                key = expected_for(name)
                truth = evaluator.make_baseline(salvage_bytes(data, name).to_dict(), key)
                theirs = evaluator.compare_records(actual, truth)
                counts = item["counts"]
                self.assertEqual(item["basis"], "organizer-damaged", (name, option))
                self.assertEqual((counts["expected"], counts["recovered"], counts["correct"], counts["missing"]),
                                 (theirs["expected_records"], theirs["recovered_records"], theirs["correct_records"],
                                  theirs["missing_records"]), (name, option))
                self.assertEqual(counts["correct"] + counts["wrong"], counts["recovered"])
                self.assertEqual(item["falseVerified"], theirs["false_verified_records"], (name, option))
                self.assertNotIn("agreement", item)
                self.server.app.drop(sid)

    def test_known_numbers_from_the_audit(self):
        sid = self.session()
        cut = self.stage(sid, ["s01.dat"], "truncate_50")[0]
        c = self.measure(sid)["files"][cut]["counts"]
        self.assertEqual((c["expected"], c["recovered"], c["correct"], c["wrong"], c["missing"]), (5, 3, 2, 1, 2))

    # --- never guess a key --------------------------------------------------------------------------------
    def test_truth_is_chosen_by_content_never_by_file_name(self):
        sid = self.session()
        self.upload(sid, "renamed.bin", (SAMPLES / "s01.dat").read_bytes())
        self.upload(sid, "s05.dat", b"LB98\x02not really a kit file")
        result = self.measure(sid)["files"]
        self.assertEqual((result["renamed.bin"]["basis"], result["renamed.bin"]["sample"]), ("organizer", "s01.dat"))
        self.assertEqual(result["renamed.bin"]["counts"]["measurements"]["accuracy"]["value"], 1.0)
        self.assertEqual((result["s05.dat"]["basis"], result["s05.dat"]["available"]), ("none", False))
        self.assertIn("not one of the kit", result["s05.dat"]["reason"])

    def test_kit_files_without_a_published_key_are_not_scored_but_damaged_copies_use_a_labelled_regression_key(self):
        sid = self.session()
        pristine = self.stage(sid, ["s02.dat"])[0]
        damaged = self.stage(sid, ["s02.dat"], "truncate_50")[0]
        result = self.measure(sid)["files"]
        self.assertEqual((result[pristine]["basis"], result[pristine]["available"]), ("none", False))
        self.assertIn("no answer key", result[pristine]["reason"])
        self.assertEqual((result[damaged]["basis"], result[damaged]["available"]), ("undamaged", True))
        self.assertIn("regression", result[damaged]["basisLabel"])
        baseline = self.server.app.truth.undamaged("s02.dat")
        self.assertEqual(result[damaged]["counts"]["expected"], len(baseline["records"]))

    def test_regression_key_holds_only_verified_records(self):
        baseline = self.server.app.truth.undamaged("s07.dat")      # 28 records, 6 unverified (deliberate CRC damage)
        pristine = salvage_bytes((SAMPLES / "s07.dat").read_bytes(), "s07.dat").to_dict()["records"]
        self.assertEqual(len(pristine), 28)
        self.assertEqual((len(baseline["records"]), len(baseline["optional_partial_records"])), (22, 6))

    def test_junk_and_empty_files_never_divide_by_zero_or_claim_accuracy(self):
        sid = self.session()
        names = self.stage(sid, ["s25_random.bin", "s26_empty.dat", "s27_notes.txt", "s28_tiny.dat", "s30_png_like.dat"])
        names += self.stage(sid, ["s25_random.bin", "s26_empty.dat"], "zero_block")
        result = self.measure(sid)
        for name in names:
            self.assertEqual((result["files"][name]["basis"], result["files"][name]["available"]), ("none", False), name)
        self.assertEqual(result["summary"]["groups"], {})
        self.assertEqual(result["summary"]["withoutAnswerKey"], len(names))

    # --- honesty ------------------------------------------------------------------------------------------
    def test_wrong_but_unflagged_record_is_called_out_with_the_reason_for_checksumless_formats(self):
        sid = self.session()
        flipped = self.stage(sid, ["s18.cvt"], "flip_middle")[0]
        pristine = self.stage(sid, ["s18.cvt"])[0]
        result = self.measure(sid)["files"]
        item = result[flipped]
        self.assertEqual((item["falseVerified"], item["integrity"]), (1, "none"))
        self.assertEqual(item["counts"]["correct"], 0)
        self.assertTrue(item["wrong"][0]["verified"])
        self.assertEqual(result[pristine]["falseVerified"], 0)
        self.assertIn("proven correct", webui.APP_JS)          # the page words this limit explicitly

    def test_summary_never_blends_different_truths(self):
        sid = self.session()
        self.stage(sid, ["s01.dat", "s05.dat"])
        self.stage(sid, ["s01.dat"], "truncate_50")
        self.stage(sid, ["s02.dat"], "truncate_50")
        self.stage(sid, ["s02.dat"])
        groups = self.measure(sid)["summary"]
        self.assertEqual(sorted(groups["groups"]), ["organizer", "organizer-damaged", "undamaged"])
        self.assertEqual(groups["withoutAnswerKey"], 1)
        organizer = groups["groups"]["organizer"]
        self.assertEqual((organizer["files"], organizer["expected"], organizer["accuracy"]), (2, 27, 1.0))
        self.assertLess(groups["groups"]["organizer-damaged"]["accuracy"], 1.0)

    def test_unavailable_when_records_cannot_be_matched_one_to_one(self):
        key = {"format": "LIBRA-98", "match_on": ["id"], "records": [{"id": 1, "title": "a"}]}
        duplicate = {"format": "LIBRA-98", "records": [{"id": 1, "title": "a"}, {"id": 1, "title": "a"}]}
        nokey = {"format": "LIBRA-98", "records": [{"title": "a"}]}
        for actual, needle in ((duplicate, "more than once"), (nokey, "identifies them")):
            out = webui_accuracy.score(actual, key)
            self.assertFalse(out["available"])
            self.assertIn(needle, out["reason"])
        wrong_format = webui_accuracy.score({"format": "WKS", "records": [{"id": 1, "title": "a"}]}, key)
        self.assertEqual(wrong_format["counts"]["correct"], 0)
        self.assertEqual(wrong_format["fields"]["correct"], 0)

    def test_asking_before_recovery_says_so(self):
        sid = self.session()
        self.stage(sid, ["s01.dat"])
        status, doc = self.json("GET", "/api/sessions/%s/accuracy" % sid)
        self.assertEqual(status, 200)
        self.assertIn("Recover", doc["files"]["s01.dat"]["reason"])

    # --- route guards and the page ---------------------------------------------------------------------------
    def test_route_is_guarded_like_every_other(self):
        sid = self.session()
        self.assertEqual(self.call("GET", "/api/sessions/%s/accuracy" % sid, host="evil.example")[0], 403)
        self.assertEqual(self.call("GET", "/api/sessions/s-000000000000/accuracy")[0], 404)

    def test_page_only_adds_an_accuracy_tab_and_card(self):
        js = webui.APP_JS
        self.assertIn("[['records','Records',doc.records.length],['damage','Damage',doc.damage.length],['bytes','Bytes'],"
                      "['details','Details'],['json','JSON'],['accuracy','Accuracy']]", js)
        self.assertIn("inner.appendChild(accuracyCard());", js)
        for forbidden in ("innerHTML", "insertAdjacentHTML", "document.write", "eval("):
            self.assertNotIn(forbidden, js)
        for text in (js, webui.APP_CSS, webui.INDEX_HTML):
            self.assertEqual({u for u in __import__("re").findall(r"https?://[^\s'\"<>)]+", text)}
                             - {"http://www.w3.org/2000/svg"}, set())


if __name__ == "__main__":
    unittest.main()
