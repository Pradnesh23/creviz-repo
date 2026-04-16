# -*- coding: utf-8 -*-
def store_flattened_metadata_blocks(blocks_json: str, requirement: str, intent_types: str, agent_state: "AgentState") -> str:
    """
    Stores a flat list of modular Creviz metadata blocks in Redis and Qdrant.
    Each block is a separate JSON object with a "type" and "data" key.

    Args:
        blocks_json: A JSON array string of flat metadata blocks.
            Each block must have "type" (e.g. form, section, component, rule, page, report, menu, dashboard, business_rule)
            and "data" (the actual schema JSON object for that type).
            Example: [{"type":"form","data":{...}},{"type":"component","data":{...}}]
        requirement: The original user requirement text used for semantic search indexing.
        intent_types: Comma-separated intent types processed (e.g. "form,section,component").

    Returns:
        Confirmation with Redis key and Qdrant status.
    """
    import json
    import hashlib
    import uuid

    # Deterministic metadata_id based on requirement enables grouping multiple
    # agent cycles (Form, Report, Dashboard) into the exact same point in Qdrant
    import hashlib
    req_hash = hashlib.md5((requirement or "default").strip().lower().encode()).hexdigest()
    # Create a deterministic valid UUID
    metadata_id = str(uuid.UUID(req_hash))
    
    redis_key = "metadata:" + metadata_id
    redis_status = "not saved"
    qdrant_status = "not indexed"

    # Parse and validate input blocks
    try:
        import ast
        if isinstance(blocks_json, (list, dict)):
            blocks = blocks_json
        else:
            try:
                blocks = json.loads(blocks_json)
            except Exception as e_json:
                try:
                    blocks = ast.literal_eval(blocks_json)
                except Exception:
                    raise e_json

        # Handle both formats: direct array OR {"blocks": [...], "count": N}
        if isinstance(blocks, dict) and "blocks" in blocks:
            blocks = blocks["blocks"]
        if not isinstance(blocks, list):
            return "ERROR: blocks_json must be a JSON array. Got: " + str(type(blocks))
        for b in blocks:
            if "type" not in b or "data" not in b:
                return "ERROR: Each block must have a type and data key. Got: " + str(b)
    except Exception as e:
        return "ERROR: Could not parse blocks_json: " + str(e)

    # Write to Redis FIRST - if this fails, skip Qdrant to stay in sync
    try:
        import redis as redis_lib
        r = redis_lib.Redis(host="localhost", port=6379, decode_responses=True)
        
        # Load existing blocks (from previous agent cycles on the same requirement)
        # and MERGE with deduplication - new blocks override old ones with same id
        existing_data = r.get(redis_key)
        if existing_data:
            try:
                existing_blocks = json.loads(existing_data)
                if isinstance(existing_blocks, list):
                    # Build index: block data.id -> block (new blocks take priority)
                    merged = {}
                    for b in existing_blocks:
                        bid = b.get("data", {}).get("id", "") if isinstance(b.get("data"), dict) else ""
                        key = b.get("type", "") + ":" + bid if bid else None
                        if key:
                            merged[key] = b
                        else:
                            merged[id(b)] = b
                    for b in blocks:
                        bid = b.get("data", {}).get("id", "") if isinstance(b.get("data"), dict) else ""
                        key = b.get("type", "") + ":" + bid if bid else None
                        if key:
                            merged[key] = b  # new block overrides old
                        else:
                            merged[id(b)] = b
                    blocks = list(merged.values())
            except Exception:
                pass

        r.set(redis_key, json.dumps(blocks))
        redis_status = "saved: " + redis_key
    except Exception as e:
        redis_status = "Redis failed: " + str(e)
        return "DONE. Redis: " + redis_status + " | Qdrant: skipped (Redis must succeed first)"

    # Write vector index to Qdrant
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams, PointStruct
        qclient = QdrantClient(host="localhost", port=6333)
        collection_name = "creviz_metadata"
        if collection_name not in [c.name for c in qclient.get_collections().collections]:
            qclient.create_collection(collection_name=collection_name, vectors_config=VectorParams(size=128, distance=Distance.COSINE))

        dim = 128
        vector = [0.0] * dim
        text_lower = requirement.lower()
        for i in range(len(text_lower) - 2):
            trigram = text_lower[i:i+3]
            idx = int(hashlib.md5(trigram.encode()).hexdigest(), 16) % dim
            vector[idx] += 1.0
        total = sum(vector) or 1.0
        vector = [v / total for v in vector]

        point_id = int(hashlib.md5(metadata_id.encode()).hexdigest(), 16) % (2**63)
        summary = requirement[:200] if requirement else "Generated Metadata"
        types_stored = ", ".join(sorted(set(b["type"] for b in blocks)))

        payload = {
            "metadata_id": metadata_id,
            "intent_type": intent_types,
            "types_stored": types_stored,
            "block_count": len(blocks),
            "summary": summary
        }
        qclient.upsert(
            collection_name=collection_name,
            points=[PointStruct(id=point_id, vector=vector, payload=payload)]
        )
        qdrant_status = "indexed in Qdrant (blocks=" + str(len(blocks)) + ", types=" + types_stored + ")"
    except Exception as e:
        qdrant_status = "Qdrant failed: " + str(e)

    return "DONE. Redis: " + redis_status + " | Qdrant: " + qdrant_status
