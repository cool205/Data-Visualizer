'use strict';

/* ── Helpers ─────────────────────────────────────────────────────────────── */
const $ = id => document.getElementById(id);
const on = (el, ev, fn) => el.addEventListener(ev, fn);

/* ── App state ───────────────────────────────────────────────────────────── */
const state = {
  headers:    [],
  rows:       [],
  hasData:    false,
  activeTab:  'upload',
  extracted:  false,
};

const graphStore = [];

/* ── Refs ────────────────────────────────────────────────────────────────── */
const generateBtn    = $('generate-btn');
const graphGrid      = $('graph-grid');
const resultsEmpty   = $('results-empty');
const resultsCharts  = $('results-charts');
const resultsCount   = $('results-count');
const previewStrip   = $('preview-strip');
const previewHead    = $('preview-head');
const previewBody    = $('preview-body');
const previewMeta    = $('preview-meta');
const previewLabel   = $('preview-label');
const dropZone       = $('drop-zone');
const fileInput      = $('file-input');
const fileBadge      = $('file-badge');
const fileNameEl     = $('file-name');
const sheetsUrl      = $('sheets-url');
const loadSheetsBtn  = $('load-sheets-btn');
const manualHead     = $('manual-head');
const manualBody     = $('manual-body');
const pasteArea      = $('paste-area');
const parseTextBtn   = $('parse-text-btn');
const extractHint    = $('extract-hint');
const spinnerOverlay = $('spinner-overlay');
const spinnerMsg     = $('spinner-msg');
const toast          = $('toast');
const editorOverlay  = $('editor-overlay');
const edClose        = $('ed-close');
const edChartName    = $('ed-chart-name');
const edRefreshStatus= $('ed-refresh-status');
const edImg          = $('ed-img');
const edLoading      = $('ed-loading');
const edTitle        = $('ed-title');
const edXlabel       = $('ed-xlabel');
const edYlabel       = $('ed-ylabel');
const edGrid         = $('ed-grid');
const edLegend       = $('ed-legend');
const edFontsize     = $('ed-fontsize');
const edFontsizeVal  = $('ed-fontsize-val');
const schemeGrid     = $('scheme-grid');
const regenNotice    = $('regen-notice');

let editorCtx  = null;
let refreshTimer = null;

