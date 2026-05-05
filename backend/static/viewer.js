// ── Boot: populate key dropdown from Redis ──────────────────
window.addEventListener('DOMContentLoaded', async () => {
    try {
        const res  = await fetch('/api/keys');
        const data = await res.json();
        const sel  = document.getElementById('key-select');
        if (data.keys) {
            data.keys.forEach(k => {
                const opt = document.createElement('option');
                opt.value = k;
                opt.textContent = k;
                sel.appendChild(opt);
            });
        }
    } catch (e) { console.error(e); }
});

document.getElementById('key-select').addEventListener('change', e => {
    if (e.target.value) document.getElementById('manual-key').value = e.target.value;
});

let currentJsonData = null;

// ── UI helpers ───────────────────────────────────────────────
function hidePanels() {
    document.getElementById('validation-banner').style.display = 'none';
    document.getElementById('validation-errors').style.display = 'none';
    document.getElementById('block-stats').style.display = 'none';
    document.getElementById('copy-btn').style.display = 'none';
}

function showValidBanner(blockCount) {
    const banner = document.getElementById('validation-banner');
    banner.className = 'validation-banner valid';
    banner.style.display = 'flex';
    banner.innerHTML = `
        <span class="icon">✅</span>
        <div class="banner-content">
            <div>Schema Validation Passed</div>
            <div class="banner-subtitle">All ${blockCount} blocks comply with Creviz production schema</div>
        </div>
    `;
}

function showInvalidBanner(errorCount, blockCount) {
    const banner = document.getElementById('validation-banner');
    banner.className = 'validation-banner invalid';
    banner.style.display = 'flex';
    banner.innerHTML = `
        <span class="icon">❌</span>
        <div class="banner-content">
            <div>Schema Validation Failed — ${errorCount} error${errorCount > 1 ? 's' : ''}</div>
            <div class="banner-subtitle">${blockCount} blocks checked against Creviz production schema</div>
        </div>
    `;
}

function showValidationErrors(errors) {
    const panel = document.getElementById('validation-errors');
    panel.style.display = 'block';

    // Layer color map
    const layerColors = {
        'SCHEMA': '#ef4444',
        'UUID':   '#f59e0b',
        'ACCESS': '#f97316',
        'XREF':   '#8b5cf6',
        'STRUCT': '#ec4899',
    };

    const errorItems = errors.map(err => {
        // Parse: [LAYER] [type] (id: xxx) - message
        const match = err.match(/^\[(\w+)\]\s*\[(\w+)\]\s*\(id:\s*([^)]+)\)\s*-\s*(.+)$/);
        if (match) {
            const layer = match[1];
            const color = layerColors[layer] || '#ef4444';
            return `<div class="error-item" style="border-left-color:${color}">
                <span style="color:${color};font-weight:700;font-size:10px;text-transform:uppercase;letter-spacing:0.5px">${layer}</span>
                <span class="error-type">${match[2]}</span>
                <span style="color:#94a3b8"> (${match[3]})</span> —
                ${escHtml(match[4])}
            </div>`;
        }
        // Fallback: [LAYER] message (STRUCT errors without id)
        const structMatch = err.match(/^\[(\w+)\]\s*(.+)$/);
        if (structMatch) {
            const layer = structMatch[1];
            const color = layerColors[layer] || '#ef4444';
            return `<div class="error-item" style="border-left-color:${color}">
                <span style="color:${color};font-weight:700;font-size:10px;text-transform:uppercase;letter-spacing:0.5px">${layer}</span>
                ${escHtml(structMatch[2])}
            </div>`;
        }
        return `<div class="error-item">${escHtml(err)}</div>`;
    }).join('');

    // Count by layer
    const layerCounts = {};
    errors.forEach(e => {
        const m = e.match(/^\[(\w+)\]/);
        if (m) layerCounts[m[1]] = (layerCounts[m[1]] || 0) + 1;
    });
    const layerBadges = Object.entries(layerCounts).map(([layer, count]) => {
        const color = layerColors[layer] || '#ef4444';
        return `<span style="display:inline-block;padding:2px 8px;border-radius:12px;font-size:10px;font-weight:600;background:${color}20;border:1px solid ${color}50;color:${color};margin-left:6px">${layer}: ${count}</span>`;
    }).join('');

    panel.innerHTML = `
        <div class="error-header">
            <span>🔍 Validation Errors (${errors.length}) ${layerBadges}</span>
            <span class="error-toggle" onclick="toggleErrors()">Collapse</span>
        </div>
        <div id="error-list">${errorItems}</div>
    `;
}

