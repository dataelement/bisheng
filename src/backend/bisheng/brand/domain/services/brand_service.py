import asyncio
import json
import mimetypes
import re
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from loguru import logger

from bisheng.brand.domain.repositories.brand_config_repository import BrandConfigRepository
from bisheng.brand.domain.schemas.brand_schema import (
    BrandAsset,
    BrandAssetCategory,
    BrandAssetOption,
    BrandAssetUploadResponse,
    BrandConfig,
    BrandConfigUpdate,
    BrandText,
)
from bisheng.common.errcode.server import UploadFileEmptyError, UploadFileExtError
from bisheng.common.services.config_service import settings as bisheng_settings
from bisheng.core.storage.minio.minio_manager import get_minio_storage

BRAND_CONFIG_KEY = "brand_config"
MAX_BRAND_ASSET_BYTES = 5 * 1024 * 1024
SUPPORTED_EXTENSIONS = {"ico", "png", "jpg", "jpeg", "svg", "gif", "webp"}
DEFAULT_ASSET_URLS = {
    "favicon": "/assets/bisheng/favicon.ico",
    "loginHeroLight": "/assets/bisheng/login-logo-big.png",
    "loginHeroDark": "/assets/bisheng/login-logo-dark.png",
    "headerLogoLight": "/assets/bisheng/login-logo-small.png",
    "headerLogoDark": "/assets/bisheng/logo-small-dark.png",
}
ASSET_CATEGORY_PREFIXES: dict[BrandAssetCategory, str] = {
    "favicon": "brand-assets/favicon",
    "loginHeroLight": "brand-assets/login-hero-light",
    "loginHeroDark": "brand-assets/login-hero-dark",
    "headerLogoLight": "brand-assets/header-logo-light",
    "headerLogoDark": "brand-assets/header-logo-dark",
    "loadingIcon": "brand-assets/loading-icon",
}
UPLOAD_NAME_PREFIX_PATTERN = re.compile(r"^[0-9a-f]{32}_(.+)$")
UNSAFE_FILENAME_PATTERN = re.compile(r'[<>:"|?*\x00-\x1f\x7f]+')
SCRIPT_RISK_PATTERN = re.compile(
    rb"(<\s*script\b|javascript\s*:|on(?:load|error|click|mouseover|focus)\s*=)",
    re.IGNORECASE,
)


def _builtin_config() -> BrandConfig:
    config = BrandConfig()
    for key, url in DEFAULT_ASSET_URLS.items():
        setattr(config.assets, key, BrandAsset(url=url, relative_path="", file_name=""))
    return config


def _merge_text(default_text: BrandText, value: Any) -> BrandText:
    if not isinstance(value, dict):
        return deepcopy(default_text)
    zh = str(value.get("zh") or "").strip()
    en = str(value.get("en") or "").strip()
    return BrandText(
        zh=zh or default_text.zh,
        en=en or default_text.en,
    )


def _merge_asset(default_asset: BrandAsset, value: Any) -> BrandAsset:
    if not isinstance(value, dict):
        return deepcopy(default_asset)
    return BrandAsset(
        url=str(value.get("url") or "").strip() or default_asset.url,
        relative_path=str(value.get("relative_path") or "").strip(),
        file_name=str(value.get("file_name") or "").strip(),
    )


def _default_config() -> BrandConfig:
    return _builtin_config()


