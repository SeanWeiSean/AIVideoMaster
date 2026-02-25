/**
 * AI Video Master - Frontend Logic
 */

const API_BASE = 'http://127.0.0.1:5678';
let currentSession = null;
let pollTimer = null;
let logOffset = 0;

// ── Navigation ──────────────────────────────────────────────

document.querySelectorAll('.nav-item').forEach(item => {
  item.addEventListener('click', () => {
    const page = item.dataset.page;
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    item.classList.add('active');
    document.getElementById(`page-${page}`).classList.add('active');
  });
});

// ── Server Health Check ─────────────────────────────────────

async function checkServer() {
  try {
    const res = await fetch(`${API_BASE}/api/health`);
    if (res.ok) {
      document.getElementById('serverStatus').className = 'status-dot connected';
      document.getElementById('serverStatusText').textContent = '已连接';
      return true;
    }
  } catch (e) {}
  document.getElementById('serverStatus').className = 'status-dot error';
  document.getElementById('serverStatusText').textContent = '未连接';
  return false;
}

setInterval(checkServer, 5000);
checkServer();

// ── Topic Pipeline ──────────────────────────────────────────

async function startTopicPipeline() {
  const topic = document.getElementById('topicInput').value.trim();
  if (!topic) { alert('请输入视频主题'); return; }

  const discussOnly = document.getElementById('topicDiscussOnly').checked;
  const qualityMode = document.getElementById('topicQuality').value;

  document.getElementById('topicStartBtn').disabled = true;
  document.getElementById('topicStopBtn').disabled = false;
  document.getElementById('topicResultPanel').classList.add('hidden');
  clearLogs('topicLogs');
  setRunStatus('topicRunStatus', 'running', '运行中...');

  try {
    await fetch(`${API_BASE}/api/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ quality_mode: qualityMode }),
    });

    const res = await fetch(`${API_BASE}/api/topic/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic, discuss_only: discussOnly }),
    });
    const data = await res.json();
    currentSession = data.session_id;
    logOffset = 0;
    startPolling('topicLogs', 'topicRunStatus', 'topicResultPanel', 'topicResults', 'topic');
  } catch (e) {
    setRunStatus('topicRunStatus', 'error', '启动失败');
    document.getElementById('topicStartBtn').disabled = false;
    appendLog('topicLogs', `❌ 启动失败: ${e.message}`, 'error');
  }
}

// ── Novel Pipeline ──────────────────────────────────────────

