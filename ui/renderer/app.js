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
      const data = await res.json();
      // 服务器状态
      document.getElementById('serverStatus').className = 'status-dot connected';
      document.getElementById('serverStatusText').textContent = '服务器: 已连接';
      // ComfyUI 状态
      if (data.comfyui_connected) {
        document.getElementById('comfyuiStatus').className = 'status-dot connected';
        document.getElementById('comfyuiStatusText').textContent = 'ComfyUI: 已连接';
      } else {
        document.getElementById('comfyuiStatus').className = 'status-dot error';
        document.getElementById('comfyuiStatusText').textContent = 'ComfyUI: 未连接';
      }
      return true;
    }
  } catch (e) {}
  // 服务器不可达 → 两个都标红
  document.getElementById('serverStatus').className = 'status-dot error';
  document.getElementById('serverStatusText').textContent = '服务器: 未连接';
  document.getElementById('comfyuiStatus').className = 'status-dot error';
  document.getElementById('comfyuiStatusText').textContent = 'ComfyUI: 未知';
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
    appendLog('topicLogs', `Job ID: ${data.session_id}`, 'highlight');
    startPolling('topicLogs', 'topicRunStatus', 'topicResultPanel', 'topicResults', 'topic');
  } catch (e) {
    setRunStatus('topicRunStatus', 'error', '启动失败');
    document.getElementById('topicStartBtn').disabled = false;
    appendLog('topicLogs', `[ERROR] 启动失败: ${e.message}`, 'error');
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
    appendLog('novelLogs', `Job ID: ${data.session_id}`, 'highlight');
    startPolling('novelLogs', 'novelRunStatus', 'novelResultPanel', 'novelResults', 'novel');
  } catch (e) {
    setRunStatus('novelRunStatus', 'error', '启动失败');
    document.getElementById('novelStartBtn').disabled = false;
    appendLog('novelLogs', `[ERROR] 启动失败: ${e.message}`, 'error');
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
          setRunStatus(statusId, 'done', '完成');
          await loadResult(resultPanelId, resultBodyId, mode);
        } else {
          setRunStatus(statusId, 'error', '出错');
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
    if (text.includes('[OK]') || text.includes('[PASS]')) cls = 'success';
    else if (text.includes('[ERROR]') || text.includes('[FAIL]') || text.includes('[WARN]')) cls = 'error';
    else if (text.includes('Phase') || text.includes('====')) cls = 'phase';
    else if (text.includes('[copywriter]') || text.includes('[cinematographer]') || text.includes('[judge]') || text.includes('[scene_analyzer]')) cls = 'highlight';
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
  const approvedLabel = result.approved === true ? '[PASS]' : result.approved === false ? '[FAIL]' : '—';
  html += `讨论轮数: ${result.rounds_used} | 通过: ${approvedLabel}`;
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
    html += `存为模板</button></div>`;

    html += `</div>`;
  });

  // 视频生成结果
  if (result.clips) {
    html += `<h3 style="margin-top:16px">视频生成结果</h3>`;
    result.clips.forEach(clip => {
      const icon = clip.status === 'success' ? '[OK]' : '[FAIL]';
      html += `<div class="field">${icon} 片段 ${clip.index}: ${clip.status}`;
      if (clip.file_path) html += ` — ${clip.file_path}`;
      if (clip.error) html += ` — <span style="color:var(--error)">${esc(clip.error)}</span>`;
      html += `</div>`;
    });
  }

  // 最终合成视频
  if (result.final_video) {
    html += `<div style="margin-top:16px; padding:12px; background:var(--bg-tertiary); border-radius:8px; border:1px solid var(--accent)">`;
    html += `<h3 style="margin:0 0 8px 0">最终合成视频</h3>`;
    html += `<div class="field" style="word-break:break-all">${esc(result.final_video)}</div>`;
    html += `</div>`;
  }
  if (result.compose_error) {
    html += `<div style="margin-top:12px; padding:10px; background:rgba(255,0,0,0.1); border-radius:8px">`;
    html += `<strong>视频合成失败:</strong> <span style="color:var(--error)">${esc(result.compose_error)}</span>`;
    html += `</div>`;
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

// ── Prompt Optimizer ────────────────────────────────────────

function updateOptimizerCharCount() {
  const len = document.getElementById('optimizerInput').value.length;
  document.getElementById('optimizerCharCount').textContent = `${len} 字`;
}

// ── Image Tools ─────────────────────────────────────────────

// ── 通用图片工具状态 ──
let imgSession = null;
let imgPollTimer = null;
let imgLogOffset = 0;
let imageBase64 = { edit: '', createV1: '' };  // edit tab + create V1 用
let lastResultImagePath = '';

// ── 智能体创作专属状态 ──
let agentJobId = null;
let agentPollTimer = null;
let agentLogOffset = 0;
let agentSlotStates = [];             // 当前所有 slot 的状态快照

function switchImageTab(tab) {
  document.querySelectorAll('.img-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.img-tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelector(`.img-tab[data-tab="${tab}"]`).classList.add('active');
  document.getElementById(`panel-${tab}`).classList.add('active');
}

// ── 图片上传（edit tab）──
function handleImageUpload(event, mode) {
  const file = event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    const dataUrl = e.target.result;
    imageBase64[mode] = dataUrl.split(',')[1] || '';
    document.getElementById(`${mode}PreviewImg`).src = dataUrl;
    document.getElementById(`${mode}PreviewImg`).classList.remove('hidden');
    document.getElementById(`${mode}Placeholder`).classList.add('hidden');
  };
  reader.readAsDataURL(file);
}

// 拖拽上传
document.addEventListener('DOMContentLoaded', () => {
  // Edit tab 拖拽
  const editArea = document.getElementById('editUploadArea');
  if (editArea) {
    editArea.addEventListener('dragover', (e) => { e.preventDefault(); editArea.classList.add('drag-over'); });
    editArea.addEventListener('dragleave', () => editArea.classList.remove('drag-over'));
    editArea.addEventListener('drop', (e) => {
      e.preventDefault();
      editArea.classList.remove('drag-over');
      const file = e.dataTransfer.files[0];
      if (file && file.type.startsWith('image/')) handleImageUpload({ target: { files: [file] } }, 'edit');
    });
  }
});

// ── AI 智能体创作 ─────────────────────────────────────────

function updateAgentBtn() {
  const on = document.getElementById('agentUseAgent').checked;
  document.getElementById('agentStartBtn').textContent =
    on ? '🏗️ 建筑师 + 描述师 启动' : '⚡ 直接提交生图';
  document.getElementById('agentToggleHint').textContent =
    on ? '已启用：输入的意图将经由建筑师与描述师深度润色后再生图'
       : '已关闭：输入内容将直接作为 Prompt 提交给 ComfyUI';
}

function onCreateVersionChange(version) {
  const v1Area = document.getElementById('createV1ImageArea');
  v1Area.style.display = version === 'v1' ? '' : 'none';
  // V2 默认步数 8，V1 默认步数 4
  const stepsEl = document.getElementById('agentSteps');
  if (stepsEl) stepsEl.value = version === 'v2' ? '8' : '4';
}

async function startImageAgentTask() {
  const intent = document.getElementById('agentUserIntent').value.trim();
  if (!intent) { alert('请输入创作意图'); return; }

  const workflowVersion = document.querySelector('input[name="createVersion"]:checked')?.value || 'v2';
  const useAgent = document.getElementById('agentUseAgent').checked;
  const count = parseInt(document.getElementById('agentCount').value) || 1;
  const steps = parseInt(document.getElementById('agentSteps').value) || (workflowVersion === 'v2' ? 8 : 4);
  const denoise = parseFloat(document.getElementById('agentDenoise').value);
  const seedVal = document.getElementById('agentSeed').value.trim();
  const seed = seedVal ? parseInt(seedVal) : null;

  // V1 需要参考图
  if (workflowVersion === 'v1' && !imageBase64['createV1']) {
    alert('V1 模式需要上传一张参考图');
    return;
  }
  const inputImageB64 = workflowVersion === 'v1' ? imageBase64['createV1'] : '';

  const btn = document.getElementById('agentStartBtn');
  btn.disabled = true;
  btn.textContent = '⏳ 运行中...';

  // 重置 UI
  document.getElementById('agentLogPanel').style.display = '';
  clearLogs('agentLogs');
  setRunStatus('agentRunStatus', 'running', '运行中...');
  document.getElementById('agentPromptPanel').style.display = 'none';
  document.getElementById('agentPromptCards').innerHTML = '';
  document.getElementById('agentResultGrid').style.display = 'none';
  document.getElementById('agentImgGrid').innerHTML = '';
  agentSlotStates = [];

  try {
    const res = await fetch(`${API_BASE}/api/image/create-with-agent`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_intent: intent,
        use_agent: useAgent,
        workflow_version: workflowVersion,
        input_image: inputImageB64,
        count, steps, denoise, seed,
      }),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    agentJobId = data.job_id;
    agentLogOffset = 0;
    appendLog('agentLogs', `Job ID: ${data.job_id}`, 'highlight');
    startAgentPolling();
  } catch (e) {
    setRunStatus('agentRunStatus', 'error', '启动失败');
    appendLog('agentLogs', `[ERROR] ${e.message}`, 'error');
    btn.disabled = false;
    btn.textContent = document.getElementById('agentUseAgent').checked ? '🏗️ 建筑师 + 描述师 启动' : '⚡ 直接提交生图';
  }
}

