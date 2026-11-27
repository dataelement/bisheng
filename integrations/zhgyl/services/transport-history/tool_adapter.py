"""Trusted local tool bridge: public request -> HTTP receipts -> fixed entry.

Workspace, origin and token are supplied by the executor, never model arguments.
This module has no BISHENG dependency and does not modify platform configuration.
"""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path

from contract import ContractError, encode, loads, require
from fetch_history import fetch, fetch_inquiry
import transport

NAME = 'transport_history'
CALL_LOCK = 'uploads/transport-runtime/.tool-call.lock'


def validate(arguments):
    require(isinstance(arguments, dict) and set(arguments) == {'request'})
    require(len(encode(arguments)) <= 65536)
    request = loads(encode(arguments['request']))
    require(isinstance(request, dict) and 'receipts' not in request)
    # Internal receipts are deliberately absent from the model-facing schema.
    internal = dict(request)
    if request.get('action') == 'history':
        internal['receipts'] = []
    transport.validate_request(internal)
    return request


@contextmanager
def transaction(root):
    for part in ['uploads', 'uploads/transport-runtime']:
        transport.safe(root, part).mkdir(exist_ok=True)
    path = transport.safe(root, CALL_LOCK)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def checked(result):
    require(isinstance(result, dict) and result.get('protocol') == transport.PROTOCOL and
            result.get('terminal') is True and result.get('next_action') == 'none' and
            isinstance(result.get('answer'), str), 'Untrusted result protocol')
    return result


def execute(arguments, *, workspace, base_url, token, api_page_size=50):
    """One bounded call. Continuations use saved state; fresh scopes fetch once."""
    phase = 'invalid_request'
    try:
        request = validate(arguments)
        root = Path(workspace)
        require(root.is_dir() and not root.is_symlink(), 'Executor workspace missing')
        root = root.resolve()
        if request['action'] == 'explain_limits':
            return checked(transport.run(request, root))
        # A clarification creates neither HTTP traffic nor runtime files.
        if request['action'] == 'inquiry':
            from inquiry import prepare
            if not prepare(request['target'])['ready']:
                return checked(transport.run(request, root))
        phase = 'state_error'
        with transaction(root):
            if request['action'] == 'history':
                phase = 'api_error'
                receipt = fetch(base_url, token, request['query'], root, api_page_size)
                internal = {**request, 'query': receipt['query'], 'receipts': receipt['receipts']}
            elif request['action'] == 'inquiry':
                # Reuse only the complete pool already accepted by the fixed entry.
                result = checked(transport.run(request, root))
                if result['outcome'] != 'needs_new_query':
                    return result
                phase = 'api_error'
                receipt = fetch_inquiry(base_url, token, request['target'], root, api_page_size)
                internal = {**request, 'receipts': receipt['receipts']}
            else:
                internal = request
            phase = 'execution_error'
            return checked(transport.run(internal, root))
    except BlockingIOError:
        return transport.final('busy', '本轮运输查询尚未完成，请稍后重试；当前查询未改变。')
    except (ContractError, ValueError, TypeError, KeyError, OSError, OverflowError, RecursionError):
        message = ('运输API取数或完整性校验失败，已停止；这不表示没有历史费用。'
                   if phase == 'api_error' else transport.MESSAGES[phase])
        return transport.final(phase, message)
    except Exception:
        return transport.final('execution_error', transport.MESSAGES['execution_error'])


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--arguments-file', required=True)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--base-url', required=True)
    args = parser.parse_args()
    try:
        arguments = loads(Path(args.arguments_file).read_bytes())
        result = execute(arguments, workspace=args.workspace, base_url=args.base_url,
                         token=os.environ.get('TRANSPORT_MOCK_TOKEN'))
    except (ContractError, OSError):
        result = transport.final('invalid_request', transport.MESSAGES['invalid_request'])
    print(encode(result).decode())