let errorsCollapsed = false;
function toggleErrors() {
    errorsCollapsed = !errorsCollapsed;
    const list = document.getElementById('error-list');
    const toggle = document.querySelector('.error-toggle');
    if (errorsCollapsed) {
        list.style.display = 'none';
        toggle.textContent = 'Expand';
    } else {
        list.style.display = 'block';
        toggle.textContent = 'Collapse';
    }
}

function showBlockStats(data, blockCount) {
    const statsEl = document.getElementById('block-stats');

    // If we have raw blocks (validation failed path), extract types from the raw data
    // If we have nested content, extract types from the tree
    let types = [];
    if (Array.isArray(data)) {
        const typeCounts = {};
        data.forEach(b => {
            const t = b.type || 'unknown';
            typeCounts[t] = (typeCounts[t] || 0) + 1;
        });
        types = Object.entries(typeCounts);
    }

    let badges = types.map(([t, c]) =>
        `<span class="stat-badge intent">${t} × ${c}</span>`
    ).join('');

    statsEl.style.display = 'flex';
    statsEl.innerHTML = `
        <div class="stat">
            <span class="stat-label">Blocks:</span>
            <span class="stat-value">${blockCount}</span>
        </div>
        <div class="stat">
            <span class="stat-label">Intents:</span>
            ${badges || '<span class="stat-value">—</span>'}
        </div>
    `;
}

// ── Fetch & render ──────────────────────────────────────────
async function fetchMetadata() {
    const key = document.getElementById('manual-key').value.trim();
    if (!key) return;

    hidePanels();
    errorsCollapsed = false;
    document.getElementById('tree-root').innerHTML =
        '<div style="color:#fff;text-align:center;padding:40px;">Loading…</div>';

    try {
        const res  = await fetch('/api/metadata/' + encodeURIComponent(key));
        const json = await res.json();

        if (!json.found) {
            document.getElementById('tree-root').innerHTML =
                `<div style="color:red;text-align:center;padding:40px;">Error: ${json.message}</div>`;
            return;
        }

        const blockCount = json.flat_block_count || '?';

        // ── Validation FAILED ──
        if (json.valid === false && json.validation_errors) {
            showInvalidBanner(json.validation_errors.length, blockCount);
            showValidationErrors(json.validation_errors);

            // Still fetch raw blocks to show stats
            try {
                const rawRes = await fetch('/api/metadata-raw/' + encodeURIComponent(key));
                const rawJson = await rawRes.json();
                if (rawJson.found && Array.isArray(rawJson.content)) {
                    showBlockStats(rawJson.content, blockCount);
                }
            } catch (e) { /* ignore */ }

            document.getElementById('tree-root').innerHTML =
                '<div style="color:#94a3b8;text-align:center;padding:40px;">Fix validation errors above to view nested structure</div>';
            return;
        }

        // ── Validation PASSED ──
        showValidBanner(blockCount);

        // Fetch raw blocks for stats
        try {
            const rawRes = await fetch('/api/metadata-raw/' + encodeURIComponent(key));
            const rawJson = await rawRes.json();
            if (rawJson.found && Array.isArray(rawJson.content)) {
                showBlockStats(rawJson.content, blockCount);
            }
        } catch (e) { /* ignore */ }

        const nested = nestJsonData(json.content);
        currentJsonData = json.content;
        document.getElementById('copy-btn').style.display = 'inline-block';
        document.getElementById('copy-btn').textContent = 'Copy JSON';

        document.getElementById('tree-root').innerHTML = renderJSON(nested, true);
        wireToggles();

    } catch (e) {
        document.getElementById('tree-root').innerHTML =
            '<div style="color:red;text-align:center;padding:40px;">Error loading data</div>';
    }
}

function wireToggles() {
    document.querySelectorAll('.json-toggle').forEach(el => {
        el.addEventListener('click', function (e) {
            e.stopPropagation();
            this.classList.toggle('collapsed');
            let sib = this.nextElementSibling;
            while (sib) {
                if (sib.classList.contains('json-dict') ||
                    sib.classList.contains('json-array')) {
                    sib.classList.toggle('collapsed-content');
                    break;
                }
                sib = sib.nextElementSibling;
            }
        });
    });
}

