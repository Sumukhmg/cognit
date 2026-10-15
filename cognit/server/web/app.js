// Cognit Web Visualizer Reactive Client

let state = {
  checkpoints: [],
  selectedCheckpoint: null,
  status: null,
  trials: [],
  locks: [],
  diffs: [],
};

async function fetchJSON(url, options = {}) {
  try {
    const res = await fetch(url, options);
    const json = await res.json();
    return json.data;
  } catch (err) {
    console.error(`Fetch error for ${url}:`, err);
    return null;
  }
}

async function loadAllData() {
  const [status, log, trials, locks, diffs] = await Promise.all([
    fetchJSON('/api/status'),
    fetchJSON('/api/log?limit=50'),
    fetchJSON('/api/trials'),
    fetchJSON('/api/locks'),
    fetchJSON('/api/diff?mode=semantic'),
  ]);

  if (status) state.status = status;
  if (log) state.checkpoints = log;
  if (trials) state.trials = trials;
  if (locks) state.locks = locks;
  if (diffs) state.diffs = diffs;

  renderNav();
  renderMetrics();
  renderTimeline();
  renderTrials();
  renderWorktree();
  renderLocks();

  if (state.checkpoints.length > 0 && !state.selectedCheckpoint) {
    selectCheckpoint(state.checkpoints[0].id);
  }
}

function renderNav() {
  if (!state.status) return;
  document.getElementById('active-branch-name').textContent = state.status.branch || 'main';
  const headId = state.status.head_checkpoint ? state.status.head_checkpoint.id.substring(0, 8) : 'empty';
  document.getElementById('head-cid-short').textContent = headId;
}

function renderMetrics() {
  document.getElementById('stat-total-checkpoints').textContent = state.checkpoints.length;
  
  const totalTokens = state.checkpoints.reduce((acc, c) => {
    return acc + (c.agent_metadata?.tokens_used || 0);
  }, 0);
  document.getElementById('stat-total-tokens').textContent = totalTokens.toLocaleString();

  const activeTrials = state.trials.filter(t => t.status === 'active').length;
  document.getElementById('stat-active-trials').textContent = activeTrials;

  document.getElementById('stat-active-locks').textContent = state.locks.length;
  document.getElementById('checkpoint-count-badge').textContent = `${state.checkpoints.length} nodes`;
}

function renderTimeline() {
  const container = document.getElementById('timeline-container');
  if (state.checkpoints.length === 0) {
    container.innerHTML = '<div class="empty-state">No checkpoints in this repository yet.</div>';
    return;
  }

  container.innerHTML = state.checkpoints.map(cp => {
    const isSelected = state.selectedCheckpoint && state.selectedCheckpoint.id === cp.id;
    const shortId = cp.id.substring(0, 8);
    const dateStr = cp.timestamp ? cp.timestamp.substring(0, 19).replace('T', ' ') : '';
    const agent = cp.agent_metadata?.agent_id || 'human';
    const model = cp.agent_metadata?.model || 'manual';
    const testStatus = cp.agent_metadata?.test_status || 'untested';

    let testBadgeClass = 'badge';
    if (testStatus === 'passed') testBadgeClass += ' green';
    else if (testStatus === 'failed') testBadgeClass += ' rose';

    return `
      <div class="timeline-item ${isSelected ? 'active' : ''}" onclick="selectCheckpoint('${cp.id}')">
        <div class="timeline-top">
          <span class="timeline-hash">${shortId}</span>
          <span class="${testBadgeClass}">${testStatus.toUpperCase()}</span>
        </div>
        <div class="timeline-msg">${escapeHTML(cp.message)}</div>
        <div class="timeline-footer">
          <span class="badge ${model.startsWith('gemini') ? 'cyan' : 'purple'}">${model}</span>
          <span>•</span>
          <span>${agent}</span>
          <span>•</span>
          <span>${dateStr}</span>
        </div>
      </div>
    `;
  }).join('');
}

