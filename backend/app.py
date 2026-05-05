"""
Creviz Metadata Viewer — Backend
Standalone Flask server that reads flat metadata blocks from Redis
and reassembles them into a nested hierarchical JSON structure.

Run:  python app.py
URL:  http://localhost:5001
"""

import json
import os
import logging
from flask import Flask, jsonify, request, send_from_directory
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

try:
    import redis as redis_lib
except ImportError:
    redis_lib = None

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))

app = Flask(__name__, static_folder="static", static_url_path="")
log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)


# ── Redis helper ──────────────────────────────────────────────
def _get_redis():
    if redis_lib is None:
        raise RuntimeError("redis package not installed — pip install redis")
    return redis_lib.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


# ── Validation Helper ─────────────────────────────────────────

import re

SCHEMA_DIR = r"c:\Users\prads\OneDrive\Desktop\creviz\letta\schemas"

# Map block types to schemas.
# Report.json expects {root,sections} (assembled) — use Report-Root for flat blocks.
SCHEMA_MAP = {
    "application": "Application.json",
    "page": "Page.json",
    "form": "Form.json",
    "dashboard": "Dashboard.json",
    "report": "Report-Root.json",
    "business_rule": "BusinessRule.json",
    "action": "Action.json",
    "component": "component.json",
    "section": "section.json",
    "event": "Event.json",
    "menu": "Menu.json",
    "report_columns": "Report-Columns.json"
}

# Schemas whose root type is "array" — flat blocks are single objects
ARRAY_ROOT_SCHEMAS = {"event", "report_columns"}

# Fields that only exist AFTER reassembly — skip from required
ASSEMBLY_ONLY_FIELDS = {
    "page": {"forms", "reports", "dashboard"},
    "form": {"sections"},
}

# Strict hex-only UUID: 8-4-4-4-12, only [0-9a-f]
UUID_REGEX = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE
)

# Known block types that MUST have an "id" field
BLOCK_TYPES_WITH_ID = {
    "application", "page", "form", "report", "dashboard",
    "event", "section", "component", "report_columns",
    "business_rule", "action", "menu"
}

# Block types that MUST have accessControl with at least one role
AC_REQUIRED_TYPES = {
    "application", "page", "form", "report", "dashboard",
    "event", "section", "component", "report_columns"
}


def remove_refs(obj):
    if isinstance(obj, dict):
        obj.pop("$ref", None)
        for k, v in list(obj.items()):
            remove_refs(v)
    elif isinstance(obj, list):
        for item in obj:
            remove_refs(item)
    return obj

_schema_cache = {}
def get_flat_block_validator(block_type):
    """Returns a JSON schema validator adapted for flat blocks."""
    cache_key = f"flat_{block_type}"
    if cache_key in _schema_cache:
        return _schema_cache[cache_key]

    schema_file = SCHEMA_MAP.get(block_type)
    if not schema_file:
        _schema_cache[cache_key] = None
        return None

    path = os.path.join(SCHEMA_DIR, schema_file)
    if not os.path.exists(path):
        _schema_cache[cache_key] = None
        return None

    with open(path, "r", encoding="utf-8") as f:
        schema = json.load(f)
        schema = remove_refs(schema)

    # For array-root schemas, extract items schema to validate single objects
    if block_type in ARRAY_ROOT_SCHEMAS and schema.get("type") == "array":
        items_schema = schema.get("items", {})
        if items_schema:
            schema = items_schema

    # Remove assembly-only fields from required list
    skip_fields = ASSEMBLY_ONLY_FIELDS.get(block_type, set())
    if skip_fields and "required" in schema:
        schema["required"] = [f for f in schema["required"] if f not in skip_fields]

    validator = Draft202012Validator(schema)
    _schema_cache[cache_key] = validator
    return validator


# ── Layer 1: JSON Schema Validation ──────────────────────────
def _validate_schema(blocks):
    """Validates each flat block against its JSON schema."""
    errors = []
    for block in blocks:
        b_type = block.get("type")
        b_data = block.get("data", {})
        b_id = b_data.get("id", "unknown")

        validator = get_flat_block_validator(b_type)
        if validator:
            block_errors = sorted(validator.iter_errors(b_data), key=lambda e: e.path)
            for err in block_errors:
                path_str = ".".join(str(p) for p in err.path) or "root"
                errors.append(f"[SCHEMA] [{b_type}] (id: {b_id}) - Field '{path_str}': {err.message}")
    return errors


