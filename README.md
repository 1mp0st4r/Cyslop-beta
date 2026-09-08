# AI-Powered Criminal Network Analysis System (`SIH26189`)

An explainable, tamper-proof, multi-source investigative co-pilot built for the **Smart India Hackathon (Problem Statement: SIH26189)**[cite: 1]. The system ingests fragmented law-enforcement data (FIRs, CDRs, financial records) and constructs a centralized, entity-resolution graph to surface hidden criminal networks, identify key operatives, and detect suspicious patterns—all while logging every query and action to an immutable blockchain audit trail[cite: 1].

---

## 🎯 Problem Overview & Positioning

Law enforcement agencies currently struggle with fragmented data silos across FIRS, CDRs, financial statements, and surveillance logs[cite: 1]. Manual link-charting and cross-referencing across thousands of records take weeks[cite: 1].

While central systems (like CCTNS and NATGRID) serve as data aggregation layers, and closed enterprise systems (like Palantir Gotham) act as opaque black boxes, this project fills the gap as an **Explainable, Reasoning-First, India-Context Analytical Layer**[cite: 1].

```
+-----------------------------------------------------------------------------------+
|                            DATA INGESTION & PIPELINE                              |
|  [FIRs (Unstructured Text)]   [CDRs (Call Logs)]   [Financial/Bank Records]       |
+----------------------------------------+------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                              ENTITY RESOLUTION (NLP)                              |
|  - Multilingual NER (spaCy / IndicNER / BERT)                                     |
|  - Anchor-based Fuzzy Matching (Phone/Vehicle/Name Disambiguation)                |
+----------------------------------------+------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                           GRAPH REASONING ENGINE (Neo4j)                          |
|  - Centrality Scoring (PageRank, Betweenness Centrality)                          |
|  - Pattern/Anomaly Detection (Circular Money Loops, Multi-Contact Nodes)           |
+----------------------------------------+------------------------------------------+
                                         |
                       +-----------------+-----------------+
                       |                                   |
                       v                                   v
+---------------------------------------------+ +-----------------------------------+
|      EXPLAINABLE INVESTIGATOR DASHBOARD     | |   BLOCKCHAIN AUDIT TRAIL LAYER    |
| - Interactive Entity Graph (Cytoscape/D3)   | | - Immutable Ledger (Hyperledger)|
| - Source Evidence Provenance & Confidence    | | - Court-Admissible Query & Edit |
| - Human-in-the-Loop Verification            | |   Chain-of-Custody Logging        |
+---------------------------------------------+ +-----------------------------------+
```[cite: 1]

---

## ✨ Key Features & Innovation

* **Multi-Source Data Ingestion & Multilingual NER:** Automatically extracts entities (names, phone numbers, vehicle numbers, locations, organizations) from unstructured natural language text—including Hindi and regional language FIRs—alongside structured CDRs and banking statements[cite: 1].
* **Entity Resolution & Disambiguation Engine:** Solves the hard problem of matching misspelled or variant names (e.g., "Ramesh Kumar" vs. "R. Kumar") using phone/vehicle anchor identifiers combined with fuzzy similarity scoring[cite: 1]. Borderline matches are flagged for human review[cite: 1].
* **Explainable AI (XAI) & Confidence-Scored Edges:** Every link in the relationship graph features a confidence probability score and points directly back to its source record and field, preventing "black-box" decisions and supporting courtroom admissibility[cite: 1].
* **Graph Analytics & Anomaly Detection:** Applies algorithms like PageRank and Betweenness Centrality to automatically highlight key suspect nodes and flag suspicious behaviors (such as circular financial transactions or frequent same-location contacts)[cite: 1].
* **Blockchain-Secured Chain of Custody:** Integrates an immutable audit trail logging every investigator search, graph modification, and human-in-the-loop approval to prevent unauthorized profiling and preserve evidentiary integrity[cite: 1].

---

## 🛠️ Tech Stack & Architecture

