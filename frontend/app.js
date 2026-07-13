/* ─────────────────────────────────────────────────────────────────
   app.js — Call Analyzer SPA (Complete Workflows)
   Handles: upload, list pagination/filters, detail tabs, status polling,
            audio<->transcript seek, interactive tag overrides, export & retry.
   ───────────────────────────────────────────────────────────────── */
const API = '/api/v1';

// --- Canonical Allowed Tag Values matching Backend enums ---
const ALLOWED_TAGS = {
  outcome: [
    { value: 'won_deal_closed', label: 'Won Deal / Closed' },
    { value: 'follow_up_scheduled', label: 'Follow Up Scheduled' },
    { value: 'not_interested', label: 'Not Interested' },
    { value: 'no_decision', label: 'No Decision' },
    { value: 'unresolved_objection', label: 'Unresolved Objection' }
  ],
  sentiment: [
    { value: 'positive', label: 'Positive' },
    { value: 'neutral', label: 'Neutral' },
    { value: 'negative', label: 'Negative' },
    { value: 'mixed', label: 'Mixed' }
  ],
  intent_level: [
    { value: 'high', label: 'High' },
    { value: 'medium', label: 'Medium' },
    { value: 'low', label: 'Low' }
  ],
  objection_type: [
    { value: 'price_budget', label: 'Price & Budget' },
    { value: 'timing_schedule', label: 'Timing & Schedule' },
    { value: 'competitor_brand', label: 'Competitor / Brand' },
    { value: 'no_immediate_need', label: 'No Immediate Need' },
    { value: 'no_purchasing_authority', label: 'No Purchasing Authority' },
    { value: 'no_objections_raised', label: 'None (No Objections)' }
  ],
  next_step: [
    { value: 'demo_scheduled', label: 'Demo Scheduled' },
    { value: 'send_proposal', label: 'Send Proposal' },
    { value: 'call_again_follow_up', label: 'Call Again / Follow Up' },
    { value: 'escalated_to_supervisor', label: 'Escalate to Supervisor' },
    { value: 'closed_lost', label: 'Closed / Lost' }
  ],
  compliance_flag: [
    { value: 'possible_sensitive_data', label: 'Possible Sensitive Data' },
    { value: 'inappropriate_language', label: 'Inappropriate Language' },
    { value: 'none', label: 'None (Compliant)' }
  ]
};

// ── DOM refs ──────────────────────────────────────────────────────
const uploadZone     = document.getElementById('uploadZone');
const uploadIcon     = document.getElementById('uploadIcon');
const uploadLabel    = document.getElementById('uploadLabel');
const uploadProgress = document.getElementById('uploadProgress');
const progressBar    = document.getElementById('progressBar');
const progressLabel  = document.getElementById('progressLabel');
const uploadBtn      = document.getElementById('uploadBtn');
const fileInput      = document.getElementById('fileInput');
const searchInput    = document.getElementById('searchInput');
const callsList      = document.getElementById('callsList');
const callsEmpty     = document.getElementById('callsEmpty');

const welcome        = document.getElementById('welcome');
const detail         = document.getElementById('detail');
const detailFilename = document.getElementById('detailFilename');
const statusBadge    = document.getElementById('statusBadge');
const langBadge      = document.getElementById('langBadge');
const downloadAudio  = document.getElementById('downloadAudio');
const exportCallJson = document.getElementById('exportCallJson');
const closeDetail    = document.getElementById('closeDetail');
const processing     = document.getElementById('processing');
const processingStatus = document.getElementById('processingStatus');
const failedState    = document.getElementById('failedState');
const errorMessageText = document.getElementById('errorMessageText');
const btnRetryCall   = document.getElementById('btnRetryCall');
const detailGrid     = document.getElementById('detailGrid');

// Polling and Stats DOM refs
const pollingIndicator = document.getElementById('pollingIndicator');
const statTotalCalls   = document.getElementById('statTotalCalls');
const statConvRate     = document.getElementById('statConvRate');
const statPosSentiment = document.getElementById('statPosSentiment');
const statTopObjection = document.getElementById('statTopObjection');

