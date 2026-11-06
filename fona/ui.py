"""HTML page for the Fona agent UI. Inlined as a Python string.

Interface language is auto-detected from the system/browser locale:
  * Russian if the first preferred language starts with "ru"
  * English for everything else
No manual switcher, no localStorage persistence — the language is
recomputed on every page load so a changed OS locale is picked up.
"""

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Fona Chat</title>
<link rel="icon" href="/favicon.ico">
<style>
:root {
  --bg: #0b0d11; --fg: #c7cbd1; --dim: #8b949e;
  --border: #2a313d; --accent: #58a6ff; --green: #7ee787;
  --red: #ff7b72; --panel: #0f1115; --block: #161a20;
}
* { box-sizing: border-box; }
html, body { height: 100%; margin: 0; }
body {
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  background: var(--bg); color: var(--fg);
  display: flex; flex-direction: column; height: 100vh;
}

header {
  display: flex; gap: .75rem; align-items: center;
  padding: .5rem .75rem; border-bottom: 1px solid var(--border);
  background: var(--panel);
}
header h1 { margin: 0; font-size: 1rem; font-weight: 600; }
header .spacer { flex: 1; }

.status-badge {
  font-size: 11px; padding: 2px 8px; border-radius: 10px;
  background: #21262d; color: var(--dim);
}
.status-badge.on  { color: var(--green); background: #0f2a1a; }
.status-badge.off { color: var(--red); background: #2a0f12; }
header .url { font-size: 11px; color: var(--dim);
              font-family: ui-monospace, monospace; }

main { flex: 1; display: flex; min-height: 0; }
.col { display: flex; flex-direction: column;
       border-right: 1px solid var(--border); overflow: hidden; }
.col:last-child { border-right: none; }
.col-1 { width: 22%; min-width: 260px; }
.col-2 { flex: 1; min-width: 380px; }
.col-3 { width: 26%; min-width: 300px; }

.col-head {
  padding: 6px 10px; font-size: 12px; font-weight: 600;
  color: var(--dim); border-bottom: 1px solid var(--border);
  background: var(--panel);
}
.col-body { flex: 1; overflow-y: auto; padding: 8px; }

.file-input {
  width: 100%; padding: 6px; background: var(--bg);
  border: 1px dashed #3a4250; border-radius: 4px;
  color: var(--dim); font-size: 12px; cursor: pointer;
}
.file-input:hover { border-color: var(--accent); }

textarea {
  width: 100%; background: var(--bg); color: var(--fg);
  border: 1px solid var(--border); border-radius: 4px;
  font-family: ui-monospace, monospace; font-size: 12px;
  padding: 6px 8px; resize: vertical;
}
textarea:focus { outline: none; border-color: var(--accent); }

button {
  background: #21262d; color: var(--fg);
  border: 1px solid var(--border); border-radius: 4px;
  padding: 4px 10px; font-size: 12px; cursor: pointer;
}
button:hover { background: #30363d; }
button.primary { background: var(--accent); color: #fff;
                 border-color: var(--accent); }
button:disabled { opacity: .5; cursor: not-allowed; }
.row { display: flex; gap: 6px; margin-top: 6px; }
.row > * { flex: 1; }

pre.status {
  margin: 0; padding: 6px 8px; background: var(--bg);
  border: 1px solid var(--border); border-radius: 4px;
  color: var(--fg); font-size: 11px; white-space: pre-wrap;
  max-height: 90px; overflow: auto;
}

#chat {
  flex: 1; overflow-y: auto; padding: 10px;
  display: flex; flex-direction: column; gap: 6px;
}
.msg {
  max-width: 78%; padding: 6px 10px; border-radius: 12px;
  font-size: 13px; line-height: 1.4; white-space: pre-wrap;
  word-wrap: break-word;
}
.msg.user { align-self: flex-end; background: #1c2a3a; color: var(--fg); }
.msg.bot  { align-self: flex-start; background: var(--block); }
.msg.system { align-self: center; color: var(--dim);
              font-size: 11px; font-style: italic; background: transparent; }

#composer {
  border-top: 1px solid var(--border); padding: 8px;
  display: flex; gap: 6px; background: var(--panel);
}
#composer input {
  flex: 1; background: var(--bg); color: var(--fg);
  border: 1px solid var(--border); border-radius: 4px;
  padding: 6px 10px; font-size: 13px;
}
#composer input:focus { outline: none; border-color: var(--accent); }

#logs {
  font-family: ui-monospace, monospace; font-size: 11px;
  white-space: pre-wrap; color: var(--fg);
  background: var(--bg); border: 1px solid var(--border);
  border-radius: 4px; padding: 6px 8px; height: 100%;
  overflow-y: auto;
}

