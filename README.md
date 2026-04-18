# DiagramAI — Offline Pendrive Setup

## Folder Structure

```
USB_DRIVE:\ [format you usb to 'exfat' file system]
├── start.bat                 ← Double-click to START
├── dev_install.bat           ← Run ONCE to download portable Python and it packages(needs internet)
├── wait_for_server.py
│
├── python\           ← python and packages (optional)
│   └── python.exe
│   └── lib\packages
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
├── wheels\
│   ├── illama.cpp whl for no need to compile  theme . because it is precompiled
│  
│
├── models\
│   ├── Phi-3-mini-4k-instruct-q4.gguf
│   └── embeddings\
│
└── data\ your pdf files or system outside location is fine .
```


## Quick Start
# Fully portable (recommended)
1. Copy to USB
2. Double-click dev_install.bat (needs internet once)(i think no need if  a github repository have python.zip)
3. Double-click start.bat
4. iff you need test you chat model cleck the chat.bat file

# after that you need on internet.


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
