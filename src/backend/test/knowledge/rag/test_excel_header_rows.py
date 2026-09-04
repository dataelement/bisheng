"""The Excel rule counts header rows the way the UI shows them (from 1); the
markdown converter slices a DataFrame (from 0). The pipeline owns that translation."""

import json
import os

import openpyxl

from bisheng.api.v1.schemas import ExcelRule, FileProcessBase
from bisheng.knowledge.rag.base_file_pipeline import BaseFilePipeline
from bisheng.knowledge.rag.pipeline.loader.excel import ExcelLoader
from bisheng.knowledge.rag.pipeline.loader.utils.md_from_excel import convert_file_to_markdown
from bisheng.utils import md5_hash


class _HeaderRowPipeline(BaseFilePipeline):
    @property
    def file_metadata(self) -> dict:
        return {}

    def prepare_local_file(self):
        pass


def _pipeline(excel_rule: ExcelRule | None) -> _HeaderRowPipeline:
    return _HeaderRowPipeline(
        invoke_user_id=1,
        file_name="sample.xlsx",
        file_rule=FileProcessBase(knowledge_id=1, excel_rule=excel_rule),
    )


def test_ui_default_first_row_becomes_dataframe_row_zero():
    assert _pipeline(ExcelRule(header_start_row=1, header_end_row=1))._excel_header_row_indices() == [0, 0]


def test_multi_row_header_shifts_both_ends():
    assert _pipeline(ExcelRule(header_start_row=2, header_end_row=3))._excel_header_row_indices() == [1, 2]


def test_missing_rule_and_bad_ranges_fall_back_to_a_single_first_row():
    # FileProcessBase fills in a default ExcelRule when none is given.
    assert _pipeline(None)._excel_header_row_indices() == [0, 0]
    assert _pipeline(ExcelRule(header_start_row=0, header_end_row=0))._excel_header_row_indices() == [0, 0]
    assert _pipeline(ExcelRule(header_start_row=3, header_end_row=1))._excel_header_row_indices() == [2, 2]


def _write_workbook(path: str) -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["name", "age"])
    sheet.append(["张三", 28])
    sheet.append(["李四", 31])
    workbook.save(path)


def test_converter_puts_the_column_names_above_the_separator(tmp_path):
    xlsx = str(tmp_path / "people.xlsx")
    _write_workbook(xlsx)
    out = str(tmp_path / "md")

    convert_file_to_markdown(xlsx, [0, 0], 10, out, append_header=True)

    content = open(os.path.join(out, sorted(os.listdir(out))[0]), encoding="utf-8").read()
    lines = content.splitlines()
    assert lines[0] == "| name | age |"
    assert lines[1].startswith("|---")
    assert lines[2] == "| 张三 | 28 |"


def test_loader_default_is_a_single_header_row(tmp_path):
    """With no rule at all the loader must not swallow the first data row either."""
    xlsx = str(tmp_path / "people.xlsx")
    _write_workbook(xlsx)

    loader = ExcelLoader(file_path=xlsx, file_metadata={}, file_extension="xlsx", tmp_dir=str(tmp_path / "work"))
    documents = loader.load()

    lines = documents[0].page_content.splitlines()
    assert lines[0] == "| name | age |"
    assert lines[2] == "| 张三 | 28 |"


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
