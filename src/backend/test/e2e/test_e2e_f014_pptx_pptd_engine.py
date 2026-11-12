"""F014 E2E: the built-in PPT skill (``bisheng-pptx``) on the PPTD engine, against a live deployment.

Read-only: the suite creates no data, so there is nothing to clean up.

    E2E_API_BASE=http://<host>:7860/api/v1 E2E_ADMIN_TOKEN=... \\
    [E2E_USER_NAME=... E2E_USER_PASSWORD=...] pytest test/e2e/test_e2e_f014_pptx_pptd_engine.py

The deployed bundle must be the one in this checkout (AC-17 compares content
hashes). The engine run (AC-01/02/09/10) needs the PPTD runtime on the machine
running pytest and skips without it; run the suite on the deployment host to
cover it. The plain-user denial pair needs E2E_USER_NAME/E2E_USER_PASSWORD and
skips without them.
"""

from __future__ import annotations

import io
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import httpx
import pytest

from bisheng.linsight.domain.services import builtin_skill_seeder as seeder
from bisheng.linsight.domain.services.skill_store import bundle_content_hash
from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers, get_admin_token, get_user_token

SKILL = "bisheng-pptx"
SKILL_API = f"{API_BASE}/linsight/skill"
TENANT_ADMIN_REQUIRED = 19801
SKILL_NOT_FOUND = 11053
SKILL_VERSION_CHANGED = 11051
PASS = "结论: 通过，可以 render"
FAIL = "结论: 需要修改"
OLD_SCRIPTS = (
    "scripts/render_deck.py",
    "scripts/inspect_deck.py",
    "scripts/probe_template.py",
    "scripts/pptx_helpers.py",
)
BRANDS = re.compile(r"(?i)(?<![a-z])dsh(?![a-z])|deepseek|workbuddy|bisheng|毕昇|灵思|linsight|dataelement")
RUNTIME = Path(os.environ.get("PPTD_RUNTIME", "/opt/pptd-runtime"))
HAS_ENGINE = (RUNTIME / "bin" / "node").exists() and (RUNTIME / "engine" / "lib" / "bin.js").exists()

pytestmark = pytest.mark.skipif(
    not (os.environ.get("E2E_ADMIN_TOKEN") or os.environ.get("E2E_ADMIN_PASSWORD")),
    reason="live E2E: set E2E_API_BASE and E2E_ADMIN_TOKEN (or E2E_ADMIN_PASSWORD)",
)


@pytest.fixture
async def admin():
    async with httpx.AsyncClient(timeout=60) as client:
        yield client, auth_headers(await get_admin_token(client))


async def _get(admin, path: str = "", **params):
    client, headers = admin
    return await client.get(f"{SKILL_API}{path}", headers=headers, params=params)


async def _bundle(admin) -> dict[str, bytes]:
    catalog = assert_resp_200(await _get(admin, "/runtime/catalog"))
    entry = next(e for e in catalog if e["name"] == SKILL)
    resp = await _get(admin, f"/runtime/{entry['id']}/bundle", version=entry["content_hash"])
    assert resp.status_code == 200, resp.text[:200]
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        return {n: zf.read(n) for n in zf.namelist() if not n.endswith("/")}


