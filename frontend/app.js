/* ─────────────────────────────────────────────────────────────────
   app.js — Call Analyzer SPA
   Handles: upload, polling, listing, call detail rendering,
            audio<->transcript synchronization, search.
───────────────────────────────────────────────────────────────── */
const API = '/api/v1';

// ── DOM refs ──────────────────────────────────────────────────────
const uploadZone    = document.getElementById('uploadZone');
const uploadIcon    = document.getElementById('uploadIcon');
const uploadLabel   = document.getElementById('uploadLabel');
const uploadProgress= document.getElementById('uploadProgress');
const progressBar   = document.getElementById('progressBar');
const progressLabel = document.getElementById('progressLabel');
const uploadBtn     = document.getElementById('uploadBtn');
const fileInput     = document.getElementById('fileInput');
const searchInput   = document.getElementById('searchInput');
const callsList     = document.getElementById('callsList');
const callsEmpty    = document.getElementById('callsEmpty');

const welcome       = document.getElementById('welcome');
const detail        = document.getElementById('detail');
const detailFilename= document.getElementById('detailFilename');
const statusBadge   = document.getElementById('statusBadge');
const langBadge     = document.getElementById('langBadge');
const downloadAudio = document.getElementById('downloadAudio');
const closeDetail   = document.getElementById('closeDetail');
const processing    = document.getElementById('processing');
const processingStatus = document.getElementById('processingStatus');
const detailGrid    = document.getElementById('detailGrid');

const playerCard    = document.getElementById('playerCard');
const audioPlayer   = document.getElementById('audioPlayer');
const transcriptBody= document.getElementById('transcriptBody');
const viewTurns     = document.getElementById('viewTurns');
const viewRaw       = document.getElementById('viewRaw');

const summaryCard   = document.getElementById('summaryCard');
const summaryText   = document.getElementById('summaryText');
const sentimentBar  = document.getElementById('sentimentBar');
const sentimentValue= document.getElementById('sentimentValue');
const intentBar     = document.getElementById('intentBar');
const intentValue   = document.getElementById('intentValue');
const keyPointsCard = document.getElementById('keyPointsCard');
const keyPointsList = document.getElementById('keyPointsList');
const tagsCard      = document.getElementById('tagsCard');
const tagsGrid      = document.getElementById('tagsGrid');
const timelineCard  = document.getElementById('timelineCard');
const timeline      = document.getElementById('timeline');

// ── State ─────────────────────────────────────────────────────────
let allCalls        = [];       // all calls from server (list)
let activeCallId    = null;     // currently displayed call
let pollTimer       = null;     // setInterval handle for in-progress calls
let rawTextCache    = '';       // raw transcript text for toggle
let turnsCache      = [];       // parsed turns for toggle
let showRaw         = false;    // transcript view mode

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
  const map = { low: 15, medium: 50, moderate: 50, high: 85, very_high: 98,
                neutral: 50, positive: 80, negative: 15, mixed: 45 };
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
  outcome:        'Outcome',
  next_step:      'Next Step',
  objection:      'Objection',
  compliance_flag:'Compliance',
  product_interest:'Product Interest',
}[key] ?? key.replace(/_/g, ' '));

const slugify = (v) => (v || '—').replace(/_/g, ' ');

// ── API calls ─────────────────────────────────────────────────────
async function fetchCalls() {
  const res = await fetch(`${API}/calls`);
  if (!res.ok) return [];
  return res.json();
}