function startAgentPolling() {
  agentPollTimer = setInterval(async () => {
    if (!agentJobId) return;
    try {
      const res = await fetch(`${API_BASE}/api/session-logs/${agentJobId}?after=${agentLogOffset}`);
      const data = await res.json();

      if (data.logs && data.logs.length > 0) {
        data.logs.forEach(line => appendLog('agentLogs', line));
        agentLogOffset = data.total;
      }

      // 同步 slot 状态（result 中带实时数据）
      if (data.result && data.result.slots) {
        renderAgentSlots(data.result.slots);
      }

      if (data.status === 'done' || data.status === 'error') {
        clearInterval(agentPollTimer);
        agentPollTimer = null;

        if (data.status === 'done') {
          setRunStatus('agentRunStatus', 'done', '完成');
        } else {
          setRunStatus('agentRunStatus', 'error', '出错');
        }

        const btn = document.getElementById('agentStartBtn');
        btn.disabled = false;
        btn.textContent = document.getElementById('agentUseAgent').checked ? '🏗️ 建筑师 + 描述师 启动' : '⚡ 直接提交生图';
      }
    } catch (e) { /* retry */ }
  }, 1500);
}

function renderAgentSlots(slots) {
  agentSlotStates = slots;

  const promptCards = document.getElementById('agentPromptCards');
  const imgGrid = document.getElementById('agentImgGrid');
  let hasPrompt = false;
  let hasResult = false;

  promptCards.innerHTML = '';
  imgGrid.innerHTML = '';

  slots.forEach((slot, i) => {
    // Prompt 卡片
    if (slot.prompt) {
      hasPrompt = true;
      const card = document.createElement('div');
      card.className = 'agent-prompt-card';
      card.innerHTML = `
        <div class="agent-prompt-header">
          <span class="agent-prompt-label">Prompt ${i + 1}</span>
          <button class="btn-copy" onclick="copyAgentPrompt(${i})">复制</button>
        </div>
        <div class="agent-prompt-text" id="agentPrompt_${i}">${esc(slot.prompt)}</div>
        ${slot.blueprint ? `
        <details style="margin-top:8px">
          <summary style="cursor:pointer;font-size:12px;color:var(--text-muted);padding:4px 0">
            🏗️ 建筑师蓝图（展开查看）
          </summary>
          <div class="agent-blueprint-text">${esc(slot.blueprint)}</div>
        </details>` : ''}
      `;
      promptCards.appendChild(card);
    }

    // 图片结果卡片
    const imgCard = document.createElement('div');
    imgCard.className = 'agent-img-card';
    imgCard.id = `agentImgCard_${i}`;

    if (slot.status === 'success' && slot.file_path) {
      hasResult = true;
      const imgUrl = `${API_BASE}/api/file?path=${encodeURIComponent(slot.file_path)}`;
      imgCard.innerHTML = `
        <div class="agent-img-slot-label">图 ${i + 1}</div>
        <img class="agent-result-img" src="${imgUrl}" alt="结果 ${i + 1}" loading="lazy">
        <div class="agent-prompt-mini">${esc((slot.prompt || '').substring(0, 60))}${slot.prompt && slot.prompt.length > 60 ? '...' : ''}</div>
        <div class="agent-img-actions">
          <button class="btn btn-secondary" onclick="downloadAgentImage('${imgUrl.replace(/'/g,"\\'")}', ${i})">💾 下载</button>
          <button class="btn btn-secondary" onclick="regenerateImage('${agentJobId}', ${i})">🔄 重做</button>
        </div>
      `;
    } else if (slot.status === 'failed') {
      hasResult = true;
      imgCard.innerHTML = `
        <div class="agent-img-slot-label">图 ${i + 1}</div>
        <div class="agent-img-error">❌ 生成失败<br><small>${esc(slot.error || '')}</small></div>
        <div class="agent-img-actions">
          <button class="btn btn-secondary" onclick="regenerateImage('${agentJobId}', ${i})">🔄 重试</button>
        </div>
      `;
    } else if (slot.status === 'generating') {
      imgCard.innerHTML = `
        <div class="agent-img-slot-label">图 ${i + 1}</div>
        <div class="agent-img-generating">
          <div class="agent-spinner"></div>
          <div>ComfyUI 生图中...</div>
        </div>
      `;
    } else {
      imgCard.innerHTML = `
        <div class="agent-img-slot-label">图 ${i + 1}</div>
        <div class="agent-img-generating">
          <div class="agent-spinner"></div>
          <div>智能体思考中...</div>
        </div>
      `;
    }
    imgGrid.appendChild(imgCard);
  });

  if (hasPrompt) document.getElementById('agentPromptPanel').style.display = '';
  if (hasResult || slots.some(s => ['generating','success','failed'].includes(s.status))) {
    document.getElementById('agentResultGrid').style.display = '';
  }
}

