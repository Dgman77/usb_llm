"""
hyde.py — HyDE (Hypothetical Document Embeddings) Query Rewriting

Before embedding the user query for retrieval, HyDE generates a hypothetical
document passage that *would* answer the query. This hypothetical passage is
then embedded instead of the raw query, bridging the semantic gap between
question-style queries and document-style chunks.

Reference: Gao et al., "Precise Zero-Shot Dense Retrieval without Relevance Labels" (2022)
"""


def rewrite_query(query: str) -> str:
    """
    Generate a hypothetical document passage that answers the query.
    
    The returned text is meant to be *embedded* (not shown to the user).
    If generation fails, returns the original query as fallback.
    
    Args:
        query: The user's original question
        
    Returns:
        A hypothetical passage answering the query (for embedding)
    """
    from llm import generate_hyde_passage

    try:
        hypothesis = generate_hyde_passage(query)
        if hypothesis and len(hypothesis.strip()) > 20:
            return hypothesis.strip()
    except Exception as e:
        print(f"[HyDE] Generation failed: {e} — using raw query")

    return query