async function fetchCallDetail(id) {
  const res = await fetch(`${API}/calls/${id}`);
  if (!res.ok) return null;
  return res.json();
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
  const ALLOWED = ['audio/wav', 'audio/mp3', 'audio/mpeg', 'audio/x-wav', 'audio/m4a', 'audio/mp4'];
  const EXT     = /\.(wav|mp3|m4a)$/i;
  if (!EXT.test(file.name)) {
    showUploadError('Unsupported format. Use WAV, MP3 or M4A.'); return;
  }
  if (file.size > 25 * 1024 * 1024) {
    showUploadError('File too large (max 25 MB).'); return;
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
    allCalls = await fetchCalls();
  } catch { allCalls = []; }
  renderCallsList(allCalls);
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
    el.innerHTML = `
      <div class="call-item-name" title="${c.filename}">${c.filename}</div>
      <div class="call-item-meta">
        <span class="badge status-badge status-${c.status}">${c.status}</span>
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
  stopPolling();
  welcome.hidden = false;
  detail.hidden  = true;
  document.querySelectorAll('.call-item').forEach(el => el.classList.remove('active'));
}

async function openCallDetail(id) {
  activeCallId = id;
  stopPolling();
  welcome.hidden = true;
  detail.hidden  = false;
  detailGrid.hidden  = true;
  processing.hidden  = false;
  summaryCard.hidden = keyPointsCard.hidden = tagsCard.hidden = timelineCard.hidden = playerCard.hidden = true;

  document.querySelectorAll('.call-item').forEach(el => {
    el.classList.toggle('active', el.dataset.id === id);
  });

  await renderCallDetail(id);

  // Poll while still processing
  const call = allCalls.find(c => c.id === id);
  if (call && !['COMPLETED', 'FAILED'].includes(call.status)) {
    pollTimer = setInterval(async () => {
      await refreshCallsList();
      await renderCallDetail(id);
      const current = allCalls.find(c => c.id === id);
      if (current && ['COMPLETED', 'FAILED'].includes(current.status)) stopPolling();
    }, 2500);
  }
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

async function renderCallDetail(id) {
  const data = await fetchCallDetail(id);
  if (!data || data.id !== activeCallId) return;

  // Update list badge in sidebar (live sync)
  const idx = allCalls.findIndex(c => c.id === id);
  if (idx >= 0) allCalls[idx] = { ...allCalls[idx], status: data.status };
  renderCallsList(allCalls);

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

  downloadAudio.hidden = !data.storage_path && data.status !== 'FAILED';
  downloadAudio.onclick = () => window.open(`${API}/calls/${id}/audio`, '_blank');
  downloadAudio.hidden = false;

  if (['COMPLETED', 'FAILED'].includes(data.status)) {
    processing.hidden  = true;
    detailGrid.hidden  = false;
    renderTranscript(data.transcript);
    if (data.status === 'COMPLETED') {
      renderSummary(data.summary);
      renderTags(data.tags);
    }
    renderTimeline(data.events);
    // Set up audio player
    if (data.status === 'COMPLETED') {
      audioPlayer.src = `${API}/calls/${id}/audio`;
      playerCard.hidden = false;
    }
  } else {
    processing.hidden   = false;
    detailGrid.hidden   = true;
    processingStatus.textContent = data.status;
  }
}

// ── Transcript ────────────────────────────────────────────────────
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

// Highlight turn as audio plays
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

// ── Summary ───────────────────────────────────────────────────────
function renderSummary(summary) {
  if (!summary) return;
  summaryCard.hidden = false;
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
  if (kp.length > 0) {
    keyPointsCard.hidden = false;
    keyPointsList.innerHTML = kp.map(p => `<li class="key-point-item">${p}</li>`).join('');
  }
}

// ── Tags ──────────────────────────────────────────────────────────
function renderTags(tags) {
  if (!tags || tags.length === 0) return;
  tagsCard.hidden = false;
  tagsGrid.innerHTML = tags.map(t => `
    <div class="tag-chip">
      <span class="tag-category">${humanTag(t.tag_category)}</span>
      <span class="tag-value">${slugify(t.tag_value)}</span>
      <span class="tag-confidence">${Math.round(t.confidence * 100)}% confidence</span>
    </div>`).join('');
}

// ── Timeline ──────────────────────────────────────────────────────
function renderTimeline(events) {
  if (!events || events.length === 0) return;
  timelineCard.hidden = false;
  timeline.innerHTML = events.map(e => {
    const p = e.payload || {};
    const label = e.event_type === 'STATUS_CHANGE'
      ? `${p.from_status ?? '—'} → ${p.to_status ?? '—'}`
      : e.event_type === 'ERROR'
        ? `Error in ${p.step ?? '?'}: ${p.error ?? ''}`
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

// ── Boot ──────────────────────────────────────────────────────────
(async function init() {
  await refreshCallsList();

  // If there is a completed call, open the most recent one automatically
  const first = allCalls.find(c => c.status === 'COMPLETED');
  if (first) openCallDetail(first.id);

  // Periodically refresh list (in case calls finish while app is open)
  setInterval(async () => {
    const prev = allCalls.map(c => c.status).join(',');
    await refreshCallsList();
    const next = allCalls.map(c => c.status).join(',');
    // If active call status changed, re-render detail
    if (prev !== next && activeCallId) await renderCallDetail(activeCallId);
  }, 5000);
})();