# ── Layer 2: UUID Format Enforcement ─────────────────────────
def _validate_uuids(blocks):
    """Ensures all 'id' fields and ID references are valid hex-only UUIDs."""
    errors = []
    for block in blocks:
        b_type = block.get("type", "unknown")
        b_data = block.get("data", {})
        b_id = b_data.get("id", "unknown")

        # Check primary "id"
        if b_type in BLOCK_TYPES_WITH_ID:
            raw_id = b_data.get("id")
            if not raw_id:
                errors.append(f"[UUID] [{b_type}] - Missing 'id' field entirely")
            elif not UUID_REGEX.match(str(raw_id)):
                errors.append(f"[UUID] [{b_type}] (id: {raw_id}) - Invalid UUID format (must be hex-only 8-4-4-4-12)")

        # Check applicationId
        app_id = b_data.get("applicationId")
        if app_id and not UUID_REGEX.match(str(app_id)):
            errors.append(f"[UUID] [{b_type}] (id: {b_id}) - Invalid applicationId '{app_id}'")

        # Check all *Ids arrays (formIds, reportIds, eventIds, etc.)
        for key, val in b_data.items():
            if key.endswith("Ids") and isinstance(val, list):
                for i, ref_id in enumerate(val):
                    if ref_id and not UUID_REGEX.match(str(ref_id)):
                        errors.append(f"[UUID] [{b_type}] (id: {b_id}) - Invalid UUID in {key}[{i}]: '{ref_id}'")

        # Check accessControl role UUIDs
        ac = b_data.get("accessControl", {})
        if isinstance(ac, dict):
            for role_id in ac.get("roles", []):
                if role_id and not UUID_REGEX.match(str(role_id)):
                    errors.append(f"[UUID] [{b_type}] (id: {b_id}) - Invalid role UUID: '{role_id}'")

    return errors


# ── Layer 3: AccessControl Enforcement ───────────────────────
def _validate_access_control(blocks):
    """Ensures accessControl.roles is never empty on entities that need it."""
    errors = []
    for block in blocks:
        b_type = block.get("type", "unknown")
        b_data = block.get("data", {})
        b_id = b_data.get("id", "unknown")

        if b_type not in AC_REQUIRED_TYPES:
            continue

        ac = b_data.get("accessControl")
        if not ac or not isinstance(ac, dict):
            errors.append(f"[ACCESS] [{b_type}] (id: {b_id}) - Missing 'accessControl' object")
            continue

        roles = ac.get("roles", [])
        if not isinstance(roles, list) or len(roles) == 0:
            errors.append(f"[ACCESS] [{b_type}] (id: {b_id}) - 'accessControl.roles' is empty (MUST have >= 1 role UUID)")

    return errors


# ── Layer 4: Cross-Reference Integrity ───────────────────────
def _validate_cross_references(blocks):
    """Ensures all ID references point to blocks that actually exist."""
    errors = []

    # Build a set of all known block IDs
    all_ids = set()
    for block in blocks:
        b_data = block.get("data", {})
        bid = b_data.get("id")
        if bid:
            all_ids.add(str(bid))

    # Check references
    for block in blocks:
        b_type = block.get("type", "unknown")
        b_data = block.get("data", {})
        b_id = b_data.get("id", "unknown")

        # Check formId, pageId, sectionId, reportId (single FK references)
        for fk_field in ["formId", "pageId", "sectionId", "reportId"]:
            ref = b_data.get(fk_field)
            if ref and str(ref) not in all_ids:
                errors.append(f"[XREF] [{b_type}] (id: {b_id}) - '{fk_field}' references '{ref}' which does not exist in any block")

        # Check *Ids arrays (formIds, reportIds, dashboardIds, eventIds)
        for key, val in b_data.items():
            if key.endswith("Ids") and isinstance(val, list):
                # Skip businessRuleIds and actionIds — they reference external entities
                if key in ("businessRuleIds", "actionIds"):
                    continue
                for ref_id in val:
                    if ref_id and str(ref_id) not in all_ids:
                        errors.append(f"[XREF] [{b_type}] (id: {b_id}) - '{key}' references '{ref_id}' which does not exist in any block")

    return errors


