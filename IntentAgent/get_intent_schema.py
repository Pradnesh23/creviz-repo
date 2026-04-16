# -*- coding: utf-8 -*-
def get_intent_schema() -> str:
    """
    Reads the Creviz intent_classifier.json and returns a COMPRESSED
    version containing only intent names, keywords, aliases, and parent
    relationships. Examples, sub_intents, and schema_rules are stripped
    to keep the output small and avoid flooding the context window.

    Returns:
        JSON string with compressed intent keyword table.
    """
    import json
    import os

    schema_paths = [
        "C:\\\\Users\\\\prads\\\\OneDrive\\\\Desktop\\\\letta\\\\intent_classifier.json",
        os.path.join(os.path.dirname(__file__), "intent_classifier.json"),
    ]

    for path in schema_paths:
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                compressed = []
                for intent in data.get("intents", []):
                    compressed.append({
                        "intent": intent.get("intent", ""),
                        "keywords": intent.get("keywords", []),
                        "aliases": intent.get("aliases", []),
                        "parent": intent.get("parent", None)
                    })
                return json.dumps({
                    "status": "loaded",
                    "source": path,
                    "intent_count": len(compressed),
                    "intents": compressed
                })
        except Exception as e:
            continue

    return json.dumps({
        "status": "fallback",
        "message": "intent_classifier.json not found, using basic list",
        "intents": [
            {"intent": "application", "keywords": ["application", "system", "platform"], "aliases": [], "parent": None},
            {"intent": "page", "keywords": ["page", "screen", "workspace"], "aliases": [], "parent": None},
            {"intent": "menu", "keywords": ["menu", "navigation", "sidebar"], "aliases": [], "parent": None},
            {"intent": "form", "keywords": ["form", "submit", "capture", "create", "record", "enter", "request", "specify"], "aliases": [], "parent": None},
            {"intent": "report", "keywords": ["report", "list", "track", "view all", "tracker"], "aliases": [], "parent": None},
            {"intent": "dashboard", "keywords": ["dashboard", "summary", "chart", "kpi", "metrics"], "aliases": [], "parent": None},
            {"intent": "validation", "keywords": ["mandatory", "required", "cannot be empty", "cannot be bypassed"], "aliases": [], "parent": "form"},
            {"intent": "business_rule", "keywords": ["auto number", "reference number", "pdf", "generate", "approval", "if", "when", "condition"], "aliases": [], "parent": None},
            {"intent": "action", "keywords": ["notify", "email", "sms", "notification", "alert"], "aliases": [], "parent": None},
            {"intent": "event", "keywords": ["button", "save button", "submit button", "on click"], "aliases": [], "parent": None}
        ]
    })