// Detail Content DOM refs
const audioPlayer    = document.getElementById('audioPlayer');
const transcriptBody = document.getElementById('transcriptBody');
const viewTurns      = document.getElementById('viewTurns');
const viewRaw        = document.getElementById('viewRaw');

const summaryCard    = document.getElementById('summaryCard');
const summaryText    = document.getElementById('summaryText');
const sentimentBar   = document.getElementById('sentimentBar');
const sentimentValue = document.getElementById('sentimentValue');
const intentBar      = document.getElementById('intentBar');
const intentValue    = document.getElementById('intentValue');
const keyPointsCard  = document.getElementById('keyPointsCard');
const keyPointsList  = document.getElementById('keyPointsList');
const timelineCard   = document.getElementById('timelineCard');
const timeline       = document.getElementById('timeline');

// Tab Navigation Refs
const btnTabOverview   = document.getElementById('btnTabOverview');
const btnTabTranscript = document.getElementById('btnTabTranscript');
const btnTabTagging    = document.getElementById('btnTabTagging');
const tabContentOverview   = document.getElementById('tabContentOverview');
const tabContentTranscript = document.getElementById('tabContentTranscript');
const tabContentTagging    = document.getElementById('tabContentTagging');

// Action Prescriptions & Inconsistencies Refs
const nextStepText        = document.getElementById('nextStepText');
const inconsistenciesBox  = document.getElementById('inconsistenciesBox');
const inconsistenciesList = document.getElementById('inconsistenciesList');

// QC Overrides & Products Grid Refs
const tagOverridesContainer = document.getElementById('tagOverridesContainer');
const productInterestsGrid  = document.getElementById('productInterestsGrid');

// ── State ─────────────────────────────────────────────────────────
let allCalls        = [];       // all calls metadata list
let activeCallId    = null;     // currently displayed call
let pollTimer       = null;     // setInterval handle for active processing call
let sidebarPollTimer= null;     // setInterval handle for refreshing list when active calls exist
let rawTextCache    = '';       // raw transcript text for toggle
let turnsCache      = [];       // parsed turns for toggle
let showRaw         = false;    // transcript view mode
let activeTab       = 'overview'; // 'overview' | 'transcript' | 'tagging'

// ── Helpers ───────────────────────────────────────────────────────
const fmtTime = (iso) => {
  if (!iso) return '—';
  const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
};

const fmtSecs = (s) => {
  if (s == null) return '';
  const m = Math.floor(s / 60);
  const sec = String(Math.floor(s % 60)).padStart(2, '0');
  return `${m}:${sec}`;
};

const pct = (val) => {
  if (val == null) return 0;
  if (typeof val === 'number') return Math.round(val * 100);
  const map = {
    low: 15, medium: 50, moderate: 50, high: 85, very_high: 98,
    neutral: 50, positive: 85, negative: 15, mixed: 45
  };
  return map[val?.toLowerCase?.()] ?? 50;
};

const avatarInitials = (speaker) => {
  if (!speaker) return '?';
  return speaker.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase();
};

const avatarClass = (speaker) => {
  if (!speaker) return 'default';
  const lower = speaker.toLowerCase();
  if (lower.includes('agent') || lower.includes('asesor') || lower.includes('vendedor') || lower.includes('ejecutivo')) return 'agent';
  if (lower.includes('client') || lower.includes('cliente') || lower.includes('customer')) return 'client';
  return 'default';
};

const humanTag = (key) => ({
  outcome:         'Outcome Status',
  sentiment:       'Customer Sentiment',
  intent_level:    'Purchase Intent Level',
  objection_type:  'Primary Objection',
  next_step:       'Prescribed Next Step',
  compliance_flag: 'Compliance Flag',
  product_interest:'Product Interest',
}[key] ?? key.replace(/_/g, ' '));

const slugify = (v) => (v || '—').replace(/_/g, ' ');

// ── API calls ─────────────────────────────────────────────────────
async function fetchCalls() {
  const res = await fetch(`${API}/calls?page_size=100`);
  if (!res.ok) return { items: [] };
  return res.json();
}

async function fetchCallDetail(id) {
  const res = await fetch(`${API}/calls/${id}`);
  if (!res.ok) return null;
  return res.json();
}

