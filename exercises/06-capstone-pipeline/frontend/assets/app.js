// ── API client ────────────────────────────────────────────────────

const api = {
  startRun(query) {
    return fetch('/api/v1/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query }),
    }).then(res => res.json());
  },
  listRuns() {
    return fetch('/api/v1/runs').then(res => res.json());
  },
  getRun(runId) {
    return fetch(`/api/v1/runs/${runId}`).then(res => res.json());
  },
  getReport(runId) {
    return fetch(`/api/v1/runs/${runId}/report`).then(res => res.json());
  },
  approve(runId) {
    return fetch(`/api/v1/runs/${runId}/approve`, { method: 'POST' }).then(res => res.json());
  },
  reject(runId) {
    return fetch(`/api/v1/runs/${runId}/reject`, { method: 'POST' }).then(res => res.json());
  },
};

// ── SSE Stream ────────────────────────────────────────────────────

class RunEventStream {
  constructor(runId, handlers) {
    this.runId = runId;
    this.handlers = handlers;
    this._es = null;
    this._lastId = 0;
  }

  connect() {
    const url = `/api/v1/runs/${this.runId}/events`;
    this._es = new EventSource(url);

    const eventTypes = [
      'stage_start', 'agent_complete', 'skill_complete',
      'hitl_required', 'pipeline_complete', 'pipeline_error', 'terminal', 'error'
    ];

    for (const type of eventTypes) {
      this._es.addEventListener(type, (e) => {
        try {
          const data = JSON.parse(e.data);
          const handler = this.handlers[type];
          if (handler) handler(data);
        } catch (_) {}
      });
    }

    this._es.onerror = () => {
      // Browser auto-reconnects EventSource; nothing needed here
    };
  }

  disconnect() {
    if (this._es) {
      this._es.close();
      this._es = null;
    }
  }
}

// ── Status badge helpers ──────────────────────────────────────────

const STATUS_CLASS = {
  queued:             'badge-queued',
  running:            'badge-running',
  awaiting_approval:  'badge-hitl',
  approved:           'badge-running',
  rejected:           'badge-rejected',
  delivered:          'badge-delivered',
  error:              'badge-error',
};

function setStatusBadge(el, status) {
  el.className = 'badge ' + (STATUS_CLASS[status] || 'badge-queued');
  el.textContent = status.replace('_', ' ');
}

function formatTime(ts) {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleString();
}

// ── Index page ────────────────────────────────────────────────────

const IndexPage = {
  _refreshTimer: null,

  init() {
    this._bindForm();
    this._loadHistory();
    this._refreshTimer = setInterval(() => this._loadHistory(), 10000);
  },

  _bindForm() {
    const form = document.getElementById('run-form');
    const input = document.getElementById('query-input');
    const btn = document.getElementById('submit-btn');
    const errEl = document.getElementById('form-error');

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const query = input.value.trim();
      if (!query) return;

      btn.disabled = true;
      btn.textContent = 'Starting...';
      errEl.classList.add('hidden');

      try {
        const result = await api.startRun(query);
        if (result.run_id) {
          window.location.href = `/run.html?id=${result.run_id}`;
        } else {
          throw new Error(result.detail || 'Unknown error');
        }
      } catch (err) {
        errEl.textContent = 'Failed to start run: ' + err.message;
        errEl.classList.remove('hidden');
        btn.disabled = false;
        btn.textContent = 'Run Pipeline';
      }
    });
  },

  async _loadHistory() {
    const indicator = document.getElementById('refresh-indicator');
    indicator.textContent = 'Refreshing...';

    try {
      const runs = await api.listRuns();
      this._renderHistory(runs);
    } catch (_) {}

    indicator.textContent = '';
  },

  _renderHistory(runs) {
    const body = document.getElementById('history-body');
    if (!runs || runs.length === 0) {
      body.innerHTML = '<div class="loading-row">No runs yet. Submit a query above.</div>';
      return;
    }

    const rows = runs.map(r => {
      const statusClass = STATUS_CLASS[r.status] || 'badge-queued';
      const risk = r.risk_score != null ? r.risk_score.toFixed(2) : '—';
      return `
        <div class="history-row" onclick="window.location='/run.html?id=${r.run_id}'">
          <span class="mono small">${r.run_id}</span>
          <span class="query-col">${escHtml(r.query || '—')}</span>
          <span class="badge ${statusClass}">${(r.status || '').replace('_', ' ')}</span>
          <span class="small">${formatTime(r.started_at)}</span>
          <span class="small">${risk}</span>
        </div>`;
    }).join('');

    body.innerHTML = `
      <div class="history-row history-thead">
        <span>Run ID</span>
        <span>Query</span>
        <span>Status</span>
        <span>Started</span>
        <span>Risk</span>
      </div>
      ${rows}`;
  },
};

