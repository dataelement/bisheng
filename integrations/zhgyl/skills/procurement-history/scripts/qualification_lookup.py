#!/usr/bin/env python3
"""Buyer whitelist membership and source-backed evidence; not a global approval verdict."""
import json
import argparse
import csv
import hashlib
from pathlib import Path
import re
import unicodedata

MAX_EVIDENCE = 20
MAX_EVIDENCE_CHARS = 8000
QSL_EVIDENCE_FIELDS = (
    'record_id', 'row_kind', 'source_row', 'parse_status', 'review_notes',
    'supplier_name', 'supplier_code', 'category', 'material_category', 'standard',
    'standard_code', 'standard_version', 'technical_standard', 'technical_standard_version',
    'grade', 'type', 'class', 'level', 'specification', 'material_designation', 'status',
    'form', 'product_form', 'part_number', 'supplier_part_number', 'aircraft',
    'registered_at', 'restrictions',
)


class CSVRecords:
    """List-like compatibility facade; a lookup streams CSV, never loads its full body."""
    def __init__(self, folder, spec, kind):
        name = spec['table']['path']
        if Path(name).name != name or name != kind + '.csv':
            raise ValueError('Unsafe qualification table path')
        self.path = folder / name
        if self.path.is_symlink() or self.path.resolve().parent != folder.resolve():
            raise ValueError('Qualification table must be a sibling regular file')
        self.spec, self.kind = spec, kind

    def __len__(self):
        return self.spec['table']['record_count']

    def __getitem__(self, position):
        if not isinstance(position, int) or position < 0:
            raise IndexError('Only nonnegative record positions are supported')
        for n, record in enumerate(self):
            if n == position:
                return record
        raise IndexError(position)

    def __iter__(self):
        if self.path.stat().st_size > 25 * 1024 * 1024:
            raise ValueError('Qualification CSV exceeds budget')
        digest = hashlib.sha256()
        with self.path.open('rb') as stream:
            for part in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(part)
        if digest.hexdigest() != self.spec['table']['sha256']:
            raise ValueError('Qualification CSV hash mismatch')
        count = 0
        with self.path.open(encoding='utf-8', newline='') as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != self.spec['table']['fields']:
                raise ValueError('Qualification CSV schema mismatch')
            for row in reader:
                count += 1
                if self.kind == 'qsl':
                    values = json.loads(row['raw_values_json'])
                    if len(values) != len(self.spec['columns']):
                        raise ValueError('QSL source column count mismatch')
                    typed = dict(zip((c['key'] for c in self.spec['columns']), values))
                    row.update(typed)
                    row.update({alias: typed[key] for alias, key in self.spec['aliases'].items()})
                    row['source_row'] = int(row['source_row'])
                    # Compatibility records retain all aliases and original columns.
                    # Large raw source containers are never forwarded as evidence.
                    row.pop('raw_values_json')
                    row.pop('cell_types_json')
                else:
                    for key in ['source_page', 'source_row', 'product_group_source_page', 'product_group_source_row']:
                        row[key] = int(row[key]) if row[key] else None
                yield row
        if count != len(self):
            raise ValueError('Qualification CSV record count mismatch')


def norm(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).split()).casefold()


def route(purchaser):
    value = norm(purchaser)
    if not value:
        return None
    if value in {'空客', '空中客车', 'airbus'}:
        return 'qpl'
    if value in {'商飞', '中国商飞', '中国商用飞机', 'comac'}:
        return 'qsl'
    return 'skip'