# ── Layer 5: Structural Consistency ──────────────────────────
def _validate_structural(blocks):
    """Checks high-level structural rules across all blocks."""
    errors = []

    # Collect applicationIds — they should all be the same
    app_ids = set()
    block_types_seen = set()

    for block in blocks:
        b_type = block.get("type", "unknown")
        b_data = block.get("data", {})
        block_types_seen.add(b_type)

        aid = b_data.get("applicationId")
        if aid:
            app_ids.add(str(aid))

    # Rule: All blocks must share the same applicationId
    if len(app_ids) > 1:
        errors.append(f"[STRUCT] Multiple applicationId values found: {app_ids} — all blocks must share ONE applicationId")

    # Rule: Must have at least one application block
    if "application" not in block_types_seen:
        errors.append("[STRUCT] No 'application' block found — every metadata set must include one")

    # Rule: Must have at least one page block
    if "page" not in block_types_seen:
        errors.append("[STRUCT] No 'page' block found — every metadata set must include one")

    # Rule: If form exists, events should exist (submit + cancel)
    if "form" in block_types_seen and "event" not in block_types_seen:
        errors.append("[STRUCT] 'form' block found but no 'event' blocks — forms require at least Submit and Cancel events")

    return errors


# ── Master Validation Orchestrator ───────────────────────────
def validate_blocks(blocks):
    """
    Runs ALL validation layers on flat blocks.
    Returns (True, None) if all valid, or (False, error_details) if invalid.
    """
    all_errors = []

    # Layer 1: JSON Schema
    all_errors.extend(_validate_schema(blocks))

    # Layer 2: UUID format (hex-only)
    all_errors.extend(_validate_uuids(blocks))

    # Layer 3: AccessControl roles not empty
    all_errors.extend(_validate_access_control(blocks))

    # Layer 4: Cross-reference integrity
    all_errors.extend(_validate_cross_references(blocks))

    # Layer 5: Structural consistency
    all_errors.extend(_validate_structural(blocks))

    if all_errors:
        return False, all_errors
    return True, None


