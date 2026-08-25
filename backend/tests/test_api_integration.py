import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_dataset_store, get_scoped_dataset_store
from app.auth.dependencies import get_current_user
from app.main import app
from app.semantic.store import DatasetStore
from tests.factories import customers_df, orders_df, to_csv_bytes, to_xlsx_bytes


@pytest.fixture
def client(tmp_path, auth_override):
    store = DatasetStore(storage_dir=tmp_path)
    app.dependency_overrides[get_dataset_store] = lambda: store
    app.dependency_overrides[get_scoped_dataset_store] = lambda: store
    app.dependency_overrides[get_current_user] = auth_override
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_upload_csv_and_multi_sheet_xlsx_in_one_request(client):
    files = [
        ("files", ("customers.csv", to_csv_bytes(customers_df()), "text/csv")),
        (
            "files",
            (
                "book.xlsx",
                to_xlsx_bytes({"Orders": orders_df(), "Empty": pd.DataFrame()}),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        ),
    ]
    response = client.post("/api/v1/datasets/upload", files=files)
    assert response.status_code == 200
    body = response.json()
    names = {d["name"] for d in body["datasets"]}
    assert "customers.csv" in names
    assert "book.xlsx — Orders" in names
    assert any("Empty" in w["message"] for w in body["warnings"])


def test_malformed_file_does_not_break_the_rest_of_the_upload(client):
    files = [
        ("files", ("good.csv", to_csv_bytes(customers_df()), "text/csv")),
        ("files", ("bad.xlsx", b"not a real workbook", "application/octet-stream")),
    ]
    response = client.post("/api/v1/datasets/upload", files=files)
    assert response.status_code == 200
    body = response.json()
    assert len(body["datasets"]) == 1
    assert len(body["errors"]) == 1
    assert body["errors"][0]["file"] == "bad.xlsx"


def test_list_and_get_dataset(client):
    files = [("files", ("customers.csv", to_csv_bytes(customers_df()), "text/csv"))]
    upload = client.post("/api/v1/datasets/upload", files=files).json()
    dataset_id = upload["datasets"][0]["id"]

    listing = client.get("/api/v1/datasets")
    assert listing.status_code == 200
    assert any(d["id"] == dataset_id for d in listing.json())

    profile = client.get(f"/api/v1/datasets/{dataset_id}")
    assert profile.status_code == 200
    assert profile.json()["row_count"] == 8

    sample = client.get(f"/api/v1/datasets/{dataset_id}/sample?n=2")
    assert sample.status_code == 200
    assert len(sample.json()) == 2


def test_get_unknown_dataset_returns_404(client):
    response = client.get("/api/v1/datasets/does-not-exist")
    assert response.status_code == 404


def test_full_relational_workflow_upload_relate_join_analyze(client):
    files = [
        ("files", ("customers.csv", to_csv_bytes(customers_df()), "text/csv")),
        ("files", ("orders.csv", to_csv_bytes(orders_df()), "text/csv")),
    ]
    upload = client.post("/api/v1/datasets/upload", files=files).json()
    by_name = {d["name"]: d["id"] for d in upload["datasets"]}

    relationships = client.get("/api/v1/relationships").json()
    assert any(r["confidence"] == "HIGH" for r in relationships)

    join_response = client.post(
        "/api/v1/relationships/join",
        json={
            "left_dataset_id": by_name["orders.csv"],
            "left_column": "customer_id",
            "right_dataset_id": by_name["customers.csv"],
            "right_column": "customer_id",
            "join_type": "inner",
        },
    )
    assert join_response.status_code == 200
    joined_id = join_response.json()["new_dataset_id"]

    analysis = client.post(
        "/api/v1/analysis/run",
        json={
            "dataset_id": joined_id,
            "metric_column": "amount",
            "aggregation": "sum",
            "dimension_column": "region",
        },
    )
    assert analysis.status_code == 200
    assert analysis.json()["result_type"] == "table"

    kpis = client.get(f"/api/v1/analysis/kpis/{joined_id}")
    assert kpis.status_code == 200
    assert len(kpis.json()) > 0

    insights = client.get(f"/api/v1/analysis/insights/{joined_id}")
    assert insights.status_code == 200
    assert len(insights.json()) > 0


def test_deleting_joined_dataset_preserves_source_datasets(client):
    files = [
        ("files", ("customers.csv", to_csv_bytes(customers_df()), "text/csv")),
        ("files", ("orders.csv", to_csv_bytes(orders_df()), "text/csv")),
    ]
    upload = client.post("/api/v1/datasets/upload", files=files).json()
    by_name = {d["name"]: d["id"] for d in upload["datasets"]}

    join_response = client.post(
        "/api/v1/relationships/join",
        json={
            "left_dataset_id": by_name["orders.csv"],
            "left_column": "customer_id",
            "right_dataset_id": by_name["customers.csv"],
            "right_column": "customer_id",
            "join_type": "inner",
        },
    )
    joined_id = join_response.json()["new_dataset_id"]

    delete_response = client.delete(f"/api/v1/datasets/{joined_id}")
    assert delete_response.status_code == 204

    assert client.get(f"/api/v1/datasets/{joined_id}").status_code == 404
    assert client.get(f"/api/v1/datasets/{by_name['orders.csv']}").status_code == 200
    assert client.get(f"/api/v1/datasets/{by_name['customers.csv']}").status_code == 200


def test_repeating_the_same_join_reuses_the_existing_derived_dataset(client):
    files = [
        ("files", ("customers.csv", to_csv_bytes(customers_df()), "text/csv")),
        ("files", ("orders.csv", to_csv_bytes(orders_df()), "text/csv")),
    ]
    upload = client.post("/api/v1/datasets/upload", files=files).json()
    by_name = {d["name"]: d["id"] for d in upload["datasets"]}

    payload = {
        "left_dataset_id": by_name["orders.csv"],
        "left_column": "customer_id",
        "right_dataset_id": by_name["customers.csv"],
        "right_column": "customer_id",
        "join_type": "inner",
    }
    first = client.post("/api/v1/relationships/join", json=payload).json()
    second = client.post("/api/v1/relationships/join", json=payload).json()

    assert first["new_dataset_id"] == second["new_dataset_id"]
    assert first["reused_existing"] is False
    assert second["reused_existing"] is True

    all_datasets = client.get("/api/v1/datasets/library").json()
    joined_rows = [d for d in all_datasets if d["file_type"] == "joined"]
    assert len(joined_rows) == 1, "repeating an identical join must not create a duplicate derived dataset"


def test_join_preview_does_not_create_a_dataset(client):
    files = [
        ("files", ("customers.csv", to_csv_bytes(customers_df()), "text/csv")),
        ("files", ("orders.csv", to_csv_bytes(orders_df()), "text/csv")),
    ]
    upload = client.post("/api/v1/datasets/upload", files=files).json()
    by_name = {d["name"]: d["id"] for d in upload["datasets"]}
    before = {d["id"] for d in client.get("/api/v1/datasets").json()}

    preview = client.post(
        "/api/v1/relationships/join/preview",
        json={
            "left_dataset_id": by_name["orders.csv"],
            "left_column": "customer_id",
            "right_dataset_id": by_name["customers.csv"],
            "right_column": "customer_id",
            "join_type": "inner",
        },
    )
    assert preview.status_code == 200
    assert preview.json()["rows_after"] > 0

    after = {d["id"] for d in client.get("/api/v1/datasets").json()}
    assert before == after, "a preview must not persist a new dataset"
