"""Trusted HTTP -> exact raw JSON receipts; loopback or explicit D private origin."""
import argparse
import os
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from contract import CALL, FUNCTION, MAX_BYTES, ContractError, encode, loads, merge_pages, query, require, sha
import inquiry


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


PRIVATE_ORIGIN = 'http://bs-d-customs-api:8080'


def fetch_inquiry(base_url, token, target, workspace, page_size=50, *, allow_private=False):
    prepared=inquiry.prepare(target)
    if not prepared['ready']:
        return {'status':'needs_clarification','questions':prepared['questions'],'terminal':True}
    receipt=fetch(base_url,token,inquiry.scope(prepared['target']),workspace,page_size,allow_private=allow_private)
    return {**receipt,'inquiry_target':prepared['target'],'strategy':inquiry.STRATEGY}


def fetch(base_url, token, conditions, workspace, page_size=50, *, allow_private=False):
    url = urlsplit(base_url)
    permitted = url.hostname == '127.0.0.1' or (allow_private is True and base_url == PRIVATE_ORIGIN)
    require(url.scheme == 'http' and permitted and url.port and not
            (url.username or url.password or url.query or url.fragment) and url.path in ('','/'),
            'This milestone only permits a loopback HTTP origin')
    require(isinstance(token, str) and 24 <= len(token) <= 256, 'Invalid local token')
    conditions = query(conditions)
    require(type(page_size) is int and 1 <= page_size <= 100, 'Invalid page size')
    root = Path(workspace).resolve()
    root.mkdir(parents=True, exist_ok=True)
    directory = root / 'uploads/customs-api'
    for part in [root/'uploads', directory]:
        require(not part.is_symlink(), 'Symlink upload directory')
        part.mkdir(exist_ok=True)
    opener = build_opener(ProxyHandler({}), NoRedirect())
    pages, receipts, total_bytes = [], [], 0
    started = time.monotonic()
    for page in range(1, 101):
        require(time.monotonic() - started <= 60, 'Fetch total time budget exceeded')
        body = {'requestQuery':{'conditions':conditions,'pageNum':page,'pageSize':page_size}}
        request = Request(base_url.rstrip('/') + CALL + '?functionCode=' + FUNCTION,
                          data=encode(body), headers={'Content-Type':'application/json', 'Authorization':'Bearer '+token})
        try:
            with opener.open(request, timeout=8) as response:
                require(response.status == 200 and response.headers.get_content_type() == 'application/json', 'Invalid HTTP response')
                raw = response.read(MAX_BYTES + 1)
        except HTTPError as exc:
            raise ContractError('Customs HTTP ' + str(exc.code)) from None
        except (URLError, TimeoutError, OSError):
            raise ContractError('Customs connection failed') from None
        payload = loads(raw)
        require(isinstance(payload, dict) and payload.get('success') is True, 'Customs API failed')
        data = payload.get('data', {}).get('data', {})
        require(type(data.get('totalPages')) is int and 1 <= data['totalPages'] <= 100, 'Invalid paging metadata')
        total_bytes += len(raw)
        require(total_bytes <= MAX_BYTES, 'Fetch total byte budget exceeded')
        path = directory / (uuid.uuid4().hex + '.json')
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        require(path.read_bytes() == raw, 'Raw JSON persistence failed')
        receipts.append({'path':path.relative_to(root).as_posix(), 'sha256':sha(raw), 'bytes':len(raw)})
        pages.append(payload)
        if page == data['totalPages']:
            break
    batch = merge_pages(pages, conditions)
    return {'status':'customs_pages_saved','query':conditions, 'snapshotId':batch['snapshotId'],
            'receipts':receipts,'matched_details':len(batch['records']), 'unique_bills':len(batch['bills'])}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', required=True); parser.add_argument('--workspace', required=True)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--query-file'); source.add_argument('--inquiry-file')
    parser.add_argument('--page-size', type=int, default=50)
    args = parser.parse_args()
    try:
        function=fetch_inquiry if args.inquiry_file else fetch
        result = function(args.base_url, os.environ.get('CUSTOMS_MOCK_TOKEN'),
                          loads(Path(args.inquiry_file or args.query_file).read_bytes()), args.workspace, args.page_size)
        print(encode(result).decode())
    except (ContractError, ValueError, OSError):
        print(encode({'status':'fetch_failed','terminal':True,'message':'本地报关取数或完整性校验失败。'}).decode())
        raise SystemExit(1)
