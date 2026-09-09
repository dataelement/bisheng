"""Controlled DSH usage reconciliation. Credentials never enter argv or output."""

import argparse
import asyncio
import getpass
import json

from bisheng.dsh.domain.services.reconciliation import ReconciliationInput


def positive_tenant(value: str) -> int:
    tenant = int(value)
    if tenant < 1:
        raise argparse.ArgumentTypeError("tenant-id must be positive")
    return tenant


def build_parser():
    parser = argparse.ArgumentParser(description="Reconcile verified DSH usage without force-unfreeze or estimates")
    commands = parser.add_subparsers(dest="command", required=True)
    submit = commands.add_parser("submit")
    submit.add_argument("--tenant-id", required=True, type=positive_tenant)
    submit.add_argument("--request-id", required=True)
    submit.add_argument("--operation-id", required=True)
    submit.add_argument("--expected-event-version", required=True, type=int)
    submit.add_argument("--evidence-object", required=True)
    submit.add_argument("--evidence-sha256", required=True)
    for name in ["input-tokens", "output-tokens", "total-tokens"]:
        submit.add_argument("--" + name, required=True, type=int)
    submit.add_argument("--reason", required=True)
    status = commands.add_parser("status")
    status.add_argument("--tenant-id", required=True, type=positive_tenant)
    status.add_argument("--operation-id", required=True)
    return parser


async def run(argv, *, service, authenticate, credential_reader=getpass.getpass):
    args = vars(build_parser().parse_args(argv))
    command = args.pop("command")
    tenant_id = args.pop("tenant_id")
    credential = credential_reader("Current administrator JWT (hidden): ")
    actor = await authenticate(credential, tenant_id=tenant_id)
    del credential
    if command == "submit":
        result = await service.submit(ReconciliationInput(**args), actor_user_id=actor)
    else:
        result = await service.status(args["operation_id"], actor_user_id=actor)
    return {
        key: result[key]
        for key in ["operation_id", "status", "result_code", "result_payload", "committed_at", "effective_at"]
        if key in result and result[key] is not None
    }


def main():
    import sys

    # Production assembly is centralized with the API/worker dependency factory.
    build_parser().parse_args(sys.argv[1:])
    from bisheng.dsh.runtime import reconciliation_cli_runtime

    async def execute():
        async with reconciliation_cli_runtime() as runtime:
            return await run(sys.argv[1:], service=runtime.reconciliation, authenticate=runtime.authenticate_admin)

    print(json.dumps(asyncio.run(execute()), ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