function copyAgentPrompt(slotIndex) {
  const el = document.getElementById(`agentPrompt_${slotIndex}`);
  if (!el) return;
  navigator.clipboard.writeText(el.textContent).catch(() => {});
  el.style.borderColor = 'var(--success)';
  setTimeout(() => { el.style.borderColor = ''; }, 1000);
}

function downloadAgentImage(url, index) {
  const a = document.createElement('a');
  a.href = url;
  a.download = `ai_create_${index + 1}.png`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

async function regenerateImage(jobId, slotIndex) {
  const slot = agentSlotStates[slotIndex];
  if (!slot || !slot.prompt) { alert('无 Prompt 可用，请先完成智能体运行'); return; }

  const workflowVersion = document.querySelector('input[name="createVersion"]:checked')?.value || 'v2';
  const steps = parseInt(document.getElementById('agentSteps').value) || (workflowVersion === 'v2' ? 8 : 4);
  const denoise = parseFloat(document.getElementById('agentDenoise').value);
  const inputImageB64 = workflowVersion === 'v1' ? (imageBase64['createV1'] || '') : '';

  // 更新 UI 为 generating 状态
  const card = document.getElementById(`agentImgCard_${slotIndex}`);
  if (card) {
    card.innerHTML = `
      <div class="agent-img-slot-label">图 ${slotIndex + 1}</div>
      <div class="agent-img-generating">
        <div class="agent-spinner"></div>
        <div>重新生图中...</div>
      </div>
    `;
  }

  try {
    await fetch(`${API_BASE}/api/image/regenerate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        job_id: jobId,
        slot_index: slotIndex,
        prompt: slot.prompt,
        workflow_version: workflowVersion,
        input_image: inputImageB64,
        steps, denoise,
        seed: null,  // 随机种子，确保不同结果
      }),
    });

    // 开始轮询这个 slot 直到完成
    const pollRegen = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/api/session/${jobId}`);
        const data = await res.json();
        const slots = data.result && data.result.slots ? data.result.slots : [];
        const updated = slots.find(s => s.index === slotIndex);
        if (updated && (updated.status === 'success' || updated.status === 'failed')) {
          clearInterval(pollRegen);
          agentSlotStates = slots;
          renderAgentSlots(slots);
        }
      } catch (e) { /* retry */ }
    }, 1500);

  } catch (e) {
    alert('重做请求失败: ' + e.message);
  }
}