async function fetchAnalyticsSummary() {
  const res = await fetch(`${API}/analytics/summary`);
  if (!res.ok) return null;
  return res.json();
}

async function sendTagOverride(id, category, value, reason) {
  const res = await fetch(`${API}/calls/${id}/tags`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ category, value, reason })
  });
  return res.ok;
}

async function triggerCallRetry(id) {
  const res = await fetch(`${API}/calls/${id}/retry`, { method: 'POST' });
  return res.ok;
}

// ── Analytics Stats Loader ────────────────────────────────────────
async function refreshStats() {
  const data = await fetchAnalyticsSummary();
  if (!data) return;

  statTotalCalls.textContent = data.total_calls;
  statConvRate.textContent = `${data.conversion_rate}%`;
  
  // Compute positive sentiment percentage from sentiment distribution
  const sentiment = data.sentiment_distribution || {};
  const totalWithSentiment = Object.values(sentiment).reduce((a, b) => a + b, 0);
  const posCount = sentiment.positive || 0;
  const posPct = totalWithSentiment > 0 ? Math.round((posCount / totalWithSentiment) * 100) : 0;
  statPosSentiment.textContent = `${posPct}%`;

  statTopObjection.textContent = slugify(data.top_objection || 'None');
}

// ── Tab Management ────────────────────────────────────────────────
function setupTabEvents() {
  const tabs = [
    { btn: btnTabOverview, content: tabContentOverview, name: 'overview' },
    { btn: btnTabTranscript, content: tabContentTranscript, name: 'transcript' },
    { btn: btnTabTagging, content: tabContentTagging, name: 'tagging' }
  ];

  tabs.forEach(tab => {
    tab.btn.addEventListener('click', () => {
      tabs.forEach(t => {
        t.btn.classList.toggle('active', t.btn === tab.btn);
        t.content.hidden = t.content !== tab.content;
      });
      activeTab = tab.name;
    });
  });
}

function resetTabs() {
  btnTabOverview.classList.add('active');
  btnTabTranscript.classList.remove('active');
  btnTabTagging.classList.remove('active');
  tabContentOverview.hidden = false;
  tabContentTranscript.hidden = true;
  tabContentTagging.hidden = true;
  activeTab = 'overview';
}

// ── Upload ────────────────────────────────────────────────────────
uploadBtn.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', () => { if (fileInput.files[0]) handleFile(fileInput.files[0]); });

uploadZone.addEventListener('dragover', (e) => { e.preventDefault(); uploadZone.classList.add('dragover'); });
uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('dragover'));
uploadZone.addEventListener('drop', (e) => {
  e.preventDefault();
  uploadZone.classList.remove('dragover');
  const f = e.dataTransfer.files[0];
  if (f) handleFile(f);
});

function handleFile(file) {
  const EXT = /\.(wav|mp3|m4a)$/i;
  if (!EXT.test(file.name)) {
    showUploadError('Unsupported format. Use WAV, MP3 or M4A.'); return;
  }
  if (file.size > 100 * 1024 * 1024) { // matching MAX_UPLOAD_MB=100
    showUploadError('File too large (max 100 MB).'); return;
  }
  startUpload(file);
}

function showUploadError(msg) {
  uploadLabel.textContent = msg;
  uploadLabel.style.color = 'var(--red)';
  setTimeout(() => { uploadLabel.textContent = 'Drop audio here'; uploadLabel.style.color = ''; }, 3000);
}

function startUpload(file) {
  uploadZone.querySelector('.upload-inner').hidden = true;
  uploadProgress.hidden = false;
  progressBar.style.width = '0%';
  progressLabel.textContent = 'Uploading…';

  const form = new FormData();
  form.append('file', file);

  const xhr = new XMLHttpRequest();
  xhr.open('POST', `${API}/calls`);
  xhr.upload.addEventListener('progress', (e) => {
    if (e.lengthComputable) {
      const p = Math.round((e.loaded / e.total) * 100);
      progressBar.style.width = `${p}%`;
      progressLabel.textContent = `Uploading… ${p}%`;
    }
  });
  xhr.addEventListener('load', async () => {
    if (xhr.status === 202) {
      progressBar.style.width = '100%';
      progressLabel.textContent = 'Upload complete!';
      const data = JSON.parse(xhr.responseText);
      setTimeout(() => resetUploadZone(), 1500);
      await refreshCallsList();
      await refreshStats();
      openCallDetail(data.call_id);
    } else {
      progressLabel.textContent = 'Upload failed.';
      progressBar.style.background = 'var(--red)';
      setTimeout(resetUploadZone, 2500);
    }
  });
  xhr.addEventListener('error', () => {
    progressLabel.textContent = 'Network error.';
    setTimeout(resetUploadZone, 2500);
  });
  xhr.send(form);
}