// ── Run page ──────────────────────────────────────────────────────

const RunPage = {
  _runId: null,
  _stream: null,
  _reportMarkdown: null,
  _pollTimer: null,

  init() {
    const params = new URLSearchParams(window.location.search);
    this._runId = params.get('id');
    if (!this._runId) {
      window.location.href = '/';
      return;
    }

    document.getElementById('run-id-display').textContent = this._runId;
    this._connectStream();
    this._pollStatus();
    this._bindHitlButtons();
    this._bindExport();
  },

  _connectStream() {
    this._stream = new RunEventStream(this._runId, {
      stage_start:       (d) => this._onStageStart(d),
      agent_complete:    (d) => this._onAgentComplete(d),
      skill_complete:    (d) => this._onSkillComplete(d),
      hitl_required:     (d) => this._onHitlRequired(d),
      pipeline_complete: (d) => this._onPipelineComplete(d),
      pipeline_error:    (d) => this._onPipelineError(d),
      terminal:          (d) => this._onTerminal(d),
    });
    this._stream.connect();
  },

  async _pollStatus() {
    // Poll run status to keep the header badge in sync
    const update = async () => {
      try {
        const run = await api.getRun(this._runId);
        document.getElementById('query-display').textContent = run.query || '—';
        setStatusBadge(document.getElementById('status-badge'), run.status);
      } catch (_) {}
    };
    await update();
    this._pollTimer = setInterval(update, 3000);
  },

  _onStageStart(data) {
    const stageMap = { 1: 'agents', 2: 'skills', 3: 'hitl' };
    const key = stageMap[data.stage];
    if (!key) return;
    const icon = document.getElementById(`icon-${key}`);
    if (icon) icon.innerHTML = '<span class="spinner"></span>';
  },

  _onAgentComplete(data) {
    const el = document.getElementById(`agent-${data.agent}`);
    if (el) el.classList.add('done');

    // Check if all 3 agents done
    const all = ['news_agent', 'sentiment_agent', 'financials_agent']
      .every(n => document.getElementById(`agent-${n}`)?.classList.contains('done'));
    if (all) {
      const icon = document.getElementById('icon-agents');
      if (icon) icon.innerHTML = '&#10003;';
      icon.classList.add('done');
    }
  },

  _onSkillComplete(data) {
    const key = data.skill === 'generate_executive_summary' ? 'generate_executive_summary' : 'classify_risk';
    const el = document.getElementById(`skill-${key}`);
    if (el) el.classList.add('done');

    const all = ['generate_executive_summary', 'classify_risk']
      .every(n => document.getElementById(`skill-${n}`)?.classList.contains('done'));
    if (all) {
      const icon = document.getElementById('icon-skills');
      if (icon) { icon.innerHTML = '&#10003;'; icon.classList.add('done'); }
    }
  },

  _onHitlRequired(data) {
    const icon = document.getElementById('icon-hitl');
    if (icon) icon.innerHTML = '&#9888;';

    document.getElementById('hitl-headline').textContent = data.headline || '—';
    document.getElementById('hitl-risk-level').textContent = data.risk_level || '—';
    document.getElementById('hitl-risk-score').textContent =
      data.risk_score != null ? data.risk_score.toFixed(2) : '—';
    document.getElementById('hitl-reason').textContent = data.reason || '—';

    document.getElementById('hitl-panel').classList.remove('hidden');
  },

  _bindHitlButtons() {
    document.getElementById('btn-approve').addEventListener('click', async () => {
      this._setHitlPending();
      try {
        await api.approve(this._runId);
        document.getElementById('icon-hitl').innerHTML = '&#10003;';
        document.getElementById('icon-hitl').classList.add('done');
      } catch (err) {
        this._setHitlError('Approve failed: ' + err.message);
      }
    });

    document.getElementById('btn-reject').addEventListener('click', async () => {
      this._setHitlPending();
      try {
        await api.reject(this._runId);
        document.getElementById('icon-hitl').innerHTML = '&#10007;';
      } catch (err) {
        this._setHitlError('Reject failed: ' + err.message);
      }
    });
  },

  _setHitlPending() {
    document.getElementById('btn-approve').disabled = true;
    document.getElementById('btn-reject').disabled = true;
    document.getElementById('hitl-pending').classList.remove('hidden');
  },

  _setHitlError(msg) {
    document.getElementById('btn-approve').disabled = false;
    document.getElementById('btn-reject').disabled = false;
    document.getElementById('hitl-pending').textContent = msg;
  },

  async _onPipelineComplete(data) {
    this._stream.disconnect();
    clearInterval(this._pollTimer);

    setStatusBadge(document.getElementById('status-badge'), 'delivered');
    document.getElementById('hitl-panel').classList.add('hidden');

    try {
      const result = await api.getReport(this._runId);
      this._reportMarkdown = result.report_markdown;
      const html = typeof marked !== 'undefined'
        ? marked.parse(this._reportMarkdown)
        : `<pre>${escHtml(this._reportMarkdown)}</pre>`;
      document.getElementById('report-content').innerHTML = html;

      const cost = data.total_cost_usd != null ? `$${Number(data.total_cost_usd).toFixed(4)}` : '—';
      const elapsed = data.elapsed_s != null ? `${Number(data.elapsed_s).toFixed(1)}s` : '—';
      document.getElementById('report-footer').textContent =
        `Total time: ${elapsed}  |  Cost: ${cost}`;

      document.getElementById('report-panel').classList.remove('hidden');
    } catch (err) {
      this._onPipelineError({ error: 'Could not load report: ' + err.message });
    }
  },

  _onPipelineError(data) {
    this._stream.disconnect();
    clearInterval(this._pollTimer);
    setStatusBadge(document.getElementById('status-badge'), 'error');
    document.getElementById('error-message').textContent =
      data.reason || data.error || 'Pipeline failed.';
    document.getElementById('error-panel').classList.remove('hidden');
  },

  _onTerminal(data) {
    if (data.status === 'delivered') return; // pipeline_complete handles this
    if (data.status === 'rejected') {
      this._stream.disconnect();
      clearInterval(this._pollTimer);
      setStatusBadge(document.getElementById('status-badge'), 'rejected');
      document.getElementById('hitl-panel').classList.add('hidden');
      document.getElementById('error-message').textContent =
        'Report was rejected at the HITL approval gate.';
      document.getElementById('error-panel').classList.remove('hidden');
    } else if (data.status === 'error') {
      this._onPipelineError({ error: 'Pipeline encountered an error.' });
    }
  },

  _bindExport() {
    document.getElementById('btn-export').addEventListener('click', () => {
      if (!this._reportMarkdown) return;
      const blob = new Blob([this._reportMarkdown], { type: 'text/markdown' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `report_${this._runId}.md`;
      a.click();
      URL.revokeObjectURL(url);
    });
  },
};

// ── Utilities ─────────────────────────────────────────────────────

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
