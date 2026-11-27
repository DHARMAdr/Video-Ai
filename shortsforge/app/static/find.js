/* find.js - the "Find" screen: describe a moment, tick the results, cut them into clips.
   WHY: automatic shorts only know kills and loud parts; here you can ask for something exact.
   HOW: the PC does the searching (shortsforge/find). This file sends your words, shows the
        results with pictures, and lets you teach example pictures by drawing a box.
   HOW TO IMPROVE: a timeline with the results as marks; editing start/end before cutting. */
(() => {
  const SF = window.SF, $ = s => document.querySelector(s), esc = SF.esc;
  const video = $('#fVideo'), canvas = $('#fDraw'), ctx = canvas.getContext('2d');
  let result = null, startPoint = null, box = null;

  const fileUrl = p => '/files/' + p.split('/').map(encodeURIComponent).join('/') + '?t=' + encodeURIComponent(SF.token) + '&v=' + Date.now();
  const source = () => $('#fSource').value.trim().replace(/^"|"$/g, '');

  function showResults(r) {
    result = r;
    $('#fResults').hidden = !r || !r.moments;
    if (!r || !r.moments) return;
    $('#fUnderstood').textContent = r.understood;
    $('#fProblems').innerHTML = [...r.problems, ...r.notes].map(p => `<p class="hint">${esc(p)}</p>`).join('');
    $('#fList').innerHTML = r.moments.map((m, i) => `<li>
      <input type="checkbox" checked data-i="${i}" aria-label="Use result ${i + 1}">
      ${m.thumb ? `<img src="${fileUrl(m.thumb)}" alt="">` : ''}
      <span><b>${SF.tc(m.start)} to ${SF.tc(m.end)}</b> · ${m.confidence}% sure<br><small>${m.why.map(esc).join('; ')}</small></span>
      <button type="button" class="quiet" data-play="${i}">Play</button></li>`).join('');
    $('#fMakeRow').hidden = !r.moments.length;
    if (!r.moments.length) $('#fList').innerHTML = '<li>No moments found.</li>';
  }
  function loadVideo(at) {
    const path = source();
    if (!path) return SF.toast('Choose a video first.');
    $('#fTeach').hidden = false;
    const go = () => { if (at !== undefined) { video.currentTime = at; video.play().catch(() => {}); } };
    if (video.dataset.path !== path) {
      video.dataset.path = path;
      video.src = '/api/video?path=' + encodeURIComponent(path) + '&t=' + encodeURIComponent(SF.token);
      video.addEventListener('loadedmetadata', go, { once: true });
    } else go();
    video.scrollIntoView({ block: 'center' });
  }
  function showStatus(s) {
    $('#fAgents').innerHTML = s.agents.map(a => `<option value="${esc(a)}">`).join('');
    $('#fVision').textContent = s.vision ? 'The picture AI is ready: you can describe scenes in your own words.'
      : 'Kills, taught pictures and speech work now. To describe other scenes, download a model and its picture reader in Settings > Built-in AI.';
    $('#fPictures').innerHTML = s.pictures.map(p => `<li><img src="${fileUrl(p.image)}" alt="">
      <span><b>${esc(p.name)}</b><br><small>${p.kind === 'feed' ? 'kill-feed icon' : 'on screen'}</small></span>
      <button type="button" class="quiet" data-forget="${esc(p.id)}">Delete</button></li>`).join('');
  }
  async function call(body) {
    try { showStatus(await SF.api('/api/find', body)); return true; }
    catch (e) { SF.toast(e.message); return false; }
  }

  $('#fBrowse').addEventListener('click', async () => {
    try {
      const r = await SF.api('/api/pick', {});
      if (r.path) $('#fSource').value = r.path;
      else if (r.unsupported) SF.toast('Paste the file path into the box.');
    } catch (e) { SF.toast(e.message); }
  });
  $('#fKnown').addEventListener('change', e => { if (e.target.value) $('#fSource').value = e.target.value; });
  $('#fExamples').addEventListener('click', e => { if (e.target.tagName === 'BUTTON') $('#fQuery').value = e.target.textContent; });
  function search() {
    if (!source()) return SF.toast('Choose a video first.');
    const query = $('#fQuery').value.trim();
    if (!query) return SF.toast('Say what to look for.');
    SF.startTask('/api/find', { action: 'search', source: source(), query }, r => showResults(r.find), 'Searching your video');
  }
  $('#fSearch').addEventListener('click', search);
  $('#fQuery').addEventListener('keydown', e => { if (e.key === 'Enter') search(); });
  $('#fList').addEventListener('click', e => {
    const b = e.target.closest('[data-play]');
    if (!b) return;
    $('#fSource').value = result.video;
    loadVideo(result.moments[+b.dataset.play].start);
  });
  $('#fMake').addEventListener('click', () => {
    const moments = [...document.querySelectorAll('#fList [data-i]:checked')].map(c => result.moments[+c.dataset.i]);
    if (!moments.length) return SF.toast('Tick at least one result.');
    SF.startTask('/api/find', { action: 'make', source: result.video, moments, layout: $('#fLayout').value, title: $('#fTitle').value },
      r => SF.openProject(r.project_name), 'Cutting your clips');
  });

  // ---- teaching a picture ----
  $('#fLoad').addEventListener('click', () => loadVideo());
  document.querySelectorAll('[data-fseek]').forEach(b => b.addEventListener('click', () => {
    video.pause(); video.currentTime = Math.max(0, video.currentTime + +b.dataset.fseek);
  }));
  $('#fBox').addEventListener('click', () => {
    if (!video.videoWidth) return SF.toast('Load the video first.');
    if (!$('#fName').value.trim()) return SF.toast('Type a name for the picture first.');
    video.pause(); box = null; video.scrollIntoView({ block: 'center' });
    canvas.width = video.clientWidth; canvas.height = video.clientHeight; canvas.hidden = false;
    canvas.style.left = video.offsetLeft + 'px'; canvas.style.top = video.offsetTop + 'px';
    SF.toast('Drag a tight box around it.');
  });
  const point = e => {
    const r = canvas.getBoundingClientRect();
    return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))];
  };
  canvas.addEventListener('pointerdown', e => { startPoint = point(e); canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener('pointermove', e => {
    if (!startPoint) return;
    const p = point(e);
    box = [Math.min(p[0], startPoint[0]), Math.min(p[1], startPoint[1]), Math.max(p[0], startPoint[0]), Math.max(p[1], startPoint[1])];
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = '#f2c230'; ctx.lineWidth = 2;
    ctx.strokeRect(box[0] * canvas.width, box[1] * canvas.height, (box[2] - box[0]) * canvas.width, (box[3] - box[1]) * canvas.height);
  });
  canvas.addEventListener('pointerup', async () => {
    startPoint = null; canvas.hidden = true; ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!box) return;
    const ok = await call({ action: 'add_picture', source: video.dataset.path, time: video.currentTime, box, name: $('#fName').value, kind: $('#fKind').value });
    if (ok) SF.toast('Saved. You can now search for it by name.');
  });
  $('#fPictures').addEventListener('click', e => {
    const b = e.target.closest('[data-forget]');
    if (b && confirm('Delete this picture?')) call({ action: 'delete_picture', id: b.dataset.forget });
  });

  addEventListener('sf:view', async e => {
    if (e.detail !== 'find') { video.pause(); return; }
    try {
      const s = await SF.api('/api/find');
      showStatus(s);
      if (s.last && s.last.moments) { showResults(s.last); if (!source()) $('#fSource').value = s.last.video; }
      const { videos } = await SF.api('/api/videos');
      $('#fKnown').innerHTML = '<option value="">Choose a video found on this PC...</option>' +
        videos.map(v => `<option value="${esc(v.path)}">${esc(v.name)}</option>`).join('');
    } catch (err) { SF.toast(err.message); }
  });
  SF.showFound = showResults;
})();
