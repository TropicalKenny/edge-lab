from pathlib import Path
import tomllib

from fastapi.routing import APIRoute

from app.dashboard_server import app as dashboard_app
from app.main import app as internal_app
from app.version import APP_VERSION


ROOT = Path(__file__).resolve().parents[1]


def _route_method_keys(app) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods or set():
            keys.append((route.path, method))
    return keys


def _operation_ids(app) -> list[str]:
    schema = app.openapi()
    operation_ids: list[str] = []
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            if isinstance(operation, dict) and operation.get("operationId"):
                operation_ids.append(str(operation["operationId"]))
    return operation_ids


def test_internal_api_has_no_duplicate_path_method_registration():
    keys = _route_method_keys(internal_app)
    assert len(keys) == len(set(keys))


def test_internal_api_has_unique_openapi_operation_ids():
    operation_ids = _operation_ids(internal_app)
    assert operation_ids
    assert len(operation_ids) == len(set(operation_ids))


def test_dashboard_surface_has_no_duplicate_path_method_registration():
    keys = _route_method_keys(dashboard_app)
    assert len(keys) == len(set(keys))


def test_application_versions_use_one_source_of_truth():
    assert internal_app.version == APP_VERSION
    assert dashboard_app.version == APP_VERSION

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert "version" in pyproject["project"]["dynamic"]
    assert pyproject["tool"]["setuptools"]["dynamic"]["version"]["attr"] == "app.version.APP_VERSION"
