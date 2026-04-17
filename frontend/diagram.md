flowchart TB
    %% Styles - Claude aesthetic with color-coded nodes
    classDef amber fill:#fef3e2,stroke:#d97706,stroke-width:2,color:#1a1915
    classDef teal fill:#e6f7f6,stroke:#0d9488,stroke-width:2,color:#1a1915
    classDef rose fill:#fce7f3,stroke:#db2777,stroke-width:2,color:#1a1915
    classDef indigo fill:#eef2ff,stroke:#4f46e5,stroke-width:2,color:#1a1915
    classDef red fill:#fef2f2,stroke:#dc2626,stroke-width:2,color:#1a1915
    classDef plain fill:#faf6ee,stroke:#e8e0d4,stroke-width:1,color:#7a756b

    subgraph INGESTION[Ingestion Pipeline]
        direction LR
        A[Upload File]:::amber --> B{File Type}:::plain
        B -->|PDF| C[extract_pdf]:::amber
        B -->|DOCX| D[extract_docx]:::amber
        B -->|TXT| E[extract_txt]:::amber
        C --> F[(page_num, text)]:::amber
        D --> F
        E --> F
        F --> G[chunk_text]:::amber
        G --> H[Chunks]:::amber
    end

    subgraph INDEXING[Index Building]
        direction TB
        H --> I[_rebuild]:::amber
        I --> J[_tokenize]:::amber
        J --> K[BM25]:::teal
        J --> L[FAISS Vector]:::teal
        K --> M[Hybrid Index]:::teal
        L --> M
    end

    subgraph STATE[Session RAM State]
        direction LR
        N[_chunks]:::indigo
        O[_chunk_doc]:::indigo
        P[_chunk_page]:::indigo
        Q[_doc_names]:::indigo
        R[vocab]:::indigo
        S[FAISS Index]:::teal
    end

    subgraph SEARCH[Query Search]
        direction TB
        T[User Query]:::plain --> U[_tokenize]:::amber
        U --> V{Hybrid Search}:::teal
        V --> W[BM25 Scores]:::teal
        V --> X[FAISS KNN]:::teal
        W --> Y[Score Fusion 0.4/0.6]:::teal
        X --> Y
        Y --> Z[Ranked Results]:::teal
    end

    subgraph REMOVAL[Document Removal]
        direction TB
        AA[remove_document]:::rose --> BB[Filter by filename]:::rose
        BB --> CC[_chunk_doc[i] != filename]:::rose
        CC --> DD[Keep Indices]:::rose
        DD --> EE[_rebuild]:::amber
        EE --> FF[Updated Index]:::teal
        EE --> GG[Return True/False]:::rose
    end

    subgraph CLEAR[Clear All]
        direction TB
        HH[clear_all]:::rose --> II[Clear all lists]:::rose
        II --> JJ[Reset BM25]:::rose
        JJ --> KK[Reset FAISS]:::rose
    end

    subgraph EXIT[Session Exit]
        direction LR
        LL[Server Restart<br/>or Tab Close]:::indigo --> MM[RAM Cleared]:::red
    end

    subgraph ERRORS[Error Handling]
        direction TB
        NN[Unsupported Type]:::red --> OO[Raise ValueError]:::red
        PP[Empty Query]:::red --> QQ[Return Empty]:::red
    end

    %% Connections between subgraphs
    INGESTION --> INDEXING
    INDEXING --> STATE
    STATE -.->|Query| SEARCH
    SEARCH -->|Results| STATE
    STATE -.->|Remove| REMOVAL
    REMOVAL --> INDEXING
    STATE -.->|Clear All| CLEAR
    CLEAR --> STATE
    EXIT -.-> STATE
    ERRORS -.->|Errors| INGESTION

    %% CSS styling via themeVariables would be in JS config