#state-json {
  font-family: ui-monospace, monospace; font-size: 11px;
  white-space: pre-wrap; background: var(--bg);
  border: 1px solid var(--border); border-radius: 4px;
  padding: 6px 8px; margin-top: 8px;
  overflow-y: auto;
}

*::-webkit-scrollbar { width: 8px; height: 8px; }
*::-webkit-scrollbar-thumb { background: var(--border); border-radius: 5px; }
</style>
</head>
<body>

<header>
  <h1 data-i18n="title">Fona Chat</h1>
  <span class="status-badge off" id="badge">offline</span>
  <span class="url" id="agent-url"></span>
  <div class="spacer"></div>
  <button id="reconnect" data-i18n="reconnect">🔄</button>
</header>

<main>
  <!-- Column 1: data input -->
  <section class="col col-1">
    <div class="col-head" data-i18n="col_data">📁</div>
    <div class="col-body">
      <input type="file" id="data-file" class="file-input"
             accept=".txt,.md,.log,.pdf,.docx,.fb2">
      <textarea id="data-text" rows="8"
                data-i18n-placeholder="data_placeholder"
                placeholder=""></textarea>
      <div class="row">
        <button id="load-data" class="primary"
                data-i18n="load_data">📥</button>
        <button id="clear-data" data-i18n="clear_data">🗑️</button>
      </div>
      <pre class="status" id="data-status"></pre>
      <textarea id="data-preview" rows="6" readonly
                data-i18n-placeholder="data_preview_placeholder"
                placeholder=""></textarea>
    </div>
  </section>

  <!-- Column 2: chat -->
  <section class="col col-2">
    <div class="col-head" data-i18n="col_dialog">💬</div>
    <div id="chat"></div>
    <form id="composer">
      <input id="user-msg" autocomplete="off"
             data-i18n-placeholder="message_placeholder" placeholder="">
      <button type="submit" class="primary"
              data-i18n="send">Send</button>
      <!-- yes/no/restart/stop are shortcuts; yes and no send fixed
           strings "да"/"нет" as the demo agents expect them. -->
      <button type="button" id="yes" title="yes">✅</button>
      <button type="button" id="no" title="no">❌</button>
      <button type="button" id="restart" data-i18n-title="restart">🔄</button>
      <button type="button" id="stop" data-i18n-title="stop">⏹</button>
    </form>
  </section>

  <!-- Column 3: logs and state -->
  <section class="col col-3">
    <div class="col-head" data-i18n="col_logs">📋</div>
    <div class="col-body" style="padding:0">
      <div id="logs" style="border:none;border-radius:0;height:50%"></div>
    </div>
    <div class="col-head" data-i18n="col_state">🔬</div>
    <div class="col-body" style="padding:0">
      <pre id="state-json" style="margin:0;border:none;border-radius:0;height:50%"></pre>
    </div>
  </section>
</main>