function resetUploadZone() {
  uploadZone.querySelector('.upload-inner').hidden = false;
  uploadProgress.hidden = true;
  progressBar.style.width = '0%';
  progressBar.style.background = '';
  fileInput.value = '';
}

// ── Calls List ────────────────────────────────────────────────────
async function refreshCallsList() {
  try {
    const res = await fetchCalls();
    allCalls = res.items || [];
  } catch { allCalls = []; }
  renderCallsList(allCalls);
  
  // Check if we need to poll sidebar updates
  const hasActiveJob = allCalls.some(c => !['COMPLETED', 'FAILED', 'DONE'].includes(c.status));
  if (hasActiveJob && !sidebarPollTimer) {
    sidebarPollTimer = setInterval(async () => {
      await refreshCallsList();
      if (activeCallId) {
        const activeCall = allCalls.find(c => c.id === activeCallId);
        if (activeCall && ['COMPLETED', 'FAILED', 'DONE'].includes(activeCall.status)) {
          await renderCallDetail(activeCallId);
        }
      }
    }, 5000);
  } else if (!hasActiveJob && sidebarPollTimer) {
    clearInterval(sidebarPollTimer);
    sidebarPollTimer = null;
  }
}

function renderCallsList(calls) {
  const q = searchInput.value.toLowerCase();
  const filtered = q ? calls.filter(c => c.filename.toLowerCase().includes(q)) : calls;

  callsList.innerHTML = '';
  if (filtered.length === 0) {
    callsList.appendChild(callsEmpty);
    callsEmpty.hidden = false;
    return;
  }
  callsEmpty.hidden = true;
  filtered.forEach(c => {
    const el = document.createElement('div');
    el.className = 'call-item' + (c.id === activeCallId ? ' active' : '');
    el.dataset.id = c.id;
    
    const sentimentBadge = c.sentiment 
      ? `<span class="badge sentiment-badge sentiment-${c.sentiment}">${c.sentiment.toUpperCase()}</span>` 
      : '';

    el.innerHTML = `
      <div class="call-item-name" title="${c.filename}">${c.filename}</div>
      <div class="call-item-meta">
        <span class="badge status-badge status-${c.status}">${c.status}</span>
        ${sentimentBadge}
        <span class="call-item-time">${fmtTime(c.uploaded_at)}</span>
      </div>`;
    el.addEventListener('click', () => openCallDetail(c.id));
    callsList.appendChild(el);
  });
}

searchInput.addEventListener('input', () => renderCallsList(allCalls));

// ── Detail View ───────────────────────────────────────────────────
closeDetail.addEventListener('click', closeDetailPanel);

function closeDetailPanel() {
  activeCallId = null;
  stopActivePolling();
  welcome.hidden = false;
  detail.hidden  = true;
  document.querySelectorAll('.call-item').forEach(el => el.classList.remove('active'));
}

async function openCallDetail(id) {
  activeCallId = id;
  stopActivePolling();
  resetTabs();

  // Leave the architecture page if it was open
  if (architecturePage && !architecturePage.hidden) {
    architecturePage.hidden = true;
    statsRow.hidden = false;
    btnArchitecture.classList.remove('active');
  }

  welcome.hidden = true;
  detail.hidden  = false;
  detailGrid.hidden  = true;
  processing.hidden  = false;
  failedState.hidden = true;

  document.querySelectorAll('.call-item').forEach(el => {
    el.classList.toggle('active', el.dataset.id === id);
  });

  await renderCallDetail(id);
}