// ── 编辑模式（旧逻辑保留）──────────────────────────────────

async function startImageTask(mode) {
  const positive = document.getElementById(`${mode}Positive`).value.trim();
  if (!positive) { alert('请输入 Prompt'); return; }
  if (!imageBase64[mode]) { alert('请上传图片'); return; }

  const negative = document.getElementById(`${mode}Negative`).value.trim();
  const steps = parseInt(document.getElementById(`${mode}Steps`).value) || 4;
  const denoise = parseFloat(document.getElementById(`${mode}Denoise`).value);
  const seedVal = document.getElementById(`${mode}Seed`).value.trim();
  const seed = seedVal ? parseInt(seedVal) : null;

  const btn = document.getElementById(`${mode}StartBtn`);
  const origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = '生成中...';
  document.getElementById('imgResultPanel').classList.add('hidden');
  document.getElementById('imgLogPanel').style.display = '';
  clearLogs('imgLogs');
  setRunStatus('imgRunStatus', 'running', '生成中...');

  try {
    const res = await fetch(`${API_BASE}/api/image/${mode}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        positive_prompt: positive,
        negative_prompt: negative,
        input_image: imageBase64[mode],
        steps, denoise, seed,
      }),
    });
    const data = await res.json();
    if (data.error) { throw new Error(data.error); }

    imgSession = data.job_id;
    imgLogOffset = 0;
    appendLog('imgLogs', `Job ID: ${data.job_id}`, 'highlight');
    startImagePolling(mode, origText);
  } catch (e) {
    setRunStatus('imgRunStatus', 'error', '启动失败');
    appendLog('imgLogs', `[ERROR] ${e.message}`, 'error');
    btn.disabled = false;
    btn.textContent = origText;
  }
}

function startImagePolling(mode, origBtnText) {
  imgPollTimer = setInterval(async () => {
    if (!imgSession) return;
    try {
      const res = await fetch(`${API_BASE}/api/session-logs/${imgSession}?after=${imgLogOffset}`);
      const data = await res.json();

      if (data.logs && data.logs.length > 0) {
        data.logs.forEach(line => appendLog('imgLogs', line));
        imgLogOffset = data.total;
      }

      if (data.status === 'done' || data.status === 'error') {
        clearInterval(imgPollTimer);
        imgPollTimer = null;

        if (data.status === 'done') {
          setRunStatus('imgRunStatus', 'done', '完成');
          await showImageResult();
        } else {
          setRunStatus('imgRunStatus', 'error', '出错');
        }

        const btn = document.getElementById(`${mode}StartBtn`);
        if (btn) { btn.disabled = false; btn.textContent = origBtnText; }
      }
    } catch (e) { /* retry */ }
  }, 1000);
}

async function showImageResult() {
  if (!imgSession) return;
  try {
    const res = await fetch(`${API_BASE}/api/session/${imgSession}`);
    const data = await res.json();
    const result = data.result;
    if (!result) return;

    if (result.status === 'success' && result.file_path) {
      lastResultImagePath = result.file_path;
      const imgUrl = `${API_BASE}/api/file?path=${encodeURIComponent(result.file_path)}`;
      document.getElementById('imgResultImage').src = imgUrl;
      document.getElementById('imgResultInfo').textContent = `模式: 图片编辑`;
      document.getElementById('imgResultPanel').classList.remove('hidden');
    } else if (result.error) {
      appendLog('imgLogs', `[FAIL] ${result.error}`, 'error');
    }
  } catch (e) {}
}

function downloadResultImage() {
  const img = document.getElementById('imgResultImage');
  if (!img.src) return;
  const a = document.createElement('a');
  a.href = img.src;
  a.download = lastResultImagePath.split('/').pop() || 'generated.png';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

function copyResultImagePath() {
  if (!lastResultImagePath) return;
  navigator.clipboard.writeText(lastResultImagePath).catch(() => {});
  const info = document.getElementById('imgResultInfo');
  const orig = info.textContent;
  info.textContent = '✅ 路径已复制';
  setTimeout(() => { info.textContent = orig; }, 1500);
}

function useAsEditInput() {
  const img = document.getElementById('imgResultImage');
  if (!img.src) return;
  switchImageTab('edit');
  const canvas = document.createElement('canvas');
  canvas.width = img.naturalWidth;
  canvas.height = img.naturalHeight;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(img, 0, 0);
  const dataUrl = canvas.toDataURL('image/png');
  imageBase64['edit'] = dataUrl.split(',')[1] || '';
  document.getElementById('editPreviewImg').src = dataUrl;
  document.getElementById('editPreviewImg').classList.remove('hidden');
  document.getElementById('editPlaceholder').classList.add('hidden');
}


async function runPromptOptimizer() {
  const text = document.getElementById('optimizerInput').value.trim();
  if (!text) { alert('请输入描述文字'); return; }

  const mode = document.getElementById('optimizerMode').value;
  const btn = document.getElementById('optimizerBtn');
  const resultPanel = document.getElementById('optimizerResultPanel');

  btn.disabled = true;
  btn.textContent = '优化中...';
  resultPanel.classList.add('hidden');

  try {
    const res = await fetch(`${API_BASE}/api/prompt/optimize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, mode }),
    });
    const data = await res.json();

    if (data.error) {
      alert('优化失败: ' + data.error);
      return;
    }

    document.getElementById('optimizerPositive').textContent = data.positive_prompt || '';
    document.getElementById('optimizerNegative').textContent = data.negative_prompt || '';
    document.getElementById('optimizerAnalysis').textContent = data.analysis || '';
    resultPanel.classList.remove('hidden');

  } catch (e) {
    alert('请求失败: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = '生成优化 Prompt';
  }
}