def _run(script: Path, *args: str, cwd: Path, runtime: str | None = None) -> str:
    env = {**os.environ, "PPTD_RUNTIME": runtime or str(RUNTIME)}
    proc = subprocess.run(
        [sys.executable, str(script), *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=300
    )
    assert proc.returncode == 0, proc.stderr[-2000:]  # contract: always exit 0, report on stdout
    return proc.stdout


class TestE2EF014PptxPptdEngine:
    async def test_ac05_trigger_boundary_with_html_report(self, admin):
        """AC-05: 「PPT 制作」触发 .pptx，网页幻灯片交给 html-report；两边描述互相写明分界。"""
        page = assert_resp_200(await _get(admin, keyword="", page_size=100))
        rows = {r["name"]: r for r in page["data"]}
        pptx = rows[SKILL]
        assert pptx["display_name"] == "PPT 制作"
        assert ".pptx" in pptx["description"] and "网页报告" in pptx["description"]
        html = rows["html-report"]
        assert "pptx" in html["description"].lower() or "PPT 制作" in html["description"]

    async def test_ac17_upgrade_replaced_builtin_in_place(self, admin):
        """AC-17: 来源仍为内置的 bisheng-pptx 已替换为本分支的内容，行（id、启用、默认勾选）原样保留。"""
        detail = assert_resp_200(await _get(admin, f"/{SKILL}"))
        assert detail["source"] == "builtin"
        assert detail["enabled"] is True
        assert isinstance(detail["default_checked"], bool)
        _, files = seeder.discover_builtin_bundles()[SKILL]
        catalog = assert_resp_200(await _get(admin, "/runtime/catalog"))
        entry = next(e for e in catalog if e["name"] == SKILL)
        assert entry["id"] == detail["id"]
        assert entry["content_hash"] == bundle_content_hash(files), "deployed bundle differs from this checkout"
        assert "PPTD" in detail["preview"]

    async def test_ac19_only_one_pptx_skill_mounted(self, admin):
        """AC-19: 新任务只挂载一个制作 .pptx 的技能，验证期的个人技能 pptd-deck 不存在。"""
        catalog = assert_resp_200(await _get(admin, "/runtime/catalog"))
        names = [e["name"] for e in catalog]
        assert names.count(SKILL) == 1
        assert not [n for n in names if "pptd" in n]
        assert_resp_error(await _get(admin, "/pptd-deck"), SKILL_NOT_FOUND)

    async def test_ac12_ac13_bundle_contents(self, admin):
        """AC-12/13: 下发的技能包含 17 套模板（政企红居首），旧脚本已删除，客户可读内容无品牌名。"""
        files = await _bundle(admin)
        assert "scripts/pptd.py" in files
        assert not [p for p in OLD_SCRIPTS if p in files]
        assert not [p for p in files if p.startswith("templates/") and p.endswith((".pptx", "layouts.json"))]
        template_ids = {p.split("/")[1] for p in files if p.startswith("templates/") and p.endswith("/design.md")}
        assert len(template_ids) == 17 and "gov-red" in template_ids
        for tid in template_ids:
            pages = [p for p in files if p.startswith(f"templates/{tid}/source-zh/pages/") and p.endswith(".page")]
            assert f"templates/{tid}/source-zh/deck.pptd" in files and len(pages) == 12, tid
        catalog_rows = [ln for ln in files["templates/catalog.md"].decode().splitlines() if ln.startswith("| ")]
        assert catalog_rows[1].startswith("| gov-red ")
        for path, data in files.items():
            if (
                "licenses/" in path
                or path.endswith("LICENSES.md")
                or not path.endswith((".md", ".py", ".pptd", ".page"))
            ):
                continue
            hit = BRANDS.search(data.decode("utf-8").replace(SKILL, ""))
            assert hit is None, f"{path}: {hit.group(0)}"

    async def test_ac04_missing_engine_stops_with_notice(self, admin, tmp_path):
        """AC-04: 下发的脚本在没有引擎的环境里提示联系管理员并给出「需要修改」，不改用其他方式。"""
        files = await _bundle(admin)
        root = tmp_path / "skills" / SKILL
        for path, data in files.items():
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_bytes(data)
        out = _run(
            root / "scripts/pptd.py",
            "check",
            str(root / "templates/gov-red/source-zh"),
            cwd=tmp_path,
            runtime=str(tmp_path / "none"),
        )
        assert "当前环境未安装 PPT 引擎，请联系管理员" in out
        assert out.strip().endswith(FAIL)

    @pytest.mark.skipif(not HAS_ENGINE, reason="PPTD runtime not installed on this machine")
    async def test_ac01_ac09_ac10_engine_check_and_render(self, admin, tmp_path):
        """AC-01/02/09/10: 用下发的技能包检查并导出政企红工程：通过检查、原生对象、无整页图片、字体只有雅黑和 Arial；字号低于下限时拒绝导出。"""
        files = await _bundle(admin)
        root = tmp_path / "skills" / SKILL
        for path, data in files.items():
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_bytes(data)
        project = root / "templates/gov-red/source-zh"
        out = _run(root / "scripts/pptd.py", "check", str(project), cwd=tmp_path)
        assert out.strip().endswith(PASS), out[-1500:]
        pptx = tmp_path / "output" / "政企红.pptx"
        out = _run(root / "scripts/pptd.py", "render", str(project), str(pptx), cwd=tmp_path)
        assert "已导出" in out, out[-1500:]
        with zipfile.ZipFile(pptx) as zf:
            names = zf.namelist()
            assert len([n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]) == 12
            assert not [n for n in names if n.startswith("ppt/media/") and not n.endswith("/")]
            slides = "".join(zf.read(n).decode("utf-8") for n in names if n.startswith("ppt/slides/slide"))
            theme = zf.read("ppt/theme/theme1.xml").decode("utf-8")
        # The stock theme also maps fallback faces per script (<a:font script="Thai" ...>); AC-10 is about the
        # faces the text uses: every run on the slides, plus the theme's major/minor latin and East Asian faces.
        faces = set(re.findall(r'typeface="([^"]+)"', slides))
        faces |= {f for f in re.findall(r'<a:(?:latin|ea) typeface="([^"]*)"', theme) if f}
        assert faces <= {"Microsoft YaHei", "Arial"}, faces

        page = next((project / "pages").glob("04*.page"))
        page.write_text(re.sub(r"fontSize: 1[1-4]\b", "fontSize: 8", page.read_text("utf-8")), "utf-8")
        out = _run(
            root / "scripts/pptd.py", "render", str(project), str(tmp_path / "output/低于下限.pptx"), cwd=tmp_path
        )
        assert "未导出" in out and not (tmp_path / "output/低于下限.pptx").exists()

    async def test_ac17_denied_for_plain_user(self, admin):
        """AC-17 拒绝配对: 普通用户不能读内置技能的管理详情（19801）。"""
        name, password = os.environ.get("E2E_USER_NAME"), os.environ.get("E2E_USER_PASSWORD")
        if not (name and password):
            pytest.skip("set E2E_USER_NAME / E2E_USER_PASSWORD for the plain-user pair")
        client, _ = admin
        headers = auth_headers(await get_user_token(client, name, password))
        resp = await client.get(f"{SKILL_API}/{SKILL}", headers=headers)
        assert_resp_error(resp, TENANT_ADMIN_REQUIRED)
        catalog = assert_resp_200(await client.get(f"{SKILL_API}/runtime/catalog", headers=headers))
        assert [e["name"] for e in catalog].count(SKILL) == 1

    async def test_bundle_rejects_stale_version(self, admin):
        """AC-19 拒绝配对: 用升级前的内容哈希下载技能包被拒绝，新任务拿不到旧版本。"""
        catalog = assert_resp_200(await _get(admin, "/runtime/catalog"))
        entry = next(e for e in catalog if e["name"] == SKILL)
        resp = await _get(admin, f"/runtime/{entry['id']}/bundle", version="0" * 64)
        assert_resp_error(resp, SKILL_VERSION_CHANGED)
