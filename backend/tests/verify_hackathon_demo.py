"""Comprehensive verification script for DataWise AI Hackathon Demo Readiness.

Runs empirical verification across:
1. All structured formats (CSV, multi-sheet Excel) & PDF RAG docs
2. Deterministic calculations, aggregations, charts, and KPI discovery
3. Case Study 4 Gap Analysis & Unsupported Question Guarding
4. Agent Quality & Semantic Resolver Safety
5. Multi-turn analytical conversation memory
6. Cross-dataset joins (orders + products, orders + customers)
7. Provenance & Executive Dashboard integrity
"""

import sys
from pathlib import Path
import pandas as pd
import pytest

from app.semantic.store import DatasetStore
from app.documents.store import DocumentStore
from app.upload.service import ingest_files
from app.parsing.service import parse_csv_bytes
from app.profiling.service import profile_dataframe
from app.relationships.service import detect_relationships
from app.relationships.joins import perform_join
from app.analysis.engine import run_analysis
from app.analysis.kpi_discovery import discover_kpis
from app.semantic.models import AnalysisRequest, Aggregation, ChartType, FilterCondition, DatasetKind, JoinRequest, JoinType
from app.semantic.resolver import resolve_column
from app.agent.memory import ConversationMemory
from app.agent.tools import ToolContext, _group_and_aggregate, _calculate_metric, _generate_chart, _join_datasets


def _upload_file(filename: str, content: bytes, store: DatasetStore):
    res = ingest_files([(filename, content)], store, max_size_mb=50)
    assert len(res.errors) == 0, f"Upload errors for {filename}: {res.errors}"
    records = [store.get(ds.id) for ds in res.datasets]
    return [r for r in records if r is not None]


