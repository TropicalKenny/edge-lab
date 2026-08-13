from app.server import app


def test_composed_server_exposes_research_routes_without_live_execution():
    paths = set(app.openapi()["paths"])
    assert "/portfolio/allocate" in paths
    assert "/portfolio/runs/{run_id}" in paths
    assert "/portfolio/treasury/status" in paths
    assert "/evaluation/strategy" in paths
    assert "/evaluation/runs/{run_id}" in paths
    assert "/evaluation/status" in paths
    assert "/signer/status" in paths
