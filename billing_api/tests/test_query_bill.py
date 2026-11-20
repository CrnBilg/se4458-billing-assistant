def test_query_bill_needs_no_token_and_returns_stored_bill(client, calculated_bill):
    r = client.get("/api/v1/bills/5551001/2026/10")
    assert r.status_code == 200
    assert r.json() == {
        "subscriberNo": "5551001",
        "month": 10,
        "year": 2026,
        "billTotal": 80.0,
        "paidAmount": 0.0,
        "remainingBalance": 80.0,
        "status": "UNPAID",
    }


def test_query_bill_reflects_partial_payment(client, ayse_h, calculated_bill):
    client.post(
        "/api/v1/payments",
        json={"subscriberNo": "5551001", "month": 10, "year": 2026, "amount": 30.5,
              "transactionId": "T-1"},
        headers=ayse_h,
    )
    data = client.get("/api/v1/bills/5551001/2026/10").json()
    assert data["paidAmount"] == 30.5
    assert data["remainingBalance"] == 49.5
    assert data["status"] == "PARTIALLY_PAID"


def test_bill_not_calculated_is_404(client):
    r = client.get("/api/v1/bills/5551001/2026/10")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "BILL_NOT_FOUND"


def test_unknown_subscriber_looks_the_same_as_missing_bill(client):
    """Public route must not reveal which subscriber numbers exist."""
    a = client.get("/api/v1/bills/9999999/2026/10")
    b = client.get("/api/v1/bills/5551001/2026/10")
    assert a.status_code == b.status_code == 404
    assert a.json()["error"]["code"] == b.json()["error"]["code"] == "BILL_NOT_FOUND"


def test_invalid_month_is_422(client):
    assert client.get("/api/v1/bills/5551001/2026/13").status_code == 422


def test_invalid_subscriber_format_is_422(client):
    assert client.get("/api/v1/bills/bad%20no!/2026/10").status_code == 422
