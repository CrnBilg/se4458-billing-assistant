URL = "/api/v1/usage"


def body(**over):
    base = {"subscriberNo": "5551001", "month": 10, "year": 2026, "usageType": "Phone"}
    return {**base, **over}


def test_phone_event_adds_10_minutes(client, admin_h):
    r = client.post(URL, json=body(), headers=admin_h)
    assert r.status_code == 201
    data = r.json()
    assert data["status"] == "SUCCESS"
    assert data["unitsAdded"] == 10 and data["unit"] == "minutes"
    assert data["periodTotalUnits"] == 10


def test_internet_event_adds_1_mb_and_totals_accumulate(client, admin_h):
    client.post(URL, json=body(usageType="Internet"), headers=admin_h)
    r = client.post(URL, json=body(usageType="Internet", count=999), headers=admin_h)
    assert r.json()["unitsAdded"] == 999
    assert r.json()["periodTotalUnits"] == 1000
    assert r.json()["unit"] == "MB"


def test_usage_type_is_case_insensitive(client, admin_h):
    r = client.post(URL, json=body(usageType="phone"), headers=admin_h)
    assert r.status_code == 201


def test_periods_are_tracked_separately(client, admin_h):
    client.post(URL, json=body(), headers=admin_h)
    r = client.post(URL, json=body(month=11), headers=admin_h)
    assert r.json()["periodTotalUnits"] == 10


def test_subscriber_token_cannot_add_usage(client, ayse_h):
    r = client.post(URL, json=body(), headers=ayse_h)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"


def test_unknown_subscriber_is_404(client, admin_h):
    r = client.post(URL, json=body(subscriberNo="9999999"), headers=admin_h)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "SUBSCRIBER_NOT_FOUND"


def test_invalid_month_is_422(client, admin_h):
    r = client.post(URL, json=body(month=13), headers=admin_h)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_invalid_usage_type_is_422(client, admin_h):
    assert client.post(URL, json=body(usageType="SMS"), headers=admin_h).status_code == 422


def test_non_positive_count_is_422(client, admin_h):
    assert client.post(URL, json=body(count=0), headers=admin_h).status_code == 422
