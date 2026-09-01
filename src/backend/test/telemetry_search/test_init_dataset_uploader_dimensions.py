"""T008 — knowledge-space content stat dataset exposes the full "原始上传库" (uploader) org
tier as dashboard dimensions, symmetric with the existing "所属" (belonging) tier (F058, AC-08).
"""

from bisheng.telemetry_search.domain.init_dataset import DASHBOARD_DATASET


def _dataset(code: str):
    return next(d for d in DASHBOARD_DATASET if d.dataset_code == code)


def test_uploader_org_dimensions_registered():
    dataset = _dataset("mid_knowledge_space_content_stat")
    fields = {dim["field"] for dim in dataset.schema_config["dimensions"]}

    for field in (
        "uploader_company_name",
        "uploader_department_name",
        "uploader_office_name",
        "uploader_squad_name",
    ):
        assert field in fields, f"{field} must be a selectable dashboard dimension"


def test_uploader_dimensions_symmetric_with_belonging_dimensions():
    dataset = _dataset("mid_knowledge_space_content_stat")
    fields = {dim["field"] for dim in dataset.schema_config["dimensions"]}

    belonging = {f for f in fields if f.startswith("belonging_")}
    uploader = {
        f
        for f in fields
        if f.startswith("uploader_") and f.endswith(("company_name", "department_name", "office_name", "squad_name"))
    }

    assert {f.removeprefix("belonging_") for f in belonging} == {f.removeprefix("uploader_") for f in uploader}
