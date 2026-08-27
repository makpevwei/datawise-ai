# DataWise AI

> **An agentic business intelligence platform**

DataWise AI lets managers ask natural-language business questions against their own data — CSV, Excel, and PDF — and receive evidence-backed analysis, charts, and actionable recommendations without writing SQL, configuring dashboards, or understanding database structure.

---

## Business Problem

Traditional BI tools require analysts who understand data structure, SQL, and chart selection. Business managers — the people who most need the insights — are locked out. They submit report requests and wait days for answers that may already be stale.

Organizations with fragmented, multi-source data (spreadsheets, exports, PDFs, scattered across teams) need a way for a non-technical manager to ask a plain-English business question and get a trustworthy, evidence-backed answer immediately — not a stale report, and not a hallucinated guess.

---

## Solution

DataWise AI acts as an autonomous analytical agent. The manager uploads their data files, asks a question in plain English, and the agent:

1. **Resolves intent** — maps natural-language terms to actual columns in the dataset
2. **Selects the right analysis** — aggregation, trend, breakdown, join, or document retrieval
3. **Runs deterministic calculations** — no LLM guessing; all numbers come from pandas/Python
4. **Detects cross-dataset relationships** — automatically discovers that `orders.customer_id → customers.customer_id` without the user specifying this
5. **Selects the right chart** — bar, line, pie, map — driven by the shape of the question and data
6. **Narrates the result** — the LLM explains findings in business language over already-calculated evidence
7. **Issues a recommendation** — actionable next step based on the evidence

---

## Core Capabilities (Empirically Verified)

| Capability | Status |
|---|---|
| Structured CSV upload & profiling | ✅ Verified |
| Excel (.xlsx) single-sheet upload | ✅ Verified |
| Excel multi-sheet workbook ingestion | ✅ Verified |
| PDF upload & RAG indexing | ✅ Verified |
| Natural-language deterministic analysis | ✅ Verified |
| Automatic semantic column resolution | ✅ Verified |
| Chart type selection (bar/line/pie/map) | ✅ Verified |
| Cross-dataset relationship detection | ✅ Verified |
| Cross-dataset join (orders → products) | ✅ Verified |
| Multi-turn analytical memory | ✅ Verified |
| KPI discovery | ✅ Verified |
| Semantic safety (unsupported metric rejection) | ✅ Verified |
| Executive PDF report generation | ✅ Implemented |
| JWT authentication & per-user data isolation | ✅ Implemented |

---

## Supported Data Formats

| Format | Use |
|---|---|
| `.csv` | Structured data — upload, profile, analyse, join |
| `.xlsx` / `.xls` | Structured data — each sheet becomes its own dataset |
| `.pdf` | Documents — extracted, chunked, RAG-indexed |
| `.docx` | Documents — extracted, chunked, RAG-indexed |
| `.pptx` | Documents — extracted, chunked, RAG-indexed |
| `.txt` / `.md` / `.html` | Documents — extracted, chunked, RAG-indexed |

---

## AI Agent Workflow

```
User question (natural language)
         │
         ▼
  Intent routing (LLM, bounded)
         │
    ┌────┴────────────────────────────────────┐
    │                                         │
  Data question                         Document question
    │                                         │
    ▼                                         ▼
Semantic column resolver           Embedding-based RAG retrieval
    │                               (TF-IDF fallback always available)
    ▼
Analysis Engine (deterministic Python/pandas)
    │
    ▼
Visualization Engine (chart type selection)
    │
    ▼
Evidence + findings structure
    │
    ▼
LLM narration over evidence (never raw calculation)
    │
    ▼
Finding + business impact + recommendation → UI
```

**Key constraint:** The LLM never performs calculations. It only narrates over structured results already produced by the deterministic engine. This eliminates hallucinated numbers.

---

## Cross-Dataset Relationship Detection

DataWise automatically discovers join keys between datasets using:
- **Identifier semantics** — columns named `*_id`, `*_code`, etc.
- **Value overlap** — what fraction of values in column A appear in column B
- **Uniqueness analysis** — distinguishing primary keys from foreign keys

No manual schema configuration is required. When `orders.csv` and `products.csv` are both uploaded, DataWise detects `product_id` as the join key and can answer "Which products have the highest sales value?" by joining them automatically.

---

## Current Dataset Limitations

The following metrics are **not supported** with the current demo datasets and DataWise will say so honestly rather than inventing a number:

- Return rate (no returns data)
- Marketing ROI (no marketing spend data)
- Stockout rate (no inventory data)
- Excess inventory (no stock level data)
- Delivery partner ratings (no ratings data)
- Employee revenue/profitability (no per-employee revenue data)
- Target attainment (no sales target data)

