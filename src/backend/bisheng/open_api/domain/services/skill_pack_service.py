"""Deterministically render and package shipped Open API skills."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from bisheng.common.errcode.open_api import ApiCredentialNotFoundError

SKILL_PACK_NAMES = frozenset({"bisheng-knowledge-search"})
_PACK_ROOT = Path(__file__).resolve().parents[2] / "skill_packs"
_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


class SkillPackService:
    @classmethod
    def build(cls, pack_name: str, *, base_url: str) -> bytes:
        if pack_name not in SKILL_PACK_NAMES:
            raise ApiCredentialNotFoundError(msg="Skill pack not found")
        normalized_base_url, outbound_origin = cls._instance_urls(base_url)
        pack_dir = (_PACK_ROOT / pack_name).resolve()
        if pack_dir.parent != _PACK_ROOT.resolve() or not pack_dir.is_dir():
            raise ApiCredentialNotFoundError(msg="Skill pack not found")

        rendered: list[tuple[str, bytes]] = []
        for path in sorted(item for item in pack_dir.rglob("*") if item.is_file()):
            relative = path.relative_to(pack_dir).as_posix()
            cls._assert_safe_relative_path(relative)
            payload = path.read_bytes()
            if path.suffix in {".md", ".py"}:
                text = payload.decode("utf-8")
                text = text.replace("{{BASE_URL}}", normalized_base_url)
                text = text.replace("{{OUTBOUND_ORIGIN}}", outbound_origin)
                payload = text.encode("utf-8")
            rendered.append((f"{pack_name}/{relative}", payload))

        output = BytesIO()
        with ZipFile(output, mode="w", compression=ZIP_STORED) as archive:
            for name, payload in rendered:
                info = ZipInfo(name, date_time=_FIXED_ZIP_TIME)
                info.compress_type = ZIP_STORED
                info.create_system = 3
                info.external_attr = (0o755 if name.endswith(".py") else 0o644) << 16
                archive.writestr(info, payload)
        return output.getvalue()

    @staticmethod
    def _instance_urls(base_url: str) -> tuple[str, str]:
        parsed = urlsplit(base_url.rstrip("/"))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        origin = f"{parsed.scheme}://{parsed.netloc}"
        path = parsed.path.rstrip("/")
        return f"{origin}{path}", origin

    @staticmethod
    def _assert_safe_relative_path(value: str) -> None:
        relative = PurePosixPath(value)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("unsafe skill-pack path")

