# -*- coding: utf-8 -*-
def generate_metadata_schema(intent_types: str) -> str:
    """
    Returns Creviz schema rules dynamically from the "schemas" folder.

    Args:
        intent_types: Comma-separated intent types e.g. "Page,Form,Validation"

    Returns:
        JSON string with schema rules for all requested intent types.
    """
    import json
    import os

    base_dir = "C:\\\\Users\\\\prads\\\\OneDrive\\\\Desktop\\\\letta\\\\schemas"
    if not os.path.exists(base_dir):
        base_dir = os.path.join(os.path.dirname(__file__), "schemas")

    requested = [t.strip().lower() for t in intent_types.split(",") if t.strip()]
    
    schema_package = {}
    unknown = []
    
    for req in requested:
        # Map "form" -> "form.json", "sub form" -> "sub_form.json"
        filename = f"{req.replace(' ', '_')}.json"
        filepath = os.path.join(base_dir, filename)
        
        try:
            if os.path.exists(filepath):
                with open(filepath, "r", encoding="utf-8") as f:
                    schema_package[req] = json.load(f)
            else:
                unknown.append(req)
        except Exception:
            unknown.append(req)

    return json.dumps({
        "intent_types": requested, 
        "schema_rules": schema_package, 
        "unknown_types": unknown, 
        "instruction": "Use ONLY the GENERATE template. Fill values from requirement. No $schema, $id, draft-07."
    })
