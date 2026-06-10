from pathlib import Path


def test_repository_keeps_business_logic_out_of_data_access_layer():
    source = Path("bisheng/developer_token/domain/repositories/developer_token_repository.py").read_text()

    forbidden_terms = [
        "ipaddress",
        "encrypt_token",
        "decrypt_token",
        "get_redis_client",
        "has_tenant_admin",
        "_check_is_global_super",
    ]
    for term in forbidden_terms:
        assert term not in source


def test_repository_exposes_required_contract_methods():
    from bisheng.developer_token.domain.repositories import DeveloperTokenRepository

    for name in (
        "list_tokens",
        "get_token_by_id",
        "get_token_by_hash",
        "create_token",
        "update_token",
        "logic_delete_token",
        "update_last_used",
    ):
        assert hasattr(DeveloperTokenRepository, name)
