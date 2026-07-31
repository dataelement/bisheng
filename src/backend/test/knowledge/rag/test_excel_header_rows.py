import os
import tempfile

import pytest

from bisheng.api.v1.schemas import ExcelRule, FileProcessBase
from bisheng.knowledge.rag.base_file_pipeline import BaseFilePipeline
from bisheng.knowledge.rag.pipeline.loader.utils.md_from_excel import convert_file_to_markdown


class _HeaderRowPipeline(BaseFilePipeline):
    @property
    def file_metadata(self) -> dict:
        return {}

    def prepare_local_file(self):
        pass


def test_excel_header_row_indices_are_zero_based():
    pipeline = _HeaderRowPipeline(
        invoke_user_id=1,
        file_name="sample.xlsx",
        file_rule=FileProcessBase(
            knowledge_id=1,
            excel_rule=ExcelRule(header_start_row=1, header_end_row=1),
        ),
    )
    assert pipeline._excel_header_row_indices() == [0, 0]

    pipeline.file_split_rule.excel_rule.header_start_row = 2
    pipeline.file_split_rule.excel_rule.header_end_row = 3
    assert pipeline._excel_header_row_indices() == [1, 2]


def test_split_fingerprint_changes_with_excel_header_rows():
    base_payload = FileProcessBase(
        knowledge_id=1,
        excel_rule=ExcelRule(header_start_row=1, header_end_row=1),
    ).model_dump(exclude={"knowledge_id"}, exclude_none=True)
    changed_payload = FileProcessBase(
        knowledge_id=1,
        excel_rule=ExcelRule(header_start_row=2, header_end_row=2),
    ).model_dump(exclude={"knowledge_id"}, exclude_none=True)
    base_fp = md5_hash(json.dumps(base_payload, sort_keys=True, ensure_ascii=False))
    changed_fp = md5_hash(json.dumps(changed_payload, sort_keys=True, ensure_ascii=False))
    assert base_fp != changed_fp


@pytest.mark.parametrize(
    "test_file",
    ["/Users/binfeng/Downloads/测试1.xlsx"],
)
def test_excel_markdown_uses_first_row_as_header(test_file: str):
    pytest.importorskip("openpyxl")
    if not os.path.exists(test_file):
        pytest.skip(f"missing fixture file: {test_file}")

    with tempfile.TemporaryDirectory() as tmp_dir:
        convert_file_to_markdown(
            input_file_path=test_file,
            num_header_rows=[0, 0],
            rows_per_markdown=10,
            base_output_dir=tmp_dir,
            append_header=True,
        )
        md_files = sorted(name for name in os.listdir(tmp_dir) if name.endswith(".md"))
        assert md_files, "expected at least one markdown chunk"
        content = open(f"{tmp_dir}/{md_files[0]}", encoding="utf-8").read()
        assert "| name | age |" in content
        assert "| 张三 | 28 |" in content
        assert content.index("| name | age |") < content.index("| 张三 | 28 |")