function startActivePolling(id) {
  stopActivePolling();
  pollingIndicator.hidden = false;
  
  pollTimer = setInterval(async () => {
    const statusData = await fetch(`${API}/calls/${id}/status`).then(r => r.ok ? r.json() : null);
    if (!statusData || statusData.call_id !== activeCallId) return;

    processingStatus.textContent = `${statusData.status} (${statusData.progress}%)`;
    
    if (['COMPLETED', 'FAILED', 'DONE'].includes(statusData.status)) {
      stopActivePolling();
      await renderCallDetail(id);
      await refreshCallsList();
      await refreshStats();
    }
  }, 3000);
}

function stopActivePolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  pollingIndicator.hidden = true;
}

async function renderCallDetail(id) {
  const data = await fetchCallDetail(id);
  if (!data || data.id !== activeCallId) return;

  // Header
  detailFilename.textContent = data.filename;
  statusBadge.textContent    = data.status;
  statusBadge.className      = `badge status-badge status-${data.status}`;

  if (data.transcript?.language) {
    langBadge.textContent = data.transcript.language.toUpperCase();
    langBadge.hidden = false;
  } else {
    langBadge.hidden = true;
  }

  // Audio download
  downloadAudio.hidden = !data.storage_path;
  downloadAudio.onclick = () => window.open(`${API}/calls/${id}/audio`, '_blank');
  
  // Export JSON bind
  exportCallJson.onclick = () => window.open(`${API}/calls/${id}/export`, '_blank');

  // Failed state retry button bind
  btnRetryCall.onclick = async () => {
    failedState.hidden = true;
    processing.hidden = false;
    const ok = await triggerCallRetry(id);
    if (ok) {
      await refreshCallsList();
      startActivePolling(id);
    } else {
      alert("Failed to enqueue retry job.");
    }
  };

  if (['COMPLETED', 'DONE'].includes(data.status)) {
    processing.hidden  = true;
    failedState.hidden = true;
    detailGrid.hidden  = false;
    
    // Bind playback src
    audioPlayer.src = `${API}/calls/${id}/audio`;
    
    // Render content panels
    renderSummary(data.summary);
    renderTranscript(data.transcript);
    renderQCPanel(data);
    renderTimeline(data.events);
  } else if (data.status === 'FAILED') {
    processing.hidden  = true;
    detailGrid.hidden  = true;
    failedState.hidden = false;
    
    // Extract failure message from events
    const errEvent = data.events?.find(e => e.event_type.includes('ERROR'));
    errorMessageText.textContent = errEvent?.payload?.error || 'An unknown error occurred during pipeline execution.';
    renderTimeline(data.events);
  } else {
    processing.hidden  = false;
    detailGrid.hidden  = true;
    failedState.hidden = true;
    
    const progressMap = { PENDING: 5, TRANSCRIBING: 35, TRANSCRIBED: 60, ANALYZING: 85 };
    const progress = progressMap[data.status] || 0;
    processingStatus.textContent = `${data.status} (${progress}%)`;
    
    startActivePolling(id);
  }
}

// ── Transcript Renderer ───────────────────────────────────────────
viewTurns.addEventListener('click', () => { showRaw = false; viewTurns.classList.add('active'); viewRaw.classList.remove('active'); renderTurnsOrRaw(); });
viewRaw.addEventListener('click',   () => { showRaw = true;  viewRaw.classList.add('active');   viewTurns.classList.remove('active'); renderTurnsOrRaw(); });

function renderTranscript(transcript) {
  if (!transcript) {
    transcriptBody.innerHTML = '<p style="color:var(--text-muted);padding:14px;">Transcript not available.</p>';
    return;
  }
  turnsCache  = transcript.turns  || [];
  rawTextCache= transcript.raw_text || '';
  showRaw     = false;
  viewTurns.classList.add('active');
  viewRaw.classList.remove('active');
  renderTurnsOrRaw();
}