function selectCheckpoint(id) {
  const cp = state.checkpoints.find(c => c.id === id);
  if (!cp) return;
  state.selectedCheckpoint = cp;
  renderTimeline();
  renderInspector();
}

function renderInspector() {
  const container = document.getElementById('inspector-content');
  const cp = state.selectedCheckpoint;
  if (!cp) return;

  document.getElementById('selected-cp-badge').textContent = cp.id.substring(0, 8);
  document.getElementById('selected-cp-timestamp').textContent = cp.timestamp?.substring(0, 19).replace('T', ' ');

  const meta = cp.agent_metadata || {};
  const tools = meta.tools_used || [];

  container.innerHTML = `
    <div class="inspector-section">
      <div class="inspector-label">Commit Message</div>
      <div style="font-weight:600; font-size:1.05rem; margin-bottom:12px;">${escapeHTML(cp.message)}</div>
    </div>

    ${meta.goal ? `
      <div class="inspector-section">
        <div class="inspector-label">Task Prompt / Agent Goal</div>
        <div class="prompt-box">${escapeHTML(meta.goal)}</div>
      </div>
    ` : ''}

    ${meta.reasoning ? `
      <div class="inspector-section">
        <div class="inspector-label">Agent Reasoning & Plan</div>
        <div class="reasoning-box">${escapeHTML(meta.reasoning)}</div>
      </div>
    ` : ''}

    <div class="inspector-section" style="display:flex; gap:16px;">
      <div class="flex-1">
        <div class="inspector-label">Model & Tokens</div>
        <div style="display:flex; gap:8px; align-items:center;">
          <span class="badge cyan">${meta.model || 'manual'}</span>
          <span class="mono text-dim">${(meta.tokens_used || 0).toLocaleString()} tokens</span>
        </div>
      </div>
      <div class="flex-1">
        <div class="inspector-label">Author / Agent ID</div>
        <div style="font-size:0.9rem;">${cp.author} / <span class="mono text-dim">${meta.agent_id || 'human'}</span></div>
      </div>
    </div>

    ${tools.length > 0 ? `
      <div class="inspector-section">
        <div class="inspector-label">Tools Invoked</div>
        <div class="tools-pills">
          ${tools.map(t => `<span class="tool-pill">${escapeHTML(t)}</span>`).join('')}
        </div>
      </div>
    ` : ''}
  `;
}

function renderTrials() {
  const container = document.getElementById('trials-container');
  if (state.trials.length === 0) {
    container.innerHTML = '<div class="empty-state">No speculative trials active.</div>';
    return;
  }

  container.innerHTML = state.trials.map(t => {
    let statusClass = 'badge';
    if (t.status === 'accepted') statusClass += ' green';
    else if (t.status === 'discarded') statusClass += ' rose';
    else statusClass += ' purple';

    return `
      <div class="timeline-item">
        <div class="timeline-top">
          <span class="sym-name">${escapeHTML(t.name)}</span>
          <span class="${statusClass}">${t.status.toUpperCase()}</span>
        </div>
        <div style="font-size:0.8rem; color:var(--text-dim); margin-bottom:4px;">
          Base: <span class="mono">${t.base_checkpoint_id.substring(0, 8)}</span>
          ${t.score !== null ? ` | Score: <b>${t.score}</b>` : ''}
        </div>
        ${t.evaluation_notes ? `<div style="font-size:0.75rem; color:var(--text-muted);">${escapeHTML(t.evaluation_notes)}</div>` : ''}
      </div>
    `;
  }).join('');
}

function renderWorktree() {
  const container = document.getElementById('worktree-files-container');
  const badge = document.getElementById('worktree-status-badge');

  const files = (state.status?.files || []).filter(f => f.status !== 'unmodified');
  if (files.length === 0) {
    badge.textContent = 'Clean ✓';
    badge.className = 'badge green';
    container.innerHTML = '<div class="empty-state">Working directory clean. Ready for agent tasks.</div>';
    return;
  }

  badge.textContent = `${files.length} Modified`;
  badge.className = 'badge amber';

  container.innerHTML = files.map(f => {
    let colorClass = 'cyan';
    if (f.status === 'added') colorClass = 'green';
    else if (f.status === 'deleted') colorClass = 'rose';
    else if (f.status === 'modified') colorClass = 'amber';

    return `
      <div class="symbol-diff-item">
        <span class="mono">${escapeHTML(f.path)}</span>
        <span class="badge ${colorClass}">${f.status.toUpperCase()}</span>
      </div>
    `;
  }).join('');
}

