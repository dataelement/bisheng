"""Explicit local dataset contract: test_scope.py EXECUTOR SYNTHETIC_DATASET."""

from pathlib import Path
from copy import deepcopy
from datetime import date
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest

EXECUTOR = Path(sys.argv.pop(1)) if __name__ == "__main__" else None
DATASET = Path(sys.argv.pop(1)) if __name__ == "__main__" else None


@unittest.skipIf(EXECUTOR is None, "Pass executor and synthetic dataset explicitly")
class OrderScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = tempfile.TemporaryDirectory(prefix="order-scope-")
        root = Path(cls.bundle.name)
        (root / "scripts").mkdir()
        (root / "assets").mkdir()
        shutil.copyfile(EXECUTOR, root / "scripts/run.py")
        shutil.copyfile(DATASET, root / "assets/orders.json")
        spec = importlib.util.spec_from_file_location(
            "scope_order_executor", root / "scripts/run.py"
        )
        cls.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.m)

    @classmethod
    def tearDownClass(cls):
        cls.bundle.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.before = os.getcwd()
        os.chdir(self.temp.name)
        self.saved = deepcopy(self.m.D)

    def tearDown(self):
        self.m.D = self.saved
        os.chdir(self.before)
        self.temp.cleanup()

    def call(self, **request):
        return self.m.execute({"as_of": "2026-11-26", **request})

    def test_exact_details_are_dates_and_countdowns(self):
        for o in self.m.D["orders"]:
            r = self.call(action="detail", order=o["number"])
            self.assertEqual(r["status"], "done")
            self.assertFalse(r["action_applied"])
            for values, key in [
                (o["lines"], "due"),
                (o["invoices"], "due"),
                (o["settlements"], "date"),
            ]:
                for row in values:
                    if row[key]:
                        self.assertIn(row[key], r["answer"])
                        self.assertIn(
                            self.m.days(row[key], date(2026, 11, 26)), r["answer"]
                        )
            for label in ["付款截止日", "计划交付日期", "结算日期"]:
                self.assertIn(label, r["answer"])
            for claim in ["已付款", "已经交付", "已到账", "应到账截止"]:
                self.assertNotIn(claim, r["answer"])

    def test_missing_dates_not_invented(self):
        o = self.m.D["orders"][0]
        for rows, key in [
            (o["lines"], "due"),
            (o["invoices"], "due"),
            (o["settlements"], "date"),
        ]:
            for row in rows:
                row[key] = None
        r = self.call(action="detail", order=o["number"])
        self.assertIn("日期未提供", r["answer"])
        self.assertNotIn("日期已过", r["answer"])
        r = self.call(action="alerts", order=o["number"], window="missing")
        self.assertEqual(r["status"], "done")

    def test_unresolved_explicit_switch_cannot_reuse_previous_order(self):
        o = self.m.D["orders"][0]
        self.call(action="detail", order=o["number"])
        self.assertEqual(
            self.call(action="detail", order="NO-SUCH-ORDER")["status"], "waiting"
        )
        r = self.call(action="detail")
        self.assertEqual(r["status"], "waiting")
        self.assertNotIn(o["number"], r["answer"])
        self.call(action="detail", order=o["number"])
        self.assertIn(o["number"], self.call(action="detail")["answer"])

    def test_ambiguous_switch_and_other_workspace_clarify(self):
        os_ = self.m.D["orders"]
        self.call(action="detail", order=os_[0]["number"])
        self.m.D["orders"][1]["number"] = os_[0]["number"] + "-SECOND"
        self.assertEqual(
            self.call(action="detail", order=os_[0]["number"].rsplit("-", 1)[0])[
                "status"
            ],
            "waiting",
        )
        self.assertEqual(
            self.call(action="reminder", node="delivery", mode="7")["status"], "waiting"
        )
        self.call(action="detail", order=os_[0]["number"])
        Path("other-chat").mkdir()
        os.chdir("other-chat")
        self.assertEqual(self.call(action="detail")["status"], "waiting")

    def test_reminders_are_review_links_and_require_node(self):
        o = self.m.D["orders"][0]
        before = deepcopy(self.m.D)
        self.assertEqual(
            self.call(action="reminder", order=o["number"], mode="7")["status"],
            "waiting",
        )
        for node in self.m.NODES:
            for mode in ["7", "30", "off", "default"]:
                r = self.call(
                    action="reminder", order=o["number"], node=node, mode=mode
                )
                self.assertFalse(r["action_applied"])
                self.assertIn("尚未保存", r["answer"])
                self.assertIn("&mode=" + mode, r["answer"])
        self.assertEqual(self.m.D, before)

    def test_open_ended_query_and_extra_fields_are_rejected(self):
        for r in [
            {"action": "sql", "query": "SELECT *"},
            {"action": "query"},
            {"action": "orders", "actual_payment_status": True},
            {"action": "orders", "estimate_receipt_deadline": True},
        ]:
            with self.assertRaises(ValueError):
                self.call(**r)


if __name__ == "__main__":
    unittest.main(verbosity=2)