This is a deliberate design choice: DataWise is calibrated to reject questions it cannot answer with the available data rather than produce plausible-looking fabrications.

---

## Technology Stack

| Component | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0 + Alembic |
| Data processing | pandas, openpyxl, pypdf, python-docx |
| Embeddings / RAG | sentence-transformers (local, free), TF-IDF fallback |
| LLM | OpenAI / Anthropic / Gemini / Groq / OpenRouter (pluggable, auto-fallback) |
| PDF reports | ReportLab |
| Dependency management | [uv](https://docs.astral.sh/uv/) |
| Frontend | Next.js 16 (App Router), TypeScript, Tailwind CSS |
| Charts | Hand-built SVG components (no external charting library) |
| Database | PostgreSQL (auth, ownership, versioning) |
| File storage | Parquet + JSON on disk (dataset content and document chunks) |
| Auth | JWT (PyJWT + bcrypt) |

---

## Project Layout

```
DataWise-AI/
├── backend/
│   ├── app/
│   │   ├── upload/          # CSV/XLSX validation
│   │   ├── parsing/         # File → pandas DataFrame
│   │   ├── profiling/       # Column types, data quality
│   │   ├── relationships/   # PK/FK detection, join engine
│   │   ├── semantic/        # Dataset registry (parquet + JSON)
│   │   ├── analysis/        # Deterministic aggregation engine
│   │   ├── visualization/   # Chart type selection
│   │   ├── geography/       # Country centroid lookup (offline)
│   │   ├── documents/       # PDF/DOCX extraction, chunking
│   │   ├── embeddings/      # Local HuggingFace embeddings
│   │   ├── ai/              # LLM provider abstraction
│   │   ├── agent/           # LangGraph planner, tools, memory
│   │   ├── auth/            # JWT authentication
│   │   ├── db/              # SQLAlchemy models, migrations
│   │   ├── api/             # FastAPI routers
│   │   ├── config.py
│   │   └── main.py
│   ├── alembic/             # Database migrations
│   ├── tests/               # pytest suite including end-to-end demo verification
│   └── pyproject.toml
├── frontend/                # Next.js app (App Router)
│   └── src/
│       ├── app/             # Routes: dashboard, ask, my-data, analyses, reports, settings
│       ├── components/      # UploadPanel, AskDataWise, RelationshipsPanel, charts, …
│       └── lib/             # api.ts, auth-context.tsx, types.ts
├── data/
│   ├── samples/             # Demo datasets (git-tracked)
│   ├── uploads/             # User uploads (git-ignored)
│   ├── documents/           # Extracted document chunks (git-ignored)
│   └── reports/             # Generated PDF reports (git-ignored)
├── docs/
│   ├── architecture.md
│   ├── embeddings.md
│   └── evaluation.md
├── .env.example
├── .gitignore
└── README.md
```

---

## Local Setup

### Prerequisites
- Python 3.12+
- Node.js 18+
- PostgreSQL (local or [Neon](https://neon.tech) free tier)
- [`uv`](https://docs.astral.sh/uv/) Python package manager

### 1. Clone and configure environment

```bash
git clone https://github.com/YOUR_ORG/DataWise-AI.git
cd DataWise-AI
cp .env.example .env
# Edit .env — fill in DATABASE_URL, JWT_SECRET_KEY, and at least one LLM key
```

### 2. Backend

```bash
cd backend
uv sync                          # creates .venv and installs all dependencies
uv run alembic upgrade head      # applies database migrations
uv run uvicorn app.main:app --reload --port 8001
```

Health check: `curl http://localhost:8001/health`
Interactive API docs: http://localhost:8001/docs

### 3. Frontend

```bash
cd frontend
npm install
# Create frontend/.env.local:
echo "NEXT_PUBLIC_API_BASE_URL=http://localhost:8001/api/v1" > .env.local
npm run dev
```

Open http://localhost:3000 — sign up, then start uploading data.

### 4. Run tests

```bash
# Backend
cd backend && uv run pytest

# Full end-to-end demo verification (takes ~20 min due to embedding model loading)
cd backend && uv run pytest tests/verify_demo.py -v

# Frontend
cd frontend && npm test
cd frontend && npx tsc --noEmit
```

---

## Demo Instructions (3-Minute Walkthrough)

### Step 1 — Upload datasets
1. Sign up / log in
2. Go to **My Data → Upload**
3. Upload `data/samples/orders.csv`, `data/samples/products.csv`, `data/samples/customers.csv`

### Step 2 — See automatic profiling and relationship detection
- DataWise profiles each dataset (rows, columns, types, quality)
- Go to **Relationships** — DataWise automatically detects:
  - `orders.product_id → products.product_id`
  - `orders.customer_id → customers.customer_id`

### Step 3 — Ask business questions (go to **Ask DataWise**)

Ask these in order, without specifying columns or chart types:

1. `"Show total price by region."`
2. `"Which region is performing best?"`
3. `"Which shipping modes have the highest late delivery risk?"`
4. `"Which products have the highest sales value?"` ← uses the detected join automatically
5. `"Tell me what is happening with this business and what management should do."`

Each response includes evidence, a chart, findings, and a recommendation.

### Step 4 — Upload a PDF document (optional)
- Upload `data/samples/rag-paper.pdf`
- Ask: `"What is retrieval-augmented generation?"`

---

## Environment Variables

Copy `.env.example` to `.env` and fill in real values.

### Required
| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `JWT_SECRET_KEY` | Random secret for JWT signing (generate with `openssl rand -hex 32`) |

### LLM (at least one required for "Ask DataWise" feature)
| Variable | Description |
|---|---|
| `LLM_PROVIDER` | `openai`, `anthropic`, `gemini`, `groq`, or `openrouter` |
| `LLM_API_KEY` | API key for the chosen provider |
| `LLM_MODEL` | Model name (optional — sensible defaults apply per provider) |

### Frontend
| Variable | Description |
|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | Backend API URL (e.g. `https://your-backend.onrender.com/api/v1`) |

### Optional
| Variable | Description |
|---|---|
| `SMTP_HOST` / `SMTP_PORT` / etc. | Email delivery for PDF reports |
| `EMBEDDING_PROVIDER` | `huggingface` (default, free, local) or `openai` |
| `TAVILY_API_KEY` / `EXA_API_KEY` | Web research (optional, agent falls back gracefully) |

---

## Deployment Architecture

```
┌─────────────────────────────┐
│  Vercel (Frontend)          │
│  Next.js — static + edge    │
│  NEXT_PUBLIC_API_BASE_URL   │
└──────────────┬──────────────┘
               │ HTTPS
┌──────────────▼──────────────┐
│  Render / Railway (Backend) │
│  FastAPI + uvicorn          │
│  Persistent disk: /data     │
│  DATABASE_URL → Neon PG     │
└─────────────────────────────┘
```

**Notes:**
- The backend requires a **persistent disk** for uploaded files and document chunks. Render's free tier provides a persistent disk option.
- Vercel's serverless functions cannot host FastAPI directly as a persistent server; backend must be deployed separately.
- PostgreSQL: [Neon](https://neon.tech) free tier works well for the auth/ownership layer.

### Render Backend Deployment
1. Connect your GitHub repo to [Render](https://render.com)
2. Create a **Web Service** with:
   - **Runtime**: Python
   - **Build command**: `cd backend && pip install uv && uv sync`
   - **Start command**: `cd backend && uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **Add a Disk** (mount path `/data`, size ≥ 1GB)
3. Set environment variables: `DATABASE_URL`, `JWT_SECRET_KEY`, `LLM_PROVIDER`, `LLM_API_KEY`, `UPLOAD_DIR=/data/uploads`, `DOCUMENT_DIR=/data/documents`, `REPORTS_DIR=/data/reports`, `CORS_ORIGINS=["https://your-vercel-app.vercel.app"]`

### Vercel Frontend Deployment
1. Connect your GitHub repo to [Vercel](https://vercel.com)
2. Set **Root Directory**: `frontend`
3. Add environment variable: `NEXT_PUBLIC_API_BASE_URL=https://your-render-backend.onrender.com/api/v1`
4. Deploy

---

## Security

- No API keys, database passwords, or uploaded data are committed to Git
- `.env`, `data/uploads/`, `data/documents/`, `data/reports/` are gitignored
- Passwords are bcrypt-hashed; the hash is never returned by any API
- Every dataset, document, and report endpoint enforces per-user ownership
- The LLM never receives raw dataset rows — only schemas, summaries, and already-computed results
- JWT tokens are signed server-side only; secrets never appear in the frontend bundle

---

## Status

DataWise AI is a working MVP: upload data, ask questions in plain English, get evidence-backed answers with charts and recommendations. All core capabilities above are verified end-to-end by `tests/verify_demo.py`.

We're building toward our first cohort of pilot customers — reach out if you'd like a walkthrough.
