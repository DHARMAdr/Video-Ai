/* editor.js - the "Editor" screen: cut, join, speed, filters, effects, text and music by hand.
   WHY: you asked for CapCut-like manual editing.
   HOW: the screen only keeps a "timeline" (a list of pieces and their settings). The PC renders it
        (shortsforge/editor.py). The live picture is an approximation made with CSS; press
        "Quick preview" to see the real result.
   HOW TO IMPROVE: drag pieces with the mouse, thumbnails on the timeline, keyframes. */
(() => {
  const SF = window.SF, $ = s => document.querySelector(s), esc = SF.esc;
  const video = $('#eVideo');
  const EMPTY = () => ({ aspect: '9:16', fit: 'crop', transition: { type: 'none', seconds: 0.5 }, segments: [], texts: [], music: null });
  let line = EMPTY(), sel = 0, history = [], choices = null, saveTimer = 0, showingResult = false;
  const CSS = { 'black and white': 'grayscale(1)', warm: 'sepia(.25) saturate(1.2)', cool: 'hue-rotate(10deg) saturate(.95)', vivid: 'saturate(1.55) contrast(1.1)',
    cinematic: 'contrast(1.12) saturate(.92)', vintage: 'sepia(.45) contrast(.95)', faded: 'contrast(.85) saturate(.75) brightness(1.06)', sepia: 'sepia(1)', negative: 'invert(1)' };
  const DEFAULT = { speed: 1, volume: 1, filter: 'none', effect: 'none', brightness: 0, contrast: 1, saturation: 1, zoom: 1, pan_x: 0, pan_y: 0, rotate: 0, mirror: false, reverse: false, fade_in: 0, fade_out: 0 };

  const seg = () => line.segments[sel];
  const name = p => String(p).split(/[\\/]/).pop();
  const url = p => '/api/video?path=' + encodeURIComponent(p) + '&t=' + encodeURIComponent(SF.token);
  const length = s => (s.end - s.start) / s.speed;
  const total = () => line.segments.reduce((a, s) => a + length(s), 0);

  function remember() { history.push(JSON.stringify(line)); if (history.length > 50) history.shift(); }
  function changed() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => SF.api('/api/editor', { action: 'save', timeline: line }).catch(() => {}), 600);
    draw();
  }
  function showSource() {
    const s = seg();
    showingResult = false;
    if (!s) { video.removeAttribute('src'); video.load(); return; }
    if (video.dataset.path !== s.source || !video.getAttribute('src')) {
      video.dataset.path = s.source; video.src = url(s.source);
      video.addEventListener('loadedmetadata', () => { video.currentTime = s.start; }, { once: true });
    } else video.currentTime = s.start;
  }
  function look() {                     // approximate picture while editing
    const s = seg();
    if (!s || showingResult) { video.style.filter = video.style.transform = ''; return; }
    video.style.filter = `${CSS[s.filter] || ''} brightness(${1 + s.brightness}) contrast(${s.contrast}) saturate(${s.saturation}) ${s.effect === 'blur' ? 'blur(4px)' : ''}`;
    video.style.transform = `scale(${(s.mirror ? -1 : 1) * s.zoom}, ${s.zoom}) rotate(${s.rotate}deg)`;
    video.playbackRate = Math.min(4, Math.max(0.25, s.speed)); video.volume = Math.min(1, s.volume);
  }
  function draw() {
    const s = seg();
    $('#eLine').innerHTML = line.segments.map((p, i) =>
      `<button type="button" class="piece" data-i="${i}" aria-pressed="${i === sel}" style="flex-grow:${Math.max(0.5, length(p))}">${i + 1}. ${esc(name(p.source))}<small>${length(p).toFixed(1)} s</small></button>`).join('');
    $('#eTotal').textContent = line.segments.length ? `${line.segments.length} piece(s), about ${total().toFixed(1)} s` : 'The timeline is empty. Add a video.';
    $('#eInspector').hidden = !s;
    if (s) document.querySelectorAll('[data-prop]').forEach(el => {
      if (el === document.activeElement && el.type === 'number') return;
      if (el.type === 'checkbox') el.checked = !!s[el.dataset.prop]; else el.value = Math.round(s[el.dataset.prop] * 100) / 100 || s[el.dataset.prop];
    });
    $('#eAspect').value = line.aspect; $('#eFit').value = line.fit;
    $('#eTrans').value = line.transition.type; $('#eTransSec').value = line.transition.seconds;
    $('#eTexts').innerHTML = line.texts.map((t, i) => `<div class="textrow" data-i="${i}">
      <input type="text" data-t="text" value="${esc(t.text)}" aria-label="Text" maxlength="200">
      <div class="grid4"><label class="field"><span>From (s)</span><input type="number" step="0.1" data-t="start" value="${t.start}"></label>
      <label class="field"><span>To (s)</span><input type="number" step="0.1" data-t="end" value="${t.end}"></label>
      <label class="field"><span>Height 0-1</span><input type="number" step="0.05" min="0" max="1" data-t="y" value="${t.y}"></label>
      <label class="field"><span>Size</span><input type="number" step="5" data-t="size" value="${t.size}"></label></div>
      <div class="wrap"><input type="color" data-t="color" value="${esc(t.color)}" aria-label="Colour">
      <select data-t="style" aria-label="Style">${['outline', 'box', 'plain'].map(v => `<option ${v === t.style ? 'selected' : ''}>${v}</option>`).join('')}</select>
      <button type="button" class="quiet" data-t="remove">Remove</button></div></div>`).join('');
    $('#eMusicName').textContent = line.music ? name(line.music.path) : 'No music';
    $('#eMusicVol').value = line.music ? line.music.volume : 0.35;
    look();
  }

  async function add(path) {
    if (!path) return;
    try {
      const info = await SF.api('/api/probe?path=' + encodeURIComponent(path));
      remember();
      line.segments.push({ ...DEFAULT, source: info.path, start: 0, end: Math.round(Math.min(info.duration, 600) * 100) / 100, duration: info.duration });
      sel = line.segments.length - 1; showSource(); changed();
    } catch (e) { SF.toast(e.message); }
  }
  async function browse(kind) {
    try {
      const r = await SF.api('/api/pick', { kind });
      if (r.path) return r.path;
      if (r.unsupported) return prompt('Paste the full path of the file:') || '';
    } catch (e) { SF.toast(e.message); }
    return '';
  }

  $('#eAdd').addEventListener('click', async () => add(await browse('video')));
  $('#eKnown').addEventListener('change', e => { add(e.target.value); e.target.value = ''; });
  $('#eLine').addEventListener('click', e => { const b = e.target.closest('[data-i]'); if (b) { sel = +b.dataset.i; showSource(); draw(); } });
  video.addEventListener('timeupdate', () => {
    const s = seg();
    $('#eTime').textContent = SF.tc(video.currentTime);
    if (s && !showingResult && !video.paused && video.currentTime >= s.end) { video.pause(); video.currentTime = s.start; }
  });
  document.querySelectorAll('[data-eseek]').forEach(b => b.addEventListener('click', () => { video.pause(); video.currentTime = Math.max(0, video.currentTime + +b.dataset.eseek); }));

  function needSource() {
    if (!seg() || showingResult) { showSource(); SF.toast('Showing your piece again. Move to the spot, then press the button.'); return false; }
    return true;
  }
  $('#eIn').addEventListener('click', () => { if (!needSource()) return; const s = seg(); if (video.currentTime >= s.end) return SF.toast('The start must be before the end.'); remember(); s.start = Math.round(video.currentTime * 100) / 100; changed(); });
  $('#eOut').addEventListener('click', () => { if (!needSource()) return; const s = seg(); if (video.currentTime <= s.start) return SF.toast('The end must be after the start.'); remember(); s.end = Math.round(video.currentTime * 100) / 100; changed(); });
  $('#eSplit').addEventListener('click', () => {
    if (!needSource()) return;
    const s = seg(), t = Math.round(video.currentTime * 100) / 100;
    if (t <= s.start + 0.2 || t >= s.end - 0.2) return SF.toast('Move inside the piece first.');
    remember(); line.segments.splice(sel, 1, { ...s, end: t }, { ...s, start: t }); changed();
  });
  $('#eCopy').addEventListener('click', () => { if (!seg()) return; remember(); line.segments.splice(sel, 0, { ...seg() }); sel++; changed(); });
  $('#eDelete').addEventListener('click', () => { if (!seg()) return; remember(); line.segments.splice(sel, 1); sel = Math.max(0, sel - 1); showSource(); changed(); });
  const move = d => { const j = sel + d; if (!seg() || j < 0 || j >= line.segments.length) return; remember(); [line.segments[sel], line.segments[j]] = [line.segments[j], line.segments[sel]]; sel = j; changed(); };
  $('#eLeft').addEventListener('click', () => move(-1));
  $('#eRight').addEventListener('click', () => move(1));
  $('#eUndo').addEventListener('click', () => { if (!history.length) return SF.toast('Nothing to undo.'); line = JSON.parse(history.pop()); sel = Math.min(sel, Math.max(0, line.segments.length - 1)); showSource(); changed(); });
  $('#eNew').addEventListener('click', () => { if (!confirm('Clear the timeline?')) return; remember(); line = EMPTY(); sel = 0; showSource(); changed(); });
  $('#eAll').addEventListener('click', () => {
    const s = seg(); if (!s) return; remember();
    line.segments.forEach(p => { for (const k of Object.keys(DEFAULT)) p[k] = s[k]; });
    changed(); SF.toast('Settings copied to every piece.');
  });

  document.querySelectorAll('[data-prop]').forEach(el => el.addEventListener('change', () => {
    const s = seg(); if (!s) return; remember();
    const k = el.dataset.prop;
    s[k] = el.type === 'checkbox' ? el.checked : (k === 'filter' || k === 'effect') ? el.value : +el.value;
    changed();
  }));
  $('#eAspect').addEventListener('change', e => { remember(); line.aspect = e.target.value; changed(); });
  $('#eFit').addEventListener('change', e => { remember(); line.fit = e.target.value; changed(); });
  $('#eTrans').addEventListener('change', e => { remember(); line.transition.type = e.target.value; changed(); });
  $('#eTransSec').addEventListener('change', e => { remember(); line.transition.seconds = +e.target.value; changed(); });
  $('#eAddText').addEventListener('click', () => { remember(); line.texts.push({ text: 'Your text', start: 0, end: 3, x: 0.5, y: 0.2, size: 90, color: '#ffffff', style: 'outline' }); changed(); });
  $('#eTexts').addEventListener('change', e => {
    const row = e.target.closest('[data-i]'), k = e.target.dataset.t; if (!row || !k) return;
    remember(); const t = line.texts[+row.dataset.i];
    t[k] = ['start', 'end', 'y', 'size'].includes(k) ? +e.target.value : e.target.value; changed();
  });
  $('#eTexts').addEventListener('click', e => { if (e.target.dataset.t !== 'remove') return; remember(); line.texts.splice(+e.target.closest('[data-i]').dataset.i, 1); changed(); });
  $('#eMusic').addEventListener('click', async () => { const p = await browse('audio'); if (!p) return; remember(); line.music = { path: p, volume: +$('#eMusicVol').value, start: 0 }; changed(); });
  $('#eNoMusic').addEventListener('click', () => { remember(); line.music = null; changed(); });
  $('#eMusicVol').addEventListener('change', e => { if (line.music) { line.music.volume = +e.target.value; changed(); } });

  function render(action) {
    if (!line.segments.length) return SF.toast('Add a video first.');
    $('#eMsg').textContent = '';
    SF.startTask('/api/editor', { action, timeline: line, title: $('#eTitle').value }, r => {
      showingResult = true; video.dataset.path = ''; video.playbackRate = 1;
      video.src = '/files/' + r.file.split('/').map(encodeURIComponent).join('/') + '?t=' + encodeURIComponent(SF.token) + '&v=' + Date.now();
      look();
      $('#eMsg').textContent = action === 'preview' ? 'This is the preview (small and fast). Press Export for full quality.' : 'Saved in the Clips tab, project "Edits".';
    }, action === 'preview' ? 'Making a preview' : 'Exporting your video');
  }
  $('#ePreview').addEventListener('click', () => render('preview'));
  $('#eExport').addEventListener('click', () => render('export'));

  async function open() {
    if (!choices) {
      choices = await SF.api('/api/editor');
      const fill = (id, list) => { $(id).innerHTML = list.map(v => `<option>${esc(v)}</option>`).join(''); };
      fill('#eFilter', choices.filters); fill('#eEffect', choices.effects); fill('#eTrans', choices.transitions); fill('#eAspect', choices.aspects);
      if (choices.draft && choices.draft.segments && !line.segments.length) line = { ...EMPTY(), ...choices.draft };
      showSource();
    }
    draw();
    try {
      const { videos } = await SF.api('/api/videos');
      $('#eKnown').innerHTML = '<option value="">Add a video found on this PC...</option>' + videos.map(v => `<option value="${esc(v.path)}">${esc(v.name)}</option>`).join('');
    } catch (e) { /* not important */ }
  }
  addEventListener('sf:view', e => { if (e.detail === 'editor') open().catch(err => SF.toast(err.message)); else video.pause(); });
  SF.editorAdd = async path => { SF.setView('editor'); await open(); await add(path); };
})();
