# -*- coding: utf-8 -*-
def generate_metadata_schema(intent_types: str) -> str:
    """
    Returns Creviz metadata templates and examples for the requested intent types.
    Uses precomputed concrete templates (not raw JSON Schema) so the agent can
    directly fill in values from the user requirement.

    Args:
        intent_types: Comma-separated intent types e.g. "Page,Form,Report"

    Returns:
        JSON string with fill-in templates and production examples for all requested types.
    """
    import json
    import os

    # Find schemas directory - try multiple paths for portability
    script_dir = os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else "."
    candidates = [
        os.path.join(script_dir, "schemas"),
        os.path.join(script_dir, "..", "schemas"),
        r"c:\Users\prads\OneDrive\Desktop\creviz\letta\schemas",
        r"C:\Users\prads\OneDrive\Desktop\creviz\letta\schemas",
    ]
    
    base_dir = None
    for c in candidates:
        if os.path.exists(c) and os.path.isdir(c):
            base_dir = c
            break
    
    if base_dir is None:
        return json.dumps({"error": "schemas directory not found", "tried": candidates})

    requested = [t.strip().lower().replace(" ", "_") for t in intent_types.split(",") if t.strip()]

    # Alias map: normalize sub-schema filename mismatches to their template keys.
    # E.g. BusinessRule.json normalizes to "businessrule" but template key is "business_rule".
    # Form-Root/Sections/DataAccessControl are sub-parts already included in the composite "form" template.
    ALIAS_MAP = {
        "businessrule": "business_rule",
        "form_root": "form",
        "form_sections": "section",
        "form_dataaccesscontrol": "form",       # DAC is part of form template
        "report_root": "report",
        "report_dataaccesscontrol": "report",   # DAC is part of report template
    }

    # Resolve aliases in requested intents
    requested = [ALIAS_MAP.get(r, r) for r in requested]
    # Deduplicate
    requested = list(dict.fromkeys(requested))

    # Load precomputed templates (contains concrete fill-in templates + full production examples)
    precomputed_path = os.path.join(base_dir, "_precomputed_templates.json")
    precomputed = {}
    if os.path.exists(precomputed_path):
        try:
            with open(precomputed_path, "r", encoding="utf-8") as f:
                precomputed = json.load(f)
        except Exception:
            pass

    templates = precomputed.get("templates", {})
    examples = precomputed.get("examples", {})
    expand_map = precomputed.get("expand_map", {})

    # Build the response: templates + relevant examples for each requested intent
    schema_package = {}
    unknown = []
    expanded_intents = set(requested)

    # Auto-expand: if "form" requested, also include section, component, event templates
    for req in requested:
        if req in expand_map:
            for sub in expand_map[req]:
                expanded_intents.add(sub)

    # Collect templates for all expanded intents
    for req in sorted(expanded_intents):
        # Check alias again for expanded intents
        resolved = ALIAS_MAP.get(req, req)
        if resolved in templates:
            schema_package[resolved] = templates[resolved]
        elif req in templates:
            schema_package[req] = templates[req]
        else:
            # Fallback: try loading individual schema file with case-insensitive search
            found = False
            for candidate_name in [req, resolved]:
                filename = candidate_name + ".json"
                filepath = os.path.join(base_dir, filename)
                if not os.path.exists(filepath):
                    for f in os.listdir(base_dir):
                        if f.lower() == filename.lower():
                            filepath = os.path.join(base_dir, f)
                            break
                if os.path.exists(filepath):
                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            schema_package[candidate_name] = json.load(f)
                        found = True
                        break
                    except Exception:
                        pass
            if not found:
                unknown.append(req)

    # Pick the most relevant examples based on requested intents
    relevant_examples = {}
    if any(i in expanded_intents for i in ["form", "section", "component", "sub_form"]):
        if "page_with_form" in examples:
            relevant_examples["page_with_form"] = examples["page_with_form"]
    if any(i in expanded_intents for i in ["report", "report_columns", "report_section", "sub_report"]):
        if "page_with_report" in examples:
            relevant_examples["page_with_report"] = examples["page_with_report"]
    # Always include both examples when page or application is requested
    if any(i in expanded_intents for i in ["page", "application"]):
        for ex_name in ["page_with_form", "page_with_report"]:
            if ex_name in examples:
                relevant_examples[ex_name] = examples[ex_name]

    return json.dumps({
        "intent_types": list(expanded_intents),
        "templates": schema_package,
        "production_examples": relevant_examples,
        "unknown_types": unknown,
        "instruction": (
            "Use the TEMPLATES as your field reference - include ALL keys shown. "
            "Use the PRODUCTION_EXAMPLES as your structural reference - match the exact nesting. "
            "Replace descriptive string values with actual values from the requirement. "
            "Generate real UUIDs (format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx). "
            "accessControl.roles MUST contain real role UUIDs, NEVER empty arrays. "
            "Components MUST have: id, type, order, isAttribute, isOnReport, accessControl, "
            "properties (with attribute, label, placeholder, labelIcon, inputIcon, withLabel, "
            "labelLayout, hidden, disabled, required), rules:[], style:{wrapperClassName, "
            "labelClassName, inputClassName, labelIconClassName, inputIconClassName}, "
            "validation:[], events:[]. "
            "Events MUST have: id, name, alias, type, sync, deleted, actionIds, "
            "businessRuleIds, accessControl, properties (with icon, variant, label, "
            "redirectPage, toast, rules). "
            "Do NOT include $schema, $id, draft-07 keys."
        )
    })