def lookup(index, purchaser, supplier_names, manufacturer_names=()):
    target = route(purchaser)
    result = {'purchaser': purchaser, 'list': target, 'approval_verdict': None}
    if target is None:
        return {**result, 'status': 'not_requested', 'whitelist_status': 'not_requested', 'meets_list_requirement': None, 'message': '未提供本次甲方，尚未触发名录核验。'}
    if target == 'skip':
        return {**result, 'status': 'not_required', 'whitelist_status': 'not_required', 'meets_list_requirement': None, 'message': '按本次范围无需名录核验；不表示已合格。'}
    if not index:
        return {**result, 'status': 'index_unavailable', 'whitelist_status': 'unavailable', 'meets_list_requirement': None, 'message': '名录索引未配置，不能判断资质。'}
    names = {norm(v): str(v).strip() for v in list(supplier_names) + list(manufacturer_names) if norm(v)}
    evidence, evidence_count, evidence_chars = [], 0, 0
    exact_supplier_hits, ambiguous_supplier_hits = 0, 0
    manufacturers = {norm(v) for v in manufacturer_names if norm(v)}
    suppliers = {norm(v) for v in supplier_names if norm(v)}

    def collect(item):
        nonlocal evidence_count, evidence_chars, exact_supplier_hits, ambiguous_supplier_hits
        if item.get('match_role') == 'historical_supplier':
            if item.get('match_method') == 'normalized_exact_company_name' and item.get('row_kind') == 'supplier_record':
                exact_supplier_hits += 1
            else:
                ambiguous_supplier_hits += 1
        evidence_count += 1
        size = len(json.dumps(item, ensure_ascii=False))
        if len(evidence) < MAX_EVIDENCE and evidence_chars + size <= MAX_EVIDENCE_CHARS:
            evidence.append(item)
            evidence_chars += size

    if target == 'qsl':
        for row in index['qsl']['records']:
            if norm(row['supplier_name']) in names:
                collect({'match_role': 'historical_supplier' if norm(row['supplier_name']) in suppliers else 'manufacturer',
                         'match_method': 'normalized_exact_company_name',
                         **{key: row[key] for key in QSL_EVIDENCE_FIELDS if key in row}})
    elif 'records' in index['qpl']:
        patterns = [(key, name, re.compile(r'(?<!\w)' + re.escape(key) + r'(?!\w)')) for key, name in names.items()]
        for row in index['qpl']['records']:
            if row['row_kind'] == 'product_group_header':
                continue
            company = norm(row['company_name'])
            candidate_text = company if company else norm(row['raw_text'])
            for key, name, pattern in patterns:
                if not pattern.search(candidate_text):
                    continue
                item = {k: row[k] for k in (
                    'record_id', 'row_kind', 'source_page', 'source_row', 'company_name',
                    'company_code', 'address', 'city', 'country', 'product_group_code',
                    'product_group', 'product_group_source_page', 'product_group_source_row',
                    'parse_status', 'review_notes')}
                item.update(queried_name=name,
                            match_method='normalized_exact_company_name' if key == company else 'literal_name_in_pdf_company_field' if company else 'literal_name_in_unparsed_pdf_fragment',
                            match_role='historical_supplier' if key in suppliers else 'manufacturer',
                            excerpt=row['raw_text'], pages=[row['source_page']],
                            identity_and_scope='requires_manual_confirmation')
                collect(item)
    else:
        # Text matching only retrieves candidate source lines, never asserts legal-entity identity.
        patterns = [(name, re.compile(r'(?<!\w)' + re.escape(key) + r'(?!\w)')) for key, name in names.items()]
        seen = {}
        for page in index['qpl']['pages']:
            for line in page['text'].splitlines():
                normalized = norm(line)
                for name, pattern in patterns:
                    if pattern.search(normalized):
                        key = (name, normalized)
                        if key not in seen:
                            seen[key] = {'queried_name': name, 'match_method': 'literal_name_in_pdf_line',
                                         'match_role': 'historical_supplier' if norm(name) in suppliers else 'manufacturer',
                                         'excerpt': line, 'pages': [],
                                         'identity_and_scope': 'requires_manual_confirmation'}
                        seen[key]['pages'].append(page['page'])
        for item in seen.values():
            collect(item)
    missing = []
    if not manufacturers:
        missing.append('采购记录缺制造商；不能补造供应商与原厂的对应关系。')
    membership = 'listed' if exact_supplier_hits else 'unresolved' if ambiguous_supplier_hits or not suppliers else 'not_listed'
    return {**result, 'whitelist_status': membership,
            'meets_list_requirement': True if membership == 'listed' else False if membership == 'not_listed' else None,
            'supplier_evidence_count': exact_supplier_hits,
            'status': 'evidence_found_scope_review' if evidence_count else
            ('insufficient_information' if missing or not names else 'no_evidence_found'),
            'information_status': 'insufficient_information' if missing else 'scope_review_required',
            'source': index[target]['source'],
            'evidence_count': evidence_count, 'evidence': evidence,
            'truncated': len(evidence) < evidence_count,
            'evidence_budget': {'max_records': MAX_EVIDENCE, 'max_characters': MAX_EVIDENCE_CHARS},
            'missing': missing, 'message': '仅提供所给版本的名录证据；主体、场所、产品范围及现行有效性须复核。'}


def load(path):
    raw = Path(path).read_bytes()
    if len(raw) > 15 * 1024 * 1024:
        raise ValueError('Qualification index exceeds budget')
    index = json.loads(raw)
    if index.get('version') == 2:
        if len(raw) > 256 * 1024:
            raise ValueError('Qualification manifest exceeds budget')
        for kind in ['qpl', 'qsl']:
            index[kind]['records'] = CSVRecords(Path(path).resolve().parent, index[kind], kind)
    elif index.get('version') != 1:
        raise ValueError('Unsupported qualification index')
    return index


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', required=True)
    parser.add_argument('--purchaser', required=True)
    parser.add_argument('--supplier-name', action='append', default=[])
    parser.add_argument('--manufacturer-name', action='append', default=[])
    args = parser.parse_args()
    print(json.dumps(lookup(load(args.index), args.purchaser, args.supplier_name,
                            args.manufacturer_name), ensure_ascii=False, allow_nan=False))
