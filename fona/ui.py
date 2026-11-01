"""HTML-страница UI. Встраивается как строка."""

HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Fona Agent</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 820px;
         margin: 2rem auto; padding: 0 1rem; }
  h1 { margin: 0 0 .5rem; font-size: 1.4rem; }
  #log { border: 1px solid #ccc; border-radius: 6px; padding: 1rem;
         height: 420px; overflow-y: auto; white-space: pre-wrap;
         font-family: ui-monospace, Menlo, monospace;
         font-size: .92rem; background: #fafafa;
         margin: .5rem 0 1rem; }
  .row { display: flex; gap: .5rem; margin-bottom: .6rem;
         align-items: center; flex-wrap: wrap; }
  input[type=text] { flex: 1; min-width: 200px;
                     padding: .55rem .7rem; font-size: 1rem;
                     border: 1px solid #ccc; border-radius: 6px; }
  select, input[type=checkbox] { font-size: .95rem; }
  button { padding: .55rem 1rem; font-size: .95rem; cursor: pointer;
           border: 1px solid #888; border-radius: 6px;
           background: #f0f0f0; }
  button.primary { background: #2c7be5; border-color: #2c7be5; color: #fff; }
  button:disabled { opacity: .45; cursor: not-allowed; }
  .status { font-size: .85rem; color: #b00; min-height: 1.2em; }
  .status.on { color: #128a36; }
  label { font-size: .9rem; display: flex; align-items: center; gap: .3rem; }
</style>
</head>
<body>
  <h1>Fona Agent</h1>
  <div class="status off" id="status">не запущен</div>
  <div id="log"></div>

  <div class="row">
    <button id="start" class="primary">Запустить</button>
    <button id="stop" disabled>Остановить</button>
    <label><input type="checkbox" id="repeat_check"> Повторять</label>
    <label>Режим:
      <select id="mode_select">
        <option>нейтральный</option>
        <option>ласковый</option>
        <option>грубый</option>
      </select>
    </label>
  </div>

  <div class="row">
    <input type="text" id="input" placeholder="Введите сообщение..." disabled>
    <button id="send" disabled>Отправить</button>
  </div>

<script>
(() => {
  const $ = id => document.getElementById(id);
  const log = $('log'), status = $('status'), input = $('input');
  const repeat = $('repeat_check'), mode = $('mode_select');
  let sid = null, es = null;

  function append(t) {
    log.textContent += t + '\n';
    log.scrollTop = log.scrollHeight;
  }

  function setRun(on) {
    status.textContent = on ? 'работает' : 'остановлен';
    status.className = 'status ' + (on ? 'on' : 'off');
    $('start').disabled = on;
    $('stop').disabled = !on;
    input.disabled = !on;
    $('send').disabled = !on;
    if (!on) input.value = '';
  }

  function collectUiValues() {
    return {
      repeat_check: repeat.checked,
      mode_select: mode.value,
    };
  }

  async function start() {
    log.textContent = '';
    setRun(false);
    try {
      const r = await fetch('/api/v1/ui/start', { method: 'POST' });
      if (!r.ok) { append('Ошибка старта: ' + await r.text()); return; }
      sid = (await r.json()).session_id;
      setRun(true);
      openStream();
    } catch (e) {
      append('Ошибка сети: ' + e.message);
    }
  }

  async function stop() {
    if (!sid) return;
    try {
      await fetch('/api/v1/ui/stop?session_id=' + encodeURIComponent(sid),
                  { method: 'POST' });
    } catch (_) {}
    closeStream(); sid = null; setRun(false);
  }

  async function send() {
    const text = input.value.trim();
    if (!text || !sid) return;
    input.value = '';
    try {
      const r = await fetch('/api/v1/ui/input', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sid,
          text,
          ui_values: collectUiValues(),
        }),
      });
      if (!r.ok) append('Ошибка отправки: ' + await r.text());
    } catch (e) {
      append('Ошибка сети: ' + e.message);
    }
  }

  function openStream() {
    closeStream();
    es = new EventSource(
      '/api/v1/ui/stream?session_id=' + encodeURIComponent(sid));
    es.addEventListener('output', e => {
      try { append(JSON.parse(e.data).text); } catch (_) {}
    });
    es.addEventListener('state', e => {
      try {
        const d = JSON.parse(e.data);
        if (d.finished || d.removed) { setRun(false); closeStream(); }
        else if (typeof d.running === 'boolean') setRun(d.running);
      } catch (_) {}
    });
  }

  function closeStream() { if (es) { es.close(); es = null; } }

  $('start').onclick = start;
  $('stop').onclick = stop;
  $('send').onclick = send;
  input.addEventListener('keydown', e => { if (e.key === 'Enter') send(); });
  window.addEventListener('beforeunload', () => {
    if (sid) navigator.sendBeacon(
      '/api/v1/ui/stop?session_id=' + encodeURIComponent(sid));
  });
})();
</script>
</body>
</html>
"""