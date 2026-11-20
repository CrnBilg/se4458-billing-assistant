URL = "/api/v1/bills/calculate"
PERIOD = {"month": 10, "year": 2026}


def test_worked_example_total_is_80(calculated_bill):
    assert calculated_bill["status"] == "SUCCESS"
    assert calculated_bill["total"] == 80.0
    assert calculated_bill["recalculated"] is False


def test_zero_usage_bills_the_internet_base_fee(client, admin_h):
    r = client.post(URL, json={"subscriberNo": "5551002", **PERIOD}, headers=admin_h)
    assert r.status_code == 200
    assert r.json()["total"] == 50.0


def test_recalculation_picks_up_new_usage(client, admin_h, add_usage, calculated_bill):
    add_usage("5551001", "Internet", 1)  # 35,001 MB: still 2 extra 10 GB blocks, total unchanged
    r = client.post(URL, json={"subscriberNo": "5551001", **PERIOD}, headers=admin_h)
    assert r.status_code == 200
    assert r.json()["recalculated"] is True
    assert r.json()["total"] == 80.0

    add_usage("5551001", "Internet", 5_000)  # 40,001 MB: 3 extra blocks -> $10 more
    r = client.post(URL, json={"subscriberNo": "5551001", **PERIOD}, headers=admin_h)
    assert r.json()["total"] == 90.0


def test_bill_with_payment_cannot_be_recalculated(client, admin_h, ayse_h, calculated_bill):
    client.post(
        "/api/v1/payments",
        json={"subscriberNo": "5551001", **PERIOD, "amount": 10, "transactionId": "T-1"},
        headers=ayse_h,
    )
    r = client.post(URL, json={"subscriberNo": "5551001", **PERIOD}, headers=admin_h)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "BILL_LOCKED"


def test_unknown_subscriber_is_404(client, admin_h):
    r = client.post(URL, json={"subscriberNo": "9999999", **PERIOD}, headers=admin_h)
    assert r.status_code == 404


def test_subscriber_token_is_forbidden(client, ayse_h):
    r = client.post(URL, json={"subscriberNo": "5551001", **PERIOD}, headers=ayse_h)
    assert r.status_code == 403


def test_missing_token_is_401(client):
    assert client.post(URL, json={"subscriberNo": "5551001", **PERIOD}).status_code == 401


def test_invalid_year_is_422(client, admin_h):
    r = client.post(URL, json={"subscriberNo": "5551001", "month": 10, "year": 1800}, headers=admin_h)
    assert r.status_code == 422
