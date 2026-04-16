# -*- coding: utf-8 -*-
def get_metadata_from_redis(redis_key: str) -> str:
    """
    Fetches existing Creviz metadata from Redis by key.

    Args:
        redis_key: The Redis key to fetch metadata from.

    Returns:
        JSON string with the stored metadata content.
    """
    import json
    try:
        import redis as redis_lib
        r = redis_lib.Redis(host="localhost", port=6379, decode_responses=True)
        if not redis_key or not redis_key.strip():
            keys = sorted(r.keys("metadata:*"))
            if not keys:
                return json.dumps({"found": False, "message": "No metadata in Redis.", "content": None})
            redis_key = keys[-1]
        value = r.get(redis_key)
        if not value:
            return json.dumps({"found": False, "message": "Key not found.", "content": None})
        data = json.loads(value)
        block_count = len(data) if isinstance(data, list) else 1
        return json.dumps({"found": True, "redis_key": redis_key, "block_count": block_count, "content": data, "message": "Retrieved " + str(block_count) + " blocks from Redis."})
    except Exception as e:
        return json.dumps({"found": False, "message": "Redis fetch failed: " + str(e), "content": None})