// ─────────────────────────────────────────────────────────────────────────────
// Toast & Spinner
// ─────────────────────────────────────────────────────────────────────────────
let toastTimer;
function showToast(msg, type = '') {
  toast.textContent = msg;
  toast.className = `toast show${type ? ' ' + type : ''}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.className = 'toast'; }, 3500);
}

function showSpinner(msg = 'Generating…') {
  spinnerMsg.textContent = msg;
  spinnerOverlay.classList.remove('hidden');
}
function hideSpinner() { spinnerOverlay.classList.add('hidden'); }

// ─────────────────────────────────────────────────────────────────────────────
// Regen notice
// ─────────────────────────────────────────────────────────────────────────────
function showRegenNotice() {
  if (graphStore.length === 0) return;
  regenNotice.classList.remove('hidden');
  generateBtn.classList.add('pulse');
}
function hideRegenNotice() {
  regenNotice.classList.add('hidden');
  generateBtn.classList.remove('pulse');
}

on($('regen-notice-btn'),   'click', () => generateBtn.click());
on($('regen-notice-close'), 'click', hideRegenNotice);

// ─────────────────────────────────────────────────────────────────────────────
// Data management
// ─────────────────────────────────────────────────────────────────────────────
function setData(headers, rows, wasExtracted = false) {
  state.headers   = headers;
  state.rows      = rows;
  state.hasData   = true;
  state.extracted = wasExtracted;
  renderPreview();
  generateBtn.disabled = false;
  const msg = wasExtracted
    ? `Extracted ${rows.length} rows × ${headers.length} cols from text`
    : `${rows.length} rows × ${headers.length} cols loaded`;
  $('data-status').textContent = msg;
  showRegenNotice();
}

function clearData() {
  state.headers = [];
  state.rows    = [];
  state.hasData = false;
  previewStrip.classList.add('hidden');
  generateBtn.disabled = true;
  generateBtn.classList.remove('pulse');
  $('data-status').textContent = '';
  hideRegenNotice();
}

// ─────────────────────────────────────────────────────────────────────────────
// Preview table
// ─────────────────────────────────────────────────────────────────────────────
function renderPreview() {
  const MAX = 6;
  previewHead.innerHTML = '';
  previewBody.innerHTML = '';

  const tr = document.createElement('tr');
  state.headers.forEach(h => {
    const th = document.createElement('th');
    th.textContent = h;
    tr.appendChild(th);
  });
  previewHead.appendChild(tr);

  state.rows.slice(0, MAX).forEach(row => {
    const r = document.createElement('tr');
    row.forEach(cell => {
      const td = document.createElement('td');
      td.textContent = cell ?? '';
      r.appendChild(td);
    });
    previewBody.appendChild(r);
  });

  previewMeta.textContent =
    `${state.rows.length} rows · ${state.headers.length} cols` +
    (state.rows.length > MAX ? ` (showing ${MAX})` : '');
  previewLabel.textContent = state.extracted ? 'Extracted data' : 'Preview';
  previewStrip.classList.remove('hidden');
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab switching
// ─────────────────────────────────────────────────────────────────────────────
document.querySelectorAll('.tab').forEach(btn => {
  on(btn, 'click', () => {
    document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    $(`pane-${btn.dataset.tab}`).classList.add('active');
    state.activeTab = btn.dataset.tab;
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// File upload
// ─────────────────────────────────────────────────────────────────────────────
function handleFile(file) {
  const fd = new FormData();
  fd.append('file', file);
  showSpinner('Reading your file…');
  fetch('/api/parse', { method: 'POST', body: fd })
    .then(r => r.json())
    .then(data => {
      hideSpinner();
      if (data.error) { showToast(data.error, 'error'); return; }
      fileNameEl.textContent = file.name;
      fileBadge.classList.remove('hidden');
      setData(data.headers, data.rows, data.extracted);
      showToast(data.extracted ? 'Numbers extracted from file!' : 'File loaded successfully!', 'success');
    })
    .catch(() => { hideSpinner(); showToast('Upload failed — try again.', 'error'); });
}

on(dropZone, 'click', () => fileInput.click());
on(fileInput, 'change', () => { if (fileInput.files[0]) handleFile(fileInput.files[0]); });
on(dropZone, 'dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
on(dropZone, 'dragleave', () => dropZone.classList.remove('drag-over'));
on(dropZone, 'drop', e => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
});
on($('remove-file'), 'click', () => {
  fileInput.value = '';
  fileBadge.classList.add('hidden');
  clearData();
});

// ─────────────────────────────────────────────────────────────────────────────
// Google Sheets
// ─────────────────────────────────────────────────────────────────────────────
on(loadSheetsBtn, 'click', () => {
  const url = sheetsUrl.value.trim();
  if (!url) { showToast('Paste a Google Sheets URL first.', 'error'); return; }
  const fd = new FormData();
  fd.append('sheets_url', url);
  showSpinner('Loading from Google Sheets…');
  fetch('/api/parse', { method: 'POST', body: fd })
    .then(r => r.json())
    .then(data => {
      hideSpinner();
      if (data.error) { showToast(data.error, 'error'); return; }
      setData(data.headers, data.rows, false);
      showToast('Google Sheet loaded!', 'success');
    })
    .catch(() => { hideSpinner(); showToast('Could not load sheet — make sure it is shared.', 'error'); });
});

// ─────────────────────────────────────────────────────────────────────────────
// Paste text
// ─────────────────────────────────────────────────────────────────────────────
on(parseTextBtn, 'click', () => {
  const text = pasteArea.value.trim();
  if (!text) { showToast('Paste some text first.', 'error'); return; }
  const fd = new FormData();
  fd.append('raw_text', text);
  showSpinner('Extracting numbers…');
  fetch('/api/parse', { method: 'POST', body: fd })
    .then(r => r.json())
    .then(data => {
      hideSpinner();
      if (data.error) { showToast(data.error, 'error'); return; }
      setData(data.headers, data.rows, true);
      extractHint.textContent = `Found ${data.rows.length} rows × ${data.headers.length} columns.`;
      showToast(`Extracted ${data.rows.length} rows of data!`, 'success');
    })
    .catch(() => { hideSpinner(); showToast('Extraction failed — try again.', 'error'); });
});

// ─────────────────────────────────────────────────────────────────────────────
// Manual table
// ─────────────────────────────────────────────────────────────────────────────
let manualCols = 3;
let manualRows = 6;

function mkHeaderInput(text) {
  const inp = document.createElement('input');
  inp.type = 'text';
  inp.value = text;
  on(inp, 'input', syncManual);
  return inp;
}

function buildManualTable() {
  manualHead.innerHTML = '';
  manualBody.innerHTML = '';
  const trh = document.createElement('tr');
  for (let c = 0; c < manualCols; c++) {
    const th = document.createElement('th');
    th.appendChild(mkHeaderInput(`Col ${c + 1}`));
    trh.appendChild(th);
  }
  manualHead.appendChild(trh);
  for (let r = 0; r < manualRows; r++) addManualRow();
}

function addManualRow(vals) {
  const tr = document.createElement('tr');
  for (let c = 0; c < manualCols; c++) {
    const td = document.createElement('td');
    td.contentEditable = 'true';
    if (vals) td.textContent = vals[c] ?? '';
    on(td, 'input', syncManual);
    tr.appendChild(td);
  }
  manualBody.appendChild(tr);
}

function syncManual() {
  if (state.activeTab !== 'manual') return;
  const headers = Array.from(manualHead.querySelectorAll('input')).map(i => i.value.trim() || '');
  const rows = Array.from(manualBody.rows)
    .map(tr => Array.from(tr.cells).map(td => td.textContent.trim()))
    .filter(r => r.some(c => c !== ''));
  if (rows.length && headers.some(h => h)) {
    state.headers = headers;
    state.rows    = rows;
    state.hasData = true;
    generateBtn.disabled = false;
    $('data-status').textContent = `${rows.length} rows × ${headers.length} cols`;
    showRegenNotice();
  } else {
    state.hasData = false;
    generateBtn.disabled = true;
    $('data-status').textContent = '';
  }
}

on($('add-row-btn'), 'click', () => { addManualRow(); syncManual(); });
on($('add-col-btn'), 'click', () => {
  manualCols++;
  const th = document.createElement('th');
  th.appendChild(mkHeaderInput(`Col ${manualCols}`));
  manualHead.rows[0].appendChild(th);
  Array.from(manualBody.rows).forEach(tr => {
    const td = document.createElement('td');
    td.contentEditable = 'true';
    on(td, 'input', syncManual);
    tr.appendChild(td);
  });
  syncManual();
});
on($('del-row-btn'), 'click', () => {
  if (manualBody.rows.length > 1) { manualBody.deleteRow(manualBody.rows.length - 1); syncManual(); }
});
on($('del-col-btn'), 'click', () => {
  if (manualCols > 1) {
    manualCols--;
    manualHead.rows[0].deleteCell(manualCols);
    Array.from(manualBody.rows).forEach(tr => tr.deleteCell(manualCols));
    syncManual();
  }
});
on($('clear-table-btn'), 'click', () => {
  manualCols = 3; manualRows = 6;
  buildManualTable();
  clearData();
});

// ─────────────────────────────────────────────────────────────────────────────
// Generate
// ─────────────────────────────────────────────────────────────────────────────
on(generateBtn, 'click', () => {
  if (state.activeTab === 'manual') {
    syncManual();
    if (!state.hasData) { showToast('Enter some data in the table first.', 'error'); return; }
  }
  if (!state.hasData) { showToast('Load some data first!', 'error'); return; }

  hideRegenNotice();
  showSpinner('Creating your charts…');
  graphGrid.innerHTML = '';

  fetch('/api/generate', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ headers: state.headers, rows: state.rows }),
  })
    .then(r => r.json())
    .then(data => {
      hideSpinner();
      if (data.error) { showToast(data.error, 'error'); return; }
      graphStore.length = 0;
      data.graphs.forEach((g, i) => graphStore.push({
        idx:    i,
        name:   g.name,
        type:   g.type,
        config: g.config,
        image:  g.image,
        options: {
          color_scheme: 'default',
          bg_style:     'white',
          show_grid:    false,
          show_legend:  true,
          font_size:    10,
          title: '', xlabel: '', ylabel: '',
        },
      }));
      renderGraphCards();
      resultsEmpty.classList.add('hidden');
      resultsCharts.classList.remove('hidden');
      resultsCount.textContent = data.graphs.length;
      // Smooth scroll to results
      resultsCharts.scrollIntoView({ behavior: 'smooth', block: 'start' });
      showToast(`${data.graphs.length} chart${data.graphs.length !== 1 ? 's' : ''} created — click any to edit!`, 'success');
    })
    .catch(() => { hideSpinner(); showToast('Something went wrong — try again.', 'error'); });
});

// ─────────────────────────────────────────────────────────────────────────────
// Chart metadata
// ─────────────────────────────────────────────────────────────────────────────
const TYPE_ICON = {
  bar:           '▊',  horizontal_bar: '▬',  dot_plot:    '⊸',
  error_bar:     '⊕',  pareto:         '⟁',  waterfall:   '⬦',
  pie:           '◔',  donut:          '◎',  scatter:     '⊹',
  regression:    '⤢',  bubble:         '⊚',  hexbin:      '⬡',
  filled_area:   '◭',  line:           '↗',  multi_line:  '⟋',
  area:          '◭',  step:           '⌐',  dual_axis:   '⇌',
  moving_avg:    '∿',  histogram:      '▮',  kde:         '⌇',
  cumulative:    '⌀',  box:            '◫',  box_cat:     '◫',
  violin:        '⌓',  violin_cat:     '⌓',  strip:       '⠿',
  stem:          '⌁',  heatmap:        '▦',  heatmap_cat: '▦',
  grouped_bar:   '▊',  stacked_bar:    '⊟',  radar:       '✦',
  pair_scatter:  '⊞',
};

const TYPE_DESC = {
  bar:            'Compare amounts across different groups',
  horizontal_bar: 'Same as bar chart — easier to read long labels',
  line:           'Show how something changes over time',
  scatter:        'Spot the relationship between two numbers',
  pie:            'Show how a total is split into parts',
  histogram:      'See how your data is spread out',
  area:           'Like a line chart, with the area filled in',
  multi_line:     'Track multiple things changing over time',
  box:            'Show min, max, average and spread',
  box_cat:        'Compare the spread of data across groups',
  grouped_bar:    'Compare multiple values side-by-side per group',
  stacked_bar:    'Show totals made up of multiple parts',
  donut:          'Like a pie chart with a center label',
  regression:     'Find the trend line between two measurements',
  bubble:         'Scatter plot where bubble size shows a third value',
  hexbin:         'Show where data points are most crowded',
  filled_area:    'Compare two measurements with shaded gap',
  step:           'Show data that changes in steps (not smoothly)',
  dual_axis:      'Plot two very different measurements on one chart',
  moving_avg:     'Smooth out noisy data to see the real trend',
  kde:            'Smooth curve showing where values are most common',
  cumulative:     'Show what percent of data falls below each value',
  violin:         'Show data distribution as a mirrored shape',
  violin_cat:     'Compare data distributions across groups',
  strip:          'Show every single data point per group',
  stem:           'Show individual data values as vertical lines',
  heatmap:        'Color grid showing how columns relate to each other',
  heatmap_cat:    'Color grid comparing groups across measurements',
  pareto:         'Bar chart with a cumulative percentage line',
  waterfall:      'Show how a total builds up step by step',
  radar:          'Compare multiple categories in a spider-web shape',
  pair_scatter:   'Compare every pair of columns at once',
  dot_plot:       'Clean version of a bar chart using dots',
  error_bar:      'Bar chart showing average plus uncertainty range',
};

// Chart type → badge CSS class
const TYPE_BADGE = {
  bar: 'badge-bar', horizontal_bar: 'badge-bar', grouped_bar: 'badge-bar',
  stacked_bar: 'badge-bar', dot_plot: 'badge-bar', error_bar: 'badge-bar',
  pareto: 'badge-bar', waterfall: 'badge-bar',
  line: 'badge-line', multi_line: 'badge-line', area: 'badge-line',
  filled_area: 'badge-line', step: 'badge-line', dual_axis: 'badge-line',
  moving_avg: 'badge-line',
  pie: 'badge-pie', donut: 'badge-pie',
  scatter: 'badge-scatter', regression: 'badge-scatter', bubble: 'badge-scatter',
  hexbin: 'badge-scatter',
  histogram: 'badge-dist', kde: 'badge-dist', cumulative: 'badge-dist',
  box: 'badge-dist', box_cat: 'badge-dist', violin: 'badge-dist',
  violin_cat: 'badge-dist', strip: 'badge-dist', stem: 'badge-dist',
  heatmap: 'badge-multi', heatmap_cat: 'badge-multi', radar: 'badge-multi',
  pair_scatter: 'badge-multi',
};

// ─────────────────────────────────────────────────────────────────────────────
// Graph cards
// ─────────────────────────────────────────────────────────────────────────────
function renderGraphCards() {
  graphGrid.innerHTML = '';
  graphStore.forEach(g => {
    const card = document.createElement('div');
    card.className = 'graph-card';
    card.dataset.idx = g.idx;
    const badge = TYPE_BADGE[g.type] || 'badge-other';
    const desc  = TYPE_DESC[g.type]  || '';
    const icon  = TYPE_ICON[g.type]  || '◈';
    card.innerHTML = `
      <div class="graph-card-header">
        <div class="graph-card-title">
          <span>${icon}</span>
          <span>${g.name}</span>
        </div>
        <span class="type-badge ${badge}">${g.type.replace(/_/g, ' ')}</span>
      </div>
      ${desc ? `<div class="card-desc">${desc}</div>` : ''}
      <img src="data:image/png;base64,${g.image}" alt="${g.name}" loading="lazy" />
      <div class="graph-card-footer">
        <span class="card-hint">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/>
            <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/>
          </svg>
          Click to edit &amp; download
        </span>
        <span class="card-best">Best match</span>
      </div>`;
    on(card, 'click', () => openEditor(g.idx));
    graphGrid.appendChild(card);
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Color scheme swatches
// ─────────────────────────────────────────────────────────────────────────────
const SCHEME_COLORS = {
  default:    ['#4361ee', '#06d6a0', '#ffd166'],
  vibrant:    ['#ff6b6b', '#feca57', '#48dbfb'],
  pastel:     ['#a8dadc', '#ffd6a5', '#fdffb6'],
  cool:       ['#03045e', '#0096c7', '#90e0ef'],
  warm:       ['#d62828', '#f77f00', '#fcbf49'],
  green:      ['#1b4332', '#52b788', '#b7e4c7'],
  monochrome: ['#212529', '#6c757d', '#dee2e6'],
  sunset:     ['#f72585', '#7209b7', '#4361ee'],
};

function buildSchemeGrid(currentScheme) {
  schemeGrid.innerHTML = '';
  Object.entries(SCHEME_COLORS).forEach(([key, colors]) => {
    const sw = document.createElement('div');
    sw.className = `scheme-swatch${key === currentScheme ? ' active' : ''}`;
    sw.dataset.scheme = key;
    sw.innerHTML = `
      <div class="scheme-dots">
        ${colors.map(c => `<span style="background:${c}"></span>`).join('')}
      </div>
      <span class="scheme-name">${key}</span>`;
    on(sw, 'click', () => {
      document.querySelectorAll('.scheme-swatch').forEach(s => s.classList.remove('active'));
      sw.classList.add('active');
      if (editorCtx) {
        graphStore[editorCtx.idx].options.color_scheme = key;
        scheduleRefresh();
      }
    });
    schemeGrid.appendChild(sw);
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Editor open / close
// ─────────────────────────────────────────────────────────────────────────────
function openEditor(idx) {
  const g = graphStore[idx];
  editorCtx = g;

  edChartName.textContent = g.name;
  edImg.src = `data:image/png;base64,${g.image}`;

  edTitle.value        = g.options.title   || '';
  edXlabel.value       = g.options.xlabel  || '';
  edYlabel.value       = g.options.ylabel  || '';
  edGrid.checked       = g.options.show_grid;
  edLegend.checked     = g.options.show_legend;
  edFontsize.value     = g.options.font_size;
  edFontsizeVal.textContent = g.options.font_size;

  document.querySelectorAll('.bg-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.bg === g.options.bg_style);
  });

  buildSchemeGrid(g.options.color_scheme);
  editorOverlay.classList.remove('hidden');
  document.body.style.overflow = 'hidden';
}

on(edClose, 'click', () => {
  editorOverlay.classList.add('hidden');
  document.body.style.overflow = '';
  editorCtx = null;
  clearTimeout(refreshTimer);
});

// ─────────────────────────────────────────────────────────────────────────────
// Editor live refresh (debounced 500ms)
// ─────────────────────────────────────────────────────────────────────────────
function scheduleRefresh() {
  clearTimeout(refreshTimer);
  edRefreshStatus.textContent = 'Updating…';
  refreshTimer = setTimeout(doRefresh, 500);
}

async function doRefresh() {
  if (!editorCtx) return;
  const g = graphStore[editorCtx.idx];
  edLoading.classList.remove('hidden');
  try {
    const resp = await fetch('/api/customize', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        headers: state.headers,
        rows:    state.rows,
        config:  g.config,
        options: g.options,
      }),
    });
    const data = await resp.json();
    if (data.error) { showToast(data.error, 'error'); }
    else {
      g.image = data.image;
      edImg.src = `data:image/png;base64,${data.image}`;
      const card = document.querySelector(`.graph-card[data-idx="${g.idx}"] img`);
      if (card) card.src = edImg.src;
      edRefreshStatus.textContent = 'Updated';
      setTimeout(() => { edRefreshStatus.textContent = ''; }, 1500);
    }
  } catch {
    showToast('Refresh failed.', 'error');
  } finally {
    edLoading.classList.add('hidden');
  }
}

function readEditorOptions() {
  if (!editorCtx) return;
  const g = graphStore[editorCtx.idx];
  g.options.title       = edTitle.value;
  g.options.xlabel      = edXlabel.value;
  g.options.ylabel      = edYlabel.value;
  g.options.show_grid   = edGrid.checked;
  g.options.show_legend = edLegend.checked;
  g.options.font_size   = parseInt(edFontsize.value, 10);
  scheduleRefresh();
}

on(edTitle,    'input', readEditorOptions);
on(edXlabel,   'input', readEditorOptions);
on(edYlabel,   'input', readEditorOptions);
on(edGrid,     'change', readEditorOptions);
on(edLegend,   'change', readEditorOptions);
on(edFontsize, 'input', () => {
  edFontsizeVal.textContent = edFontsize.value;
  readEditorOptions();
});

document.querySelectorAll('.bg-btn').forEach(btn => {
  on(btn, 'click', () => {
    document.querySelectorAll('.bg-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    if (editorCtx) {
      graphStore[editorCtx.idx].options.bg_style = btn.dataset.bg;
      scheduleRefresh();
    }
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Download
// ─────────────────────────────────────────────────────────────────────────────
document.querySelectorAll('.dl-btn').forEach(btn => {
  on(btn, 'click', async () => {
    if (!editorCtx) return;
    const g = graphStore[editorCtx.idx];
    const fmt = btn.dataset.fmt;
    btn.style.opacity = '0.5';
    btn.style.pointerEvents = 'none';
    try {
      const resp = await fetch('/api/download', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          headers: state.headers,
          rows:    state.rows,
          config:  g.config,
          options: g.options,
          format:  fmt,
          name:    g.name,
        }),
      });
      if (!resp.ok) {
        const err = await resp.json();
        showToast(err.error || 'Download failed.', 'error');
        return;
      }
      const blob = await resp.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href     = url;
      a.download = `${g.name.replace(/\s+/g, '_')}.${fmt}`;
      a.click();
      URL.revokeObjectURL(url);
      showToast(`Downloaded as ${fmt.toUpperCase()}!`, 'success');
    } catch {
      showToast('Download failed — try again.', 'error');
    } finally {
      btn.style.opacity = '';
      btn.style.pointerEvents = '';
    }
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Init
// ─────────────────────────────────────────────────────────────────────────────
buildManualTable();
generateBtn.disabled = true;
