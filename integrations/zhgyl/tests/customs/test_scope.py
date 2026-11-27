"""Local HTTP checks; usage: test_scope.py ENGINE_DIR SYNTHETIC_SNAPSHOT.
The snapshot is an explicit test input, never loaded from a live application.
"""

from pathlib import Path
import ast
import asyncio
import importlib.util
import json
import logging
import secrets
import sys
import tempfile
import threading
import unittest
from copy import deepcopy

ENGINE = (
    Path(sys.argv.pop(1)).resolve()
    if __name__ == "__main__"
    else Path(__file__).resolve().parents[2] / "skills/customs-history/scripts"
)
SNAPSHOT = Path(sys.argv.pop(1)).resolve() if __name__ == "__main__" else None
sys.path.insert(0, str(ENGINE))
customs = importlib.import_module("customs")
contract = importlib.import_module("contract")
inquiry = importlib.import_module("inquiry")
tool_adapter = importlib.import_module("tool_adapter")

SERVICE = Path(__file__).resolve().parents[2] / "services/customs-history/server.py"
spec = importlib.util.spec_from_file_location("customs_fixture", SERVICE)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
SNAP = json.loads(SNAPSHOT.read_text()) if SNAPSHOT else None
FIRST = SNAP["details"][0] if SNAP else {}
TARGET = {
    k: FIRST[k]
    for k in [
        "destination",
        "model",
        "gross_weight_kg",
        "length_cm",
        "width_cm",
        "height_cm",
        "package_count",
        "dangerous_goods",
    ]
    if k in FIRST
}


