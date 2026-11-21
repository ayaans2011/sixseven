"""Admin access integration tests. Configure tokens and a non-production test URL via environment variables."""
import os
import pytest
import requests

BASE_URL = os.environ.get("ZEROAXIS_TEST_BASE_URL", "").rstrip("/")
API = f"{BASE_URL}/api" if BASE_URL else ""
ADMIN_TOKEN = os.environ.get("ZEROAXIS_TEST_ADMIN_TOKEN", "")
CUSTOMER_TOKEN = os.environ.get("ZEROAXIS_TEST_CUSTOMER_TOKEN", "")


@pytest.fixture(scope="module")
def api_url():
    if not BASE_URL:
        pytest.skip("Set ZEROAXIS_TEST_BASE_URL to a dedicated test deployment; production is never used by default.")
    return API


def _session(token):
    session = requests.Session()
    if token:
        session.headers.update({"Authorization": f"Bearer {token}"})
    return session


@pytest.fixture(scope="module")
def admin_session(api_url):
    if not ADMIN_TOKEN:
        pytest.skip("Set ZEROAXIS_TEST_ADMIN_TOKEN in the test environment.")
    return _session(ADMIN_TOKEN)


@pytest.fixture(scope="module")
def customer_session(api_url):
    if not CUSTOMER_TOKEN:
        pytest.skip("Set ZEROAXIS_TEST_CUSTOMER_TOKEN in the test environment.")
    return _session(CUSTOMER_TOKEN)


def test_admin_stats_unauthenticated_is_denied(api_url):
    response = requests.get(f"{api_url}/admin/stats", timeout=15)
    assert response.status_code in (401, 403)


def test_customer_cannot_access_admin_routes(api_url, customer_session):
    paths = [
        "/admin/stats",
        "/admin/customers",
        "/orders/admin/all",
        "/enquiries/admin/all",
        "/reports/monthly",
        "/support/admin/tickets",
    ]
    for path in paths:
        response = customer_session.get(f"{api_url}{path}", timeout=15)
        assert response.status_code == 403, f"{path} returned {response.status_code}"


def test_admin_can_access_admin_dashboard_api(api_url, admin_session):
    response = admin_session.get(f"{api_url}/admin/stats", timeout=15)
    assert response.status_code == 200, response.text[:200]
    assert isinstance(response.json(), dict)