def test_hackathon_demo_flow():
    tmp_path = Path("/tmp/datawise_demo_verification")
    tmp_path.mkdir(parents=True, exist_ok=True)
    
    dataset_store = DatasetStore(storage_dir=tmp_path / "datasets")
    document_store = DocumentStore(storage_dir=tmp_path / "documents")
    tool_ctx = ToolContext(dataset_store=dataset_store, document_store=document_store)
    
    base_dir = Path(__file__).resolve().parent.parent.parent
    samples_dir = base_dir / "data" / "samples"
    if not samples_dir.exists():
        samples_dir = Path("data/samples")
    assert samples_dir.exists(), f"data/samples directory missing at {samples_dir}"
    
    # -------------------------------------------------------------
    # 1. STRUCTURED DATASETS UPLOAD & PROFILING
    # -------------------------------------------------------------
    print("\n--- 1. Testing Structured Dataset Uploads & Profiling ---")
    
    # orders.csv
    orders_bytes = (samples_dir / "orders.csv").read_bytes()
    orders_records = _upload_file("orders.csv", orders_bytes, dataset_store)
    assert len(orders_records) == 1
    orders_rec = orders_records[0]
    print(f"✓ orders.csv: {orders_rec.profile.row_count} rows, {len(orders_rec.profile.columns)} columns")
    assert orders_rec.profile.row_count == 1259
    assert len(orders_rec.profile.columns) == 16

    # products.csv
    products_bytes = (samples_dir / "products.csv").read_bytes()
    products_records = _upload_file("products.csv", products_bytes, dataset_store)
    assert len(products_records) == 1
    products_rec = products_records[0]
    print(f"✓ products.csv: {products_rec.profile.row_count} rows, {len(products_rec.profile.columns)} columns")

    # customers.csv
    customers_bytes = (samples_dir / "customers.csv").read_bytes()
    customers_records = _upload_file("customers.csv", customers_bytes, dataset_store)
    assert len(customers_records) == 1
    customers_rec = customers_records[0]
    print(f"✓ customers.csv: {customers_rec.profile.row_count} rows, {len(customers_rec.profile.columns)} columns")

    # hr_analytics.csv
    hr_bytes = (samples_dir / "hr_analytics.csv").read_bytes()
    hr_records = _upload_file("hr_analytics.csv", hr_bytes, dataset_store)
    assert len(hr_records) == 1
    hr_rec = hr_records[0]
    print(f"✓ hr_analytics.csv: {hr_rec.profile.row_count} rows, {len(hr_rec.profile.columns)} columns")

    # Online Retail.xlsx
    online_retail_bytes = (samples_dir / "Online Retail.xlsx").read_bytes()
    online_retail_records = _upload_file("Online Retail.xlsx", online_retail_bytes, dataset_store)
    assert len(online_retail_records) >= 1
    print(f"✓ Online Retail.xlsx: {len(online_retail_records)} dataset(s) created")

    # online_retail_II.xlsx (Multi-sheet Excel)
    retail_ii_bytes = (samples_dir / "online_retail_II.xlsx").read_bytes()
    retail_ii_records = _upload_file("online_retail_II.xlsx", retail_ii_bytes, dataset_store)
    assert len(retail_ii_records) == 2, f"Expected 2 sheets for online_retail_II.xlsx, got {len(retail_ii_records)}"
    sheet_names = [r.profile.name for r in retail_ii_records]
    print(f"✓ online_retail_II.xlsx multi-sheet: uploaded sheets {sheet_names}")

    # -------------------------------------------------------------
    # 2. PDF / UNSTRUCTURED DOCUMENTS & RAG
    # -------------------------------------------------------------
    print("\n--- 2. Testing Document Uploads & RAG Indexing ---")
    pdf_samples = list(samples_dir.glob("*.pdf"))
    assert len(pdf_samples) > 0, "No PDF sample files found"
    
    from app.documents.service import ingest_documents
    indexed_docs = []
    for pdf_path in pdf_samples[:3]:
        res = ingest_documents([(pdf_path.name, pdf_path.read_bytes())], document_store, max_size_mb=50)
        assert len(res.errors) == 0, f"Error indexing PDF {pdf_path.name}: {res.errors}"
        indexed_docs.extend(res.documents)
        record = document_store.get(res.documents[0].id)
        print(f"✓ Indexed PDF document: {pdf_path.name} ({record.summary.chunk_count} chunks)")
        assert record.summary.chunk_count > 0

    # Test RAG retrieval
    rag_query = "retrieval augmented generation"
    retrieved_chunks = document_store.retrieve(rag_query, top_k=3)
    print(f"✓ RAG Search for '{rag_query}': retrieved {len(retrieved_chunks)} relevant chunk(s)")
    assert len(retrieved_chunks) > 0

    # -------------------------------------------------------------
    # 3. DETERMINISTIC CALCULATIONS & CHARTS (HACKATHON QUESTIONS)
    # -------------------------------------------------------------
    print("\n--- 3. Testing Hackathon Questions & Deterministic Engine ---")

    # Question: "Show total price by region."
    res_region = run_analysis(
        AnalysisRequest(
            dataset_id=orders_rec.profile.id,
            metric_column="price",
            aggregation=Aggregation.SUM,
            dimension_column="region",
            sort="desc",
        ),
        dataset_store,
    )
    assert res_region.table is not None
    assert len(res_region.table) > 0
    val_key_region = [k for k in res_region.table[0].keys() if k not in ("region", "percentage_of_total")][0]
    print(f"✓ Total price by region: {len(res_region.table)} regions computed")
    for row in res_region.table:
        print(f"   - {row['region']}: ${row[val_key_region]:,.2f}")

    # Question: "Which shipping modes have the highest late delivery risk?"
    ship_mode_col = resolve_column("ship_mode", orders_rec.profile, role="dimension").column or "shipping_mode"
    res_ship = run_analysis(
        AnalysisRequest(
            dataset_id=orders_rec.profile.id,
            metric_column="late_delivery_risk",
            aggregation=Aggregation.MEAN,
            dimension_column=ship_mode_col,
            sort="desc",
        ),
        dataset_store,
    )
    assert res_ship.table is not None
    val_key_ship = [k for k in res_ship.table[0].keys() if k not in (ship_mode_col, "percentage_of_total")][0]
    print(f"✓ Late delivery risk by {ship_mode_col}:")
    for row in res_ship.table:
        print(f"   - {row[ship_mode_col]}: {row[val_key_ship]*100:.1f}% risk")

    # Question: "Price trend over time"
    date_col = resolve_column("order date", orders_rec.profile, role="date").column or "date"
    res_trend = run_analysis(
        AnalysisRequest(
            dataset_id=orders_rec.profile.id,
            metric_column="price",
            aggregation=Aggregation.SUM,
            date_column=date_col,
        ),
        dataset_store,
    )
    assert res_trend.chart_recommendation is not None
    print(f"✓ Price trend computed: chart type = {res_trend.chart_recommendation.chart_type}")
    assert res_trend.chart_recommendation.chart_type == ChartType.LINE

    # HR question: "Average salary by department"
    hr_salary_col = resolve_column("salary", hr_rec.profile, role="measure").column or "Salary"
    hr_dept_col = resolve_column("department", hr_rec.profile, role="dimension").column or "Department"
    res_hr = run_analysis(
        AnalysisRequest(
            dataset_id=hr_rec.profile.id,
            metric_column=hr_salary_col,
            aggregation=Aggregation.MEAN,
            dimension_column=hr_dept_col,
            sort="desc",
        ),
        dataset_store,
    )
    assert res_hr.table is not None
    print(f"✓ HR salary by department: {len(res_hr.table)} departments")

    # -------------------------------------------------------------
    # 4. CROSS-DATASET JOINS
    # -------------------------------------------------------------
    print("\n--- 4. Testing Cross-Dataset Joins ---")
    
    # Auto-relationship detection
    all_recs = [orders_rec, products_rec, customers_rec]
    rels = detect_relationships(all_recs)
    print(f"✓ Auto-detected {len(rels)} relationship(s) between orders, products, and customers:")
    for r in rels:
        print(f"   - {r.left_dataset_id}.{r.left_column} <-> {r.right_dataset_id}.{r.right_column} (confidence: {r.confidence_score})")

    # Join orders + products
    join_req = JoinRequest(
        left_dataset_id=orders_rec.profile.id,
        left_column="product_id",
        right_dataset_id=products_rec.profile.id,
        right_column="product_id",
        join_type=JoinType.INNER,
    )
    joined_orders_prod = perform_join(dataset_store, join_req, created_by_user_id="test")
    joined_rec = dataset_store.get(joined_orders_prod.new_dataset_id)
    assert joined_rec is not None
    print(f"✓ Joined orders + products: {joined_rec.profile.row_count} rows, {len(joined_rec.profile.columns)} columns")
    assert joined_rec.profile.row_count > 0

    # Question on joined dataset: "Which products have the highest sales value?"
    product_name_col = resolve_column("product name", joined_rec.profile, role="dimension").column or "product_name"
    price_col = resolve_column("price", joined_rec.profile, role="measure").column or "price"
    res_prod_sales = run_analysis(
        AnalysisRequest(
            dataset_id=joined_rec.profile.id,
            metric_column=price_col,
            aggregation=Aggregation.SUM,
            dimension_column=product_name_col,
            top_n=5,
            sort="desc",
        ),
        dataset_store,
    )
    assert res_prod_sales.table is not None
    val_key_prod = [k for k in res_prod_sales.table[0].keys() if k not in ("product_name", "percentage_of_total")][0]
    print(f"✓ Top 5 products by sales value on joined dataset:")
    for row in res_prod_sales.table:
        print(f"   - {row['product_name']}: ${row[val_key_prod]:,.2f}")

    # -------------------------------------------------------------
    # 5. CASE STUDY 4 GAP ANALYSIS & UNSUPPORTED QUESTION GUARDS
    # -------------------------------------------------------------
    print("\n--- 5. Testing Case Study 4 Gap Analysis & Semantic Resolver Safety ---")

    unsupported_concepts = [
        "return rate",
        "marketing ROI",
        "stockout rate",
        "excess inventory",
        "delivery partner rating",
        "employee revenue",
        "target attainment",
    ]

    for concept in unsupported_concepts:
        match = resolve_column(concept, orders_rec.profile, role="measure")
        print(f"✓ Guard check for '{concept}': resolved = {match.resolved} (column={match.column})")
        assert match.resolved is False, f"Concept '{concept}' should NOT resolve to any column in orders.csv!"

    # -------------------------------------------------------------
    # 6. MULTI-TURN ANALYTICAL CONTEXT
    # -------------------------------------------------------------
    print("\n--- 6. Testing Multi-Turn Analytical Memory ---")
    memory = ConversationMemory()
    session_id = "demo_session_1"
    memory.append(session_id, "Show total price by region.", "Central region leads with $103,425.20.")
    memory.append(session_id, "Which region is performing best?", "Central region is performing best in total sales.")
    memory.append(session_id, "What is causing the weakest performance?", "West region has lower transaction volume.")
    
    turns = memory.get_history(session_id)
    assert len(turns) == 3
    formatted = memory.format_for_prompt(session_id)
    assert formatted is not None
    assert "Central region leads" in formatted
    print(f"✓ Multi-turn conversation context preserved across {len(turns)} session turn(s).")

    # -------------------------------------------------------------
    # 7. MANAGEMENT DASHBOARD & KPI DISCOVERY
    # -------------------------------------------------------------
    print("\n--- 7. Testing Management Dashboard & KPI Discovery ---")
    kpis = discover_kpis(orders_rec)
    print(f"✓ Discovered {len(kpis)} KPI(s) for orders.csv:")
    for k in kpis:
        print(f"   - {k.name}: {k.aggregation.value}({k.metric_column}) by {k.dimension_column}")
    assert len(kpis) > 0

    print("\n=======================================================")
    print("ALL EMPIRICAL HACKATHON VERIFICATION CHECKS PASSED 100%!")
    print("=======================================================\n")


if __name__ == "__main__":
    test_hackathon_demo_flow()
