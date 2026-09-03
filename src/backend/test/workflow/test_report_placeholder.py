"""F043: report template placeholder key normalization.

The report node writes placeholders as ``{{display name|node_id.field}}`` so
users can read which node a variable comes from, while execution still resolves
values by node id (release-contract INV-8). Legacy templates hold the bare
``{{node_id.field}}`` form and must keep resolving unchanged, forever.

See features/v3.0.0-beta1/043-report-node-optimization/design.md §3 decision 3/4.
"""

from bisheng.workflow.nodes.report.docx_replace import normalize_placeholder_key


class TestNormalizePlaceholderKey:
    """AC-04 / AC-05 / AC-06 — display name is stripped, node id is the key."""

    def test_new_format_strips_display_name(self):
        # AC-04: the readable prefix never reaches the variable lookup.
        assert normalize_placeholder_key('报告生成|node_a.output') == 'node_a.output'

    def test_legacy_format_passes_through(self):
        # AC-06: templates written before this feature keep working untouched.
        assert normalize_placeholder_key('node_a.output') == 'node_a.output'

    def test_display_name_containing_separator(self):
        # A node named "a|b" must not shift the split point: take the LAST pipe.
        assert normalize_placeholder_key('a|b|node_a.output') == 'node_a.output'

    def test_array_index_suffix_preserved(self):
        # `#index` belongs to the lookup key and must survive normalization.
        assert normalize_placeholder_key('汇总节点|node_a.out#0') == 'node_a.out#0'

    def test_empty_display_name(self):
        assert normalize_placeholder_key('|node_a.out') == 'node_a.out'

    def test_surrounding_whitespace_trimmed(self):
        # Editors may introduce stray spaces around the separator.
        assert normalize_placeholder_key(' 报告 | node_a.out ') == 'node_a.out'

    def test_empty_string(self):
        assert normalize_placeholder_key('') == ''