async function startNovelPipeline() {
  const text = document.getElementById('novelInput').value.trim();
  if (!text) { alert('请输入小说文字'); return; }

  const discussOnly = document.getElementById('novelDiscussOnly').checked;

  document.getElementById('novelStartBtn').disabled = true;
  document.getElementById('novelStopBtn').disabled = false;
  document.getElementById('novelResultPanel').classList.add('hidden');
  clearLogs('novelLogs');
  setRunStatus('novelRunStatus', 'running', '运行中...');

  try {
    const res = await fetch(`${API_BASE}/api/novel/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ novel_text: text, discuss_only: discussOnly }),
    });
    const data = await res.json();
    currentSession = data.session_id;
    logOffset = 0;
    startPolling('novelLogs', 'novelRunStatus', 'novelResultPanel', 'novelResults', 'novel');
  } catch (e) {
    setRunStatus('novelRunStatus', 'error', '启动失败');
    document.getElementById('novelStartBtn').disabled = false;
    appendLog('novelLogs', `❌ 启动失败: ${e.message}`, 'error');
  }
}

function updateCharCount() {
  const len = document.getElementById('novelInput').value.length;
  document.getElementById('novelCharCount').textContent = `${len} 字`;
}

// ── Log Polling ─────────────────────────────────────────────

function startPolling(logContainerId, statusId, resultPanelId, resultBodyId, mode) {
  pollTimer = setInterval(async () => {
    if (!currentSession) return;
    try {
      const res = await fetch(`${API_BASE}/api/session-logs/${currentSession}?after=${logOffset}`);
      const data = await res.json();

      if (data.logs && data.logs.length > 0) {
        data.logs.forEach(line => appendLog(logContainerId, line));
        logOffset = data.total;
      }

      if (data.status === 'done' || data.status === 'error') {
        clearInterval(pollTimer);
        pollTimer = null;

        if (data.status === 'done') {
          setRunStatus(statusId, 'done', '✅ 完成');
          await loadResult(resultPanelId, resultBodyId, mode);
        } else {
          setRunStatus(statusId, 'error', '❌ 出错');
        }

        // 恢复按钮
        document.getElementById(mode === 'topic' ? 'topicStartBtn' : 'novelStartBtn').disabled = false;
        document.getElementById(mode === 'topic' ? 'topicStopBtn' : 'novelStopBtn').disabled = true;
      }
    } catch (e) {
      // 网络错误，继续尝试
    }
  }, 1000);
}

function stopWatching() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  document.getElementById('topicStartBtn').disabled = false;
  document.getElementById('topicStopBtn').disabled = true;
  document.getElementById('novelStartBtn').disabled = false;
  document.getElementById('novelStopBtn').disabled = true;
}

async function loadResult(panelId, bodyId, mode) {
  if (!currentSession) return;
  try {
    const res = await fetch(`${API_BASE}/api/session/${currentSession}`);
    const data = await res.json();
    if (data.result) {
      renderResult(bodyId, data.result, mode);
      document.getElementById(panelId).classList.remove('hidden');
    }
  } catch (e) {}
}

// ── Log Helpers ─────────────────────────────────────────────

function clearLogs(containerId) {
  document.getElementById(containerId).innerHTML = '';
}

function appendLog(containerId, text, cls = '') {
  const container = document.getElementById(containerId);
  const placeholder = container.querySelector('.log-placeholder');
  if (placeholder) placeholder.remove();

  const div = document.createElement('div');
  div.className = 'log-line';

  // 自动颜色
  if (!cls) {
    if (text.includes('✅')) cls = 'success';
    else if (text.includes('❌') || text.includes('⚠️')) cls = 'error';
    else if (text.includes('Phase') || text.includes('====')) cls = 'phase';
    else if (text.includes('📝') || text.includes('🎬') || text.includes('⚖️') || text.includes('📖')) cls = 'highlight';
  }
  if (cls) div.classList.add(cls);

  div.textContent = text;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function setRunStatus(elemId, status, text) {
  const el = document.getElementById(elemId);
  el.className = `log-status ${status}`;
  el.textContent = text;
}

// ── Result Rendering ────────────────────────────────────────

function renderResult(bodyId, result, mode) {
  const body = document.getElementById(bodyId);
  const segments = result.segments || [];

  let html = `<div style="margin-bottom:12px; color:var(--text-secondary)">`;
  html += `讨论轮数: ${result.rounds_used} | 通过: ${result.approved ? '✅' : '❌'}`;
  if (result.prompts_json) html += ` | <span style="color:var(--text-muted)">JSON: ${result.prompts_json}</span>`;
  html += `</div>`;

  segments.forEach(seg => {
    html += `<div class="segment-card">`;
    html += `<h4>片段 ${seg.index}（${seg.time_range}）</h4>`;

    if (mode === 'novel') {
      html += `<div class="field"><strong>旁白:</strong> ${esc(seg.narration || '')}</div>`;
      html += `<div class="field"><strong>场景:</strong> ${esc(seg.scene_description || '')}</div>`;
      html += `<div class="field"><strong>镜头:</strong> ${esc(seg.camera_type || '')}</div>`;
      html += `<div class="field"><strong>参考图 Prompt:</strong></div>`;
      html += `<div class="prompt-text">${esc(seg.image_prompt || '')}</div>`;
      html += `<div class="field" style="margin-top:8px"><strong>视频动作 Prompt:</strong></div>`;
      html += `<div class="prompt-text">${esc(seg.video_prompt || '')}</div>`;
    } else {
      html += `<div class="field"><strong>文案:</strong> ${esc(seg.copywriting || '')}</div>`;
      html += `<div class="field"><strong>场景:</strong> ${esc(seg.scene_description || '')}</div>`;
      html += `<div class="field"><strong>镜头:</strong> ${esc(seg.camera_type || '')}</div>`;
      html += `<div class="field"><strong>Positive Prompt:</strong></div>`;
      html += `<div class="prompt-text">${esc(seg.positive_prompt || '')}</div>`;
    }

    html += `<div class="field" style="margin-top:8px"><strong>Negative:</strong></div>`;
    html += `<div class="prompt-text">${esc(seg.negative_prompt || '')}</div>`;

    // 保存为模板按钮
    html += `<div style="margin-top:10px; text-align:right">`;
    html += `<button class="btn btn-secondary" style="font-size:12px; padding:4px 12px" `;
    html += `onclick='saveSegmentAsTemplate(${JSON.stringify(seg).replace(/'/g, "&#39;")}, "${mode}")'>`;
    html += `💾 存为模板</button></div>`;

    html += `</div>`;
  });

  // 视频生成结果
  if (result.clips) {
    html += `<h3 style="margin-top:16px">🎬 视频生成结果</h3>`;
    result.clips.forEach(clip => {
      const icon = clip.status === 'success' ? '✅' : '❌';
      html += `<div class="field">${icon} 片段 ${clip.index}: ${clip.status}`;
      if (clip.file_path) html += ` — ${clip.file_path}`;
      if (clip.error) html += ` — <span style="color:var(--error)">${esc(clip.error)}</span>`;
      html += `</div>`;
    });
  }

  body.innerHTML = html;
}

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function saveSegmentAsTemplate(seg, mode) {
  document.getElementById('tplName').value = '';
  document.getElementById('tplDesc').value = '';
  document.getElementById('tplTags').value = '';
  document.getElementById('tplPositive').value = mode === 'novel' ? (seg.image_prompt || '') : (seg.positive_prompt || '');
  document.getElementById('tplNegative').value = seg.negative_prompt || '';
  document.getElementById('tplSource').value = seg.copywriting || seg.narration || '';
  document.getElementById('tplScore').value = 8;
  showModal('templateModal');
}