| Layer | Technologies & Frameworks |
| :--- | :--- |
| **NLP & AI Engine** | Python, spaCy, IndicNER, HuggingFace / Transformers (BERT)[cite: 1] |
| **Graph Database** | Neo4j (Cypher Query Language) / NetworkX[cite: 1] |
| **Backend & APIs** | FastAPI / Node.js, PostgreSQL (Structured Storage)[cite: 1] |
| **Frontend & Viz** | React.js, Cytoscape.js / D3.js / Kepler.gl[cite: 1] |
| **Security & Audit** | Solidity, Web3.js / Hyperledger Fabric (Blockchain Audit Logging)[cite: 1] |

---

## 🚀 Deploy (Production)

```bash
cp .env.example .env   # set CYSLOP_JWT_SECRET (32+ chars), FRONTEND_ORIGINS, CYSLOP_SEED_USERS
docker compose up --build -d
curl http://localhost:8000/healthz
ALLOW_INSECURE_DEV=1 CYSLOP_ENV=dev python -m pytest tests/ -q
```

Production notes: run behind TLS (reverse proxy), `CYSLOP_ENV=production` hides
`/docs`, CORS is pinned to `FRONTEND_ORIGINS`, login is rate-limited
(`10/minute` + 5-fail/5-min lockout with `LOGIN_FAILED` audit), users seed from
`CYSLOP_SEED_USERS` only, audit anchor lives at `CYSLOP_ANCHOR_PATH` with
optional external `CYSLOP_ANCHOR_URL`. SQLite volume `cyslop-data` must be
backed up; move to managed Postgres for multi-replica scale.

## 🚀 Quick Start (Local Setup)

### Prerequisites
* Python 3.11+
* Node.js v20+
* Docker (recommended) or local Python/Node

### 1. Clone & Set Up Backend
```bash
git clone https://github.com/your-org/SIH26189-criminal-network-analysis.git
cd SIH26189-criminal-network-analysis/backend

python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

```

### 2. Configure Environment

Create a `.env` file in the `backend/` directory:

```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_secure_password
POSTGRES_DB=police_analytics
BLOCKCHAIN_RPC_URL=http://127.0.0.1:8545

```

### 3. Initialize & Run Data Ingestion MVP

Run the synthetic data pipeline script to seed the graph database with mock FIRs, CDR logs, and transaction tables[cite: 1]:

```bash
python scripts/seed_synthetic_data.py
uvicorn app.main:app --reload

```

### 4. Set Up Frontend Dashboard

```bash
cd ../frontend
npm install
npm start

```

---

## 🧪 Synthetic Demo Scenario

Because real-world police data is restricted, this prototype runs on a controllable synthetic dataset[cite: 1]:

1. **Upload Case Files:** Ingest 10 mock FIRs, 500 CDR records, and 100 bank transaction rows[cite: 1].
2. **Automated Link Generation:** The system highlights three core suspects connected via a shared burner phone number and a circular money transfer pattern[cite: 1].
3. **Traceability:** Click any edge on the rendered graph to view the underlying evidence (e.g., *"Linked via FIR #204/23, Section 379 IPC"* or *"CDR log matching 14 calls within 48 hours"*)[cite: 1].
4. **Audit Logging:** Every graph inspection generates a cryptographic transaction hash recorded on the local blockchain ledger[cite: 1].

---

## 🛡️ Privacy, Ethics & Legal Safeguards

* **Case-Bound Access:** Designed to run queries only against records explicitly tied to active case files; it is not a population-wide surveillance tool[cite: 1].
* **Human-in-the-Loop:** AI-suggested connections remain unconfirmed until a authorized investigator reviews and signs off on the match[cite: 1].
* **DPDP Act & Regulatory Alignment:** Designed with strict access control and auditing to align with India's Digital Personal Data Protection (DPDP) framework[cite: 1].

---

## 📄 License

Distributed under the MIT License. See `LICENSE` for details[cite: 1].
