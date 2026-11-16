const $ = (id) => document.getElementById(id);
const api = async (path, opts = {}) => {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) throw new Error((data && data.detail) || res.statusText);
  return data;
};
const toast = (msg, kind = '') => {
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.textContent = msg;
  $('toast').appendChild(el);
  setTimeout(() => el.remove(), 5000);
};
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;' }[c]));
const ts = (n) => n ? new Date(n * 1000).toLocaleString('zh-CN', { hour12: false }) : '—';

async function health() {
  try {
    const d = await api('/api/health');
    $('health').textContent = `v${d.version} · ${d.data_dir} · 出口 ${d.global_rate}/s · 二维码解码${d.qr_decode ? '✓' : '✗'}`;
  } catch { $('health').textContent = '服务异常'; }
}

async function login() {
  const username = $('u').value.trim(), password = $('p').value;
  if (!username || !password) return toast('手机号和密码都要填', 'bad');
  try {
    const d = await api('/api/accounts/login', { method: 'POST', body: JSON.stringify({ username, password }) });
    toast(`登录成功：${d.real_name || d.username}`, 'ok');
    $('p').value = '';
    refreshAll();
  } catch (e) { toast(`登录失败：${e.message}`, 'bad'); }
}

async function importCookie() {
  const username = $('iu').value.trim(), cookies = $('ic').value.trim(), operator = $('iop').value.trim();
  if (!username || !cookies) return toast('手机号和 Cookie 都要填', 'bad');
  try {
    const d = await api('/api/accounts/import', {
      method: 'POST',
      body: JSON.stringify({ username, cookies, operator, note: '' }),
    });
    toast(`导入成功：${d.username}（模式 ${d.mode}${d.delegation_id ? '，托管 #' + d.delegation_id : ''}）`, 'ok');
    $('ic').value = '';
    refreshAll();
  } catch (e) { toast(`导入失败：${e.message}`, 'bad'); }
}

async function loadAccounts() {
  const list = await api('/api/accounts');
  if (!list.length) { $('accounts').innerHTML = '<div class="empty">暂无账号</div>'; return; }
  $('accounts').innerHTML = `<table><thead><tr>
      <th>手机号</th><th>姓名</th><th>模式</th><th>身份</th><th>状态</th><th style="width:300px">操作</th>
    </tr></thead><tbody>${list.map((a) => `<tr>
      <td class="mono">${esc(a.username)}</td>
      <td>${esc(a.real_name) || '<span class="dim">—</span>'}</td>
      <td><span class="pill">${a.mode === 'password' ? '密码' : a.mode === 'cookie' ? 'Cookie托管' : '无凭证'}</span>
          ${a.delegation ? `<span class="dim" style="font-size:12px"> · ${esc(a.delegation.operator)}</span>` : ''}</td>
      <td class="mono dim" style="font-size:12px">${a.device_code || '—'}<br>${esc(a.proxy)}</td>
      <td>${a.enabled ? '<span class="ok">启用</span>' : '<span class="dim">停用</span>'}
          ${a.cookie_ok ? '' : '<span class="bad">· 无Cookie</span>'}
          ${a.cooling_down ? `<span class="bad">· 退避${a.cooling_down}s</span>` : ''}</td>
      <td class="row">
        <button onclick="syncCourses(${a.id})">同步课程</button>
        <button onclick="scan(${a.id})">扫描签到</button>
        <button class="${a.enabled ? 'danger' : ''}" onclick="toggle(${a.id}, ${!a.enabled})">${a.enabled ? '停用' : '启用'}</button>
      </td></tr>`).join('')}</tbody></table>`;
}

async function toggle(id, enabled) {
  try { await api(`/api/accounts/${id}/enable`, { method: 'POST', body: JSON.stringify({ enabled }) }); loadAccounts(); }
  catch (e) { toast(e.message, 'bad'); }
}

async function syncCourses(id) {
  toast('正在同步课程…');
  try {
    const d = await api(`/api/accounts/${id}/courses?sync=true`);
    toast(`同步到 ${d.length} 门课程`, 'ok');
  } catch (e) { toast(`同步失败：${e.message}`, 'bad'); }
}

async function scan(id) {
  toast('正在扫描…');
  try {
    const d = await api(`/api/accounts/${id}/activities?sync=false`);
    renderActs(d, id);
    if (!d.length) toast('没有进行中的签到');
  } catch (e) { toast(`扫描失败：${e.message}`, 'bad'); }
}

const KIND_HINT = {
  plain: '', gesture: '', location: '需要经纬度', photo: '需要图片或云盘 0.jpg',
  qrcode: '需要 enc', signcode: '需要签到码', face: '需已采集人脸',
};

