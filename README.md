# DiagramAI — Offline Pendrive Setup

## Folder Structure

```
USB_DRIVE:\
├── start.bat                 ← Double-click to START
├── setup.bat                 ← Run ONCE to download portable Python
├── wait_for_server.py
│
├── python_runtime\           ← Created by setup.bat (optional)
│   └── python.exe
│
├── backend\
│   ├── main.py
│   ├── llm.py
│   ├── rag.py
│   ├── router.py
│   └── requirements.txt
│
├── frontend\
│   ├── index.html
│   └── mermaid.min.js
│
├── models\
│   ├── Phi-3-mini-4k-instruct-q4.gguf
│   └── embeddings\
│
└── data\
```

## Quick Start

### Option 1: Use system Python (no setup needed)
1. Copy to USB
2. Double-click start.bat
3. First run will install packages automatically

### Option 2: Fully portable (recommended)
1. Copy to USB
2. Double-click setup.bat (needs internet once)
3. Double-click start.bat

## Usage

1. Plug in USB
2. Double-click start.bat
3. Wait 30-60 seconds
4. Browser opens at http://localhost:8787
5. Press any key to stop

## Requirements

- Windows 10/11 (64-bit)
- At least 4GB RAM
- Model file in models\ folder (.gguf format)