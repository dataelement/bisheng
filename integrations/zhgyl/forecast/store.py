"""Idempotent monthly simulation state; original fixtures remain immutable."""
import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))

def now_text():
    return datetime.now(TZ).isoformat(timespec="seconds")

def add_month(month, offset):
    y, m = map(int, month.split("-")); n = y * 12 + m - 1 + offset
    return f"{n // 12:04}-{n % 12 + 1:02}"

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

class MonthlyStore:
    def __init__(self, fixture, runtime):
        self.fixture = json.loads(Path(fixture).read_text())
        self.root = Path(runtime); self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        path = self.root / "monthly-state.json"
        self.state = json.loads(path.read_text()) if path.exists() else {"records": self.fixture["records"], "batches": [], "jobs": []}

    def snapshot(self):
        with self.lock:
            batch = self.state["batches"][-1] if self.state["batches"] else None
            cutoff = batch['as_of'] if batch else self.fixture['cutoff']
            return {**self.fixture, "records": json.loads(json.dumps(self.state["records"])), "batch": batch, 'cutoff':cutoff, 'window':{**self.fixture['window'],'end':cutoff}}

    def _save(self):
        temp = self.root / "monthly-state.tmp"
        temp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2));temp.replace(self.root / "monthly-state.json")

    def refresh(self, month, forecast_provider, as_of=None):
        with self.lock:
            as_of = as_of or datetime.now(TZ).date().isoformat()
            previous = len(self.state["records"])
            ids = {r["order_id"] for r in self.state["records"]}
            added = [r for r in self.fixture["incoming_orders"] if r["date"] <= as_of and r["date"][:7] <= month and r["order_id"] not in ids]
            if self.state['batches'] and self.state['batches'][-1]['month']==month and not added:
                return self.state['batches'][-1]
            self.state["records"].extend(added)
            batch = {"month": month, "version": f"SIM-{month}-{len(self.state['batches'])+1}", "generated_at": now_text(),
                     "added_count": len(added), "order_ids": [r["order_id"] for r in added], "previous_rows": previous,
                     "dataset_rows": len(self.state["records"]), "dataset_sha": digest(self.state["records"]), "next_run": add_month(month, 1) + "-01"}
            batch['as_of'] = as_of
            batch['included_order_ids'] = [r['order_id'] for r in self.state['records']]
            batch['new_order_totals'] = {}
            incoming_ids={r['order_id'] for r in self.fixture['incoming_orders']}
            for r in self.state['records']:
                if r['order_id'] not in incoming_ids: continue
                key = r['spec'] + '|' + r['customer']
                batch['new_order_totals'][key] = batch['new_order_totals'].get(key, 0) + r['quantity']
            snapshots = []
            for spec in self.fixture["materials"]:
                if spec == "ZERO-PRED-001": continue
                for customer in self.fixture["customers"]:
                    snapshots.append({"spec": spec, "customer": customer, "output": forecast_provider(spec, customer, add_month(month, 1), 12, batch)})
            (self.root / f"batch-{batch['version']}.json").write_text(json.dumps({"batch": batch, "forecasts": snapshots}, ensure_ascii=False, indent=2))
            self.state["batches"].append(batch); self._save()
            return batch

    def catalog(self):
        with self.lock:
            batch = self.state["batches"][-1] if self.state["batches"] else None
            return {"ok": True, "specs": [{"spec": k, "material": v["material"]} for k,v in self.fixture["materials"].items() if k != "ZERO-PRED-001"],
                    "customers": self.fixture["customers"], "default_start": add_month(batch["month"],1) if batch else "2026-12",
                    "default_months": 12, "batch": batch, "recent_batches": self.state["batches"][-6:]}

    def recalculate(self, spec):
        with self.lock:
            old = next((j for j in self.state["jobs"] if j["spec"] == spec), None)
            if old: return old
            job = {"id": uuid.uuid4().hex, "spec": spec, "status": "waiting_for_data", "created_at": now_text(),
                   "message": "已登记离线重新计算任务，等待补充历史样本；不会即时生成缺乏依据的预测。"}
            self.state["jobs"].append(job); self._save(); return job
