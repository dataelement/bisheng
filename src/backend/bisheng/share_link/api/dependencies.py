"""Compatibility exports for sharing dependencies; authorization is unchanged."""

from bisheng.share_link.domain.services.share_token_dependencies import (
    get_share_link_repository as get_share_link_repository,
    get_share_link_service as get_share_link_service,
    header_share_token_parser as header_share_token_parser,
)