@unittest.skipIf(
    SNAPSHOT is None, "Pass a synthetic snapshot to this test script explicitly"
)
class ScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.token = secrets.token_urlsafe(32)
        cls.api = fixture.make_server(SNAPSHOT, cls.token)
        cls.thread = threading.Thread(target=cls.api.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = "http://127.0.0.1:" + str(cls.api.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.api.shutdown()
        cls.api.server_close()
        cls.thread.join()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, request, token=None):
        return tool_adapter.execute(
            {"request": request},
            workspace=self.root,
            base_url=self.origin,
            token=token or self.token,
        )

    def history(self, **view):
        return self.call(
            {
                "action": "history",
                "query": {"destination": FIRST["destination"]},
                **view,
            }
        )

    def no_advice(self, r):
        self.assertNotIn("recommendation", r)
        for text in ["推荐", "首选", "抽单费", "仓储费", "费用明细", "费用项目"]:
            self.assertNotIn(text, r["answer"])

    def test_history_and_detail_single_verified_fee(self):
        r = self.history()
        self.no_advice(r)
        self.assertTrue(r["bills"])
        b = r["bills"][0]
        raw = next(x for x in SNAP["bills"] if x["bill_no"] == b["bill_no"])
        self.assertEqual(b["customs_fee_amount"], contract.customs_fee(raw))
        self.assertNotIn("total_amount", b)
        self.assertIn(raw["history_date"][:10], r["answer"])
        r = self.call(
            {"action": "detail", "reference": b["reference"], "query_id": r["query_id"]}
        )
        self.no_advice(r)
        self.assertIn("历史报关费", r["answer"])
        self.assertIn(FIRST["master_no"], r["answer"])
        self.assertIn(FIRST["contract_no"], r["answer"])
        self.assertIn(customs.amount(contract.customs_fee(raw)), r["answer"])
        if "total_amount" in raw and raw["total_amount"] != contract.customs_fee(raw):
            self.assertNotIn(customs.amount(raw["total_amount"]), r["answer"])

    def test_history_filters_reset_pagination(self):
        a = self.history(page_size=1)
        self.no_advice(a)
        r = self.call(
            {"action": "filter", "set": {"dangerous_goods": FIRST["dangerous_goods"]}}
        )
        self.no_advice(r)
        r = self.call({"action": "reset"})
        self.no_advice(r)
        self.assertEqual(a["counts"]["matched_details"], r["counts"]["matched_details"])
        self.assertEqual(a["counts"]["unique_bills"], r["counts"]["unique_bills"])
        if a["has_more"]:
            r = self.call({"action": "show", "page": 2, "page_size": 1})
            self.no_advice(r)
            self.assertNotEqual(a["bills"][0]["bill_no"], r["bills"][0]["bill_no"])

    def test_shared_coverage_is_complete_fee_once(self):
        shared = next(b for b in SNAP["bills"] if b["detail_count"] > 1)
        house = shared["house_numbers"].split(";")[0]
        r = self.call({"action": "history", "query": {"house_numbers": [house]}})
        self.assertEqual(r["counts"]["unique_bills"], 1)
        self.assertEqual(r["bills"][0]["coverage_count"], shared["detail_count"])
        self.assertEqual(
            r["bills"][0]["customs_fee_amount"], contract.customs_fee(shared)
        )
        self.no_advice(r)

    def test_explicit_inquiry_exact(self):
        r = self.call({"action": "inquiry", "target": TARGET})
        self.assertEqual(r["match"]["match_type"], "full")
        self.assertTrue(r["recommendation"])
        self.assertIn("历史参考明细", r["answer"])
        self.assertLess(len(r["recommendation"]), 20)
        self.assertNotIn("抽单费", r["answer"])
        self.assertIn("历史报关费", r["answer"])

    def test_explicit_inquiry_approximate(self):
        r = self.call(
            {"action": "inquiry", "target": {**TARGET, "gross_weight_kg": 999999}}
        )
        self.assertEqual(r["match"]["match_type"], "approximate")
        self.assertTrue(r["recommendation"])
        self.assertIn("本次999999", r["answer"])

    def test_no_protected_history_fallback(self):
        r = self.call(
            {"action": "inquiry", "target": {**TARGET, "destination": "NO-SUCH-PORT"}}
        )
        self.assertEqual(r["outcome"], "recommended")
        self.assertEqual(r["counts"]["matched_details"], 0)
        self.assertIn("相近经验", r["answer"])

    def test_no_data_and_clarification(self):
        r = self.call(
            {"action": "inquiry", "target": {"destination": FIRST["destination"]}}
        )
        self.assertEqual(r["outcome"], "needs_clarification")
        self.assertFalse((self.root / "uploads").exists())
        r = self.call(
            {"action": "history", "query": {"house_numbers": ["NO-SUCH-HOUSE"]}}
        )
        self.assertEqual(r["outcome"], "no_records")
        self.no_advice(r)
        r = self.call(
            {"action": "inquiry", "target": {**TARGET, "carrier": "NO-SUCH-AGENT"}}
        )
        self.assertEqual(r["outcome"], "no_records")
        self.assertFalse(r["recommendation"])

    def test_error_and_injected_pool_preserve_state(self):
        self.history()
        before = (self.root / customs.STATE).read_bytes()
        r = self.call(
            {
                "action": "history",
                "query": {"destination": FIRST["destination"]},
                "pool_receipts": [],
            }
        )
        self.assertEqual(r["outcome"], "invalid_request")
        r = self.call(
            {"action": "history", "query": {"destination": FIRST["destination"]}},
            token="invalid-token-with-sufficient-length",
        )
        self.assertEqual(r["outcome"], "api_error")
        self.assertEqual((self.root / customs.STATE).read_bytes(), before)
        self.assertTrue(r["terminal"])

    def test_legacy_advice_never_resurfaces(self):
        self.history()
        s = customs.read(self.root / customs.STATE)[1]
        row = s["batch"]["records"][0]
        s["advice"] = {
            "basis": {k: row[k] for k in ["house_no", *customs.ADVICE_KEYS]},
            "profiles": 1,
            "total": 0,
            "items": [],
        }
        customs.save(self.root, s)
        for r in [
            {"action": "show"},
            {"action": "filter", "set": {"dangerous_goods": row["dangerous_goods"]}},
            {"action": "reset"},
        ]:
            self.no_advice(self.call(r))

    def minimal(self, amount="missing"):
        d = deepcopy(SNAP)
        for r in d["details"]:
            for k in [*contract.FEE_FIELDS, "total_amount", "customs_fee_amount"]:
                r.pop(k, None)
            if amount != "missing":
                r["customs_fee_amount"] = amount
        for b in d["bills"]:
            for k in ["fee_items", "total_amount", "customs_fee_amount"]:
                b.pop(k, None)
            if amount != "missing":
                b["customs_fee_amount"] = amount
        return d

    def check_replacement(self, d):
        path = self.root / "input.json"
        path.write_bytes(contract.encode(d))
        api = fixture.make_server(path, self.token)
        thread = threading.Thread(target=api.serve_forever, daemon=True)
        thread.start()
        origin = "http://127.0.0.1:" + str(api.server_port)
        try:
            result = tool_adapter.execute(
                {
                    "request": {
                        "action": "history",
                        "query": {"destination": FIRST["destination"]},
                    }
                },
                workspace=self.root,
                base_url=origin,
                token=self.token,
            )
            inquiry_result = tool_adapter.execute(
                {"request": {"action": "inquiry", "target": TARGET}},
                workspace=self.root,
                base_url=origin,
                token=self.token,
            )
            self.assertTrue(inquiry_result["recommendation"])
            self.assertEqual(inquiry_result["outcome"], "ok")
            return result
        finally:
            api.shutdown()
            api.server_close()
            thread.join()

    def test_only_verified_fee_without_twenty_components(self):
        r = self.check_replacement(self.minimal(321.45))
        self.assertIn("321.45", r["answer"])
        self.assertEqual(r["bills"][0]["customs_fee_amount"], 321.45)
        self.no_advice(r)

    def test_missing_fee_is_not_zero_or_legacy_total(self):
        d = self.minimal()
        for r in d["details"]:
            r["total_amount"] = 98765
        for b in d["bills"]:
            b["total_amount"] = 98765
        r = self.check_replacement(d)
        self.assertIsNone(r["bills"][0]["customs_fee_amount"])
        self.assertIn("未提供", r["answer"])
        self.assertNotIn("98,765", r["answer"])
        result = inquiry.recommend(d["details"], d["bills"], TARGET)
        self.assertTrue(result["items"])
        self.assertIsNone(result["items"][0]["fee_min"])

    def test_explicit_zero_fee(self):
        r = self.check_replacement(self.minimal(0))
        self.assertEqual(r["bills"][0]["customs_fee_amount"], 0)
        self.assertIn("0.00", r["answer"])
        self.assertNotIn("未提供", r["answer"])

    def test_conflicting_or_invalid_fee_fails_closed(self):
        for value in [-1, True, float("nan"), "321.45"]:
            d = self.minimal(value)
            with self.assertRaises(contract.ContractError):
                contract.validate_entities(d["details"], d["bills"])
        d = self.minimal(5)
        d["bills"][0]["customs_fee_amount"] = 6
        with self.assertRaises(contract.ContractError):
            contract.validate_entities(d["details"], d["bills"])

    def test_platform_history_only_fetches_requested_scope_once(self):
        path = (
            Path(__file__).resolve().parents[4]
            / "src/backend/bisheng/linsight/domain/services/customs_tools.py"
        )
        tree = ast.parse(path.read_text())
        cls = next(
            n
            for n in tree.body
            if isinstance(n, ast.ClassDef) and n.name == "CustomsTool"
        )
        fn = deepcopy(
            next(
                n
                for n in cls.body
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "_arun"
            )
        )
        for arg in fn.args.args:
            arg.annotation = None
        fn.returns = None
        fetched = []
        fixed = []

        async def fetch(r, workspace):
            fetched.append(deepcopy(r))
            return ["receipt"]

        async def run_fixed(r, config):
            fixed.append(r)
            return customs.final("ok", "历史费用")

        ns = {
            "normalize_request": lambda r: r,
            "fetch_and_upload": fetch,
            "business_process": lambda scene, r, result: result["answer"],
            "json": json,
            "logging": logging,
            "PROTOCOL": customs.PROTOCOL,
            "FAILURE": "failed",
        }
        exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), "exec"), ns)
        obj = type(
            "Runtime", (), {"workspace": object(), "_fixed": staticmethod(run_fixed)}
        )()
        request = {"action": "history", "query": {"house_numbers": [FIRST["house_no"]]}}
        asyncio.run(ns["_arun"](obj, request))
        self.assertEqual(fetched, [request])
        self.assertEqual(fixed, [{**request, "receipts": ["receipt"]}])


if __name__ == "__main__":
    unittest.main(verbosity=2)