function renderActs(list, accountId) {
  if (!list.length) { $('acts').innerHTML = '<div class="empty">没有进行中的签到</div>'; return; }
  $('acts').innerHTML = `<table><thead><tr>
      <th>类型</th><th>课程</th><th>活动</th><th>开始</th><th style="width:360px">签到</th>
    </tr></thead><tbody>${list.map((a) => `
      <tr>
        <td><span class="pill">${esc(a.kind_text)}</span></td>
        <td>${esc(a.course)}</td>
        <td>${esc(a.name)}<div class="dim mono">${a.active_id}</div></td>
        <td class="dim">${a.age_seconds}s 前</td>
        <td>
          <div class="row">
            ${a.kind === 'signcode' ? `<input id="code-${a.active_id}" placeholder="签到码" style="flex:1" />` : ''}
            ${a.kind === 'qrcode' ? `<input id="qr-${a.active_id}" placeholder="扫到的二维码文本 / enc" style="flex:1" />` : ''}
            ${a.kind === 'qrcode' ? `<button onclick="pickQr(${accountId}, '${a.active_id}')">传图</button>` : ''}
            <button class="primary" onclick="sign(${accountId}, '${a.active_id}', '${a.kind}')">
              ${a.needs_input ? '提交' : '签到'}
            </button>
          </div>
          ${KIND_HINT[a.kind] ? `<div class="dim" style="font-size:12px;margin-top:4px">${KIND_HINT[a.kind]}</div>` : ''}
        </td>
      </tr>`).join('')}</tbody></table>`;
}

/** 选一张二维码截图 → 交给服务端解码 → 回填 enc */
function pickQr(accountId, activeId) {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/*';
  input.onchange = async () => {
    const file = input.files && input.files[0];
    if (!file) return;
    toast('正在解码二维码…');
    try {
      const res = await fetch('/api/qr/decode-image', {
        method: 'POST',
        headers: { 'Content-Type': file.type || 'image/png' },
        body: file,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || '解码失败');
      const el = $(`qr-${activeId}`);
      if (el) el.value = data.enc;
      toast(`识别到 enc：${data.enc.slice(0, 16)}…`, 'ok');
    } catch (e) {
      toast(`解码失败：${e.message}`, 'bad');
    }
  };
  input.click();
}

async function sign(accountId, activeId, kind) {
  const body = { account_id: accountId, active_id: activeId };
  const codeEl = $(`code-${activeId}`);
  if (codeEl) body.sign_code = codeEl.value.trim();
  const qrEl = $(`qr-${activeId}`);
  if (qrEl) body.qr_text = qrEl.value.trim();
  try {
    const d = await api('/api/sign', { method: 'POST', body: JSON.stringify(body) });
    toast(d.ok ? `签到成功：${d.message}` : `签到失败：${d.message}`, d.ok ? 'ok' : 'bad');
    refreshAll();
  } catch (e) { toast(`签到失败：${e.message}`, 'bad'); }
}

async function loadLogs() {
  const list = await api('/api/logs?limit=50&operator=true');
  if (!list.length) { $('logs').innerHTML = '<div class="empty">暂无记录</div>'; return; }
  $('logs').innerHTML = `<table><thead><tr>
      <th>时间</th><th>账号</th><th>类型</th><th>结果</th><th>授权人</th><th>活动</th>
    </tr></thead><tbody>${list.map((l) => `<tr>
      <td class="dim mono">${ts(l.created_at)}</td>
      <td class="mono">#${l.account_id}</td>
      <td><span class="pill">${esc(l.kind)}</span></td>
      <td class="${l.ok ? 'ok' : 'bad'}">${l.ok ? '成功' : '失败'}</td>
      <td class="dim">${esc(l.operator) || '—'}</td>
      <td class="dim">${esc(l.message)}<div class="mono">${esc(l.active_id)}</div></td>
    </tr>`).join('')}</tbody></table>`;
}

async function monitor(action) {
  try {
    const body = action === 'start' ? { interval: Number($('interval').value) || 20, auto_sign: true } : {};
    const d = await api(`/api/monitor/${action}`, { method: 'POST', body: JSON.stringify(body) });
    toast(action === 'start' ? '监听已启动' : '监听已停止', 'ok');
    if (d && d.interval) $('interval').value = d.interval;
  } catch (e) { toast(e.message, 'bad'); }
}

async function loadMonitor() {
  try {
    const d = await api('/api/monitor');
    $('mstat').textContent =
      `${d.running ? '● 运行中' : '○ 已停止'} · 间隔 ${d.interval}s · 轮次 ${d.rounds}` +
      (d.last_scan_at ? ` · 上次扫描 ${new Date(d.last_scan_at * 1000).toLocaleTimeString('zh-CN', { hour12: false })}` : '') +
      (d.last_error ? ` · 异常：${d.last_error}` : '');
  } catch { $('mstat').textContent = '无法获取监听状态'; }
}

function refreshAll() { loadAccounts(); loadLogs(); loadMonitor(); }

health();
refreshAll();
setInterval(refreshAll, 10000);