async function copyMetadata() {
    if (!currentJsonData) return;
    try {
        const jsonString = JSON.stringify(currentJsonData, null, 2);
        await navigator.clipboard.writeText(jsonString);
        const btn = document.getElementById('copy-btn');
        btn.textContent = 'Copied!';
        setTimeout(() => { btn.textContent = 'Copy JSON'; }, 2000);
    } catch (e) {
        console.error('Failed to copy text: ', e);
        alert('Failed to copy JSON to clipboard.');
    }
}

// ── Nest flat Creviz blocks into a tree ─────────────────────
function nestJsonData(dataArray) {
    if (!Array.isArray(dataArray)) dataArray = [dataArray];

    const idMap = {};
    dataArray.forEach(b => { if (b.data && b.data.id) idMap[b.data.id] = b; });

    const childMap = {};
    dataArray.forEach(block => {
        const d = block.data || {};
        [d.applicationId, d.pageId, d.formId, d.sectionId].forEach(pId => {
            if (pId && idMap[pId]) {
                if (!childMap[pId]) childMap[pId] = [];
                childMap[pId].push(block);
            }
        });
        [d.pageIds, d.formIds, d.sectionIds, d.componentIds].forEach(list => {
            if (Array.isArray(list)) {
                list.forEach(cId => {
                    if (idMap[cId]) {
                        if (!childMap[d.id]) childMap[d.id] = [];
                        if (!childMap[d.id].find(c => c.data.id === cId))
                            childMap[d.id].push(idMap[cId]);
                    }
                });
            }
        });
    });

    const allChildren = new Set();
    Object.values(childMap).forEach(ch => ch.forEach(c => allChildren.add(c.data?.id)));

    const roots = dataArray.filter(b => !allChildren.has(b.data?.id));

    function build(block) {
        const obj = JSON.parse(JSON.stringify(block));
        const ch  = childMap[block.data?.id] || [];
        if (ch.length) obj._children = ch.map(c => build(c));
        return obj;
    }
    return roots.map(r => build(r));
}

// ── Recursive JSON → HTML renderer ─────────────────────────
function renderJSON(data, isLast = true) {
    if (typeof data === 'string')
        return `<span class="json-string">"${esc(data)}"</span>`;
    if (typeof data === 'number')
        return `<span class="json-number">${data}</span>`;
    if (typeof data === 'boolean')
        return `<span class="json-boolean">${data}</span>`;
    if (data === null)
        return `<span class="json-null">null</span>`;

    const comma = isLast ? '' : ',';

    if (Array.isArray(data)) {
        if (!data.length) return `[]${comma}`;
        const preview = `Array[${data.length}]`;
        let html = `<span class="json-toggle"></span>[` +
                    `<span class="json-collapsed-preview"> // ${preview}</span>` +
                    `<div class="json-array">`;
        data.forEach((item, i) => {
            html += `<div class="json-item">${renderJSON(item, i === data.length - 1)}</div>`;
        });
        return html + `</div>]${comma}`;
    }

    if (typeof data === 'object') {
        const keys = Object.keys(data);
        if (!keys.length) return `{}${comma}`;

        const parts = [];
        if (data.type) parts.push(data.type.toUpperCase());
        if (keys.includes('pages')) parts.push('Metadata Payload');
        if (data.name) parts.push(data.name);
        else if (data.title) parts.push(data.title);
        else if (data.label) parts.push(data.label);
        else if (data.data && typeof data.data === 'object') {
            if (data.data.name) parts.push(data.data.name);
            else if (data.data.title) parts.push(data.data.title);
        }
        const preview = parts.length ? parts.join(': ') : `Object{${keys.length}}`;

        let html = `<span class="json-toggle"></span>{` +
                    `<span class="json-collapsed-preview"> // ${preview}</span>` +
                    `<div class="json-dict">`;
        keys.forEach((k, i) => {
            html += `<div class="json-item">` +
                    `<span class="json-key">"${k}"</span>: ` +
                    `${renderJSON(data[k], i === keys.length - 1)}</div>`;
        });
        return html + `</div>}${comma}`;
    }
    return '';
}

function esc(s) { return s.replace(/\\/g, '\\\\').replace(/"/g, '\\"'); }
function escHtml(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
