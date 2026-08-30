"""Backend auth enforcement tests for admin routes."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://business-platform-75.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "zeroaxis.pvtltd.in@gmail.com"
ADMIN_PASSWORD = "admin123"
CUSTOMER_EMAIL = "qrtest@zeroaxis.in"
CUSTOMER_PASSWORD = "Test@1234"


def _login(email, password):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    return s, r


@pytest.fixture(scope="module")
def admin_session():
    s, r = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    if r.status_code != 200:
        pytest.skip(f"Admin login failed: {r.status_code} {r.text}")
    return s


@pytest.fixture(scope="module")
def customer_session():
    s, r = _login(CUSTOMER_EMAIL, CUSTOMER_PASSWORD)
    if r.status_code != 200:
        # Try alternative test customer
        s, r = _login("testcustomer@zeroaxis.in", "Test@1234")
        if r.status_code != 200:
            pytest.skip(f"Customer login failed: {r.status_code} {r.text}")
    return s


# ---- Unauthenticated ----
def test_admin_stats_unauth_returns_401():
    r = requests.get(f"{API}/admin/stats", timeout=15)
    assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"


# ---- Customer forbidden on admin routes ----
def test_customer_forbidden_admin_stats(customer_session):
    r = customer_session.get(f"{API}/admin/stats", timeout=15)
    assert r.status_code == 403, f"expected 403, got {r.status_code} body={r.text[:200]}"


def test_customer_forbidden_admin_customers(customer_session):
    r = customer_session.get(f"{API}/admin/customers", timeout=15)
    assert r.status_code == 403, f"expected 403, got {r.status_code}"


def test_customer_forbidden_orders_admin_all(customer_session):
    r = customer_session.get(f"{API}/orders/admin/all", timeout=15)
    assert r.status_code in (403, 404), f"expected 403, got {r.status_code}"


# ---- Admin succeeds ----
def test_admin_can_get_stats(admin_session):
    r = admin_session.get(f"{API}/admin/stats", timeout=15)
    assert r.status_code == 200, f"expected 200, got {r.status_code} body={r.text[:200]}"
    data = r.json()
    assert isinstance(data, dict) and len(data) > 0


def test_admin_me_role(admin_session):
    r = admin_session.get(f"{API}/auth/me", timeout=15)
    assert r.status_code == 200
    assert r.json().get("role") == "admin"


def test_customer_me_role(customer_session):
    r = customer_session.get(f"{API}/auth/me", timeout=15)
    assert r.status_code == 200
    assert r.json().get("role") == "customer"
