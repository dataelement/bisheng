#!/usr/bin/env python3
"""Fetch the MK-shaped mock, verify all pages, then produce isolated model batches."""
import argparse
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen, build_opener, HTTPRedirectHandler

import query_orders as engine

CALL = '/openapi/tic-definition/integrationInterface/call'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def post(base, route, body, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = Request(base.rstrip('/') + route, data=json.dumps(body).encode(), headers=headers)
    try:
        with build_opener(NoRedirect).open(request, timeout=8) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise ValueError('API response exceeds budget')
            return json.loads(raw)
    except HTTPError as error:
        # Never render credential-bearing request URLs or a server's untrusted error body.
        raise ValueError('API returned HTTP ' + str(error.code)) from None
    except URLError:
        raise ValueError('API connection failed') from None


def fetch(config, model, match_mode='exact', reference_model=None, page_size=50):
    base = config['base_url']
    u = urlsplit(base)
    if u.scheme not in ('http', 'https') or not u.netloc or u.username or u.query or u.fragment or u.path not in ('', '/'):
        raise ValueError('base_url must be an authorized HTTP(S) origin')
    if type(page_size) is not int or not 1 <= page_size <= 100:
        raise ValueError('page_size must be 1-100')
    auth = post(base, '/authapi/getToken', {k: config[k] for k in ('appKey', 'appSecret')})
    token = auth.get('access_token')
    if auth.get('errcode') != 0 or not isinstance(token, str) or not token:
        raise ValueError('Mock authentication failed')
    route = CALL + '?' + urlencode({'functionCode': config['functionCode']})
    all_rows, all_sources, first = [], [], None
    for page in range(1, 101):
        response = post(base, route, {'requestQuery': {'model': model, 'match_mode': match_mode,
                        'pageNum': page, 'pageSize': page_size}}, token)
        if response.get('success') is not True or response.get('data', {}).get('status') != 200:
            raise ValueError('API envelope reports failure')
        data = response['data']['data']
        required = ('snapshotId', 'fieldMap', 'source', 'schemaVersion', 'totalElements', 'totalPages', 'query', 'mock')
        if first is None:
            first = data
            if data.get('schemaVersion') != 'procurement-excel-v1' or data.get('mock') is not True:
                raise ValueError('Unexpected API data contract')
            if type(data.get('totalElements')) is not int or not 0 <= data['totalElements'] <= 10000:
                raise ValueError('Result count exceeds budget')
            if len(data.get('fieldMap', [])) != 129 or len({c['key'] for c in data['fieldMap']}) != 129:
                raise ValueError('Missing or duplicate field keys')
            for _, (index, label) in engine.FIELDS.items():
                if data['fieldMap'][index]['label'] != label:
                    raise ValueError('Unexpected field mapping')
        if any(data.get(k) != first.get(k) for k in required):
            raise ValueError('API snapshot or metadata changed across pages')
        if data.get('pageNum') != page or data.get('pageSize') != page_size:
            raise ValueError('API pagination mismatch')
        rows, sources = data.get('result'), data.get('sourceRows')
        expected = min(page_size, max(0, data['totalElements'] - (page - 1) * page_size))
        if not isinstance(rows, list) or not isinstance(sources, list) or len(rows) != len(sources) or len(rows) != expected:
            raise ValueError('Incomplete API page')
        fields = [c['key'] for c in data['fieldMap']]
        if any(not isinstance(row, dict) or set(row) != set(fields) for row in rows):
            raise ValueError('API record fields are incomplete')
        if any(type(n) is not int or n < 2 for n in sources):
            raise ValueError('Invalid source row')
        all_rows.extend(rows)
        all_sources.extend(sources)
        has_next = page * page_size < data['totalElements']
        expected_pages = (data['totalElements'] + page_size - 1) // page_size
        if data['totalPages'] != expected_pages or data.get('hasNext') != has_next:
            raise ValueError('Inconsistent pagination totals')
        if not has_next:
            break
    else:
        raise ValueError('Pagination budget exceeded; no complete batch was written')
    if len(all_rows) != first['totalElements'] or len(set(all_sources)) != len(all_sources):
        raise ValueError('API rows missing or repeated across pages')
    groups = {}
    for row, source in zip(all_rows, all_sources):
        key = engine.norm(row.get('col_CJ', ''))
        if not key or (match_mode == 'exact' and key != engine.norm(model)):
            raise ValueError('Unexpected or missing model in API result')
        groups.setdefault(key, []).append((row, source))
    if first.get('matchedModelCount') != len(groups):
        raise ValueError('API model count mismatch')
    reference = engine.norm(reference_model or model)
    ordered = sorted(groups, key=lambda key: (-SequenceMatcher(None, reference, key).ratio(), key))
    batches = []
    for key in ordered[:3]:
        members = groups[key]
        batch = {'schema_version': 1, 'model': members[0][0]['col_CJ'], 'complete': True,
                 'total_records': len(members), 'columns': [c['label'] for c in first['fieldMap']],
                 'rows': [[row[c['key']] for c in first['fieldMap']] for row, _ in members],
                 'source_rows': [source for _, source in members],
                 'provenance': {**first['source'], 'transport': 'actual_http_mock',
                                'snapshot_id': first['snapshotId'], 'query': first['query']}}
        batches.append(batch)
    manifest = {'status': 'ok' if batches else 'no_records', 'mock': True,
                'complete': True, 'scope': first['source']['scope'], 'query': first['query'],
                'snapshot_id': first['snapshotId'], 'total_records': len(all_rows),
                'matched_models': len(groups), 'displayed_models': len(batches),
                'omitted_models': max(0, len(groups) - 3),
                'selection': 'exact normalized model' if match_mode == 'exact' else
                'top 3 string similarity to reference_model; ties normalized model ascending; not substitutability',
                'reference_model': reference_model, 'models': []}
    return batches, manifest


def write_batches(output_dir, batches, manifest):
    target = Path(output_dir)
    if target.exists() and any(target.iterdir()):
        raise ValueError('Use a new per-conversation output directory; existing files are preserved')
    target.mkdir(parents=True, exist_ok=True)
    for i, batch in enumerate(batches, 1):
        name = 'model-' + str(i) + '.json'
        raw = json.dumps(batch, ensure_ascii=False, allow_nan=False, indent=2) + '\n'
        (target / name).write_text(raw)
        manifest['models'].append({'model': batch['model'], 'records': batch['total_records'],
                                   'batch': name, 'sha256': hashlib.sha256(raw.encode()).hexdigest()})
    (target / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config-file', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--match-mode', choices=['exact', 'regex'], default='exact')
    parser.add_argument('--reference-model')
    parser.add_argument('--page-size', type=int, default=50)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    try:
        config = json.loads(Path(args.config_file).read_text())
        batches, manifest = fetch(config, args.model, args.match_mode, args.reference_model, args.page_size)
        print(json.dumps(write_batches(args.output_dir, batches, manifest), ensure_ascii=False))
    except (ValueError, KeyError, OSError):
        print(json.dumps({'status': 'fetch_error', 'message': 'API取数或完整性校验失败；未形成可分析的完整批次。'}))
        sys.exit(1)


if __name__ == '__main__':
    main()