function copyToClipboard(elementId) {
  const text = document.getElementById(elementId).textContent;
  if (!text) return;
  navigator.clipboard.writeText(text).then(() => {
    // 显示短暂提示
    const el = document.getElementById(elementId);
    const original = el.style.borderColor;
    el.style.borderColor = 'var(--success)';
    setTimeout(() => { el.style.borderColor = original; }, 800);
  }).catch(() => {
    // fallback
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  });
}

// ── I2V Video Generation ────────────────────────────────────

let i2vSession = null;
let i2vPollTimer = null;
let i2vLogOffset = 0;
let i2vImageBase64 = '';
let lastI2VResultPath = '';

// ── I2V 模型切换 ──
function onI2VModelChange() {
  const model = document.getElementById('i2vModel').value;
  const wanParams = document.getElementById('i2vWanParams');
  const ltxParams = document.getElementById('i2vLtxParams');
  const lengthSel = document.getElementById('i2vLength');
  const widthInput = document.getElementById('i2vWidth');
  const heightInput = document.getElementById('i2vHeight');

  if (model === 'ltx2') {
    wanParams.style.display = 'none';
    ltxParams.style.display = '';
    // LTX 默认参数
    widthInput.value = 1280;
    heightInput.value = 720;
    // 更新帧数选项 (25fps)
    lengthSel.innerHTML = `
      <option value="121">121帧 (~4.8秒)</option>
      <option value="161">161帧 (~6.4秒)</option>
      <option value="201">201帧 (~8秒)</option>
      <option value="241" selected>241帧 (~9.6秒)</option>
    `;
  } else {
    wanParams.style.display = '';
    ltxParams.style.display = 'none';
    // Wan2.2 默认参数
    widthInput.value = 1088;
    heightInput.value = 720;
    // 恢复帧数选项 (16fps)
    lengthSel.innerHTML = `
      <option value="49">49帧 (~3秒)</option>
      <option value="65">65帧 (~4秒)</option>
      <option value="81" selected>81帧 (~5秒)</option>
    `;
  }
}

function handleI2VImageUpload(event) {
  const file = event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    const dataUrl = e.target.result;
    i2vImageBase64 = dataUrl.split(',')[1] || '';
    document.getElementById('i2vPreviewImg').src = dataUrl;
    document.getElementById('i2vPreviewImg').classList.remove('hidden');
    document.getElementById('i2vPlaceholder').classList.add('hidden');
  };
  reader.readAsDataURL(file);
}

// 拖拽上传
document.addEventListener('DOMContentLoaded', () => {
  const uploadArea = document.getElementById('i2vUploadArea');
  if (uploadArea) {
    uploadArea.addEventListener('dragover', (e) => {
      e.preventDefault();
      uploadArea.classList.add('drag-over');
    });
    uploadArea.addEventListener('dragleave', () => {
      uploadArea.classList.remove('drag-over');
    });
    uploadArea.addEventListener('drop', (e) => {
      e.preventDefault();
      uploadArea.classList.remove('drag-over');
      const file = e.dataTransfer.files[0];
      if (file && file.type.startsWith('image/')) {
        handleI2VImageUpload({ target: { files: [file] } });
      }
    });
  }
});

