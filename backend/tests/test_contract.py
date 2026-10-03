"""Contract tests: the YAML and the Pydantic models must not drift.

This is the guard the build prompts ask for: the four mandatory endpoints keep
their exact field names, and every documented path exists in the app.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.main import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OPENAPI_YAML = PROJECT_ROOT / "openapi.yaml"

# Fields the PS7/PS1 statement fixes by name. These may never disappear.
MANDATORY_FIELDS = {
    "AskRequest": {"question", "user_id"},
    "AskResponse": {"answer", "sources", "confidence"},
    "RouteRequest": {"request_id", "query", "complexity_hint"},
    "RouteResponse": {"request_id", "routed_to", "reasoning", "latency_ms", "estimated_cost"},
    "ResourceStatus": {"ram_available_mb", "cpu_load_pct", "bandwidth_kbps", "api_quota_remaining"},
}

MANDATORY_PATHS = [
    "/ask",
    "/health",
    "/route",
    "/resource-status",
]

EXTRA_PATHS = [
    "/ingest",
    "/ask/trace/{request_id}",
    "/placement/eligibility",
    "/placement/match",
    "/placement/skill-gap/{student_id}",
    "/placement/what-if",
    "/metrics",
    "/router/decisions",
    "/simulate",
    "/eval/run",
]


@pytest.fixture(scope="module")
def spec() -> dict:
    return yaml.safe_load(OPENAPI_YAML.read_text(encoding="utf-8"))


def test_openapi_yaml_exists_and_parses(spec: dict) -> None:
    assert spec["openapi"].startswith("3.")
    assert spec["info"]["title"]
    assert spec["paths"]


def test_every_documented_path_is_mounted(spec: dict) -> None:
    app = create_app()
    mounted = set(app.openapi()["paths"])
    for path in MANDATORY_PATHS + EXTRA_PATHS:
        assert f"/api/v1{path}" in mounted, f"{path} documented but not mounted"


def test_mandatory_fields_present_in_spec(spec: dict) -> None:
    schemas = spec["components"]["schemas"]
    for name, fields in MANDATORY_FIELDS.items():
        assert name in schemas, f"{name} missing from openapi.yaml"
        actual = set(schemas[name].get("properties", {}))
        missing = fields - actual
        assert not missing, f"{name} lost mandatory fields: {sorted(missing)}"


def test_mandatory_fields_present_in_models() -> None:
    from app.core import schemas

    for name, fields in MANDATORY_FIELDS.items():
        model = getattr(schemas, name)
        actual = set(model.model_fields)
        missing = fields - actual
        assert not missing, f"{name} lost mandatory fields: {sorted(missing)}"


def test_models_do_not_drift_from_yaml(spec: dict) -> None:
    """Compare documented property names against the generated JSON schema."""
    from app.core import schemas

    documented = spec["components"]["schemas"]
    checked = 0
    for name, schema in documented.items():
        model = getattr(schemas, name, None)
        if model is None or not hasattr(model, "model_json_schema"):
            continue
        generated = set(model.model_json_schema().get("properties", {}))
        expected = set(schema.get("properties", {}))
        assert expected <= generated, (
            f"{name}: documented properties missing from the model: "
            f"{sorted(expected - generated)}"
        )
        checked += 1
    assert checked >= 15, f"only {checked} schemas compared; the drift check is too weak"


def test_route_enum_matches_statement(spec: dict) -> None:
    assert set(spec["components"]["schemas"]["Route"]["enum"]) == {
        "cache",
        "local_model",
        "offline_fallback",
        "cloud_api",
    }


def test_live_app_schema_is_servable(client) -> None:
    """The running app serves an OpenAPI document with all required paths."""
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    for path in MANDATORY_PATHS + EXTRA_PATHS:
        assert f"/api/v1{path}" in paths