<script>
(() => {
  'use strict';

  // ====================================================================
  // Translations
  // ====================================================================
  const I18N = {
    en: {
      title: "Fona Chat",
      status_online: "online",
      status_offline: "offline",
      reconnect: "🔄 Reconnect",
      col_data: "📁 Data",
      col_dialog: "💬 Dialog",
      col_logs: "📋 Logs",
      col_state: "🔬 State",
      data_placeholder: "Or paste text...",
      load_data: "📥 Load",
      clear_data: "🗑️ Clear",
      data_not_loaded: "No data loaded",
      data_preview_placeholder: "Preview...",
      message_placeholder: "Message...",
      send: "Send",
      restart: "Restart session",
      stop: "Stop session",
      connecting_to: "Connecting to {url}...",
      session_msg: "Session {id}...",
      connect_error: "Connection error: {msg}",
      disconnected: "Disconnected.",
      no_session: "No session",
      send_error: "Send error: {status}",
      network_error: "Network: {msg}",
      no_data: "✗ No data",
      data_loaded: "✓ Loaded {n} characters",
      data_cleared: "Data cleared",
      data_file_error: "✗ {msg}"
    },
    ru: {
      title: "Fona Чат",
      status_online: "онлайн",
      status_offline: "офлайн",
      reconnect: "🔄 Переподключиться",
      col_data: "📁 Данные",
      col_dialog: "💬 Диалог",
      col_logs: "📋 Логи",
      col_state: "🔬 Состояние",
      data_placeholder: "Или вставьте текст…",
      load_data: "📥 Загрузить",
      clear_data: "🗑️ Очистить",
      data_not_loaded: "Данные не загружены",
      data_preview_placeholder: "Превью…",
      message_placeholder: "Сообщение…",
      send: "Отправить",
      restart: "Перезапустить сессию",
      stop: "Остановить сессию",
      connecting_to: "Подключение к {url}…",
      session_msg: "Сессия {id}…",
      connect_error: "Ошибка подключения: {msg}",
      disconnected: "Отключено.",
      no_session: "Нет сессии",
      send_error: "Ошибка отправки: {status}",
      network_error: "Сеть: {msg}",
      no_data: "✗ Нет данных",
      data_loaded: "✓ Загружено {n} символов",
      data_cleared: "Данные очищены",
      data_file_error: "✗ {msg}"
    }
  };

  let currentLang = 'en';

  function t(key, vars) {
    const table = I18N[currentLang] || I18N.en;
    let s = table[key];
    if (s === undefined) s = I18N.en[key];
    if (s === undefined) s = key;
    if (vars) {
      for (const k of Object.keys(vars)) {
        s = s.split('{' + k + '}').join(String(vars[k]));
      }
    }
    return s;
  }

  // ====================================================================
  // Language detection — system/browser locale only.
  //
  // Rule: Russian if the first preferred language starts with "ru",
  // English for everything else.
  //
  // Sources, in order of priority:
  //   1. navigator.languages[0]  (full preference list, most reliable)
  //   2. navigator.language
  //   3. Intl.DateTimeFormat().resolvedOptions().locale
  //   4. "en"
  //
  // No localStorage, no manual switcher: a changed OS locale must be
  // picked up on the next page load without any "sticky" override.
  // ====================================================================
  function detectLang() {
    let lang = '';

    try {
      if (Array.isArray(navigator.languages) && navigator.languages.length) {
        lang = navigator.languages[0] || '';
      }
    } catch (_) {}
    if (!lang) {
      try { lang = navigator.language || ''; } catch (_) {}
    }
    if (!lang) {
      try {
        lang = (Intl.DateTimeFormat().resolvedOptions().locale) || '';
      } catch (_) {}
    }

    lang = String(lang).toLowerCase();
    return lang.startsWith('ru') ? 'ru' : 'en';
  }

  function applyLang(lang) {
    currentLang = (lang === 'ru') ? 'ru' : 'en';
    document.documentElement.lang = currentLang;
    document.title = t('title');

    document.querySelectorAll('[data-i18n]').forEach(el => {
      el.textContent = t(el.dataset.i18n);
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
      el.placeholder = t(el.dataset.i18nPlaceholder);
    });
    document.querySelectorAll('[data-i18n-title]').forEach(el => {
      el.title = t(el.dataset.i18nTitle);
    });

    updateBadge();
    renderDataStatus();
  }

  // ====================================================================
  // State
  // ====================================================================
  const $ = id => document.getElementById(id);
  const ORIGIN = location.origin;

  let sessionId = null;
  let running = false;
  let pollTimer = null;
  let abortCtl = null;
  let dataStatus = { key: 'data_not_loaded', vars: {} };

  // ====================================================================
  // Badge / status
  // ====================================================================
  function updateBadge() {
    const b = $('badge');
    b.textContent = running ? t('status_online') : t('status_offline');
    b.className = 'status-badge ' + (running ? 'on' : 'off');
  }

  function setRunning(on) {
    running = on;
    updateBadge();
  }

  // ====================================================================
  // Data status
  // ====================================================================
  function setDataStatus(key, vars) {
    dataStatus = { key: key, vars: vars || {} };
    renderDataStatus();
  }

  function renderDataStatus() {
    $('data-status').textContent = t(dataStatus.key, dataStatus.vars);
  }

  // ====================================================================
  // Chat
  // ====================================================================
  function append(text, role) {
    const el = document.createElement('div');
    el.className = 'msg ' + role;
    el.textContent = text;
    const chat = $('chat');
    chat.appendChild(el);
    chat.scrollTop = chat.scrollHeight;
  }

  // ====================================================================
  // Connect
  // ====================================================================
  async function connect() {
    if (abortCtl) { abortCtl.abort(); abortCtl = null; }
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    if (sessionId) {
      try {
        await fetch(`${ORIGIN}/api/v1/ui/stop?session_id=${encodeURIComponent(sessionId)}`,
                    { method: 'POST' });
      } catch (_) {}
    }
    sessionId = null;
    setRunning(false);
    append(t('connecting_to', { url: ORIGIN }), 'system');

    try {
      const r = await fetch(`${ORIGIN}/api/v1/ui/start`, { method: 'POST' });
      if (!r.ok) throw new Error('start ' + r.status);
      const d = await r.json();
      sessionId = d.session_id;
      setRunning(true);
      append(t('session_msg', { id: sessionId.slice(0, 8) }), 'system');
      startPolling();
    } catch (e) {
      append(t('connect_error', { msg: e.message }), 'system');
      setRunning(false);
    }
  }

  // ====================================================================
  // SSE polling (short-lived fetch per tick)
  // ====================================================================
  function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(pollOnce, 500);
  }

  async function pollOnce() {
    if (!sessionId) return;
    if (abortCtl) abortCtl.abort();
    abortCtl = new AbortController();
    try {
      const url = `${ORIGIN}/api/v1/ui/stream?session_id=${encodeURIComponent(sessionId)}`;
      const r = await fetch(url, { signal: abortCtl.signal });
      if (!r.ok) { setRunning(false); return; }
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf('\n\n')) !== -1) {
          const chunk = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          handleEvent(chunk);
        }
      }
    } catch (e) {
      if (e.name !== 'AbortError') setRunning(false);
    }
  }

  function handleEvent(chunk) {
    let type = 'message';
    let data = '';
    for (const line of chunk.split('\n')) {
      if (line.startsWith('event: ')) type = line.slice(7).trim();
      else if (line.startsWith('data: ')) data += line.slice(6);
    }
    if (!data) return;
    try {
      const obj = JSON.parse(data);
      if (type === 'output') {
        const msg = obj.text || '';
        if (msg && !msg.startsWith('Agent finished execution')) {
          append(msg, 'bot');
        }
      } else if (type === 'state') {
        if (obj.removed) { setRunning(false); }
        else if (typeof obj.running === 'boolean') setRunning(obj.running);
      }
    } catch (_) {}
  }

  // ====================================================================
  // Send
  // ====================================================================
  async function send(text, uiValues) {
    text = (text || '').trim();
    if (!sessionId) { append(t('no_session'), 'system'); return; }
    if (text) append(text, 'user');
    try {
      const r = await fetch(`${ORIGIN}/api/v1/ui/input`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          text: text,
          ui_values: uiValues || {},
        }),
      });
      if (!r.ok) append(t('send_error', { status: r.status }), 'system');
    } catch (e) {
      append(t('network_error', { msg: e.message }), 'system');
    }
  }

  // ====================================================================
  // Data load / clear
  // ====================================================================
  async function loadData() {
    const file = $('data-file').files[0];
    const text = $('data-text').value;
    const parts = [];
    if (file) {
      try {
        const r = await file.text();
        parts.push(r);
      } catch (e) {
        setDataStatus('data_file_error', { msg: e.message });
        return;
      }
    }
    if (text.trim()) parts.push(text);
    if (!parts.length) {
      setDataStatus('no_data');
      return;
    }
    const combined = parts.join('\n\n').replace(/"/g, "'");
    await send('', { data: combined });
    setDataStatus('data_loaded', { n: combined.length });
    $('data-preview').value = combined.slice(0, 500) +
      (combined.length > 500 ? '…' : '');
  }

  async function clearData() {
    await send('', { data: null });
    setDataStatus('data_cleared');
    $('data-preview').value = '';
  }

  // ====================================================================
  // Bindings
  // ====================================================================
  $('reconnect').onclick = async () => { await connect(); };

  $('composer').onsubmit = (e) => {
    e.preventDefault();
    const txt = $('user-msg').value;
    $('user-msg').value = '';
    send(txt);
  };
  // Yes/No shortcuts send "да"/"нет" — the demo agents expect these
  // exact Russian words. If your agent uses English keywords, change
  // the literal values here or handle both in the Prolog program.
  $('yes').onclick = () => send('да');
  $('no').onclick  = () => send('нет');
  $('restart').onclick = async () => { await connect(); };
  $('stop').onclick = async () => {
    if (sessionId) {
      try {
        await fetch(`${ORIGIN}/api/v1/ui/stop?session_id=${encodeURIComponent(sessionId)}`,
                    { method: 'POST' });
      } catch (_) {}
      sessionId = null;
    }
    setRunning(false);
    append(t('disconnected'), 'system');
  };

  $('load-data').onclick = loadData;
  $('clear-data').onclick = clearData;

  // ====================================================================
  // State panel
  // ====================================================================
  $('agent-url').textContent = ORIGIN;
  setInterval(() => {
    $('state-json').textContent = JSON.stringify({
      url: ORIGIN,
      session_id: sessionId,
      running: running,
      lang: currentLang,
    }, null, 2);
  }, 500);

  // ====================================================================
  // Boot
  // ====================================================================
  applyLang(detectLang());
  connect();
})();
</script>
</body>
</html>
"""