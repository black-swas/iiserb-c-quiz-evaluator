/* C Lab Quiz Evaluator — single-page UI. Plain JavaScript, no dependencies.
 * Security note: every piece of server/student-supplied text is inserted with textContent (via h()),
 * never innerHTML, so file names, comments or code cannot inject markup. */
(() => {
  'use strict';

  // ------------------------------------------------------------------ helpers
  const $ = (id) => document.getElementById(id);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const natural = (a, b) => String(a).localeCompare(String(b), undefined, { numeric: true });

  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    if (attrs) {
      for (const [key, value] of Object.entries(attrs)) {
        if (value === null || value === undefined || value === false) continue;
        if (key === 'class') el.className = value;
        else if (key === 'text') el.textContent = value;
        else if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2), value);
        else el.setAttribute(key, value === true ? '' : value);
      }
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      el.append(child.nodeType ? child : document.createTextNode(String(child)));
    }
    return el;
  }

  function fmtBytes(n) {
    if (n < 1024) return `${n} B`;
    if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / 1048576).toFixed(1)} MB`;
  }

  let toastTimer = null;
  function toast(message) {
    const el = $('toast');
    el.textContent = message;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 3500);
  }

  function download(filename, text, mime) {
    const url = URL.createObjectURL(new Blob([text], { type: mime }));
    const a = h('a', { href: url, download: filename });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function csvCell(value) {
    let s = value === null || value === undefined ? '' : String(value);
    if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;               // spreadsheet formula injection guard
    return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }
  const toCsv = (rows) => rows.map((r) => r.map(csvCell).join(',')).join('\r\n') + '\r\n';
  const slug = (s) => String(s || 'results').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') || 'results';

  const TAB_LABEL = { RED: 'Needs review', BLUE: 'Creative approach', GREEN: 'Clear', GRAY: 'Unverified' };
  const CHEAT_LABEL = {
    NONE: '', HARDCODED_PRINTF: 'Hard-coded output', SAMPLE_INPUT_SPOOFING: 'Sample-input special-casing',
    DEAD_CODE_PADDING: 'Decoy code', PLAGIARISM_CLONE: 'Strong clone match', PROMPT_INJECTION: 'Text aimed at grader',
    SECURITY_VIOLATION: 'Security violation', RULE_VIOLATION: 'Forbidden construct', COMPILE_ERROR: 'Compile error',
    TIMEOUT: 'Timeout', BROKEN_LOGIC: 'Fails tests', UNSUBMITTED_OR_STUB: 'Empty / unattempted',
  };

  // ------------------------------------------------------------------ state
  const state = {
    config: null,
    token: sessionStorage.getItem('qe_token') || '',
    view: 'setup',
    paper: null, paperText: '', files: [],
    report: null, ta: {}, alias: {},
    ui: { tab: 'triage', q: null, filter: 'RED', search: '', selected: null, anonymize: false },
  };

  // ------------------------------------------------------------------ API
  class ApiError extends Error {
    constructor(message, status) { super(message); this.status = status; }
  }

  function askToken() {
    return new Promise((resolve) => {
      const dialog = $('tokenDialog');
      const input = $('tokenInput');
      input.value = '';
      const onClose = () => {
        dialog.removeEventListener('close', onClose);
        const token = input.value.trim();
        if (dialog.returnValue === 'save' && token) {
          state.token = token;
          sessionStorage.setItem('qe_token', token);
          renderStatusPills();
          resolve(true);
        } else {
          resolve(false);
        }
      };
      dialog.addEventListener('close', onClose);
      dialog.showModal();
      input.focus();
    });
  }

  async function api(path, options = {}, allowRetry = true) {
    const headers = Object.assign({}, options.headers || {});
    if (state.token) headers['X-API-Key'] = state.token;
    let resp;
    try {
      resp = await fetch(path, Object.assign({}, options, { headers }));
    } catch (_err) {
      throw new ApiError('Cannot reach the server. Check your connection and try again.', 0);
    }
    if (resp.status === 401 && allowRetry && (await askToken())) return api(path, options, false);
    if (!resp.ok) {
      let detail = resp.statusText;
      try {
        const body = await resp.json();
        if (typeof body.detail === 'string') detail = body.detail;
        else if (Array.isArray(body.detail)) detail = body.detail.map((d) => d.msg || JSON.stringify(d)).join('; ');
      } catch (_ignored) { /* keep statusText */ }
      throw new ApiError(detail || `Request failed (${resp.status})`, resp.status);
    }
    return resp;
  }

  // ------------------------------------------------------------------ chrome (status pills, header actions, views)
  function renderStatusPills() {
    const box = $('statusPills');
    box.replaceChildren();
    const c = state.config;
    if (!c) {
      box.append(h('span', { class: 'pill pill-warn', text: 'Server unreachable' }));
      return;
    }
    box.append(
      h('span', { class: 'pill ' + (c.sandbox ? 'pill-ok' : 'pill-warn'), text: c.sandbox ? 'Sandbox ready' : 'Sandbox unavailable' }),
      h('span', { class: 'pill ' + (c.llm.available ? 'pill-ok' : ''), text: c.llm.available ? `AI review: ${c.llm.model}` : 'AI review off' }),
    );
    if (c.auth_required) box.append(h('span', { class: 'pill ' + (state.token ? 'pill-ok' : 'pill-warn'), text: state.token ? 'Signed in' : 'Token needed' }));
  }

  function renderHeaderActions() {
    const box = $('headerActions');
    box.replaceChildren();
    if (state.view !== 'results') return;
    box.append(
      h('label', { class: 'pill pill-check' }, h('input', {
        type: 'checkbox', checked: state.ui.anonymize ? true : null,
        onchange: (e) => { state.ui.anonymize = e.target.checked; renderTab(); },
      }), ' Hide student ids'),
      h('button', { class: 'btn btn-sm', type: 'button', text: 'Export CSV', onclick: exportDetailedCsv }),
      h('button', { class: 'btn btn-sm', type: 'button', text: 'Save session', onclick: saveSession }),
      h('button', { class: 'btn btn-sm', type: 'button', text: 'New evaluation', onclick: newEvaluation }),
    );
  }

  function showView(name) {
    state.view = name;
    $('viewSetup').hidden = name !== 'setup';
    $('viewProgress').hidden = name !== 'progress';
    $('viewResults').hidden = name !== 'results';
    renderHeaderActions();
    window.scrollTo({ top: 0 });
  }

  function newEvaluation() {
    if (state.report && !confirm('Start a new evaluation? Save the session first if you want to keep these results.')) return;
    state.report = null; state.ta = {};
    showView('setup');
  }

  // ------------------------------------------------------------------ setup: question paper
  async function loadSamples() {
    try {
      const list = await (await api('/api/samples')).json();
      const select = $('sampleSelect');
      for (const s of list) select.append(h('option', { value: s.name, text: `${s.title} (${s.questions} questions)` }));
      if (!list.length) select.hidden = true;
    } catch (_err) { $('sampleSelect').hidden = true; }
  }

  function showSetupError(message) {
    const box = $('setupError');
    box.textContent = message || '';
    box.hidden = !message;
  }

  function loadPaper(text, source) {
    const box = $('paperSummary');
    state.paper = null; state.paperText = '';
    showSetupError('');
    try {
      let data = JSON.parse(text);
      if (Array.isArray(data)) data = { questions: data };
      if (!data || !Array.isArray(data.questions) || !data.questions.length) throw new Error('Expected a "questions" list with at least one question.');
      const blocking = [];
      const notes = [];
      let anySample = false;
      const items = data.questions.map((q, i) => {
        const id = q && q.question_id;
        if (!/^Q\d{1,2}$/.test(id || '')) blocking.push(`Question ${i + 1}: "question_id" must look like "Q1".`);
        const tests = Array.isArray(q && q.test_cases) ? q.test_cases : [];
        const samples = tests.filter((t) => t.is_sample).length;
        if (samples) anySample = true;
        if (!tests.length) notes.push(`${id || 'Question ' + (i + 1)} has no test cases, so its submissions will be unverified.`);
        return h('li', { text: `${id} · ${q.title || 'Untitled'} — ${tests.length} tests (${samples} sample, ${tests.length - samples} hidden)` });
      });
      if (!anySample) notes.push('No test is marked "is_sample": true, so special-casing of sample inputs cannot be detected.');
      box.replaceChildren(
        h('strong', { text: data.quiz_title || source }),
        h('ul', null, items),
        ...notes.map((n) => h('div', { class: 'muted small', text: '⚠ ' + n })),
        ...blocking.map((n) => h('div', { class: 'fail small', text: n })),
      );
      box.hidden = false;
      if (!blocking.length) { state.paper = data; state.paperText = JSON.stringify(data); }
    } catch (err) {
      box.replaceChildren(h('span', { class: 'fail', text: `Could not read ${source}: ${err.message}` }));
      box.hidden = false;
    }
    updateRunButton();
  }

  // ------------------------------------------------------------------ setup: student files
  function setFiles(fileList) {
    const all = Array.from(fileList);
    const files = all.filter((f) => /\.(zip|c)$/i.test(f.name));
    state.files = files;
    const box = $('filesSummary');
    showSetupError('');
    if (!files.length) {
      box.replaceChildren(h('span', { class: 'fail', text: all.length ? 'No .zip or .c files in that selection.' : '' }));
      box.hidden = !all.length;
      updateRunButton();
      return;
    }
    const total = files.reduce((s, f) => s + f.size, 0);
    const limit = state.config ? state.config.limits.max_upload_mb * 1048576 : Infinity;
    const shown = files.slice(0, 6).map((f) => h('li', { text: `${f.name} (${fmtBytes(f.size)})` }));
    if (files.length > 6) shown.push(h('li', { class: 'muted', text: `…and ${files.length - 6} more` }));
    box.replaceChildren(
      h('strong', { text: `${files.length} file${files.length > 1 ? 's' : ''} · ${fmtBytes(total)}` }),
      all.length > files.length ? h('span', { class: 'muted', text: ` (${all.length - files.length} ignored)` }) : null,
      h('ul', null, shown),
      total > limit ? h('div', { class: 'fail small', text: `Total size exceeds the ${fmtBytes(limit)} server limit.` }) : null,
    );
    box.hidden = false;
    if (total > limit) state.files = [];
    updateRunButton();
  }

  function updateRunButton() {
    const ready = Boolean(state.paper) && state.files.length > 0;
    $('runBtn').disabled = !ready;
    $('runHint').textContent = ready ? `${state.paper.questions.length} question(s), ${state.files.length} file(s) ready.`
      : 'Add a valid question paper and at least one file to continue.';
  }

  // ------------------------------------------------------------------ running an evaluation
  function setProgress(fraction, stage, message) {
    const pct = Math.round(Math.min(1, Math.max(0, fraction || 0)) * 100);
    $('progressBar').style.width = pct + '%';
    $('progressTrack').setAttribute('aria-valuenow', String(pct));
    $('progressPct').textContent = pct + '%';
    $('progressStage').textContent = stage || 'Working…';
    $('progressMsg').textContent = message || '';
  }

  async function pollJob(jobId) {
    let failures = 0;
    for (;;) {
      await sleep(1200);
      try {
        const status = await (await api(`/api/jobs/${jobId}`)).json();
        failures = 0;
        setProgress(status.progress, status.stage, status.message);
        if (status.status === 'done') return await (await api(`/api/jobs/${jobId}/result`)).json();
        if (status.status === 'error') throw new Error(status.error || 'The evaluation failed.');
      } catch (err) {
        if (err instanceof ApiError && err.status === 0 && ++failures < 6) continue;   // transient network error
        throw err;
      }
    }
  }

  async function startEvaluation() {
    showSetupError('');
    const form = new FormData();
    form.append('question_paper_json', state.paperText);
    for (const f of state.files) form.append('archives', f, f.name);
    showView('progress');
    setProgress(0.01, 'Uploading…', `Uploading ${state.files.length} file(s)`);
    try {
      const created = await (await api('/api/jobs', { method: 'POST', body: form })).json();
      const report = await pollJob(created.job_id);
      openReport(report, {});
    } catch (err) {
      showView('setup');
      showSetupError(err.message);
    }
  }

  // ------------------------------------------------------------------ results: data helpers
  const questions = () => state.report.questions;
  const evalsFor = (qid) => state.report.evaluations_by_question[qid] || [];
  const findEval = (roll, qid) => evalsFor(qid).find((e) => e.roll_no === roll);
  const taKey = (ev) => `${ev.roll_no}|${ev.question_id}`;
  const effectiveTab = (ev) => (state.ta[taKey(ev)] ? state.ta[taKey(ev)].category : ev.tab_category);
  const displayName = (roll) => (state.ui.anonymize ? state.alias[roll] || roll : roll);
  const testsLabel = (ev) => (ev.gcc_result && ev.gcc_result.total_count ? `${ev.gcc_result.passed_count}/${ev.gcc_result.total_count} tests` : 'no tests');
  const llmRedReview = (ev) => {
    const rec = ev && ev.llm_red_review;
    if (!rec || rec.status !== 'RED_REVIEW') return { status: 'NONE', reason: '', confidence: null, evidence_lines: [] };
    return {
      status: 'RED_REVIEW',
      reason: typeof rec.reason === 'string' ? rec.reason : '',
      confidence: Number.isFinite(rec.confidence) ? rec.confidence : null,
      evidence_lines: Array.isArray(rec.evidence_lines) ? rec.evidence_lines.filter((n) => Number.isInteger(n) && n > 0) : [],
    };
  };

  function openReport(report, ta) {
    state.report = report;
    state.ta = ta || {};
    const rolls = Object.keys(report.student_matrix || {}).sort(natural);
    state.alias = {};
    rolls.forEach((r, i) => { state.alias[r] = `Student ${i + 1}`; });
    const first = report.questions[0].question_id;
    state.ui = { tab: 'triage', q: first, filter: 'RED', search: '', selected: null, anonymize: false };
    autoFilter();
    showView('results');
    renderResults();
  }

  function autoFilter() {
    const list = evalsFor(state.ui.q);
    const order = ['RED', 'BLUE', 'GRAY', 'GREEN'];
    state.ui.filter = order.find((t) => list.some((e) => effectiveTab(e) === t)) || 'ALL';
  }

  // ------------------------------------------------------------------ results: frame
  function renderResults() {
    const r = state.report;
    $('resultsTitle').textContent = r.quiz_title || 'Results';
    $('resultsSub').textContent = `${r.course_code} · evaluated ${r.evaluated_at || ''} · ${r.elapsed_seconds || 0}s`;
    renderSummary();
    renderEngineNote();
    renderWarnings();
    renderTabs();
    renderTab();
  }

  function effectiveCounts() {
    const counts = { RED: 0, BLUE: 0, GREEN: 0, GRAY: 0 };
    for (const q of questions()) for (const e of evalsFor(q.question_id)) counts[effectiveTab(e)] += 1;
    return counts;
  }

  function renderSummary() {
    const r = state.report;
    const c = effectiveCounts();
    const metric = (label, value, cls) => h('div', { class: 'metric ' + (cls ? 'metric-' + cls : '') },
      h('div', { class: 'metric-value', text: String(value) }), h('div', { class: 'metric-label', text: label }));
    const box = $('summaryStrip');
    box.replaceChildren(
      metric('Students', r.student_count), metric('C files', r.total_c_files),
      metric('Needs review', c.RED, 'RED'), metric('Creative approach', c.BLUE, 'BLUE'),
      metric('Clear', c.GREEN, 'GREEN'), metric('Unverified', c.GRAY, 'GRAY'),
      metric('Collusion pairs', (r.collusion_pairs || []).length, (r.collusion_pairs || []).length ? 'RED' : ''),
    );
  }

  function renderEngineNote() {
    const box = $('engineNote');
    const engine = state.report.engine || {};
    const llm = engine.llm || {};
    box.className = 'alert';
    box.hidden = false;
    if (!llm.enabled) {
      box.classList.add('alert-info');
      box.textContent = `AI review was not used (${llm.skipped_reason || 'disabled'}). All verdicts are deterministic: compiler, tests, static checks and plagiarism analysis.`;
    } else if (llm.errors && llm.errors.length) {
      box.classList.add('alert-warn');
      box.textContent = `AI review was only partly available (${llm.ok_calls || 0}/${llm.calls || 0} calls succeeded): ${llm.errors[0]} Deterministic verdicts are unaffected.`;
    } else {
      box.classList.add('alert-info');
      box.textContent = `AI review (${(llm.models_used || [llm.primary_model]).join(', ')}) looked at the approach of ${llm.submissions_reviewed || 0} passing submissions. It cannot change test results or integrity flags.`;
    }
    if (engine.sandbox === false) {
      box.className = 'alert alert-warn';
      box.textContent = 'The gcc sandbox was unavailable, so no tests were run and every submission is unverified.';
    }
  }

  function renderWarnings() {
    const warnings = state.report.ingestion_warnings || [];
    $('warningsBox').hidden = !warnings.length;
    if (!warnings.length) return;
    $('warningsSummary').textContent = `${warnings.length} notice${warnings.length > 1 ? 's' : ''} from file ingestion`;
    $('warningsList').replaceChildren(...warnings.slice(0, 100).map((w) => h('li', { text: w })));
  }

  const TABS = [['triage', 'Triage'], ['matrix', 'Class matrix'], ['integrity', 'Integrity'], ['memory', 'TA memory']];
  function renderTabs() {
    $('tabs').replaceChildren(...TABS.map(([id, label]) => h('button', {
      class: 'tab' + (state.ui.tab === id ? ' active' : ''), type: 'button', role: 'tab',
      'aria-selected': state.ui.tab === id ? 'true' : 'false', text: label,
      onclick: () => { state.ui.tab = id; renderTabs(); renderTab(); },
    })));
  }

  function renderTab() {
    const panel = $('tabPanel');
    panel.replaceChildren();
    if (!state.report) return;
    if (state.ui.tab === 'triage') renderTriage(panel);
    else if (state.ui.tab === 'matrix') renderMatrix(panel);
    else if (state.ui.tab === 'integrity') renderIntegrity(panel);
    else renderMemory(panel);
  }

  // ------------------------------------------------------------------ triage
  function badge(tab, text) { return h('span', { class: `badge badge-${tab}`, text: text || TAB_LABEL[tab] }); }

  function renderTriage(panel) {
    const qs = questions();
    const q = qs.find((x) => x.question_id === state.ui.q) || qs[0];
    state.ui.q = q.question_id;

    const qSwitch = h('div', { class: 'q-switch', role: 'group', 'aria-label': 'Question' }, qs.map((x) => h('button', {
      class: 'seg-btn' + (x.question_id === q.question_id ? ' active' : ''), type: 'button', text: x.question_id,
      title: x.title,
      onclick: () => { state.ui.q = x.question_id; state.ui.selected = null; autoFilter(); renderTab(); },
    })));
    const search = h('input', {
      type: 'search', placeholder: 'Filter by student id…', 'aria-label': 'Filter by student id', value: state.ui.search,
      oninput: (e) => { state.ui.search = e.target.value; renderList(); },
    });
    panel.append(
      h('div', { class: 'toolbar-row' }, qSwitch, h('strong', { text: q.title }), h('span', { class: 'spacer' }), search),
      h('details', { class: 'q-info card' }, h('summary', { text: 'Problem statement, tags and tests' }),
        h('div', { class: 'q-body', text: q.problem_statement }),
        h('div', { class: 'muted small', text: `Topic tags: ${(q.topic_tags || []).join(', ') || 'none'} · expected complexity ${q.expected_complexity} · ${q.test_cases.length} tests` })),
      h('div', { class: 'toolbar-row', id: 'filterRow' }),
      h('div', { class: 'triage-layout' },
        h('div', { class: 'sub-list', id: 'subList', role: 'listbox', 'aria-label': 'Submissions', tabindex: '0', onkeydown: onListKey }),
        h('div', { class: 'inspector', id: 'inspector' })),
    );
    renderFilters();
    renderList();
    renderInspector();
  }

  function renderFilters() {
    const list = evalsFor(state.ui.q);
    const countOf = (t) => list.filter((e) => effectiveTab(e) === t).length;
    const chips = [['ALL', 'All', list.length], ['RED', TAB_LABEL.RED, countOf('RED')], ['BLUE', TAB_LABEL.BLUE, countOf('BLUE')],
      ['GREEN', TAB_LABEL.GREEN, countOf('GREEN')], ['GRAY', TAB_LABEL.GRAY, countOf('GRAY')]];
    $('filterRow').replaceChildren(...chips.map(([id, label, n]) => h('button', {
      class: 'chip' + (state.ui.filter === id ? ' active' : ''), type: 'button',
      onclick: () => { state.ui.filter = id; renderFilters(); renderList(); },
    }, label, h('span', { class: 'chip-count', text: String(n) }))));
  }

  function visibleEvals() {
    const needle = state.ui.search.trim().toLowerCase();
    return evalsFor(state.ui.q)
      .filter((e) => state.ui.filter === 'ALL' || effectiveTab(e) === state.ui.filter)
      .filter((e) => !needle || e.roll_no.toLowerCase().includes(needle) || displayName(e.roll_no).toLowerCase().includes(needle))
      .sort((a, b) => natural(a.roll_no, b.roll_no));
  }

  function renderList() {
    const box = $('subList');
    const items = visibleEvals();
    if (!items.length) { box.replaceChildren(h('div', { class: 'empty', text: 'No submissions match this filter.' })); return; }
    box.replaceChildren(...items.map((e) => {
      const tab = effectiveTab(e);
      const strong = (e.clone_matches || []).filter((m) => m.strength === 'STRONG').length;
      return h('button', {
        class: 'sub-row' + (state.ui.selected === e.roll_no ? ' selected' : ''), type: 'button', role: 'option',
        'aria-selected': state.ui.selected === e.roll_no ? 'true' : 'false',
        'data-roll': e.roll_no, onclick: () => selectSubmission(e.roll_no),
      },
      h('div', { class: 'sub-row-main' }, h('span', { class: 'sub-name', text: displayName(e.roll_no) }), badge(tab)),
      h('div', { class: 'sub-meta' }, h('span', { text: e.verdict_badge }), h('span', { text: testsLabel(e) }),
        strong ? h('span', { class: 'fail', text: `${strong} strong match${strong > 1 ? 'es' : ''}` }) : null,
        state.ta[taKey(e)] ? h('span', { text: 'TA reviewed' }) : null));
    }));
  }

  function selectSubmission(roll) {
    state.ui.selected = roll;
    for (const row of document.querySelectorAll('#subList .sub-row')) {
      const on = row.getAttribute('data-roll') === roll;
      row.classList.toggle('selected', on);
      row.setAttribute('aria-selected', on ? 'true' : 'false');
    }
    renderInspector();
  }

  function onListKey(event) {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    event.preventDefault();
    const items = visibleEvals();
    if (!items.length) return;
    const index = items.findIndex((e) => e.roll_no === state.ui.selected);
    const next = event.key === 'ArrowDown' ? Math.min(items.length - 1, index + 1) : Math.max(0, index - 1);
    selectSubmission(items[next].roll_no);
    const row = document.querySelector(`#subList .sub-row[data-roll="${CSS.escape(items[next].roll_no)}"]`);
    if (row) row.scrollIntoView({ block: 'nearest' });
  }

  // ------------------------------------------------------------------ inspector
  function renderCode(code, flaggedLines, annotations, tab) {
    const wrap = h('div', { class: 'code', tabindex: '0', role: 'region', 'aria-label': 'Source code' });
    const flagged = new Set(flaggedLines || []);
    const cls = tab === 'RED' ? 'flag-red' : tab === 'BLUE' ? 'flag-blue' : 'flag-gray';
    String(code).replace(/\r\n?/g, '\n').split('\n').forEach((line, i) => {
      const n = i + 1;
      wrap.append(h('div', { class: 'code-line' + (flagged.has(n) ? ' ' + cls : '') },
        h('span', { class: 'ln', text: String(n) }), h('span', { class: 'src', text: line === '' ? ' ' : line })));
      const note = annotations && annotations[String(n)];
      if (note) wrap.append(h('div', { class: 'code-note ' + (tab === 'RED' ? 'red' : tab === 'BLUE' ? 'blue' : ''), text: note }));
    });
    return wrap;
  }

  function renderInspector() {
    const box = $('inspector');
    const ev = state.ui.selected ? findEval(state.ui.selected, state.ui.q) : null;
    if (!ev) { box.replaceChildren(h('div', { class: 'empty', text: 'Select a submission to inspect its code, tests and evidence.' })); return; }
    const q = questions().find((x) => x.question_id === ev.question_id);
    const tab = effectiveTab(ev);
    const rec = llmRedReview(ev);
    const g = ev.gcc_result;
    const cheat = CHEAT_LABEL[ev.cheat_type];
    const recLines = rec.evidence_lines.length ? rec.evidence_lines.join(', ') : 'none provided';

    const head = h('div', { class: 'insp-head' },
      h('div', { class: 'insp-title' }, h('h3', { text: displayName(ev.roll_no) }), badge(tab),
        tab !== ev.tab_category ? h('span', { class: 'tag', text: `automatic: ${TAB_LABEL[ev.tab_category]}` }) : null,
        h('span', { class: 'tag', text: ev.filename }), ev.uncommon_approach_tag ? h('span', { class: 'tag', text: ev.uncommon_approach_tag }) : null),
      h('div', { class: 'callout', text: ev.verdict_badge + (cheat && ev.verdict_badge !== cheat ? ` · ${cheat}` : '') }),
      h('div', { text: ev.logic_summary }),
      h('div', { class: 'muted small', text: `${ev.instructor_callout}  ·  Evidence strength ${ev.confidence_score}/100 (not a probability)` }),
      ev.llm_summary ? h('div', { class: 'ai-note' }, h('strong', { text: 'AI note: ' }), `${ev.llm_summary} ${ev.llm_callout || ''}`,
        h('div', { class: 'muted small', text: `Advisory only · ${ev.llm_model || ''}` })) : null);

    const sections = [head];

    if (rec.status === 'RED_REVIEW') {
      sections.push(h('div', { class: 'insp-section' },
        h('div', { class: 'alert alert-warn' },
          h('strong', { text: 'AI advisory: recommend manual RED review' }),
          h('div', { text: rec.reason || 'Potential integrity concern flagged by the AI.' }),
          h('div', { class: 'muted small', text: `Confidence: ${rec.confidence === null ? 'n/a' : `${rec.confidence}/100`} · Evidence lines: ${recLines}` }),
          h('ul', { class: 'notes-list' }, [
            h('li', { text: 'Inspect the highlighted/evidence code lines and compare the implementation against expected logic.' }),
            h('li', { text: 'Open Similar submissions when available to compare structure and context.' }),
            h('li', { text: 'Use TA decision: Agree, or Override → Needs review (RED), add a reason, then Save override.' }),
            h('li', { text: 'This recommendation is advisory only and never changes the verdict automatically.' }),
          ]))));
    }

    if (ev.integrity_notes && ev.integrity_notes.length) {
      sections.push(h('div', { class: 'insp-section' }, h('h4', { text: 'Integrity notes' }),
        h('ul', { class: 'notes-list' }, ev.integrity_notes.map((n) => h('li', { text: n })))));
    }

    const codeHints = rec.status === 'RED_REVIEW'
      ? Array.from(new Set([...(ev.flagged_lines || []), ...rec.evidence_lines])).sort((a, b) => a - b)
      : ev.flagged_lines;
    sections.push(h('div', { class: 'insp-section' }, h('h4', { text: 'Code' }),
      renderCode(ev.raw_code, codeHints, ev.line_annotations, rec.status === 'RED_REVIEW' ? 'RED' : ev.tab_category)));

    if (g) sections.push(renderTestsSection(g));

    const st = ev.static_analysis;
    const findings = [...(st.static_suspicion_reasons || []), ...(st.uncommon_construct_notes || []).map((n) => `Approach: ${n}`), ...(st.include_notes || [])];
    if (findings.length) {
      sections.push(h('div', { class: 'insp-section' }, h('h4', { text: 'Static findings' }),
        h('ul', { class: 'notes-list' }, findings.map((n) => h('li', { text: n })))));
    }

    if (ev.clone_matches && ev.clone_matches.length) sections.push(renderMatchesSection(ev));
    sections.push(renderTaSection(ev, q));
    box.replaceChildren(...sections);
  }

  function renderTestsSection(g) {
    const section = h('div', { class: 'insp-section' }, h('h4', { text: 'Tests' }));
    if (!g.compiled) {
      section.append(h('div', { class: 'fail', text: 'Did not compile' }), h('div', { class: 'code' }, h('div', { class: 'code-line' }, h('span', { class: 'src', text: g.compiler_errors || 'Compilation failed.' }))));
      return section;
    }
    if (!g.case_details || !g.case_details.length) { section.append(h('div', { class: 'muted', text: g.skipped_reason || 'No tests ran.' })); return section; }
    const rows = g.case_details.map((d) => h('tr', null,
      h('td', { text: String(d.case_index) }), h('td', { text: d.is_sample ? 'sample' : 'hidden' }),
      h('td', { class: 'mono', text: d.input === '' ? '(empty)' : d.input }), h('td', { class: 'mono', text: d.expected }),
      h('td', { class: 'mono', text: d.actual }), h('td', { class: d.passed ? 'pass' : 'fail', text: d.passed ? 'pass' : 'fail' })));
    section.append(h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
      h('thead', null, h('tr', null, ['#', 'Type', 'Input', 'Expected', 'Actual', 'Result'].map((t) => h('th', { text: t })))), h('tbody', null, rows))));
    if (g.compiler_warnings) section.append(h('details', { class: 'small' }, h('summary', { text: 'Compiler warnings' }), h('div', { class: 'code' }, h('div', { class: 'code-line' }, h('span', { class: 'src', text: g.compiler_warnings })))));
    return section;
  }

  function renderMatchesSection(ev) {
    const rows = ev.clone_matches.map((m) => h('tr', null,
      h('td', { text: displayName(m.partner_roll_no) }), h('td', { text: `${m.similarity_percent}%` }),
      h('td', null, h('span', { class: 'badge ' + (m.strength === 'STRONG' ? 'badge-RED' : 'badge-GRAY'), text: m.strength === 'STRONG' ? 'Strong' : 'Weak' })),
      h('td', { text: `${m.exclusive_percent}%` }), h('td', { text: String(m.cluster_size) }),
      h('td', null, h('button', { class: 'btn btn-sm', type: 'button', text: 'Compare', onclick: () => openCompare(ev, m) }))));
    return h('div', { class: 'insp-section' }, h('h4', { text: 'Similar submissions' }),
      h('div', { class: 'muted small', text: 'Strong = the shared structure is distinctive in this class. Weak = a common textbook shape, shown for context only.' }),
      h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
        h('thead', null, h('tr', null, ['Student', 'Similarity', 'Evidence', 'Distinctive', 'Group size', ''].map((t) => h('th', { text: t })))),
        h('tbody', null, rows))));
  }

  function openCompare(ev, match) {
    const partner = findEval(match.partner_roll_no, ev.question_id);
    $('compareTitle').textContent = `${ev.question_id}: ${displayName(ev.roll_no)} vs ${displayName(match.partner_roll_no)} (${match.similarity_percent}% similar, ${match.strength.toLowerCase()} evidence)`;
    $('compareBody').replaceChildren(
      h('div', { class: 'muted small', text: 'Highlighted lines have the same normalised structure (identifiers, literals and for/while differences ignored).' }),
      h('div', { class: 'compare-grid' },
        h('div', { class: 'compare-pane' }, h('h4', { text: displayName(ev.roll_no) }), renderCode(ev.raw_code, match.matched_lines_self, null, 'RED')),
        h('div', { class: 'compare-pane' }, h('h4', { text: displayName(match.partner_roll_no) }),
          partner ? renderCode(partner.raw_code, match.matched_lines_partner, null, 'RED') : h('div', { class: 'muted', text: 'Partner code not available.' }))));
    $('compareDialog').showModal();
  }

  // ------------------------------------------------------------------ TA decision
  function renderTaSection(ev, q) {
    const key = taKey(ev);
    const current = state.ta[key];
    const section = h('div', { class: 'insp-section ta-box' }, h('h4', { text: 'TA decision' }));
    section.append(h('div', { class: 'ta-status', text: current
      ? `Your decision: ${current.decision === 'AGREE' ? 'agreed with the verdict' : `moved to “${TAB_LABEL[current.category]}”`}${current.note ? ` — ${current.note}` : ''}`
      : 'Not reviewed yet. Corrections are saved as calibration examples for the AI approach review.' }));

    const form = h('div', { class: 'row', hidden: true });
    const select = h('select', { 'aria-label': 'Move to' }, ['GREEN', 'BLUE', 'RED'].map((t) => h('option', { value: t, text: TAB_LABEL[t], selected: t === ev.tab_category ? true : null })));
    const note = h('input', { type: 'text', maxlength: '300', placeholder: 'Reason (short, plain text)…', 'aria-label': 'Reason' });
    form.append(select, note, h('button', { class: 'btn btn-primary btn-sm', type: 'button', text: 'Save override',
      onclick: () => submitTa(ev, q, 'DISAGREE', select.value, note.value.trim()) }));
    const buttons = h('div', { class: 'row' },
      ev.tab_category === 'GRAY' ? null : h('button', { class: 'btn btn-sm', type: 'button', text: 'Agree with verdict', onclick: () => submitTa(ev, q, 'AGREE', ev.tab_category, '') }),
      h('button', { class: 'btn btn-sm btn-danger', type: 'button', text: 'Override…', onclick: () => { form.hidden = !form.hidden; } }));
    section.append(buttons, form);
    return section;
  }

  async function submitTa(ev, q, decision, category, note) {
    state.ta[taKey(ev)] = { decision, category, note };
    renderSummary(); renderFilters(); renderList(); renderInspector();
    try {
      await api('/api/hitl-feedback', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          course_code: state.report.course_code, question_id: ev.question_id, topic_tags: (q && q.topic_tags) || [],
          problem_summary: (q && q.title) || ev.question_id, roll_no: ev.roll_no, raw_code: ev.raw_code.slice(0, 20000),
          original_category: ev.tab_category, original_cheat_type: ev.cheat_type, ta_decision: decision,
          override_category: category, ta_explanation: note,
        }),
      });
      toast('Decision saved');
    } catch (err) {
      toast(`Saved in this session only: ${err.message}`);
    }
  }

  // ------------------------------------------------------------------ class matrix
  function renderMatrix(panel) {
    const rolls = Object.keys(state.report.student_matrix).sort(natural);
    const qs = questions();
    const head = h('tr', null, h('th', { text: 'Student' }), qs.map((q) => h('th', { text: q.question_id, title: q.title })),
      h('th', { text: 'Tests passed' }), h('th', { text: 'Needs review' }));
    const rows = rolls.map((roll) => {
      let passed = 0, total = 0, red = 0;
      const cells = qs.map((q) => {
        const cell = state.report.student_matrix[roll][q.question_id];
        const ev = findEval(roll, q.question_id);
        const tab = ev ? effectiveTab(ev) : 'GRAY';
        if (cell) { passed += cell.passed || 0; total += cell.total || 0; }
        if (tab === 'RED') red += 1;
        if (!cell || cell.submitted === false) return h('td', null, h('span', { class: 'tag', text: 'not submitted' }));
        return h('td', null, h('button', {
          class: `matrix-cell ${tab}`, type: 'button', title: `${cell.verdict_badge} · ${TAB_LABEL[tab]}`,
          onclick: () => { state.ui.tab = 'triage'; state.ui.q = q.question_id; state.ui.filter = 'ALL'; state.ui.search = ''; state.ui.selected = roll; renderTabs(); renderTab(); },
        }, cell.passed_tests, ' ', h('span', { text: TAB_LABEL[tab] })));
      });
      return h('tr', null, h('td', { text: displayName(roll) }), cells,
        h('td', { text: total ? `${Math.round((100 * passed) / total)}% (${passed}/${total})` : '-' }),
        h('td', { text: red ? String(red) : '-' }));
    });
    panel.append(
      h('div', { class: 'toolbar-row' }, h('div', { class: 'muted' }, 'Each cell shows tests passed and the triage verdict. Click a cell to open the submission.'),
        h('span', { class: 'spacer' }), h('button', { class: 'btn btn-sm', type: 'button', text: 'Download matrix CSV', onclick: exportMatrixCsv })),
      h('div', { class: 'table-wrap' }, h('table', { class: 'table matrix-table' }, h('thead', null, head), h('tbody', null, rows))));
  }

  // ------------------------------------------------------------------ integrity
  function strongPairs() {
    const out = [];
    for (const q of questions()) {
      for (const ev of evalsFor(q.question_id)) {
        for (const m of ev.clone_matches || []) {
          if (m.strength === 'STRONG' && ev.roll_no < m.partner_roll_no) out.push({ q: q.question_id, ev, m });
        }
      }
    }
    return out.sort((a, b) => b.m.similarity_percent - a.m.similarity_percent);
  }

  function renderIntegrity(panel) {
    const pairs = state.report.collusion_pairs || [];
    panel.append(h('div', { class: 'alert alert-info', text: 'Matches are evidence for a human decision, not proof. Programs for simple problems often look alike; a match is “strong” only when the shared structure is distinctive in this class or repeats across questions.' }));

    panel.append(h('h3', { class: 'section-title', text: 'Possible collusion (strong matches in several questions)' }));
    if (!pairs.length) panel.append(h('div', { class: 'muted', text: 'No pair of students has strong matches in more than one question.' }));
    for (const p of pairs) {
      const buttons = p.shared_questions.map((qid) => {
        const evA = findEval(p.roll_a, qid);
        const match = evA && (evA.clone_matches || []).find((m) => m.partner_roll_no === p.roll_b);
        return match ? h('button', { class: 'btn btn-sm', type: 'button', text: `Compare ${qid}`, onclick: () => openCompare(evA, match) }) : null;
      });
      panel.append(h('div', { class: 'pair-card' },
        h('div', { class: 'pair-head' }, h('strong', { text: `${displayName(p.roll_a)}  ↔  ${displayName(p.roll_b)}` }),
          h('span', { class: 'badge badge-RED', text: `${p.shared_questions.length} questions` }),
          h('span', { class: 'muted', text: `average ${p.average_similarity}% · max ${p.max_similarity}%` })),
        h('div', { class: 'toolbar-row' }, buttons)));
    }

    const strong = strongPairs();
    panel.append(h('h3', { class: 'section-title', text: 'All strong matches' }));
    if (!strong.length) panel.append(h('div', { class: 'muted', text: 'None.' }));
    else {
      const rows = strong.map(({ q, ev, m }) => h('tr', null, h('td', { text: q }), h('td', { text: displayName(ev.roll_no) }), h('td', { text: displayName(m.partner_roll_no) }),
        h('td', { text: `${m.similarity_percent}%` }), h('td', { text: `${m.exclusive_percent}%` }), h('td', { text: m.corroborated ? 'repeats across questions' : 'distinctive structure' }),
        h('td', null, h('button', { class: 'btn btn-sm', type: 'button', text: 'Compare', onclick: () => openCompare(ev, m) }))));
      panel.append(h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
        h('thead', null, h('tr', null, ['Question', 'Student A', 'Student B', 'Similarity', 'Distinctive', 'Why strong', ''].map((t) => h('th', { text: t })))), h('tbody', null, rows))));
    }

    panel.append(h('h3', { class: 'section-title', text: 'Common solutions (weak evidence)' }));
    const lines = [];
    for (const q of questions()) {
      const weak = new Set();
      let biggest = 0;
      for (const ev of evalsFor(q.question_id)) for (const m of ev.clone_matches || []) {
        if (m.strength === 'WEAK') { weak.add([ev.roll_no, m.partner_roll_no].sort().join('|')); biggest = Math.max(biggest, m.cluster_size); }
      }
      if (weak.size) lines.push(h('li', { text: `${q.question_id}: ${weak.size} similar pair(s); the largest group has ${biggest} near-identical submissions.` }));
    }
    panel.append(lines.length ? h('ul', { class: 'notes-list' }, lines) : h('div', { class: 'muted', text: 'None.' }));
  }

  // ------------------------------------------------------------------ TA memory
  async function renderMemory(panel) {
    panel.append(h('div', { class: 'muted', text: 'Loading…', id: 'memoryLoading' }));
    try {
      const data = await (await api('/api/hitl-examples')).json();
      if (state.ui.tab !== 'memory') return;
      panel.replaceChildren();
      const s = data.stats || { agree: 0, disagree: 0, total: 0 };
      panel.append(
        h('div', { class: 'alert alert-info', text: 'Corrections are shown to the AI when it judges approach (standard vs creative). They cannot change test results or integrity flags.' }),
        h('div', { class: 'summary-strip' },
          h('div', { class: 'metric' }, h('div', { class: 'metric-value', text: String(s.total) }), h('div', { class: 'metric-label', text: 'TA reviews recorded' })),
          h('div', { class: 'metric metric-GREEN' }, h('div', { class: 'metric-value', text: s.total ? `${Math.round((100 * s.agree) / s.total)}%` : '-' }), h('div', { class: 'metric-label', text: 'TA agreement with verdicts' })),
          h('div', { class: 'metric metric-RED' }, h('div', { class: 'metric-value', text: String(s.disagree) }), h('div', { class: 'metric-label', text: 'Corrections' }))));
      if (!data.examples.length) panel.append(h('div', { class: 'muted', text: 'No corrections yet.' }));
      for (const ex of data.examples) {
        panel.append(h('div', { class: 'memory-item' },
          h('div', { class: 'pair-head' }, h('strong', { text: `${ex.question_id} · ${ex.problem_summary}` }),
            badge(ex.original_category), h('span', { text: '→' }), badge(ex.override_category)),
          h('div', { class: 'muted', text: ex.ta_explanation || '(no reason given)' }),
          h('div', { class: 'code' }, h('div', { class: 'code-line' }, h('span', { class: 'src', text: ex.code_snippet })))));
      }
    } catch (err) {
      panel.replaceChildren(h('div', { class: 'alert alert-error', text: `Could not load calibration memory: ${err.message}` }));
    }
  }

  // ------------------------------------------------------------------ exports and sessions
  function exportDetailedCsv() {
    const rows = [['student', 'question', 'tab', 'verdict', 'cheat_type', 'tests_passed', 'tests_total', 'max_similarity_percent',
      'strong_match_partners', 'integrity_notes', 'ai_summary', 'ai_red_review', 'ai_red_review_confidence', 'ai_red_review_lines',
      'ta_decision', 'ta_category', 'ta_note']];
    for (const q of questions()) for (const ev of evalsFor(q.question_id).slice().sort((a, b) => natural(a.roll_no, b.roll_no))) {
      const ta = state.ta[taKey(ev)] || {};
      const rec = llmRedReview(ev);
      const g = ev.gcc_result;
      rows.push([displayName(ev.roll_no), q.question_id, ev.tab_category, ev.verdict_badge, ev.cheat_type, g ? g.passed_count : '', g ? g.total_count : '',
        ev.max_clone_similarity, (ev.clone_matches || []).filter((m) => m.strength === 'STRONG').map((m) => displayName(m.partner_roll_no)).join(' '),
        (ev.integrity_notes || []).join(' | '), ev.llm_summary || '', rec.status === 'RED_REVIEW' ? rec.reason : '',
        rec.status === 'RED_REVIEW' && rec.confidence !== null ? rec.confidence : '', rec.status === 'RED_REVIEW' ? rec.evidence_lines.join(' ') : '',
        ta.decision || '', ta.category || '', ta.note || '']);
    }
    download(`${slug(state.report.quiz_title)}_results.csv`, toCsv(rows), 'text/csv');
  }

  function exportMatrixCsv() {
    const qs = questions();
    const rows = [['student', ...qs.map((q) => `${q.question_id}_tests`), ...qs.map((q) => `${q.question_id}_verdict`), 'tests_passed_percent']];
    for (const roll of Object.keys(state.report.student_matrix).sort(natural)) {
      let passed = 0, total = 0;
      const tests = [], verdicts = [];
      for (const q of qs) {
        const cell = state.report.student_matrix[roll][q.question_id];
        const ev = findEval(roll, q.question_id);
        tests.push(cell ? cell.passed_tests : '');
        verdicts.push(ev ? TAB_LABEL[effectiveTab(ev)] : 'Not submitted');
        if (cell) { passed += cell.passed || 0; total += cell.total || 0; }
      }
      rows.push([displayName(roll), ...tests, ...verdicts, total ? Math.round((100 * passed) / total) : '']);
    }
    download(`${slug(state.report.quiz_title)}_matrix.csv`, toCsv(rows), 'text/csv');
  }

  function saveSession() {
    download(`${slug(state.report.quiz_title)}_session.json`,
      JSON.stringify({ format: 'iiserb-quiz-session', version: 1, report: state.report, ta: state.ta }), 'application/json');
  }

  async function openSessionFile(file) {
    try {
      const data = JSON.parse(await file.text());
      if (data.format !== 'iiserb-quiz-session' || !data.report || !data.report.evaluations_by_question || !Array.isArray(data.report.questions) || !data.report.questions.length) {
        throw new Error('This is not a saved session from this tool.');
      }
      openReport(data.report, data.ta || {});
    } catch (err) {
      showSetupError(`Could not open the session: ${err.message}`);
    }
  }

  // ------------------------------------------------------------------ init
  async function init() {
    $('paperInput').addEventListener('change', async (e) => {
      const file = e.target.files[0];
      if (file) loadPaper(await file.text(), file.name);
    });
    $('sampleSelect').addEventListener('change', async (e) => {
      if (!e.target.value) return;
      try { loadPaper(JSON.stringify(await (await api(`/api/samples/${encodeURIComponent(e.target.value)}`)).json()), e.target.value); }
      catch (err) { showSetupError(err.message); }
    });
    const drop = $('dropZone');
    const filesInput = $('filesInput');
    drop.addEventListener('click', () => filesInput.click());
    drop.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); filesInput.click(); } });
    filesInput.addEventListener('change', (e) => setFiles(e.target.files));
    for (const ev of ['dragenter', 'dragover']) drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add('dragover'); });
    for (const ev of ['dragleave', 'drop']) drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove('dragover'); });
    drop.addEventListener('drop', (e) => setFiles(e.dataTransfer.files));
    $('runBtn').addEventListener('click', startEvaluation);
    $('sessionInput').addEventListener('change', (e) => { if (e.target.files[0]) openSessionFile(e.target.files[0]); e.target.value = ''; });
    $('tokenInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); $('tokenSave').click(); } });
    $('compareClose').addEventListener('click', () => $('compareDialog').close());

    try { state.config = await (await api('/api/config')).json(); } catch (_err) { state.config = null; }
    renderStatusPills();
    loadSamples();
    updateRunButton();
    showView('setup');
  }

  init();
})();
