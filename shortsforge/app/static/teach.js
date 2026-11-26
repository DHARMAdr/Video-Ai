/* teach.js - the "Teach" screen: show the app an example video of yours.
   WHY: one fixed rule cannot fit every recording; your own marks and name make detection fit yours.
   HOW: you play the video, mark moments where you got a kill, drag a box around the kill feed and
        around your name; the PC tries several methods and reports how many marks it found.
   HOW TO IMPROVE: show the found kills on a timeline so you can correct them. */
(() => {
  const SF = window.SF, $ = s => document.querySelector(s);
  const video = $('#tVideo'), canvas = $('#tDraw'), ctx = canvas.getContext('2d');
  let source = '', marks = [], drawing = '', startPoint = null, box = null, area = null;

  function load() {
    const path = $('#tSource').value.trim();
    if (!path) return SF.toast('Choose your example video first.');
    source = path; marks = []; renderMarks(); $('#tWork').hidden = false; $('#tMsg').textContent = '';
    video.src = '/api/video?path=' + encodeURIComponent(path) + '&t=' + encodeURIComponent(SF.token);
  }
  video.addEventListener('error', () => {
    if (source) $('#tMsg').textContent = 'This window cannot play that file (or it was not found). MP4 (H.264) works best.';
  });
  function renderMarks() {
    $('#tMarks').innerHTML = marks.map((t, i) =>
      `<li><button type="button" class="quiet" data-go="${t}">${SF.tc(t)}</button> <button type="button" class="quiet" data-del="${i}" aria-label="Remove mark">✕</button></li>`).join('');
    $('#tCount').textContent = marks.length + ' kill' + (marks.length === 1 ? '' : 's') + ' marked';
  }
  async function status() {
    try {
      const s = await SF.api('/api/teach');
      area = s.area;
      $('#tState').textContent = !s.taught ? 'Nothing taught yet. The built-in rule is used.'
        : `Method: ${s.method}. ${s.name ? 'Your name is saved. ' : ''}${s.report ? s.report.message : ''}`;
    } catch (e) { $('#tState').textContent = e.message; }
  }
  // ---- drawing a box on the paused picture ----
  function startDraw(kind) {
    if (!video.videoWidth) return SF.toast('Load the video first.');
    video.pause(); drawing = kind; box = null;
    video.scrollIntoView({ block: 'center' });
    canvas.width = video.clientWidth; canvas.height = video.clientHeight; canvas.hidden = false;
    canvas.style.left = video.offsetLeft + 'px'; canvas.style.top = video.offsetTop + 'px';
    $('#tMsg').textContent = kind === 'area' ? 'Drag a box around the whole kill feed.'
      : 'Drag a tight box around YOUR NAME in one kill-feed line where you are the killer.';
  }
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
    startPoint = null;
    if (!box) return;
    try {
      await SF.api('/api/teach', { action: drawing, box, source, time: video.currentTime });
      $('#tMsg').textContent = drawing === 'area' ? 'Kill-feed area saved.' : 'Your name is saved.';
      status();
    } catch (e) { $('#tMsg').textContent = e.message; }
    canvas.hidden = true; ctx.clearRect(0, 0, canvas.width, canvas.height); drawing = '';
  });

  $('#tLoad').addEventListener('click', load);
  $('#tBrowse').addEventListener('click', async () => {
    try {
      const r = await SF.api('/api/pick', {});
      if (r.path) { $('#tSource').value = r.path; load(); }
      else if (r.unsupported) SF.toast('Paste the file path into the box.');
    } catch (e) { SF.toast(e.message); }
  });
  $('#tKnown').addEventListener('change', () => { if ($('#tKnown').value) { $('#tSource').value = $('#tKnown').value; load(); } });
  document.querySelectorAll('[data-seek]').forEach(b => b.addEventListener('click', () => {
    video.pause(); video.currentTime = Math.max(0, video.currentTime + +b.dataset.seek);
  }));
  $('#tMark').addEventListener('click', () => {
    if (!video.videoWidth) return SF.toast('Load the video first.');
    marks.push(Math.round(video.currentTime * 10) / 10); marks.sort((a, b) => a - b); renderMarks();
  });
  $('#tMarks').addEventListener('click', e => {
    const go = e.target.closest('[data-go]'), del = e.target.closest('[data-del]');
    if (go) { video.currentTime = +go.dataset.go; video.pause(); }
    if (del) { marks.splice(+del.dataset.del, 1); renderMarks(); }
  });
  $('#tArea').addEventListener('click', () => startDraw('area'));
  $('#tName').addEventListener('click', () => startDraw('name'));
  $('#tLearn').addEventListener('click', () => {
    if (!marks.length) return SF.toast('Mark at least one kill first. Four or more is best.');
    $('#tMsg').textContent = 'Learning... watch the progress strip.';
    SF.startTask('/api/teach', { action: 'learn', source, marks }, r => { $('#tMsg').textContent = r.teach.message; status(); }, 'Learning from your kills');
  });
  $('#tReset').addEventListener('click', async () => {
    if (!confirm('Forget what was taught (name, area, method)?')) return;
    await SF.api('/api/teach', { action: 'reset' }); $('#tMsg').textContent = ''; status();
  });

  addEventListener('sf:view', async e => {
    if (e.detail !== 'teach') { video.pause(); return; }
    status();
    try {
      const { videos } = await SF.api('/api/videos');
      $('#tKnown').innerHTML = '<option value="">Choose a video found on this PC...</option>' +
        videos.map(v => `<option value="${SF.esc(v.path)}">${SF.esc(v.name)}</option>`).join('');
    } catch (err) { /* not important */ }
  });
  SF.teachLoad = path => { $('#tSource').value = path; load(); };
})();
