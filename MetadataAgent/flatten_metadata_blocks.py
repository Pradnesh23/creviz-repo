# -*- coding: utf-8 -*-
def flatten_metadata_blocks(nested_json: str, intent_types: str) -> str:
    """
    Takes a complete nested metadata JSON string and breaks it into flat blocks.
    Handles forms (sections->components), reports (sections->columns),
    subForms, subReports, inline events, and application->pages->reports hierarchy.

    Args:
        nested_json: A JSON string of the complete metadata object.
        intent_types: Comma-separated intent types e.g. "form,section,component"

    Returns:
        A JSON string containing flat blocks ready for storage.
    """
    import json as _json
    import ast
    import uuid

    metadata = None
    try:
        metadata = _json.loads(nested_json)
    except Exception:
        try:
            metadata = ast.literal_eval(nested_json)
        except Exception:
            pass

    if metadata is None:
        return "ERROR: Could not parse the nested JSON."

    intents = [t.strip().lower().replace(" ", "_") for t in intent_types.split(",") if t.strip()]
    blocks = []

    # If already a list of {type, data} blocks, pass through
    if isinstance(metadata, list):
        for item in metadata:
            if isinstance(item, dict) and "type" in item and "data" in item:
                blocks.append(item)
            elif isinstance(item, dict):
                blocks.append({"type": "unknown", "data": item})
        return _json.dumps({"blocks": blocks, "count": len(blocks)})

    if not isinstance(metadata, dict):
        return "ERROR: Expected a JSON object or array."

    if "type" in metadata and "data" in metadata and isinstance(metadata["data"], dict):
        blocks.append(metadata)
        return _json.dumps({"blocks": blocks, "count": 1})

    possible_intents = [
        "application", "form", "section", "component", "form_components",
        "page", "report", "report_columns", "report_components", "report_section",
        "dashboard", "menu", "action", "event", "business_rule", "rule",
        "validation", "sub_form", "sub_report"
    ]

    # -- Work queue for iterative processing --
    work_queue = []

    # -- Step 1: Extract clearly keyed top-level intents --
    skip_nested = ("sections", "events", "components", "columns", "subForms", "subReports")
    for k in list(metadata.keys()):
        if k in skip_nested:
            continue
        k_lower = k.lower()
        val = metadata[k]
        block_type = k_lower
        if block_type.endswith("s") and block_type[:-1] in possible_intents:
            block_type = block_type[:-1]
        elif block_type == "business_rules":
            block_type = "business_rule"
        elif block_type == "report_columns":
            block_type = "report_columns"

        if block_type in possible_intents:
            if isinstance(val, dict):
                if "id" not in val:
                    val["id"] = str(uuid.uuid4())
                blocks.append({"type": block_type, "data": val})
                del metadata[k]
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        if "id" not in item:
                            item["id"] = str(uuid.uuid4())
                        blocks.append({"type": block_type, "data": item})
                del metadata[k]

    # -- Step 2: Extract remaining nested data --
    top_sections = metadata.pop("sections", None)
    top_events = metadata.pop("events", None)
    top_sub_forms = metadata.pop("subForms", None)
    top_sub_reports = metadata.pop("subReports", None)

    # -- Step 3: Create root block --
    skip_keys = ("components", "columns")
    root_fields = {k: v for k, v in metadata.items() if k not in skip_keys}
    root_id = None
    root_type = intents[0] if intents else "form"

    if len(root_fields) > 1 or "name" in root_fields or "collectionName" in root_fields:
        if "id" not in root_fields:
            root_fields["id"] = str(uuid.uuid4())
        root_id = root_fields["id"]
        blocks.append({"type": root_type, "data": root_fields})
    else:
        root_id = str(uuid.uuid4())

    # -- Step 4: Process blocks for nested children --
    # Use a multi-pass approach: keep processing until no new blocks are added
    processed_ids = set()

    def _process_block(b):
        """Process a single block, extracting nested children into work_queue."""
        bt = b["type"]
        bd = b["data"]
        block_key = bt + ":" + str(bd.get("id", ""))
        if block_key in processed_ids:
            return
        processed_ids.add(block_key)
        r_id = bd.get("id", root_id)

        if bt == "application":
            # Extract pages[] from application
            inline_pages = bd.pop("pages", None)
            if inline_pages and isinstance(inline_pages, list):
                for pg in inline_pages:
                    if isinstance(pg, dict):
                        if "id" not in pg:
                            pg["id"] = str(uuid.uuid4())
                        blocks.append({"type": "page", "data": pg})
            # Extract dashboards[] from application
            inline_dashboards = bd.pop("dashboards", None)
            if inline_dashboards and isinstance(inline_dashboards, list):
                for db in inline_dashboards:
                    if isinstance(db, dict):
                        if "id" not in db:
                            db["id"] = str(uuid.uuid4())
                        blocks.append({"type": "dashboard", "data": db})
            # Extract menus[] from application
            inline_menus = bd.pop("menus", None)
            if inline_menus and isinstance(inline_menus, list):
                for mn in inline_menus:
                    if isinstance(mn, dict):
                        if "id" not in mn:
                            mn["id"] = str(uuid.uuid4())
                        blocks.append({"type": "menu", "data": mn})

        elif bt in ("form", "sub_form"):
            s = bd.pop("sections", top_sections if bt == "form" else None)
            if s:
                work_queue.append(("sections", s, r_id, bt))
            e = bd.pop("events", top_events if bt == "form" else None)
            if e and isinstance(e, list):
                work_queue.append(("events_list", e, r_id, "formId"))
            sf = bd.pop("subForms", None)
            if sf:
                work_queue.append(("sub_forms", sf, r_id))

        elif bt in ("report", "sub_report"):
            s = bd.pop("sections", None)
            if s:
                work_queue.append(("sections", s, r_id, bt))
            e = bd.pop("events", None)
            if e and isinstance(e, list):
                work_queue.append(("events_list", e, r_id, "reportId"))
            sr = bd.pop("subReports", None)
            if sr:
                work_queue.append(("sub_reports", sr, r_id))

        elif bt == "page":
            # Extract inline reports
            inline_reports = bd.pop("reports", None)
            if inline_reports and isinstance(inline_reports, list):
                for rpt in inline_reports:
                    if isinstance(rpt, dict) and "id" in rpt:
                        blocks.append({"type": "report", "data": rpt})
                # Set reports to null on the page block (schema expects null or UUID array)
                bd["reports"] = None
            # Extract inline forms
            inline_forms = bd.pop("forms", None)
            if inline_forms and isinstance(inline_forms, list):
                for frm in inline_forms:
                    if isinstance(frm, dict) and "id" in frm:
                        blocks.append({"type": "form", "data": frm})
                bd["forms"] = None
            # Extract inline dashboards
            inline_dashboards = bd.pop("dashboards", None)
            if inline_dashboards and isinstance(inline_dashboards, list):
                for db in inline_dashboards:
                    if isinstance(db, dict) and "id" in db:
                        blocks.append({"type": "dashboard", "data": db})

    # Multi-pass: keep processing until all blocks are handled
    while True:
        unprocessed = [b for b in blocks if (b["type"] + ":" + str(b["data"].get("id", ""))) not in processed_ids]
        if not unprocessed:
            break
        for b in unprocessed:
            _process_block(b)

    # Handle remaining top-level data
    if top_sections:
        work_queue.append(("sections", top_sections, root_id, root_type))
    if top_events and isinstance(top_events, list):
        work_queue.append(("events_list", top_events, root_id, "formId"))
    if top_sub_forms:
        work_queue.append(("sub_forms", top_sub_forms, root_id))
    if top_sub_reports:
        work_queue.append(("sub_reports", top_sub_reports, root_id))

    # -- Step 5: Process work queue iteratively (NO recursion, NO nested defs) --
    while work_queue:
        task = work_queue.pop(0)
        action = task[0]

        if action == "sections":
            sections_list, parent_id, parent_type = task[1], task[2], task[3]
            if not isinstance(sections_list, list):
                continue
            for idx, sec in enumerate(sections_list):
                if not isinstance(sec, dict):
                    continue
                comps = sec.pop("components", None)
                cols = sec.pop("columns", None)
                sec_events = sec.pop("events", None)

                if "id" not in sec:
                    sec["id"] = str(uuid.uuid4())
                s_id = sec["id"]
                sec.setdefault("order", idx + 1)

                if parent_type in ("form", "sub_form"):
                    sec.setdefault("formId", parent_id)
                elif parent_type in ("report", "sub_report"):
                    sec.setdefault("reportId", parent_id)

                if sec_events and isinstance(sec_events, list):
                    work_queue.append(("events_list", sec_events, s_id, "sectionId"))

                blocks.append({"type": "section", "data": sec})

                if comps and isinstance(comps, list):
                    for cidx, c in enumerate(comps):
                        if isinstance(c, dict):
                            if "id" not in c:
                                c["id"] = str(uuid.uuid4())
                            c.setdefault("formId", parent_id)
                            c.setdefault("sectionId", s_id)
                            c.setdefault("order", cidx + 1)
                            comp_events = c.pop("events", None)
                            if comp_events and isinstance(comp_events, list):
                                work_queue.append(("events_list", comp_events, c["id"], "componentId"))
                            blocks.append({"type": "component", "data": c})

                if cols and isinstance(cols, list):
                    for cidx, c in enumerate(cols):
                        if isinstance(c, dict):
                            if "id" not in c:
                                c["id"] = str(uuid.uuid4())
                            c.setdefault("reportId", parent_id)
                            c.setdefault("sectionId", s_id)
                            c.setdefault("order", cidx + 1)
                            blocks.append({"type": "report_columns", "data": c})

        elif action == "events_list":
            events_list, parent_id, parent_key = task[1], task[2], task[3]
            if not isinstance(events_list, list):
                continue
            for evt in events_list:
                if not isinstance(evt, dict):
                    continue
                if "id" not in evt:
                    evt["id"] = str(uuid.uuid4())
                evt.setdefault(parent_key, parent_id)
                brs = evt.pop("businessRules", None)
                if brs and isinstance(brs, list):
                    for br in brs:
                        if isinstance(br, dict):
                            if "id" not in br:
                                br["id"] = str(uuid.uuid4())
                            blocks.append({"type": "business_rule", "data": br})
                blocks.append({"type": "event", "data": evt})

        elif action == "sub_forms":
            sub_forms_list, parent_id = task[1], task[2]
            if not isinstance(sub_forms_list, list):
                continue
            for sf in sub_forms_list:
                if not isinstance(sf, dict):
                    continue
                if "id" not in sf:
                    sf["id"] = str(uuid.uuid4())
                sf_sections = sf.pop("sections", None)
                sf_events = sf.pop("events", None)
                sf_sub_forms = sf.pop("subForms", None)
                sf.setdefault("parentFormId", parent_id)
                blocks.append({"type": "sub_form", "data": sf})

                if sf_sections:
                    work_queue.append(("sections", sf_sections, sf["id"], "sub_form"))
                if sf_events and isinstance(sf_events, list):
                    work_queue.append(("events_list", sf_events, sf["id"], "formId"))
                if sf_sub_forms:
                    work_queue.append(("sub_forms", sf_sub_forms, sf["id"]))

        elif action == "sub_reports":
            sub_reports_list, parent_id = task[1], task[2]
            if not isinstance(sub_reports_list, list):
                continue
            for sr in sub_reports_list:
                if not isinstance(sr, dict):
                    continue
                if "id" not in sr:
                    sr["id"] = str(uuid.uuid4())
                sr_sections = sr.pop("sections", None)
                sr_events = sr.pop("events", None)
                sr_sub_reports = sr.pop("subReports", None)
                sr.setdefault("parentReportId", parent_id)
                blocks.append({"type": "sub_report", "data": sr})

                if sr_sections:
                    work_queue.append(("sections", sr_sections, sr["id"], "sub_report"))
                if sr_events and isinstance(sr_events, list):
                    work_queue.append(("events_list", sr_events, sr["id"], "reportId"))
                if sr_sub_reports:
                    work_queue.append(("sub_reports", sr_sub_reports, sr["id"]))

    if len(blocks) == 0:
        return "ERROR: Could not extract any valid blocks from the nested JSON."

    return _json.dumps({"blocks": blocks, "count": len(blocks)})
