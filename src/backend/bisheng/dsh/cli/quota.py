"""Operator entry point for audited quota initialization/recovery and shared activation."""

import argparse
import asyncio
import getpass
import json

from bisheng.dsh.cli.reconcile import positive_tenant


def build_parser():
    parser = argparse.ArgumentParser(description="Restore DSH quota only from complete immutable audit evidence")
    parser.add_argument("command", choices=["initialize", "recover"])
    parser.add_argument("--tenant-id", required=True, type=positive_tenant)
    parser.add_argument("--manifest-object", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--isolation-attestation", required=True)
    return parser


async def run(argv, *, runtime, credential_reader=getpass.getpass):
    args = build_parser().parse_args(argv)
    token = credential_reader("Current administrator JWT (hidden): ")
    actor = await runtime.authenticate_admin(token, tenant_id=args.tenant_id)
    del token
    return await runtime.recover_quota(
        command=args.command,
        manifest_object=args.manifest_object,
        manifest_sha256=args.manifest_sha256,
        isolation_attestation=args.isolation_attestation,
        actor_user_id=actor,
    )


def main():
    import sys

    build_parser().parse_args(sys.argv[1:])
    from bisheng.dsh.runtime import reconciliation_cli_runtime

    async def execute():
        async with reconciliation_cli_runtime() as runtime:
            return await run(sys.argv[1:], runtime=runtime)

    print(json.dumps(asyncio.run(execute()), ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
