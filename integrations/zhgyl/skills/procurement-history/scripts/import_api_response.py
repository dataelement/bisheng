#!/usr/bin/env python3
"""Validate credential-free MK response pages and write isolated model batches.

No HTTP calls. Reuses the existing fetcher's pagination validation and slicing
through a bounded in-memory replay transport; authentication is never replayed
from a stored token response. Imported cell text remains untrusted data.
"""
import argparse
import json
from pathlib import Path
import sys

import fetch_history


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON object key')
        result[key] = value
    return result


def import_pages(payload, model, match_mode='exact', reference_model=None):
    if not isinstance(model, str) or not 0 < len(model.strip()) <= 256:
        raise ValueError('Invalid model')
    if match_mode not in ('exact', 'regex'):
        raise ValueError('Invalid match mode')
    if match_mode == 'regex' and (not isinstance(reference_model, str) or
                                 not 0 < len(reference_model.strip()) <= 256):
        raise ValueError('Regex requires the original reference model')
    if not isinstance(payload, dict) or set(payload) != {'pages'}:
        raise ValueError('Expected pages wrapper')
    pages = payload['pages']
    if not isinstance(pages, list) or not 1 <= len(pages) <= 100:
        raise ValueError('Expected 1-100 complete response pages')
    # Envelopes only: never persist request config, headers or token responses.
    permitted = {'success', 'code', 'msg', 'data', 'traceId'}
    model_count = None
    for page in pages:
        if not isinstance(page, dict) or set(page) - permitted:
            raise ValueError('Unexpected envelope fields')
        if page.get('success') is not True or not isinstance(page.get('data'), dict):
            raise ValueError('API envelope reports failure')
        data = page['data'].get('data')
        if not isinstance(data, dict):
            raise ValueError('Missing business response')
        if data.get('query') != {'model': model, 'match_mode': match_mode}:
            raise ValueError('Response query does not match this request')
        if not isinstance(data.get('source'), dict) or not isinstance(data['source'].get('scope'), str):
            raise ValueError('Missing source scope')
        if not isinstance(data.get('snapshotId'), str) or not data['snapshotId']:
            raise ValueError('Missing snapshot')
        if type(data.get('matchedModelCount')) is not int or data['matchedModelCount'] < 0:
            raise ValueError('Invalid model count')
        if model_count is not None and data['matchedModelCount'] != model_count:
            raise ValueError('Model count changed across pages')
        model_count = data['matchedModelCount']
        if type(data.get('pageNum')) is not int or type(data.get('pageSize')) is not int:
            raise ValueError('Invalid pagination types')
        if type(data.get('totalPages')) is not int or type(data.get('hasNext')) is not bool:
            raise ValueError('Invalid pagination types')
        fields = data.get('fieldMap')
        if not isinstance(fields, list) or len(fields) != 129:
            raise ValueError('Expected 129 field definitions')
        for i, field in enumerate(fields, 1):
            number, letters = i, ''
            while number:
                number, remainder = divmod(number - 1, 26)
                letters = chr(65 + remainder) + letters
            if not isinstance(field, dict) or field.get('key') != 'col_' + letters or field.get('column') != letters:
                raise ValueError('Field order does not match the mock contract')
            if not isinstance(field.get('label'), str):
                raise ValueError('Invalid field label')
        if not isinstance(data.get('result'), list):
            raise ValueError('Missing rows')
        for row in data['result']:
            if not isinstance(row, dict) or any(isinstance(value, (dict, list)) for value in row.values()):
                raise ValueError('Cells must be scalar data')
    page_size = pages[0]['data']['data']['pageSize']
    cursor = 0

    def replay(base, route, body, token=None):
        nonlocal cursor
        if route == '/authapi/getToken':
            # An internal transport marker, never an actual credential/token.
            return {'errcode': 0, 'access_token': 'offline-replay-marker'}
        requested_page = body['requestQuery']['pageNum']
        if cursor >= len(pages) or requested_page != cursor + 1:
            raise ValueError('Missing or repeated page')
        response = pages[cursor]
        cursor += 1
        return response

    # This CLI is single-threaded. Always restore the module transport, even on
    # validation failure. fetch() never sees a real origin or credentials here.
    original = fetch_history.post
    fetch_history.post = replay
    try:
        batches, manifest = fetch_history.fetch(
            {'base_url': 'http://offline.invalid', 'functionCode': 'offline',
             'appKey': '', 'appSecret': ''},
            model, match_mode, reference_model, page_size)
    finally:
        fetch_history.post = original
    if cursor != len(pages):
        raise ValueError('Unexpected extra response pages')
    for batch in batches:
        batch['provenance']['transport'] = 'platform_api_tool_response_import'
    manifest['transport'] = 'platform_api_tool_response_import'
    return batches, manifest


def read_response_files(response_file=None, page_files=None):
    """Read only raw JSON files; never reconstruct JSON from rendered tool text."""
    if bool(response_file) == bool(page_files):
        raise ValueError('Choose one response wrapper or raw page files')
    paths = [response_file] if response_file else page_files
    if not 1 <= len(paths) <= 100:
        raise ValueError('Expected 1-100 response files')
    remaining = 64 * 1024 * 1024
    values = []
    for path in paths:
        with Path(path).open('rb') as source:
            raw = source.read(remaining + 1)
        if len(raw) > remaining:
            raise ValueError('Response files exceed budget')
        remaining -= len(raw)
        values.append(json.loads(raw, object_pairs_hook=unique_object,
                                 parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value))))
    return values[0] if response_file else {'pages': values}


def main():
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--response-file', help='Existing JSON wrapper containing pages')
    source.add_argument('--page-file', action='append', help='Raw MK response JSON file; repeat in page order')
    parser.add_argument('--model', required=True)
    parser.add_argument('--match-mode', choices=['exact', 'regex'], default='exact')
    parser.add_argument('--reference-model')
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    try:
        payload = read_response_files(args.response_file, args.page_file)
        batches, manifest = import_pages(payload, args.model, args.match_mode, args.reference_model)
        result = fetch_history.write_batches(args.output_dir, batches, manifest)
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        result = {'status': 'import_error',
                  'message': 'API响应或完整性校验失败；未形成可分析的完整批次。'}
    # Tool callers need the structured failure too; a non-zero subprocess exit
    # can cause some interpreter adapters to discard stdout.
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