function renderLocks() {
  const container = document.getElementById('locks-container');
  if (state.locks.length === 0) {
    container.innerHTML = '<div class="empty-state">No files or symbols locked. Agents can operate safely.</div>';
    return;
  }

  container.innerHTML = state.locks.map(l => `
    <div class="symbol-diff-item">
      <div>
        <div class="sym-name">${escapeHTML(l.target)}</div>
        <div style="font-size:0.75rem; color:var(--text-muted);">Goal: ${escapeHTML(l.goal || 'Work in progress')}</div>
      </div>
      <div style="text-align:right;">
        <span class="badge amber">${escapeHTML(l.agent_id)}</span>
        <div style="font-size:0.7rem; color:var(--text-muted); margin-top:2px;">Expires: ${l.expires_at.substring(11, 19)}</div>
      </div>
    </div>
  `).join('');
}

function escapeHTML(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// Modal handling
const modal = document.getElementById('modal-checkpoint');
document.getElementById('btn-new-snap').addEventListener('click', () => modal.classList.remove('hidden'));
document.getElementById('modal-close').addEventListener('click', () => modal.classList.add('hidden'));
document.getElementById('btn-cancel-modal').addEventListener('click', () => modal.classList.add('hidden'));

document.getElementById('btn-submit-checkpoint').addEventListener('click', async () => {
  const msg = document.getElementById('input-msg').value.trim();
  if (!msg) {
    alert('Please enter a checkpoint message');
    return;
  }

  const payload = {
    message: msg,
    author: 'Agent Developer',
    agent_metadata: {
      agent_id: document.getElementById('input-agent-id').value,
      model: document.getElementById('input-model').value,
      goal: document.getElementById('input-goal').value,
      reasoning: document.getElementById('input-reasoning').value,
      test_status: document.getElementById('input-test-status').value,
      tokens_used: parseInt(document.getElementById('input-tokens').value) || 0,
    }
  };

  await fetch('/api/checkpoint', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  modal.classList.add('hidden');
  document.getElementById('input-msg').value = '';
  document.getElementById('input-goal').value = '';
  document.getElementById('input-reasoning').value = '';

  await loadAllData();
});

document.getElementById('btn-undo').addEventListener('click', async () => {
  if (confirm('Are you sure you want to undo to the parent checkpoint?')) {
    await fetch('/api/undo', { method: 'POST' });
    await loadAllData();
  }
});

document.getElementById('btn-refresh').addEventListener('click', loadAllData);

// Tab switching
document.querySelectorAll('.nav-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    const target = tab.dataset.tab;
    document.getElementById(target).classList.add('active');
    if (target === 'tab-flight') loadFlightData();
  });
});

