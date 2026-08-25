"""Small synthetic dataset builders shared across tests.

Never used as demo/product data -- only for exercising the engine in
automated tests. Kept intentionally tiny and deterministic.
"""

import io

import pandas as pd


def customers_df() -> pd.DataFrame:
    # 8 rows -- large enough to clear the identifier-detection sample-size
    # guard (which ignores columns with 5 or fewer values to avoid false
    # positives on tiny samples).
    return pd.DataFrame(
        {
            "customer_id": [1, 2, 3, 4, 5, 6, 7, 8],
            "name": ["Alice", "Bob", "Carol", "Dave", "Eve", "Frank", "Grace", "Heidi"],
            "segment": [
                "Consumer",
                "Corporate",
                "Consumer",
                "Home Office",
                "Consumer",
                "Corporate",
                "Consumer",
                "Home Office",
            ],
        }
    )


def orders_df(n: int = 20) -> pd.DataFrame:
    regions = ["North", "South", "East", "West"]
    return pd.DataFrame(
        {
            "order_id": list(range(1, n + 1)),
            "date": [f"2024-{(i % 6) + 1:02d}-15" for i in range(1, n + 1)],
            "customer_id": [(i % 5) + 1 for i in range(1, n + 1)],
            "amount": [100.0 + i * 10 for i in range(1, n + 1)],
            "region": [regions[i % 4] for i in range(1, n + 1)],
        }
    )


def to_csv_bytes(df: pd.DataFrame, sep: str = ",") -> bytes:
    return df.to_csv(index=False, sep=sep).encode("utf-8")


def to_xlsx_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)
    return buf.getvalue()