// ── Templates ───────────────────────────────────────────────

async function loadTemplates() {
  try {
    const res = await fetch(`${API_BASE}/api/templates`);
    const templates = await res.json();
    const container = document.getElementById('templateList');

    if (!templates.length) {
      container.innerHTML = '<div class="log-placeholder">暂无保存的模板</div>';
      return;
    }

    container.innerHTML = templates.map(t => `
      <div class="template-card">
        <h4>「${esc(t.name)}」</h4>
        <div class="tags">${(t.tags||[]).map(tag => `<span class="tag">${esc(tag)}</span>`).join('')}</div>
        ${t.description ? `<div class="desc">📝 ${esc(t.description)}</div>` : ''}
        ${t.quality_score > 0 ? `<div class="score">⭐ ${t.quality_score}/10</div>` : ''}
        <div class="prompt-preview">${esc(t.positive_prompt || '')}</div>
        <div class="card-actions">
          <button class="btn btn-danger" onclick="deleteTemplate('${esc(t.name)}')">🗑️ 删除</button>
        </div>
      </div>
    `).join('');

  } catch (e) {
    document.getElementById('templateList').innerHTML =
      `<div class="log-placeholder" style="color:var(--error)">加载失败: ${e.message}</div>`;
  }
}

function showAddTemplate() {
  document.getElementById('tplName').value = '';
  document.getElementById('tplDesc').value = '';
  document.getElementById('tplTags').value = '';
  document.getElementById('tplPositive').value = '';
  document.getElementById('tplNegative').value = '';
  document.getElementById('tplSource').value = '';
  document.getElementById('tplScore').value = 8;
  showModal('templateModal');
}