# ── Reassembly: flat blocks → nested hierarchy ───────────────
def reassemble(flat_blocks):
    """
    Takes a flat list of {type, data} blocks from Redis and rebuilds
    the nested Creviz production structure:

    {
      "application": {
        ...,
        "pages": [{
          ...,
          "forms": [{ sections: [{ components: [...], events: [...] }], events: [...], subForms: [...] }],
          "reports": [{ sections: [{ columns: [...], events: [...] }], events: [...], subReports: [...] }]
        }]
      }
    }
    """
    # ── Step 1: Index all blocks by type ──
    by_type = {}
    for b in flat_blocks:
        t = b.get("type", "unknown")
        by_type.setdefault(t, []).append(b.get("data", {}))

    applications = by_type.get("application", [])
    pages = by_type.get("page", [])
    forms = by_type.get("form", [])
    reports = by_type.get("report", [])
    sections = by_type.get("section", [])
    components = by_type.get("component", [])
    columns = by_type.get("report_columns", [])
    events = by_type.get("event", [])
    business_rules = by_type.get("business_rule", [])
    dashboards = by_type.get("dashboard", [])
    menus = by_type.get("menu", [])
    sub_forms = by_type.get("sub_form", [])
    sub_reports = by_type.get("sub_report", [])
    actions_list = by_type.get("action", [])

    # Build lookup maps by id
    def by_id(items):
        return {item.get("id"): item for item in items if item.get("id")}

    br_map = by_id(business_rules)
    action_map = by_id(actions_list)
    dashboard_map = by_id(dashboards)

    # ── Step 2: Attach events to their parents ──
    # Events link via formId, sectionId, or componentId
    form_events = {}      # formId -> [events]
    section_events = {}   # sectionId -> [events]
    component_events = {} # componentId -> [events]

    for evt in events:
        # Resolve inline businessRules by ID if they're just IDs
        br_ids = evt.get("businessRuleIds", [])
        if br_ids and not evt.get("businessRules"):
            evt["businessRules"] = [br_map[bid] for bid in br_ids if bid in br_map]

        # Resolve inline actions by ID
        act_ids = evt.get("actionIds", [])
        if act_ids and not evt.get("actions"):
            evt["actions"] = [action_map[aid] for aid in act_ids if aid in action_map]

        if evt.get("componentId"):
            component_events.setdefault(evt["componentId"], []).append(evt)
        elif evt.get("sectionId"):
            section_events.setdefault(evt["sectionId"], []).append(evt)
        elif evt.get("formId"):
            form_events.setdefault(evt["formId"], []).append(evt)
        elif evt.get("reportId"):
            form_events.setdefault(evt["reportId"], []).append(evt)

    # ── Step 3: Attach components to sections ──
    section_components = {}  # sectionId -> [components]
    for comp in components:
        sid = comp.get("sectionId")
        if sid:
            # Attach component-level events inline
            cid = comp.get("id")
            if cid and cid in component_events:
                comp["events"] = component_events[cid]
            else:
                comp.setdefault("events", [])
            section_components.setdefault(sid, []).append(comp)

    # ── Step 4: Attach columns to report sections ──
    section_columns = {}  # sectionId -> [columns]
    for col in columns:
        sid = col.get("sectionId")
        if sid:
            section_columns.setdefault(sid, []).append(col)

    # ── Step 5: Build sections with nested children ──
    form_sections = {}    # formId -> [sections]
    report_sections = {}  # reportId -> [sections]

    for sec in sections:
        sid = sec.get("id")
        # Attach components or columns
        if sid in section_components:
            sec["components"] = sorted(section_components[sid], key=lambda x: x.get("order", 0))
        if sid in section_columns:
            sec["columns"] = sorted(section_columns[sid], key=lambda x: x.get("order", 0))
        # Attach section-level events
        if sid in section_events:
            sec["events"] = section_events[sid]
            # Also build eventIds from the events
            sec["eventIds"] = [e.get("id") for e in sec["events"] if e.get("id")]
        else:
            sec.setdefault("events", [])

        # Route section to its parent
        fid = sec.get("formId")
        rid = sec.get("reportId")
        if fid:
            form_sections.setdefault(fid, []).append(sec)
        elif rid:
            report_sections.setdefault(rid, []).append(sec)

    # ── Step 6: Build subForms recursively ──
    parent_sub_forms = {}  # parentFormId -> [sub_forms]
    for sf in sub_forms:
        pid = sf.get("parentFormId")
        if pid:
            sfid = sf.get("id")
            if sfid in form_sections:
                sf["sections"] = sorted(form_sections[sfid], key=lambda x: x.get("order", 0))
            if sfid in form_events:
                sf["events"] = form_events[sfid]
                sf["eventIds"] = [e.get("id") for e in sf["events"] if e.get("id")]
            parent_sub_forms.setdefault(pid, []).append(sf)

    # ── Step 7: Build subReports recursively ──
    parent_sub_reports = {}  # parentReportId -> [sub_reports]
    for sr in sub_reports:
        pid = sr.get("parentReportId")
        if pid:
            srid = sr.get("id")
            if srid in report_sections:
                sr["sections"] = sorted(report_sections[srid], key=lambda x: x.get("order", 0))
            if srid in form_events:
                sr["events"] = form_events[srid]
            parent_sub_reports.setdefault(pid, []).append(sr)

    # ── Step 8: Build complete forms ──
    built_forms = {}
    for form in forms:
        fid = form.get("id")
        if fid in form_sections:
            form["sections"] = sorted(form_sections[fid], key=lambda x: x.get("order", 0))
        else:
            form.setdefault("sections", [])
        if fid in form_events:
            form["events"] = form_events[fid]
            form["eventIds"] = [e.get("id") for e in form["events"] if e.get("id")]
        else:
            form.setdefault("events", [])
        if fid in parent_sub_forms:
            form["subForms"] = parent_sub_forms[fid]
            form["subFormIds"] = [sf.get("id") for sf in form["subForms"] if sf.get("id")]
        else:
            form.setdefault("subForms", [])
        built_forms[fid] = form

    # ── Step 9: Build complete reports ──
    built_reports = {}
    for report in reports:
        rid = report.get("id")
        if rid in report_sections:
            report["sections"] = sorted(report_sections[rid], key=lambda x: x.get("order", 0))
        else:
            report.setdefault("sections", [])
        if rid in form_events:
            report["events"] = form_events[rid]
            report["eventIds"] = [e.get("id") for e in report["events"] if e.get("id")]
        else:
            report.setdefault("events", [])
        if rid in parent_sub_reports:
            report["subReports"] = parent_sub_reports[rid]
            report["subReportIds"] = [sr.get("id") for sr in report["subReports"] if sr.get("id")]
        else:
            report.setdefault("subReports", [])
        built_reports[rid] = report

    # ── Step 10: Build pages with nested forms and reports ──
    built_pages = []
    used_form_ids = set()
    used_report_ids = set()
    all_used_dashboard_ids = set()

    for page in pages:
        page_form_ids = page.get("formIds", [])
        page_report_ids = page.get("reportIds", [])
        page_dashboard_ids = page.get("dashboardIds", [])

        # Also try to find forms/reports/dashboards by applicationId match
        app_id = page.get("applicationId")

        # Nest full form objects
        page_forms = []
        for fid in page_form_ids:
            if fid in built_forms:
                page_forms.append(built_forms[fid])
                used_form_ids.add(fid)
        # If no formIds specified, attach forms matching same applicationId
        if not page_forms and app_id:
            for fid, form in built_forms.items():
                if form.get("applicationId") == app_id and fid not in used_form_ids:
                    page_forms.append(form)
                    used_form_ids.add(fid)
        page["forms"] = page_forms

        # Nest full report objects
        page_reports = []
        for rid in page_report_ids:
            if rid in built_reports:
                page_reports.append(built_reports[rid])
                used_report_ids.add(rid)
        if not page_reports and app_id:
            for rid, report in built_reports.items():
                if report.get("applicationId") == app_id and rid not in used_report_ids:
                    page_reports.append(report)
                    used_report_ids.add(rid)
        page["reports"] = page_reports

        # Nest full dashboard objects
        page_dashboards = []
        for did in page_dashboard_ids:
            if did in dashboard_map:
                page_dashboards.append(dashboard_map[did])
                all_used_dashboard_ids.add(did)
        if not page_dashboards and app_id:
            for did, db in dashboard_map.items():
                if db.get("applicationId") == app_id and did not in all_used_dashboard_ids:
                    page_dashboards.append(db)
                    all_used_dashboard_ids.add(did)
        page["dashboards"] = page_dashboards
        # Remove stale singular 'dashboard' key if present
        page.pop("dashboard", None)

        built_pages.append(page)

    # Find a default role array to use for synthetic containers
    default_roles = []
    for item in forms + reports + dashboards:
        r = item.get("accessControl", {}).get("roles", [])
        if r:
            default_roles = r
            break

    # If no pages exist, create a synthetic one
    if not built_pages and (built_forms or built_reports):
        app_id = None
        if applications:
            app_id = applications[0].get("id")
        elif built_forms:
            app_id = list(built_forms.values())[0].get("applicationId")

        now = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        synthetic_page = {
            "id": "auto-generated-page",
            "name": "Main Page",
            "alias": "main-page",
            "description": "Auto-generated page containing all forms and reports",
            "applicationId": app_id,
            "formIds": list(built_forms.keys()),
            "reportIds": list(built_reports.keys()),
            "dashboardIds": list(dashboard_map.keys()),
            "forms": list(built_forms.values()),
            "reports": list(built_reports.values()),
            "dashboards": list(dashboard_map.values()),
            "displayHeader": True,
            "deleted": False,
            "accessControl": {"roles": default_roles, "userGroups": [], "users": []},
            "createdAt": now,
            "modifiedAt": now,
            "createdBy": "",
            "modifiedBy": "",
            "properties": {
                "positions": []
            }
        }
        # Build positions from forms and reports
        order = 1
        for fid in built_forms:
            synthetic_page["properties"]["positions"].append({
                "width": "w-full", "id": fid, "type": "form", "order": order
            })
            order += 1
        for rid in built_reports:
            synthetic_page["properties"]["positions"].append({
                "width": "w-full", "id": rid, "type": "report", "order": order
            })
            order += 1
        for did in dashboard_map:
            synthetic_page["properties"]["positions"].append({
                "width": "w-full", "id": did, "type": "dashboard", "order": order
            })
            order += 1
        built_pages.append(synthetic_page)

    # ── Step 11: Build application wrapper ──
    # Format: {"application": {..., "pages": [...]}}
    if applications:
        app_obj = applications[0]
    else:
        # Create synthetic application from common applicationId
        app_id = None
        for form in forms:
            if form.get("applicationId"):
                app_id = form["applicationId"]
                break
        if not app_id:
            for report in reports:
                if report.get("applicationId"):
                    app_id = report["applicationId"]
                    break
        now = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        app_obj = {
            "id": app_id or "auto-generated-app",
            "name": "Application",
            "alias": "application",
            "description": "Auto-generated application wrapper",
            "deleted": False,
            "accessControl": {"roles": default_roles, "userGroups": [], "users": []},
            "properties": {},
            "createdAt": now,
            "modifiedAt": now,
            "createdBy": "",
            "modifiedBy": ""
        }

    app_obj["pages"] = built_pages

    # Attach ONLY orphan dashboards (not already in a page) and menus at application level
    orphan_dashboards = [d for d in dashboards if d.get("id") not in all_used_dashboard_ids]
    if orphan_dashboards:
        app_obj["dashboards"] = orphan_dashboards
    if menus:
        app_obj["menus"] = menus

    return {"application": app_obj}