class BrandService:
    def __init__(self, repository: BrandConfigRepository | None = None) -> None:
        self.repository = repository or BrandConfigRepository()

    async def get_config(self) -> BrandConfig:
        raw_value = await self.repository.get_value(BRAND_CONFIG_KEY)
        config = _default_config()
        if raw_value:
            try:
                saved = BrandConfig.model_validate(json.loads(raw_value))
                config = self._merge_with_defaults(saved)
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning("Invalid brand_config in DB, using defaults: %s", exc)
        await self._hydrate_asset_urls(config)
        return config

    async def save_config(self, config: BrandConfigUpdate) -> BrandConfig:
        normalized = self._merge_with_defaults(config)
        normalized.URLLoadingIcon = self._resolve_loading_icon_url(normalized)
        persisted = normalized.model_dump(mode="json")
        persisted.pop("linsightAgentName", None)
        await self.repository.upsert_value(
            BRAND_CONFIG_KEY,
            json.dumps(persisted, ensure_ascii=False),
        )
        await self._hydrate_asset_urls(normalized)
        return normalized

    async def list_asset_options(self, category: BrandAssetCategory) -> list[BrandAssetOption]:
        options = [self._default_asset_option(category)]

        minio_client = await get_minio_storage()
        bucket = bisheng_settings.object_storage.minio.public_bucket
        prefix = f"{ASSET_CATEGORY_PREFIXES[category]}/"

        try:
            objects = await asyncio.to_thread(
                lambda: list(
                    minio_client.minio_client_sync.list_objects(
                        bucket,
                        prefix=prefix,
                        recursive=True,
                    )
                )
            )
        except Exception:
            logger.exception("Failed to list brand asset options for category: %s", category)
            raise

        def sort_key(item: Any) -> datetime:
            return getattr(item, "last_modified", None) or datetime.min.replace(tzinfo=UTC)

        for item in sorted(objects, key=sort_key, reverse=True):
            object_name = getattr(item, "object_name", "")
            if not object_name:
                continue
            url = await minio_client.get_share_link(object_name, bucket=bucket)
            options.append(
                BrandAssetOption(
                    url=url,
                    relative_path=object_name,
                    file_name=self._display_filename_from_object_name(object_name),
                )
            )

        return options

    async def upload_asset(
        self,
        file: UploadFile,
        category: BrandAssetCategory | None = None,
    ) -> BrandAssetUploadResponse:
        if not file:
            raise UploadFileEmptyError()

        filename = PurePath(file.filename or "").name
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in SUPPORTED_EXTENSIONS:
            raise UploadFileExtError()

        payload = await file.read()
        if not payload:
            raise UploadFileEmptyError()
        if len(payload) > MAX_BRAND_ASSET_BYTES:
            raise HTTPException(status_code=413, detail="Brand asset size cannot exceed 5MB")
        if ext == "svg" and SCRIPT_RISK_PATTERN.search(payload):
            raise UploadFileExtError()

        object_name = self._build_object_name(filename, ext, category)
        content_type = file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        minio_client = await get_minio_storage()
        bucket = bisheng_settings.object_storage.minio.public_bucket
        await minio_client.put_object(
            bucket_name=bucket,
            object_name=object_name,
            file=payload,
            content_type=content_type,
        )
        url = await minio_client.get_share_link(object_name, bucket=bucket)
        return BrandAssetUploadResponse(url=url, relative_path=object_name, file_name=filename)

    async def delete_asset(self, category: BrandAssetCategory, relative_path: str) -> BrandAsset:
        object_name = relative_path.strip()
        self._validate_asset_object_name(category, object_name)

        minio_client = await get_minio_storage()
        bucket = bisheng_settings.object_storage.minio.public_bucket
        await minio_client.remove_object(bucket_name=bucket, object_name=object_name)
        await self._reset_saved_asset_if_deleted(category, object_name)

        default_asset = self._default_asset_option(category)
        return BrandAsset(
            url=default_asset.url,
            relative_path=default_asset.relative_path,
            file_name=default_asset.file_name,
        )

    async def get_runtime_config(self) -> dict[str, Any]:
        raw_value = await self.repository.get_value(BRAND_CONFIG_KEY)
        if not raw_value:
            return {}

        try:
            saved = BrandConfig.model_validate(json.loads(raw_value))
            config = self._merge_with_defaults(saved)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Invalid brand_config in DB, using static defaults for runtime: %s", exc)
            return {}

        await self._hydrate_asset_urls(config)
        payload_data = config.model_dump(mode="json")
        payload_data.pop("linsightAgentName", None)
        return payload_data

    def _merge_with_defaults(self, incoming: BrandConfig | BrandConfigUpdate) -> BrandConfig:
        merged = _default_config()
        data: dict[str, Any] = incoming.model_dump(mode="json")
        merged.brandName = _merge_text(merged.brandName, data.get("brandName"))
        merged.linsightAgentName = _merge_text(merged.linsightAgentName, data.get("linsightAgentName"))
        for key in DEFAULT_ASSET_URLS:
            saved_asset = data.get("assets", {}).get(key) or {}
            default_asset = getattr(merged.assets, key)
            setattr(
                merged.assets,
                key,
                BrandAsset(
                    url=saved_asset.get("url") or default_asset.url,
                    relative_path=saved_asset.get("relative_path") or "",
                    file_name=saved_asset.get("file_name") or "",
                ),
            )

        loading = data.get("loading") or {}
        icon_data = deepcopy(loading.get("icon")) if loading.get("icon") else None
        merged.loading.animation = loading.get("animation") or ""
        default_loading_icon = merged.loading.icon
        merged.loading.icon = (
            _merge_asset(default_loading_icon, icon_data)
            if icon_data and default_loading_icon
            else (BrandAsset.model_validate(icon_data) if icon_data else default_loading_icon)
        )
        merged.loading.iconOptions = [
            BrandAsset.model_validate(option) for option in loading.get("iconOptions") or [] if option
        ]
        merged.URLLoadingIcon = data.get("URLLoadingIcon") or merged.URLLoadingIcon
        if data.get("workbenchTheme") in ("blue", "green"):
            merged.workbenchTheme = data["workbenchTheme"]
        return merged

    async def _hydrate_asset_urls(self, config: BrandConfig) -> None:
        for key in DEFAULT_ASSET_URLS:
            asset = getattr(config.assets, key)
            await self._hydrate_asset_url(asset)
        if config.loading.icon:
            await self._hydrate_asset_url(config.loading.icon)
        for option in config.loading.iconOptions:
            await self._hydrate_asset_url(option)
        config.URLLoadingIcon = self._resolve_loading_icon_url(config)

    async def _hydrate_asset_url(self, asset: BrandAsset) -> None:
        if not asset.relative_path:
            return
        try:
            minio_client = await get_minio_storage()
            bucket = bisheng_settings.object_storage.minio.public_bucket
            asset.url = await minio_client.get_share_link(asset.relative_path, bucket=bucket)
        except Exception:
            logger.exception("Failed to build brand asset share link: %s", asset.relative_path)
            raise

    def _resolve_loading_icon_url(self, config: BrandConfig) -> str:
        if config.loading.icon and config.loading.icon.url:
            return config.loading.icon.url
        return config.URLLoadingIcon or ""

    def _default_asset_option(self, category: BrandAssetCategory) -> BrandAssetOption:
        default_url = DEFAULT_ASSET_URLS.get(category)
        if default_url:
            default_asset = getattr(_default_config().assets, category)
            return BrandAssetOption(
                url=default_asset.url,
                relative_path=default_asset.relative_path,
                file_name=default_asset.file_name or PurePath(default_asset.url).name,
                is_default=True,
            )
        default_loading = _default_config().loading.icon
        return BrandAssetOption(
            url=default_loading.url if default_loading else "",
            relative_path=default_loading.relative_path if default_loading else "",
            file_name=(default_loading.file_name if default_loading else "") or "default-loading-icon",
            is_default=True,
        )

    async def _reset_saved_asset_if_deleted(
        self,
        category: BrandAssetCategory,
        object_name: str,
    ) -> None:
        raw_value = await self.repository.get_value(BRAND_CONFIG_KEY)
        if not raw_value:
            return

        try:
            saved = BrandConfig.model_validate(json.loads(raw_value))
            normalized = self._merge_with_defaults(saved)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Invalid brand_config while deleting asset, skip config reset: %s", exc)
            return

        if category == "loadingIcon":
            changed = False
            if normalized.loading.icon and normalized.loading.icon.relative_path == object_name:
                normalized.loading.icon = None
                normalized.URLLoadingIcon = ""
                changed = True
            next_options = [option for option in normalized.loading.iconOptions if option.relative_path != object_name]
            if len(next_options) != len(normalized.loading.iconOptions):
                normalized.loading.iconOptions = next_options
                changed = True
            if not changed:
                return
            normalized.URLLoadingIcon = self._resolve_loading_icon_url(normalized)
            await self.repository.upsert_value(
                BRAND_CONFIG_KEY,
                json.dumps(normalized.model_dump(mode="json"), ensure_ascii=False),
            )
            return

        current_asset = getattr(normalized.assets, category)
        if current_asset.relative_path != object_name:
            return

        default_asset = getattr(_default_config().assets, category)
        setattr(
            normalized.assets,
            category,
            BrandAsset(
                url=default_asset.url, relative_path=default_asset.relative_path, file_name=default_asset.file_name
            ),
        )
        normalized.URLLoadingIcon = self._resolve_loading_icon_url(normalized)
        await self.repository.upsert_value(
            BRAND_CONFIG_KEY,
            json.dumps(normalized.model_dump(mode="json"), ensure_ascii=False),
        )

    def _validate_asset_object_name(self, category: BrandAssetCategory, object_name: str) -> None:
        prefix = f"{ASSET_CATEGORY_PREFIXES[category]}/"
        if not object_name or not object_name.startswith(prefix) or object_name.endswith("/"):
            raise HTTPException(status_code=400, detail="Invalid brand asset path")
        if ".." in PurePath(object_name).parts:
            raise HTTPException(status_code=400, detail="Invalid brand asset path")

    def _build_object_name(
        self,
        filename: str,
        ext: str,
        category: BrandAssetCategory | None,
    ) -> str:
        if not category:
            return f"brand/{uuid4().hex}.{ext}"

        prefix = ASSET_CATEGORY_PREFIXES[category]
        safe_filename = self._safe_filename(filename, ext)
        return f"{prefix}/{uuid4().hex}_{safe_filename}"

    def _safe_filename(self, filename: str, ext: str) -> str:
        safe_name = UNSAFE_FILENAME_PATTERN.sub("_", PurePath(filename or "").name).strip(" ._")
        if not safe_name:
            return f"asset.{ext}"

        suffix = f".{ext}"
        if not safe_name.lower().endswith(suffix):
            safe_name = f"{safe_name}{suffix}"

        if len(safe_name) <= 120:
            return safe_name

        stem = safe_name[: 120 - len(suffix)].rstrip(" ._")
        return f"{stem or 'asset'}{suffix}"

    def _display_filename_from_object_name(self, object_name: str) -> str:
        filename = PurePath(object_name).name
        match = UPLOAD_NAME_PREFIX_PATTERN.match(filename)
        return match.group(1) if match else filename
