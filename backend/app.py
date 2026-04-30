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
            nested = reassemble(data)
            return jsonify({
                "found": True,
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