# ── Routes ────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/keys")
def get_keys():
    try:
        r = _get_redis()
        keys = sorted(r.keys("metadata:*"))
        return jsonify({"keys": keys})
    except Exception as e:
        return jsonify({"error": str(e), "keys": []})


@app.route("/api/metadata/<path:key>")
def get_metadata(key):
    """Returns reassembled nested metadata hierarchy from flat blocks."""
    try:
        r = _get_redis()
        val = r.get(key)
        if not val:
            return jsonify({"found": False, "message": "Key not found."})
        data = json.loads(val)

        # If data is already nested (has "application" key), return as-is
        if isinstance(data, dict) and "application" in data:
            return jsonify({"found": True, "content": data})

        # If data is a flat list of {type, data} blocks, reassemble
        if isinstance(data, list) and data and isinstance(data[0], dict) and "type" in data[0]:
            is_valid, validation_errors = validate_blocks(data)
            if not is_valid:
                return jsonify({
                    "found": True,
                    "valid": False,
                    "error": "Schema validation failed",
                    "validation_errors": validation_errors,
                    "flat_block_count": len(data)
                }), 400

            nested = reassemble(data)
            return jsonify({
                "found": True,
                "valid": True,
                "content": nested,
                "flat_block_count": len(data)
            })

        # Fallback: return raw
        return jsonify({"found": True, "content": data})
    except Exception as e:
        return jsonify({"found": False, "message": "Redis error: " + str(e)})


@app.route("/api/metadata-raw/<path:key>")
def get_metadata_raw(key):
    """Returns the raw flat blocks as stored in Redis (for debugging)."""
    try:
        r = _get_redis()
        val = r.get(key)
        if not val:
            return jsonify({"found": False, "message": "Key not found."})
        data = json.loads(val)
        return jsonify({"found": True, "content": data})
    except Exception as e:
        return jsonify({"found": False, "message": "Redis error: " + str(e)})


# ── Entry point ───────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Creviz Metadata Viewer -> http://localhost:5001")
    print(f"Redis target           -> {REDIS_HOST}:{REDIS_PORT}")
    print(f"GET /api/metadata/<key>     -> nested hierarchy")
    print(f"GET /api/metadata-raw/<key> -> raw flat blocks")
    app.run(host="0.0.0.0", port=5001, debug=False)