async function saveTemplate() {
  const name = document.getElementById('tplName').value.trim();
  if (!name) { alert('请输入模板名称'); return; }

  const data = {
    name,
    description: document.getElementById('tplDesc').value.trim(),
    tags: document.getElementById('tplTags').value.split(',').map(s => s.trim()).filter(Boolean),
    positive_prompt: document.getElementById('tplPositive').value.trim(),
    negative_prompt: document.getElementById('tplNegative').value.trim(),
    source_topic: document.getElementById('tplSource').value.trim(),
    quality_score: parseFloat(document.getElementById('tplScore').value) || 0,
  };

  try {
    await fetch(`${API_BASE}/api/templates`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    hideModal('templateModal');
    loadTemplates();
  } catch (e) {
    alert('保存失败: ' + e.message);
  }
}

async function deleteTemplate(name) {
  if (!confirm(`确定删除模板「${name}」？`)) return;
  try {
    await fetch(`${API_BASE}/api/templates/${encodeURIComponent(name)}`, { method: 'DELETE' });
    loadTemplates();
  } catch (e) {
    alert('删除失败: ' + e.message);
  }
}

// ── Settings ────────────────────────────────────────────────

async function loadSettings() {
  try {
    const res = await fetch(`${API_BASE}/api/config`);
    const cfg = await res.json();

    document.getElementById('cfgLlmKey').value = cfg.llm_api_key || '';
    document.getElementById('cfgLlmUrl').value = cfg.llm_base_url || '';
    document.getElementById('cfgLlmModel').value = cfg.llm_model || '';
    document.getElementById('cfgComfyUrl').value = cfg.comfyui_url || '';
    document.getElementById('cfgQuality').value = cfg.quality_mode || 'fast';
    document.getElementById('cfgWidth').value = cfg.width || 640;
    document.getElementById('cfgHeight').value = cfg.height || 640;
    document.getElementById('cfgLength').value = cfg.length || 81;
    document.getElementById('cfgFps').value = cfg.fps || 16;
    document.getElementById('cfgMaxRounds').value = cfg.max_rounds || 3;
    document.getElementById('cfgImgUrl').value = cfg.image_api_url || '';
    document.getElementById('cfgImgKey').value = cfg.image_api_key || '';
  } catch (e) {
    alert('加载设置失败: ' + e.message);
  }
}

async function saveSettings() {
  const cfg = {
    llm_api_key: document.getElementById('cfgLlmKey').value,
    llm_base_url: document.getElementById('cfgLlmUrl').value,
    llm_model: document.getElementById('cfgLlmModel').value,
    comfyui_url: document.getElementById('cfgComfyUrl').value,
    quality_mode: document.getElementById('cfgQuality').value,
    width: parseInt(document.getElementById('cfgWidth').value) || 640,
    height: parseInt(document.getElementById('cfgHeight').value) || 640,
    length: parseInt(document.getElementById('cfgLength').value) || 81,
    fps: parseInt(document.getElementById('cfgFps').value) || 16,
    max_rounds: parseInt(document.getElementById('cfgMaxRounds').value) || 3,
    image_api_url: document.getElementById('cfgImgUrl').value,
    image_api_key: document.getElementById('cfgImgKey').value,
  };

  try {
    await fetch(`${API_BASE}/api/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cfg),
    });
    alert('✅ 设置已保存');
  } catch (e) {
    alert('保存失败: ' + e.message);
  }
}

// ── Modal ───────────────────────────────────────────────────

function showModal(id) {
  document.getElementById(id).classList.remove('hidden');
}

function hideModal(id) {
  document.getElementById(id).classList.add('hidden');
}

// ── Init ────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  loadSettings();
  // 设置页进入时刷新
  document.querySelector('[data-page="settings"]').addEventListener('click', loadSettings);
  document.querySelector('[data-page="templates"]').addEventListener('click', loadTemplates);
});
