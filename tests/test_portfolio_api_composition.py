from app.server import app


def test_composed_server_exposes_portfolio_routes_without_live_execution():
    paths = {path for route in app.routes if (path := getattr(route, "path", None)) is not None}
    assert "/portfolio/allocate" in paths
    assert "/portfolio/runs/{run_id}" in paths
    assert "/portfolio/treasury/status" in paths
    assert "/signer/status" in paths