// Impact Analysis
document.getElementById('btn-run-impact').addEventListener('click', async () => {
  const target = document.getElementById('input-impact-target').value.trim();
  if (!target) return;
  const container = document.getElementById('impact-results-container');
  container.innerHTML = '<div class="empty-state">Computing dependency graph and blast radius...</div>';

  const data = await fetchJSON(`/api/impact?target=${encodeURIComponent(target)}`);
  if (!data || data.error) {
    container.innerHTML = `<div class="empty-state rose">Error: ${data?.error || 'Target not found'}</div>`;
    return;
  }

  const direct = data.direct_dependents || [];
  const transitive = data.transitive_dependents || [];
  const tests = data.affected_tests || [];

  let riskClass = 'green';
  if (data.risk_level === 'critical') riskClass = 'rose';
  else if (data.risk_level === 'high') riskClass = 'amber';
  else if (data.risk_level === 'medium') riskClass = 'purple';

  container.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
      <div>
        <h3 style="font-size:1.1rem; font-weight:700;">Target: <span class="mono cyan">${escapeHTML(data.target)}</span></h3>
      </div>
      <span class="badge ${riskClass}">${data.risk_level.toUpperCase()} BLAST RADIUS</span>
    </div>

    <div class="impact-grid">
      <div class="impact-card">
        <h4>Direct Dependents (${direct.length})</h4>
        <ul class="impact-list">
          ${direct.length ? direct.map(d => `<li>${escapeHTML(d)}</li>`).join('') : '<li class="text-dim">None (leaf file)</li>'}
        </ul>
      </div>

      <div class="impact-card">
        <h4>Tests to Re-run (${tests.length})</h4>
        <ul class="impact-list">
          ${tests.length ? tests.map(t => `<li style="color:var(--accent-emerald)">✓ ${escapeHTML(t)}</li>`).join('') : '<li class="text-dim">No direct test suites</li>'}
        </ul>
      </div>

      <div class="impact-card" style="grid-column: span 2;">
        <h4>Transitive Downstream Dependents (${transitive.length})</h4>
        <ul class="impact-list">
          ${transitive.length ? transitive.map(t => `<li>${escapeHTML(t)}</li>`).join('') : '<li class="text-dim">No transitive dependents</li>'}
        </ul>
      </div>
    </div>
  `;
});

// Context Generator
document.getElementById('btn-run-context').addEventListener('click', async () => {
  const goal = document.getElementById('input-context-goal').value.trim();
  if (!goal) return;
  const container = document.getElementById('context-output-container');
  container.innerHTML = '<div class="empty-state">Extracting relevant symbol signatures and call graph...</div>';

  const data = await fetchJSON(`/api/context?goal=${encodeURIComponent(goal)}`);
  if (!data || data.error) {
    container.innerHTML = `<div class="empty-state rose">Error generating context.</div>`;
    return;
  }

  container.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
      <span class="badge cyan">${data.approx_tokens} Target Tokens</span>
      <button class="btn btn-secondary" onclick="navigator.clipboard.writeText(document.getElementById('compact-ctx-text').innerText)">Copy to Prompt</button>
    </div>
    <pre id="compact-ctx-text" class="mono" style="background:rgba(0,0,0,0.5); padding:16px; border-radius:8px; font-size:0.8rem; overflow-x:auto; white-space:pre-wrap;">${escapeHTML(data.context)}</pre>
  `;
});

// Flight Recorder
async function loadFlightData() {
  const container = document.getElementById('flight-timeline-container');
  const log = await fetchJSON('/api/flight');
  if (!log || log.length === 0) {
    container.innerHTML = '<div class="empty-state">Flight recorder has no active steps recorded.</div>';
    return;
  }

  container.innerHTML = log.map(step => `
    <div class="timeline-item">
      <div class="timeline-top">
        <span class="mono cyan">Step #${step.step_index}</span>
        <span class="badge ${step.syntax_valid ? 'green' : 'rose'}">${step.syntax_valid ? 'SYNTAX OK' : 'SYNTAX ERROR'}</span>
      </div>
      <div style="font-weight:600; font-size:0.88rem; margin:4px 0;">${escapeHTML(step.action)}</div>
      <div style="font-size:0.75rem; color:var(--text-muted); display:flex; gap:12px;">
        <span>Agent: <b>${escapeHTML(step.agent_id)}</b></span>
        <span>Time: ${step.timestamp.substring(11, 19)}</span>
        <span>Files: ${step.modified_files.length}</span>
      </div>
    </div>
  `).reverse().join('');
}

document.getElementById('btn-rollback-step').addEventListener('click', async () => {
  if (confirm('Rollback 1 micro-step in the flight recorder?')) {
    await fetch('/api/flight/rollback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ steps: 1 }),
    });
    await loadFlightData();
    await loadAllData();
  }
});

// Initial load and periodic refresh
loadAllData();
setInterval(loadAllData, 4000);