function renderTurnsOrRaw() {
  if (showRaw) {
    transcriptBody.innerHTML = `<pre class="raw-text">${rawTextCache}</pre>`;
    return;
  }
  transcriptBody.innerHTML = '';
  turnsCache.forEach((turn, i) => {
    const el = document.createElement('div');
    el.className = 'turn';
    el.dataset.start = turn.start;
    const cls = avatarClass(turn.speaker);
    el.innerHTML = `
      <div class="turn-avatar ${cls}">${avatarInitials(turn.speaker)}</div>
      <div class="turn-content">
        <div class="turn-speaker">${turn.speaker || 'Unknown'}</div>
        <div class="turn-text">${turn.text}</div>
      </div>
      <div class="turn-time">${fmtSecs(turn.start)}</div>`;
    el.addEventListener('click', () => seekAudio(turn.start, el));
    transcriptBody.appendChild(el);
  });
}

function seekAudio(start, turnEl) {
  if (!audioPlayer.src || audioPlayer.src === window.location.href) return;
  audioPlayer.currentTime = start;
  audioPlayer.play().catch(() => {});
  document.querySelectorAll('.turn').forEach(el => el.classList.remove('highlight'));
  turnEl.classList.add('highlight');
  turnEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// Highlight dialogue turns dynamically as audio plays
audioPlayer.addEventListener('timeupdate', () => {
  const t = audioPlayer.currentTime;
  let active = null;
  turnsCache.forEach((turn, i) => {
    if (t >= turn.start && t < (turnsCache[i+1]?.start ?? Infinity)) active = i;
  });
  document.querySelectorAll('.turn').forEach((el, i) => {
    el.classList.toggle('highlight', i === active);
  });
});

// ── Summary Renderer ──────────────────────────────────────────────
function renderSummary(summary) {
  if (!summary) return;
  summaryText.textContent = summary.summary_text || '—';

  const insights = summary.insights || {};
  const sentScore = pct(insights.sentiment_score ?? insights.sentiment);
  sentimentBar.style.width  = `${sentScore}%`;
  sentimentValue.textContent= insights.sentiment ? `${insights.sentiment} (${sentScore}%)` : `${sentScore}%`;

  const intScore = pct(insights.intent_score ?? insights.purchase_intent);
  intentBar.style.width  = `${intScore}%`;
  intentValue.textContent= insights.purchase_intent ? `${slugify(insights.purchase_intent)} (${intScore}%)` : `${intScore}%`;

  // Key points
  const kp = summary.key_points || [];
  keyPointsList.innerHTML = kp.length > 0
    ? kp.map(p => `<li class="key-point-item">${p}</li>`).join('')
    : '<li style="color:var(--text-muted);">No key points recorded.</li>';

  // Prescribed Next Step
  nextStepText.textContent = slugify(insights.next_step || 'None prescribed');

  // Inconsistencies Box
  const inc = insights.inconsistencies || [];
  if (inc.length > 0) {
    inconsistenciesBox.hidden = false;
    inconsistenciesList.innerHTML = inc.map(i => `<li>${i}</li>`).join('');
  } else {
    inconsistenciesBox.hidden = true;
  }
}

// ── QC Panel Overrides Renderer ───────────────────────────────────
function renderQCPanel(call) {
  // 1. Render closed override categories
  tagOverridesContainer.innerHTML = '';
  
  // Group call's tags for access
  const effectiveTags = {};
  const modelTags = {};
  const overrideTags = {};
  
  call.tags.forEach(t => {
    const cat = t.tag_category;
    if (t.source === 'override') {
      overrideTags[cat] = t;
    } else {
      modelTags[cat] = t;
    }
    // Effective tag computation logic (override takes precedence)
    if (!effectiveTags[cat] || t.source === 'override') {
      effectiveTags[cat] = t;
    }
  });

  Object.entries(ALLOWED_TAGS).forEach(([category, options]) => {
    const effTag = effectiveTags[category];
    const effValue = effTag?.tag_value || '';
    const modelTag = modelTags[category];
    const hasOverride = !!overrideTags[category];
    const modelConf = modelTag ? Math.round(modelTag.confidence * 100) : null;

    const groupEl = document.createElement('div');
    groupEl.className = 'qc-override-group';
    
    // Add overridden badge
    const overriddenBadge = hasOverride ? '<span class="qc-badge-overridden">Overridden</span>' : '';
    const confidenceText = modelConf !== null ? `<span class="qc-confidence-label">AI Confidence: ${modelConf}%</span>` : '';

    groupEl.innerHTML = `
      <div class="qc-group-header">
        <span class="qc-group-title">${humanTag(category)}</span>
        ${overriddenBadge}
      </div>
      ${confidenceText}
      <div class="qc-pill-grid"></div>
      <input type="text" class="qc-reason-input" placeholder="Optional audit override reason..." value="${effTag?.reason || ''}" />
    `;

    const pillGrid = groupEl.querySelector('.qc-pill-grid');
    const reasonInput = groupEl.querySelector('.qc-reason-input');

    options.forEach(opt => {
      const btn = document.createElement('button');
      btn.className = 'qc-pill' + (opt.value === effValue ? ' selected' : '');
      btn.textContent = opt.label;
      
      btn.addEventListener('click', async () => {
        if (opt.value === effValue) return; // ignore click if already selected

        const previousClass = btn.className;
        // Optimistic UI updates
        pillGrid.querySelectorAll('.qc-pill').forEach(p => p.classList.remove('selected'));
        btn.classList.add('selected');

        const ok = await sendTagOverride(call.id, category, opt.value, reasonInput.value);
        if (ok) {
          await renderCallDetail(call.id);
          await refreshCallsList();
          await refreshStats();
        } else {
          alert('Failed to save override tag.');
          // Revert selection
          btn.className = previousClass;
        }
      });
      pillGrid.appendChild(btn);
    });

    // Update override on reason blur
    reasonInput.addEventListener('blur', async () => {
      if (reasonInput.value !== (effTag?.reason || '')) {
        await sendTagOverride(call.id, category, effValue, reasonInput.value);
        await renderCallDetail(call.id);
      }
    });

    tagOverridesContainer.appendChild(groupEl);
  });

  // 2. Render read-only Product Interests
  productInterestsGrid.innerHTML = '';
  const productTags = call.tags.filter(t => t.tag_category === 'product_interest');
  if (productTags.length > 0) {
    productInterestsGrid.innerHTML = productTags.map(t => `
      <span class="product-interest-chip">${slugify(t.tag_value)}</span>
    `).join('');
  } else {
    productInterestsGrid.innerHTML = '<span style="color:var(--text-muted);font-size:12.5px;padding:0 4px;">No product interests identified.</span>';
  }
}

// ── Timeline Renderer ─────────────────────────────────────────────
function renderTimeline(events) {
  if (!events || events.length === 0) {
    timelineCard.hidden = true;
    return;
  }
  timelineCard.hidden = false;
  timeline.innerHTML = events.map(e => {
    const p = e.payload || {};
    const label = e.event_type === 'STATUS_CHANGE'
      ? `${p.from_status ?? '—'} → ${p.to_status ?? '—'}`
      : e.event_type === 'ERROR'
        ? `Error: ${p.error ?? ''}`
        : JSON.stringify(p);
    const dotCls = p.to_status === 'COMPLETED' ? 'completed' : p.to_status === 'FAILED' ? 'failed' : '';
    return `
      <li class="timeline-item">
        <div class="timeline-dot ${dotCls}"></div>
        <div class="timeline-content">
          <div class="timeline-event">${e.event_type}</div>
          <div class="timeline-detail">${label}</div>
        </div>
        <div class="timeline-time">${fmtTime(e.created_at)}</div>
      </li>`;
  }).join('');
}

// ── Architecture page ─────────────────────────────────────────────
const btnArchitecture   = document.getElementById('btnArchitecture');
const closeArchitecture = document.getElementById('closeArchitecture');
const architecturePage  = document.getElementById('architecturePage');
const statsRow          = document.getElementById('statsRow');
const archSummary       = document.getElementById('archSummary');
const archConstraints   = document.getElementById('archConstraints');
const archLayers        = document.getElementById('archLayers');
const archPipeline      = document.getElementById('archPipeline');
const archScaling       = document.getElementById('archScaling');

const LAYER_ICON = {
  client: 'i-monitor', api: 'i-brackets', storage: 'i-cloud', queue: 'i-layers',
  stt: 'i-mic', llm: 'i-sparkles', state: 'i-refresh', db: 'i-database',
  observability: 'i-activity',
};

let architectureLoaded = false;

async function fetchArchitecture() {
  const res = await fetch(`${API}/architecture`);
  if (!res.ok) return null;
  return res.json();
}

function renderArchitecture(data) {
  archSummary.textContent = data.summary;

  archConstraints.innerHTML = (data.constraints || [])
    .map(c => `<span class="arch-constraint">${c}</span>`).join('');

  archLayers.innerHTML = (data.layers || []).map(l => {
    const icon = LAYER_ICON[l.id] || 'i-layers';
    const bps = (l.best_practices || []).map(b => `<li>${b}</li>`).join('');
    return `
      <div class="arch-layer">
        <div class="arch-layer-head">
          <span class="arch-layer-icon"><svg class="icon" aria-hidden="true"><use href="#${icon}"/></svg></span>
          <div>
            <div class="arch-layer-title">${l.title}</div>
            <div class="arch-layer-tech">${l.tech}</div>
          </div>
        </div>
        <p class="arch-layer-resp">${l.responsibility}</p>
        <ul class="arch-bp-list">${bps}</ul>
      </div>`;
  }).join('');

  archPipeline.innerHTML = (data.pipeline || []).map((s, i) => `
    <li class="arch-step">
      <span class="arch-step-num">${i + 1}</span>
      <div class="arch-step-body">
        <div class="arch-step-head">
          <span class="arch-step-name">${s.step}</span>
          <span class="arch-step-state">${s.state}</span>
        </div>
        <p class="arch-step-detail">${s.detail}</p>
      </div>
    </li>`).join('');

  const sc = data.scaling || {};
  const strategy = (sc.strategy || []).map(s =>
    `<div class="arch-strategy-item"><div class="t">${s.title}</div><div class="d">${s.detail}</div></div>`).join('');
  const bottlenecks = (sc.bottlenecks || []).map(b =>
    `<div class="arch-bottleneck"><div class="bn">${b.name}</div><div class="bm">${b.mitigation}</div></div>`).join('');
  const pii = (sc.pii || []).map(p => `<li>${p}</li>`).join('');

  archScaling.innerHTML = `
    <div class="arch-scale-envs">
      <div class="arch-scale-env"><h4>Development</h4><p>${sc.dev || ''}</p></div>
      <div class="arch-scale-env"><h4>Production</h4><p>${sc.production || ''}</p></div>
    </div>
    <div>
      <div class="arch-subhead">Scaling strategy</div>
      <div class="arch-strategy-grid">${strategy}</div>
    </div>
    <div>
      <div class="arch-subhead">Bottlenecks &amp; mitigations</div>
      ${bottlenecks}
    </div>
    <div>
      <div class="arch-subhead">PII handling</div>
      <ul class="arch-pii-list">${pii}</ul>
    </div>`;
}

async function showArchitecture() {
  stopActivePolling();
  activeCallId = null;
  document.querySelectorAll('.call-item').forEach(el => el.classList.remove('active'));

  welcome.hidden = true;
  detail.hidden = true;
  statsRow.hidden = true;
  architecturePage.hidden = false;
  btnArchitecture.classList.add('active');
  architecturePage.scrollTop = 0;

  if (!architectureLoaded) {
    const data = await fetchArchitecture();
    if (data) { renderArchitecture(data); architectureLoaded = true; }
    else { archSummary.textContent = 'Could not load architecture document.'; }
  }
}

function hideArchitecture() {
  architecturePage.hidden = true;
  statsRow.hidden = false;
  btnArchitecture.classList.remove('active');
  welcome.hidden = false;
  detail.hidden = true;
}

btnArchitecture.addEventListener('click', showArchitecture);
closeArchitecture.addEventListener('click', hideArchitecture);

// ── Boot ──────────────────────────────────────────────────────────
(async function init() {
  setupTabEvents();
  await refreshCallsList();
  await refreshStats();

  // If there is a completed call, open the most recent one automatically on boot
  const first = allCalls.find(c => c.status === 'COMPLETED' || c.status === 'DONE');
  if (first) openCallDetail(first.id);

  // Periodically refresh list of calls & stats every 8s
  setInterval(async () => {
    await refreshStats();
  }, 8000);
})();
