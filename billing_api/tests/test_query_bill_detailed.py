URL = "/api/v1/bills/5551001/2026/10/detailed"


def test_detailed_breakdown_matches_worked_example(client, ayse_h, calculated_bill):
    r = client.get(URL, headers=ayse_h)
    assert r.status_code == 200
    d = r.json()
    assert d["billTotal"] == 80.0 and d["remainingBalance"] == 80.0
    assert d["phone"] == {
        "minutes": 1350, "includedMinutes": 1000, "billableMinutes": 350,
        "extraBlocks": 1, "charge": 10.0,
    }
    assert d["internet"]["mb"] == 35_000 and d["internet"]["gb"] == 35.0
    assert d["internet"]["extraBlocks"] == 2
    assert d["internet"]["baseCharge"] == 50.0
    assert d["internet"]["additionalCharge"] == 20.0
    assert d["internet"]["charge"] == 70.0
    assert d["dueDate"] == "2026-11-15"


def test_usage_list_is_paged(client, ayse_h, add_usage, admin_h):
    for _ in range(5):
        add_usage("5551001", "Phone", 1)
    client.post("/api/v1/bills/calculate",
                json={"subscriberNo": "5551001", "month": 10, "year": 2026}, headers=admin_h)

    p1 = client.get(URL, params={"page": 1, "pageSize": 2}, headers=ayse_h).json()["usage"]
    assert (p1["page"], p1["pageSize"], p1["totalItems"], p1["totalPages"]) == (1, 2, 5, 3)
    assert len(p1["items"]) == 2

    p3 = client.get(URL, params={"page": 3, "pageSize": 2}, headers=ayse_h).json()["usage"]
    assert len(p3["items"]) == 1

    p4 = client.get(URL, params={"page": 4, "pageSize": 2}, headers=ayse_h).json()["usage"]
    assert p4["items"] == []


def test_subscriber_cannot_read_another_subscribers_bill(client, mehmet_h, calculated_bill):
    r = client.get(URL, headers=mehmet_h)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"


def test_admin_can_read_any_bill(client, admin_h, calculated_bill):
    assert client.get(URL, headers=admin_h).status_code == 200


def test_missing_token_is_401(client, calculated_bill):
    assert client.get(URL).status_code == 401


def test_bill_not_calculated_is_404(client, ayse_h):
    assert client.get(URL, headers=ayse_h).status_code == 404


def test_invalid_paging_params_are_422(client, ayse_h, calculated_bill):
    assert client.get(URL, params={"page": 0}, headers=ayse_h).status_code == 422
    assert client.get(URL, params={"pageSize": 101}, headers=ayse_h).status_code == 422
