URL = "/api/v1/payments"


def pay(client, headers, amount, tx, subscriber="5551001"):
    return client.post(
        URL,
        json={"subscriberNo": subscriber, "month": 10, "year": 2026, "amount": amount,
              "transactionId": tx},
        headers=headers,
    )


def test_partial_payment_reduces_balance_but_bill_not_paid(client, ayse_h, calculated_bill):
    r = pay(client, ayse_h, 30, "TX-1")
    assert r.status_code == 201
    d = r.json()
    assert d["status"] == "SUCCESS"
    assert d["paidAmount"] == 30.0 and d["totalPaid"] == 30.0
    assert d["remainingBalance"] == 50.0
    assert d["billStatus"] == "PARTIALLY_PAID"


def test_two_payments_settle_the_bill(client, ayse_h, calculated_bill):
    pay(client, ayse_h, 30, "TX-1")
    r = pay(client, ayse_h, 50, "TX-2")
    assert r.status_code == 201
    assert r.json()["remainingBalance"] == 0.0
    assert r.json()["billStatus"] == "PAID"


def test_duplicate_transaction_id_is_rejected_and_balance_unchanged(client, ayse_h, calculated_bill):
    assert pay(client, ayse_h, 10, "TX-1").status_code == 201
    r = pay(client, ayse_h, 10, "TX-1")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "DUPLICATE_TRANSACTION"
    assert client.get("/api/v1/bills/5551001/2026/10").json()["remainingBalance"] == 70.0


def test_amount_above_balance_is_rejected(client, ayse_h, calculated_bill):
    r = pay(client, ayse_h, 80.01, "TX-1")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "AMOUNT_EXCEEDS_BALANCE"
    assert client.get("/api/v1/bills/5551001/2026/10").json()["paidAmount"] == 0.0


def test_paying_an_already_paid_bill_is_409(client, ayse_h, calculated_bill):
    pay(client, ayse_h, 80, "TX-1")
    r = pay(client, ayse_h, 1, "TX-2")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "BILL_ALREADY_PAID"


def test_subscriber_cannot_pay_someone_elses_bill(client, mehmet_h, calculated_bill):
    r = pay(client, mehmet_h, 10, "TX-1", subscriber="5551001")
    assert r.status_code == 403
    assert client.get("/api/v1/bills/5551001/2026/10").json()["paidAmount"] == 0.0


def test_missing_token_is_401(client, calculated_bill):
    assert pay(client, {}, 10, "TX-1").status_code == 401


def test_bill_not_calculated_is_404(client, ayse_h):
    r = pay(client, ayse_h, 10, "TX-1")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "BILL_NOT_FOUND"


def test_non_positive_amount_is_422(client, ayse_h, calculated_bill):
    assert pay(client, ayse_h, 0, "TX-1").status_code == 422
    assert pay(client, ayse_h, -5, "TX-2").status_code == 422


def test_more_than_two_decimal_places_is_422(client, ayse_h, calculated_bill):
    assert pay(client, ayse_h, 10.123, "TX-1").status_code == 422


def test_missing_transaction_id_is_422(client, ayse_h, calculated_bill):
    r = client.post(
        URL,
        json={"subscriberNo": "5551001", "month": 10, "year": 2026, "amount": 10},
        headers=ayse_h,
    )
    assert r.status_code == 422
