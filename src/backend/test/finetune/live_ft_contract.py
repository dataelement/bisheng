"""Opt-in contract check against an already running FT service and real completed jobs.

Run from src/backend: python test/finetune/live_ft_contract.py --host URL --jobs ID ID ID --output FILE
This uses the production HTTP adapter. It does not stand in for a logged-in platform/database E2E.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bisheng.core.context.manager import app_context
from bisheng.core.external.http_client.http_client_manager import HttpClientManager, get_http_client
from bisheng.finetune.domain.sft_backend import SFTBackend


async def check(args):
    app_context.register_context(HttpClientManager())
    evidence = {"layer": "production_platform_adapter_to_formal_ft_http", "full_platform_e2e": False, "jobs": []}
    ok, capabilities = await SFTBackend.get_capabilities(args.host)
    assert ok and capabilities["contract_version"] == 2
    evidence["capabilities"] = capabilities
    for job_id in args.jobs:
        ok, state = await SFTBackend.get_job_status(args.host, job_id)
        assert ok and state["status"] == "FINISHED", state
        assert state["artifacts"]["complete"]
        ok, logs = await SFTBackend.get_job_log(args.host, job_id)
        assert ok and logs.get("train_log") and logs.get("log_data"), logs
        ok, metrics = await SFTBackend.get_job_metrics(args.host, job_id)
        assert ok and isinstance(metrics.get("report"), dict), metrics
        evidence["jobs"].append(
            {
                "id": job_id,
                "state": state,
                "metrics": metrics,
                "log_bytes": len(logs["train_log"]),
                "trainer_log_bytes": len(logs["log_data"]),
            }
        )
    ok, preflight = await SFTBackend.preflight(
        args.host,
        {
            "capability_id": "qwen3-0.6b-lora-20261102",
            "data_type": "text",
            "method": "lora",
            "parameters": {"max_steps": 2},
        },
    )
    assert ok and preflight["passed"], preflight
    evidence["preflight"] = preflight
    ok, inference = await SFTBackend.validate_inference(
        args.host,
        args.jobs[0],
        {
            "prompt": "Classify this ticket as IT, ADMIN or FINANCE. I cannot connect to the office printer.",
            "generation": {"max_new_tokens": 32},
            "baseline": False,
        },
    )
    assert ok and inference.get("completed") and inference.get("answer"), inference
    evidence["new_inference"] = inference
    evidence["passed"] = True
    Path(args.output).write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    await (await get_http_client()).close_aiohttp_client()
    print(json.dumps({"passed": True, "jobs": args.jobs, "answer": inference["answer"]}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--jobs", nargs=3, required=True)
    parser.add_argument("--output", required=True)
    asyncio.run(check(parser.parse_args()))
