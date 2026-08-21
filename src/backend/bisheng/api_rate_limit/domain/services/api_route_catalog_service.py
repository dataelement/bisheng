from __future__ import annotations

from collections.abc import Sequence
from math import ceil

from fastapi.routing import APIRoute
from starlette.routing import BaseRoute

from bisheng.api_rate_limit.domain.schemas.api_rate_limit import (
    ApiRateLimitRouteCatalog,
    ApiRateLimitRouteCatalogItem,
    HttpMethod,
)
from bisheng.api_rate_limit.route_scope import (
    SUPPORTED_HTTP_METHODS,
    is_api_rate_limit_excluded,
)

UNCATEGORIZED_ROUTE_TAG = "__uncategorized__"
_METHOD_ORDER = {method: index for index, method in enumerate(("GET", "POST", "PUT", "PATCH", "DELETE"))}


class ApiRouteCatalogService:
    @classmethod
    def list_routes(
        cls,
        routes: Sequence[BaseRoute],
        *,
        keyword: str | None = None,
        method: HttpMethod | None = None,
        tag: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> ApiRateLimitRouteCatalog:
        all_items = cls._extract_routes(routes)
        categories = sorted(
            {item.primary_tag for item in all_items},
            key=lambda value: (value == UNCATEGORIZED_ROUTE_TAG, value.casefold()),
        )

        filtered_items = all_items
        if method is not None:
            filtered_items = [item for item in filtered_items if item.method == method]
        if tag:
            normalized_tag = tag.strip().casefold()
            filtered_items = [
                item
                for item in filtered_items
                if item.primary_tag.casefold() == normalized_tag
                or any(route_tag.casefold() == normalized_tag for route_tag in item.tags)
            ]
        if keyword:
            normalized_keyword = keyword.strip().casefold()
            if normalized_keyword:
                filtered_items = [item for item in filtered_items if normalized_keyword in cls._searchable_text(item)]

        total = len(filtered_items)
        total_pages = ceil(total / page_size) if total else 0
        start = (page - 1) * page_size
        return ApiRateLimitRouteCatalog(
            items=filtered_items[start : start + page_size],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            categories=categories,
        )

    @classmethod
    def _extract_routes(cls, routes: Sequence[BaseRoute]) -> list[ApiRateLimitRouteCatalogItem]:
        items_by_identity: dict[tuple[str, str], ApiRateLimitRouteCatalogItem] = {}
        for route in routes:
            if not isinstance(route, APIRoute):
                continue
            path = route.path_format or route.path
            tags = cls._normalize_tags(route.tags)
            primary_tag = tags[0] if tags else UNCATEGORIZED_ROUTE_TAG
            for method in sorted(route.methods or set(), key=lambda value: _METHOD_ORDER.get(value, 999)):
                normalized_method = method.upper()
                if normalized_method not in SUPPORTED_HTTP_METHODS or is_api_rate_limit_excluded(
                    path, normalized_method
                ):
                    continue
                identity = (normalized_method, path)
                items_by_identity.setdefault(
                    identity,
                    ApiRateLimitRouteCatalogItem(
                        method=HttpMethod(normalized_method),
                        path=path,
                        tags=tags,
                        primary_tag=primary_tag,
                        name=route.name or "",
                        summary=route.summary or "",
                    ),
                )
        return sorted(
            items_by_identity.values(),
            key=lambda item: (
                item.primary_tag == UNCATEGORIZED_ROUTE_TAG,
                item.primary_tag.casefold(),
                item.path,
                _METHOD_ORDER.get(item.method.value, 999),
            ),
        )

    @staticmethod
    def _normalize_tags(tags: Sequence[str | object]) -> list[str]:
        normalized: list[str] = []
        for tag in tags:
            value = str(getattr(tag, "value", tag)).strip()
            if value and value not in normalized:
                normalized.append(value)
        return normalized

    @staticmethod
    def _searchable_text(item: ApiRateLimitRouteCatalogItem) -> str:
        return " ".join(
            (
                item.method.value,
                item.path,
                *item.tags,
                item.primary_tag,
                item.name,
                item.summary,
            )
        ).casefold()
