# Flash AI with RAG  — Offline Pendrive Setup
# usb_llm

A fully offline, portable AI assistant with Retrieval-Augmented Generation (RAG) and Graphviz diagram generation, designed to run directly from a USB pendrive.

---

## Features

### 100% Offline
- Runs completely locally.
- Uses bundled or pre-downloaded GGUF models through `llama-cpp-python`.
- No internet connection required.

### FastAPI Backend
- REST API powered by FastAPI.
- Serves static frontend assets from `frontend/index.html`.

### Dense Vector RAG
Supports:

- PDF
- DOCX
- TXT
- CSV
- XLSX
- PPTX
- HTML
- Markdown
- JSON
- XML
- RTF
- Images (OCR)

Features:

- FAISS vector indexing
- SQLite metadata storage
- Semantic search and retrieval
- Token-aware chunking

### Dynamic Diagram Engine
Automatically generates Graphviz DOT diagrams from prompts and document content.

Supported diagram types:

- Flowcharts
- Sequence Diagrams
- ER Diagrams
- Class Diagrams
- State Diagrams
- Gantt Charts
- Mind Maps

### Low-Spec Optimization
- CPU-friendly inference
- Resident model loading
- Lightweight retrieval pipeline
- Portable deployment from USB storage

---

# Project Structure

```text
usb_llm/
├── backend/
│   ├── main.py            # FastAPI server and startup lifecycle
│   ├── llm.py             # Model loading and text generation
│   ├── rag.py             # Document extraction, FAISS, SQLite storage
│   ├── router.py          # Request routing (QA vs Diagram)
│   ├── orchestrator.py    # RAG orchestration pipeline
│   ├── crag.py            # Corrective RAG evaluation
│   ├── hyde.py            # HyDE query transformation
│   ├── reranker.py        # Retrieval reranking
│   └── requirements.txt   # Python dependencies
│
├── frontend/
│   ├── index.html         # Web user interface
│   └── diagram.md         # Diagram specifications
│
├── graphviz/              # Portable Graphviz binaries
├── Wheels/                # Offline wheel packages
├── models/                # GGUF language models
├── chat.py                # CLI interface
└── README.md
```

---

# Requirements

- Python 3.11+
- Windows, Linux, or macOS (64-bit)
- Minimum 4 GB RAM
- Recommended 8 GB RAM
- GGUF model file

Example models:

- TinyLlama
- Phi-3 Mini
- Mistral 7B Instruct
- Llama 3.x GGUF variants

---

# Installation

## Clone Repository

```bash
git clone https://github.com/Dgman77/usb_llm.git
cd usb_llm
```

## Install Dependencies

```bash
Setup.Bat - # Used to install a Sepertate Python environment + Extra Dependencies

Note : It will create a python folder inside we have  all dependencies + Modified AI Model Also Downloaded In \models Folder.
```

## Add Model
```text
You can add a Different Model But it Will Struggle to Create a DOT code fort Diagram generation.

Always Increase The Context Window Value.
```

---


# Running the Application

## Start Web Server

```bash
Douple - Click The start.bat (or) .\start.bat Inside the Powershell To run the application [http://localhost:8787]

Note: Before click the start.bat , You must Ran the setup.bat .
```



## Run CLI Chat

```bash
python chat.py
```

---

# RAG Workflow

```text
User Query
     │
     ▼
HyDE Query Rewriter
     │
     ▼
FAISS Retrieval
     │
     ▼
CRAG Validation
     │
     ▼
Context Assembly
     │
     ▼
LLM Generation
     │
     ▼
Response
```

---

# Diagram Generation Workflow

```text
Prompt
   │
   ▼
Diagram Intent Detection
   │
   ▼
DOT Generation
   │
   ▼
Graphviz Rendering
   │
   ▼
PNG / SVG Output
```

---

# Supported Document Types

| Type | Supported |
|--------|-----------|
| PDF | ✅ |
| DOCX | ✅ |
| TXT | ✅ |
| CSV | ✅ |
| XLSX | ✅ |
| PPTX | ✅ |
| HTML | ✅ |
| Markdown | ✅ |
| JSON | ✅ |
| XML | ✅ |
| RTF | ✅ |
| Images | ✅ |

---

# API Overview

## Chat Endpoint

```http
POST /chat
```

Example Request:

```json
{
  "message": "Explain the uploaded project architecture."
}
```

---

## Upload Endpoint

```http
POST /upload
```

Upload documents to populate the RAG knowledge base.

---

## Diagram Endpoint

```http
POST /diagram
```

Example Request:

```json
{
  "prompt": "Create an ERP workflow diagram."
}
```

---

# Offline Deployment

Designed for:

- USB Pendrives
- Air-gapped environments
- Local enterprise deployments
- Secure internal networks
- Educational labs
- Field operations

No cloud dependencies required after setup.

---

# Technology Stack

- Python
- FastAPI
- llama-cpp-python
- FAISS
- SQLite
- Graphviz
- HTML/CSS/JavaScript

---

# Future Enhancements

- Multi-model support
- Quantized model auto-selection
- Hybrid retrieval
- Knowledge graph integration
- Local speech-to-text
- Local text-to-speech
- Multi-user document collections

---

