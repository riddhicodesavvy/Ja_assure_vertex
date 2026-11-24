# JA Assure — Research & Discovery Agent Backend

*A deterministic evidence-processing pipeline and structured research intelligence engine for market intelligence, competitor tracking, and trend analysis.*

> **Architecture & Implementation Clarification:** While the repository name `Ja_assure_vertex` reflects the original hackathon project track, the implemented and tested production backend relies on a deterministic Python evidence processor, **Tavily Search API** for web retrieval, **Groq LLM** (`llama-3.3-70b` / `groq/compound`) for evidence-grounded synthesis, and **Supabase PostgreSQL** for persistence and caching.

---

## 🎯 Problem Statement & Motivation

Automated research and competitive intelligence systems powered by raw LLMs frequently suffer from two critical flaws:
1. **Hallucination & Fabricated Citations**: General-purpose LLMs generate convincing market claims but often fabricate URLs, attribute statistics to non-existent whitepapers, or blend timeline events.
2. **Uncontrolled Search Costs & Rate Limits**: Unconstrained autonomous agents execute runaway search loops, leading to duplicate queries, irrelevant crawling, and high token overhead.

**JA Assure's Discover Agent** solves this through a **strict separation of responsibilities**:
- **Tavily** executes bounded, structured web searches and extractions.
- **Python (Deterministic Engine)** cleans, normalizes, deduplicates (via SHA-256 hashing), date-filters, and detects changes.
- **Groq LLM** acts solely as an evidence-bounded reasoning layer operating on pre-filtered JSON payloads with strict anti-hallucination verification.
- **Supabase** maintains runs, evidence provenance, findings, and TTL-governed cache.

---

## 🏗️ System Architecture

```
Research Request (Brand, Market, Research Type)
                      │
                      ▼
        [Deterministic Research Planner]
        • Selects query templates by ResearchType
        • Bounds max API calls and extraction depth
                      │
                      ▼
         [Tavily Research Adapter]
        • Executes search / extract / crawl operations
        • Isolates network retries and timeout boundaries
                      │
                      ▼
         [Deterministic Evidence Engine]
        • Normalization: Unicode NFC, date parsing
        • Deduplication: SHA-256 content & URL hashing
        • Relevance & Date Filtering
        • Change Detection: Identifies UNCHANGED runs to skip LLM calls
                      │
                      ▼
           [Groq Analysis Adapter]
        • Structured JSON payload strictly containing filtered evidence
        • Anti-Hallucination Guard: Validates every returned finding against
          known evidence IDs; drops fabricated URLs automatically
                      │
                      ▼
          [Supabase Persistence Layer]
        • Atomic persistence of runs, evidence records, and findings
        • Cache-first lookup with per-type TTL
                      │
                      ▼
                 [FastAPI REST API]
        • Endpoints consumed by frontend intelligence dashboards
```

---

## 🔬 Core Capabilities & Supported Research Types

| Research Type | Focus Area | Planner Operations |
| :--- | :--- | :--- |
| `competitor_monitoring` | Launches, pricing changes, partnerships, leadership shifts | Targeted domain searches, changelog extraction, change detection |
| `market_research` | Industry TAM/SAM trends, regulatory updates, macroeconomic shifts | Broad multi-angle search, relevance filtering |
| `trend_research` | Emerging technology adoption, consumer sentiment, viral patterns | High-velocity news and article indexing |
| `campaign_research` | Marketing initiatives, creative campaigns, brand positioning | Multi-channel social and press release aggregation |

---

## 🛡️ Anti-Hallucination & Evidence Provenance

1. **Strict Reference Validation**: The output schema validator requires every finding to reference explicit `supporting_evidence_ids`. Any finding referencing a fabricated or non-existent evidence ID is automatically dropped.
2. **Fabricated URL Filtering**: If the model introduces an external URL not present in the original source evidence corpus, the URL is scrubbed or the finding is flagged.
3. **Change Detection**: When monitored competitor pages exhibit zero delta since the last run, the system marks the run as `UNCHANGED` and completely bypasses the LLM layer, saving API compute.

---

## 🚀 Setup & Execution

### Prerequisites
- Python 3.11+
- Supabase PostgreSQL project with schema applied
- Tavily Search API key
- Groq API key

### 1. Installation
```bash
# Clone repository
git clone https://github.com/riddhicodesavvy/Ja_assure_vertex.git
cd Ja_assure_vertex

# Create virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1  # On Windows

# Install pinned dependencies
pip install -r requirements.txt
```

### 2. Environment Configuration
Configure `.env`:
```ini
TAVILY_API_KEY=your_tavily_key
GROQ_API_KEY=your_groq_key
GROQ_MODEL=groq/compound
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
```

### 3. Run Development Server
```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
API documentation is accessible at `http://127.0.0.1:8000/docs`.

---

## 🧪 Verification & Automated Testing

The backend includes a comprehensive 125-test unit and pipeline verification suite:

```bash
# Execute unit and pipeline test suite
python -m pytest tests/ -v
```

*Test Coverage Highlights:*
- `test_planner.py`: Verifies query generation, bounded call estimations, and complexity matching.
- `test_normalization.py`: Verifies Unicode NFC handling, URL canonicalization, and date extraction.
- `test_processing.py`: Verifies SHA-256 deduplication and relevance filtering.
- `test_groq_validation.py`: Verifies anti-hallucination guards, JSON schema enforcement, and fabricated URL dropping.
- `test_manager_pipeline.py`: Verifies end-to-end mocked execution from planning through cache storage.
- `test_api_endpoints.py`: Verifies FastAPI request validation, error codes, and absence of exposed credentials.

---

## 📑 Research Limitations

- **JavaScript-Rendered Sites**: The Tavily extraction layer parses HTML; dynamic client-side SPA applications without server-side rendering may yield partial text.
- **Rate Limits & Budgets**: Search queries are bounded to prevent runaway costs; exhaustive crawling of large competitor intranets is intentionally restricted.
