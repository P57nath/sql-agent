import pytest
from mcp_server.guardrails import GuardrailError, validate_query


def test_valid_select():
    sql = validate_query("SELECT id, name FROM customers")
    assert "LIMIT" in sql


def test_rejects_insert():
    with pytest.raises(GuardrailError, match="Only SELECT"):
        validate_query("INSERT INTO customers (name) VALUES ('x')")


def test_rejects_drop():
    with pytest.raises(GuardrailError):
        validate_query("DROP TABLE customers")


def test_rejects_comment():
    with pytest.raises(GuardrailError, match="comments"):
        validate_query("SELECT * FROM customers -- bypass")


def test_limit_already_present():
    sql = validate_query("SELECT * FROM customers LIMIT 10")
    # Should not double-add LIMIT
    assert sql.count("LIMIT") == 1


def test_empty_query():
    with pytest.raises(GuardrailError, match="Empty"):
        validate_query("")