async function startI2V() {
  const positive = document.getElementById('i2vPositive').value.trim();
  if (!positive) { alert('请输入动作描述 Prompt'); return; }
  if (!i2vImageBase64) { alert('请上传参考图片'); return; }

  const model = document.getElementById('i2vModel').value;
  const negative = document.getElementById('i2vNegative').value.trim();
  const width = parseInt(document.getElementById('i2vWidth').value) || (model === 'ltx2' ? 1280 : 1088);
  const height = parseInt(document.getElementById('i2vHeight').value) || 720;
  const length = parseInt(document.getElementById('i2vLength').value) || (model === 'ltx2' ? 241 : 81);

  const btn = document.getElementById('i2vStartBtn');
  btn.disabled = true;
  btn.textContent = '生成中...';
  document.getElementById('i2vResultPanel').classList.add('hidden');
  document.getElementById('i2vLogPanel').style.display = '';
  clearLogs('i2vLogs');
  setRunStatus('i2vRunStatus', 'running', '生成中...');

  try {
    let apiPath, bodyData;

    if (model === 'ltx2') {
      // LTX-2.0 I2V
      const steps = parseInt(document.getElementById('i2vLtxSteps').value) || 20;
      const cfg_pass1 = parseFloat(document.getElementById('i2vLtxCfg1').value) || 4.0;
      const cfg_pass2 = parseFloat(document.getElementById('i2vLtxCfg2').value) || 1.0;
      const seedVal = document.getElementById('i2vLtxSeed').value.trim();
      const seed = seedVal ? parseInt(seedVal) : null;
      apiPath = '/api/video/ltx-i2v';
      bodyData = {
        positive_prompt: positive,
        negative_prompt: negative,
        input_image: i2vImageBase64,
        width, height, length,
        steps, cfg_pass1, cfg_pass2, seed,
      };
    } else {
      // Wan2.2 I2V
      const quality = document.getElementById('i2vQuality').value;
      const use_fast_lora = quality === 'fast';
      const seedVal = document.getElementById('i2vSeed').value.trim();
      const seed = seedVal ? parseInt(seedVal) : null;
      apiPath = '/api/video/i2v';
      bodyData = {
        positive_prompt: positive,
        negative_prompt: negative,
        input_image: i2vImageBase64,
        width, height, length,
        use_fast_lora, seed,
      };
    }

    const res = await fetch(`${API_BASE}${apiPath}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(bodyData),
    });
    const data = await res.json();
    if (data.error) { throw new Error(data.error); }

    i2vSession = data.job_id;
    i2vLogOffset = 0;
    appendLog('i2vLogs', `Job ID: ${data.job_id}`, 'highlight');
    startI2VPolling();
  } catch (e) {
    setRunStatus('i2vRunStatus', 'error', '启动失败');
    appendLog('i2vLogs', `[ERROR] ${e.message}`, 'error');
    btn.disabled = false;
    btn.textContent = '🎬 开始生成';
  }
}

function startI2VPolling() {
  i2vPollTimer = setInterval(async () => {
    if (!i2vSession) return;
    try {
      const res = await fetch(`${API_BASE}/api/session-logs/${i2vSession}?after=${i2vLogOffset}`);
      const data = await res.json();

      if (data.logs && data.logs.length > 0) {
        data.logs.forEach(line => appendLog('i2vLogs', line));
        i2vLogOffset = data.total;
      }

      if (data.status === 'done' || data.status === 'error') {
        clearInterval(i2vPollTimer);
        i2vPollTimer = null;

        if (data.status === 'done') {
          setRunStatus('i2vRunStatus', 'done', '完成');
          await showI2VResult();
        } else {
          setRunStatus('i2vRunStatus', 'error', '出错');
        }

        const btn = document.getElementById('i2vStartBtn');
        btn.disabled = false;
        btn.textContent = '🎬 开始生成';
      }
    } catch (e) { /* retry */ }
  }, 1500);
}

async function showI2VResult() {
  if (!i2vSession) return;
  try {
    const res = await fetch(`${API_BASE}/api/session/${i2vSession}`);
    const data = await res.json();
    const result = data.result;
    if (!result) return;

    if (result.status === 'success' && result.file_path) {
      lastI2VResultPath = result.file_path;
      const videoUrl = `${API_BASE}/api/file?path=${encodeURIComponent(result.file_path)}`;
      document.getElementById('i2vResultVideo').src = videoUrl;

      const modeLabel = result.use_fast_lora ? '4步快速' : '20步标准';
      document.getElementById('i2vResultInfo').textContent =
        `模式: ${modeLabel} | 尺寸: ${result.width}×${result.height} | 帧数: ${result.length}`;

      document.getElementById('i2vResultPanel').classList.remove('hidden');
    } else if (result.error) {
      appendLog('i2vLogs', `[FAIL] ${result.error}`, 'error');
    }
  } catch (e) {}
}

function downloadI2VResult() {
  const video = document.getElementById('i2vResultVideo');
  if (!video.src) return;
  const a = document.createElement('a');
  a.href = video.src;
  a.download = lastI2VResultPath.split('/').pop() || 'i2v_output.mp4';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

function copyI2VResultPath() {
  if (!lastI2VResultPath) return;
  navigator.clipboard.writeText(lastI2VResultPath).catch(() => {});
  const info = document.getElementById('i2vResultInfo');
  const orig = info.textContent;
  info.textContent = '✅ 路径已复制';
  setTimeout(() => { info.textContent = orig; }, 1500);
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
        ${t.description ? `<div class="desc">${esc(t.description)}</div>` : ''}
        ${t.quality_score > 0 ? `<div class="score">${t.quality_score}/10</div>` : ''}
        <div class="prompt-preview">${esc(t.positive_prompt || '')}</div>
        <div class="card-actions">
          <button class="btn btn-danger" onclick="deleteTemplate('${esc(t.name)}')"删除</button>
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
    alert('设置已保存');
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

// ── Jobs (作品库) ───────────────────────────────────────────

async function loadJobs() {
  const container = document.getElementById('jobsList');
  try {
    const res = await fetch(`${API_BASE}/api/jobs`);
    const jobs = await res.json();

    if (!jobs.length) {
      container.innerHTML = '<div class="log-placeholder">暂无任务记录，开始创作吧！</div>';
      return;
    }

    container.innerHTML = jobs.map(job => {
      const modeLabel = job.mode === 'novel' ? '小说改编' : '主题创作';
      const statusMap = {
        'created': '<span class="job-status created">等待</span>',
        'running': '<span class="job-status running">运行中</span>',
        'done': '<span class="job-status done">完成</span>',
        'error': '<span class="job-status error">失败</span>',
      };
      const status = statusMap[job.status] || job.status;
      const time = new Date(job.created_at * 1000).toLocaleString('zh-CN');
      const duration = job.finished_at
        ? `${Math.round(job.finished_at - job.created_at)}s`
        : '—';
      const videoTag = job.has_video ? '<span class="job-tag video-tag">有视频</span>' : '';
      const clipTag = job.clip_count > 0 ? `<span class="job-tag clip-tag">${job.clip_count} 片段</span>` : '';

      return `
        <div class="job-card" onclick="viewJobDetail('${job.id}')">
          <div class="job-card-left">
            <div class="job-card-info">
              <div class="job-card-title">${esc(job.title || '未命名任务')}</div>
              <div class="job-card-meta">
                <span class="job-id-badge">${job.id}</span>
                <span>${modeLabel}</span>
                <span>${time}</span>
                <span>耗时 ${duration}</span>
              </div>
            </div>
          </div>
          <div class="job-card-right">
            ${videoTag}${clipTag}
            ${status}
          </div>
        </div>
      `;
    }).join('');

  } catch (e) {
    container.innerHTML =
      `<div class="log-placeholder" style="color:var(--error)">加载失败: ${e.message}</div>`;
  }
}

async function viewJobDetail(jobId) {
  // 隐藏列表，显示详情
  document.getElementById('jobsListHeader').classList.add('hidden');
  document.getElementById('jobsToolbar').classList.add('hidden');
  document.getElementById('jobsList').classList.add('hidden');
  document.getElementById('jobDetailView').classList.remove('hidden');

  document.getElementById('jobDetailId').textContent = `Job ID: ${jobId}`;
  document.getElementById('jobDetailTitle').textContent = '加载中...';
  document.getElementById('jobDetailBody').innerHTML = '<div class="log-placeholder">加载中...</div>';

  try {
    const res = await fetch(`${API_BASE}/api/jobs/${jobId}`);
    const job = await res.json();

    if (job.error && !job.result) {
      document.getElementById('jobDetailTitle').textContent = '任务失败';
      document.getElementById('jobDetailBody').innerHTML =
        `<div style="color:var(--error);padding:16px">${esc(job.error)}</div>`;
      return;
    }

    const modeLabel = job.mode === 'novel' ? '小说改编' : '主题创作';
    document.getElementById('jobDetailTitle').textContent = `${modeLabel}`;

    let html = '';
    const result = job.result || {};
    const time = new Date(job.created_at * 1000).toLocaleString('zh-CN');
    const duration = job.finished_at ? `${Math.round(job.finished_at - job.created_at)}s` : '—';

    // ── 概览信息
    html += `<div class="job-overview">`;
    html += `<div class="job-overview-item"><strong>主题 / 文本:</strong> ${esc(job.title)}</div>`;
    html += `<div class="job-overview-item"><strong>时间:</strong> ${time}</div>`;
    html += `<div class="job-overview-item"><strong>耗时:</strong> ${duration}</div>`;
    const approvedText = result.approved === true ? '[PASS]' : result.approved === false ? '[FAIL]' : '—';
    html += `<div class="job-overview-item"><strong>讨论轮数:</strong> ${result.rounds_used || '—'} | <strong>通过:</strong> ${approvedText}</div>`;
    if (result.visual_style) {
      html += `<div class="job-overview-item"><strong>视觉风格:</strong> ${esc(result.visual_style)}</div>`;
    }
    html += `</div>`;

    // ── 最终合成视频（最醒目）
    if (result.final_video) {
      const videoUrl = `${API_BASE}/api/file?path=${encodeURIComponent(result.final_video)}`;
      html += `<div class="job-section job-final-video">`;
      html += `<h3>最终合成视频</h3>`;
      html += `<video controls class="video-player" src="${videoUrl}" preload="metadata"></video>`;
      html += `<div class="job-file-path">${esc(result.final_video)}</div>`;
      html += `</div>`;
    }
    if (result.compose_error) {
      html += `<div class="job-section" style="border-color:var(--error)">`;
      html += `<h3>视频合成失败</h3><p style="color:var(--error)">${esc(result.compose_error)}</p>`;
      html += `</div>`;
    }

    // ── 各片段（含单独视频 + prompt）
    const segments = result.segments || [];
    const clips = result.clips || [];
    if (segments.length) {
      html += `<div class="job-section"><h3>视频片段 & Prompt 详情</h3>`;
      segments.forEach(seg => {
        const clip = clips.find(c => c.index === seg.index);
        html += `<div class="job-segment-card">`;
        html += `<div class="job-segment-header">`;
        html += `<h4>片段 ${seg.index}（${seg.time_range || ''}）</h4>`;
        if (clip) {
          const icon = clip.status === 'success' ? '[OK]' : '[FAIL]';
          html += `<span class="job-status ${clip.status === 'success' ? 'done' : 'error'}">${icon} ${clip.status}</span>`;
        }
        html += `</div>`;

        // 视频预览
        if (clip && clip.status === 'success' && clip.file_path) {
          const clipUrl = `${API_BASE}/api/file?path=${encodeURIComponent(clip.file_path)}`;
          html += `<video controls class="video-player-sm" src="${clipUrl}" preload="metadata"></video>`;
        }

        // 详细字段
        if (job.mode === 'novel') {
          if (seg.narration) html += `<div class="job-field"><strong>旁白:</strong> ${esc(seg.narration)}</div>`;
          if (seg.scene_description) html += `<div class="job-field"><strong>场景:</strong> ${esc(seg.scene_description)}</div>`;
          if (seg.camera_type) html += `<div class="job-field"><strong>镜头:</strong> ${esc(seg.camera_type)}</div>`;
          if (seg.image_prompt) {
            html += `<div class="job-field"><strong>参考图 Prompt:</strong></div>`;
            html += `<div class="job-prompt-box">${esc(seg.image_prompt)}</div>`;
          }
          if (seg.video_prompt) {
            html += `<div class="job-field"><strong>视频 Prompt:</strong></div>`;
            html += `<div class="job-prompt-box">${esc(seg.video_prompt)}</div>`;
          }
        } else {
          if (seg.copywriting) html += `<div class="job-field"><strong>文案:</strong> ${esc(seg.copywriting)}</div>`;
          if (seg.scene_description) html += `<div class="job-field"><strong>场景:</strong> ${esc(seg.scene_description)}</div>`;
          if (seg.camera_type) html += `<div class="job-field"><strong>镜头:</strong> ${esc(seg.camera_type)}</div>`;
          if (seg.positive_prompt) {
            html += `<div class="job-field"><strong>Positive Prompt:</strong></div>`;
            html += `<div class="job-prompt-box">${esc(seg.positive_prompt)}</div>`;
          }
        }
        if (seg.negative_prompt) {
          html += `<div class="job-field"><strong>Negative Prompt:</strong></div>`;
          html += `<div class="job-prompt-box negative">${esc(seg.negative_prompt)}</div>`;
        }
        if (clip && clip.error) {
          html += `<div class="job-field" style="color:var(--error)"><strong>错误:</strong> ${esc(clip.error)}</div>`;
        }

        html += `</div>`;
      });
      html += `</div>`;
    }

    // ── 讨论日志（可折叠）
    if (job.logs && job.logs.length) {
      html += `<div class="job-section">`;
      html += `<h3 class="collapsible" onclick="toggleCollapse(this)">讨论日志 (${job.logs.length} 行) ▸</h3>`;
      html += `<div class="collapsible-body collapsed">`;
      html += `<div class="log-body" style="max-height:500px">`;
      job.logs.forEach(line => {
        let cls = '';
        if (line.includes('[OK]') || line.includes('[PASS]')) cls = 'success';
        else if (line.includes('[ERROR]') || line.includes('[FAIL]') || line.includes('[WARN]')) cls = 'error';
        else if (line.includes('Phase') || line.includes('====')) cls = 'phase';
        else if (line.includes('[copywriter]') || line.includes('[cinematographer]') || line.includes('[judge]') || line.includes('[scene_analyzer]')) cls = 'highlight';
        html += `<div class="log-line ${cls}">${esc(line)}</div>`;
      });
      html += `</div></div></div>`;
    }

    document.getElementById('jobDetailBody').innerHTML = html;

  } catch (e) {
    document.getElementById('jobDetailBody').innerHTML =
      `<div class="log-placeholder" style="color:var(--error)">加载失败: ${e.message}</div>`;
  }
}

function backToJobList() {
  document.getElementById('jobDetailView').classList.add('hidden');
  document.getElementById('jobsListHeader').classList.remove('hidden');
  document.getElementById('jobsToolbar').classList.remove('hidden');
  document.getElementById('jobsList').classList.remove('hidden');
}

function toggleCollapse(header) {
  const body = header.nextElementSibling;
  const isCollapsed = body.classList.toggle('collapsed');
  header.textContent = header.textContent.replace(/[▸▾]/, isCollapsed ? '▸' : '▾');
}

// ── Init ────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  loadSettings();
  // 设置页进入时刷新
  document.querySelector('[data-page="settings"]').addEventListener('click', loadSettings);
  document.querySelector('[data-page="templates"]').addEventListener('click', loadTemplates);
  document.querySelector('[data-page="jobs"]').addEventListener('click', () => {
    backToJobList();
    loadJobs();
  });
});
