# -*- coding: utf-8 -*-
def semantic_search_qdrant(intent_query: str) -> str:
    """
    Searches Qdrant vector database for existing Creviz metadata
    matching the given intent query using character trigram similarity.

    Args:
        intent_query: The user requirement text to search for similar metadata.

    Returns:
        JSON string - found metadata info or empty result signal.
    """
    import json
    import hashlib

    # Inline vector generation (no nested function)
    dim = 128
    vector = [0.0] * dim
    text_lower = intent_query.lower()
    for i in range(len(text_lower) - 2):
        trigram = text_lower[i:i+3]
        idx = int(hashlib.md5(trigram.encode()).hexdigest(), 16) % dim
        vector[idx] += 1.0
    total = sum(vector) or 1.0
    query_vector = [v / total for v in vector]

    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(host="localhost", port=6333)
        collection_name = "creviz_metadata"
        collections = client.get_collections().collections
        if collection_name not in [c.name for c in collections]:
            return json.dumps({"found": False, "message": "No metadata collection yet. Generate fresh.", "results": []})
        search_result = client.query_points(collection_name=collection_name, query=query_vector, limit=3, score_threshold=0.80, with_payload=True)
        results_raw = search_result.points if hasattr(search_result, "points") else []
        if not results_raw:
            return json.dumps({"found": False, "message": "No similar metadata found. Generate fresh.", "results": []})
        results = [{"score": round(h.score, 3), "metadata_id": h.payload.get("metadata_id", ""), "intent_type": h.payload.get("intent_type", "")} for h in results_raw]
        return json.dumps({"found": True, "message": "Similar metadata found.", "best_match_redis_key": "metadata:" + results[0]["metadata_id"], "best_match_score": results[0]["score"], "results": results})
    except Exception as e:
        return json.dumps({"found": False, "message": "Qdrant search failed: " + str(e), "results": []})
