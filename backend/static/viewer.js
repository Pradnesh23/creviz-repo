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

// ── Fetch & render ──────────────────────────────────────────
async function fetchMetadata() {
    const key = document.getElementById('manual-key').value.trim();
    if (!key) return;
    document.getElementById('tree-root').innerHTML =
        '<div style="color:#fff">Loading…</div>';
    document.getElementById('copy-btn').style.display = 'none';

    try {
        const res  = await fetch('/api/metadata/' + encodeURIComponent(key));
        const json = await res.json();
        if (!json.found) {
            document.getElementById('tree-root').innerHTML =
                `<div style="color:red">Error: ${json.message}</div>`;
            return;
        }

        const nested = nestJsonData(json.content);
        currentJsonData = json.content; // Save the raw/reassembled JSON for copying
        document.getElementById('copy-btn').style.display = 'inline-block';
        document.getElementById('copy-btn').textContent = 'Copy JSON';

        document.getElementById('tree-root').innerHTML = renderJSON(nested, true);

        // wire up all collapse toggles
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

    } catch (e) {
        document.getElementById('tree-root').innerHTML =
            '<div style="color:red">Error loading data</div>';
    }
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

        // build a human-readable collapsed preview
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
