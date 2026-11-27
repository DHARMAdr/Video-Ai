/* editor.js - the "Editor" screen: a timeline editor with layers, keyframes and shortcuts.
   WHY: you asked for editing that works like CapCut.
   HOW: the screen only keeps a "timeline" (plain data). Tracks:
          Video   - main pieces, one after another (drag to reorder, drag edges to trim)
          Overlay - pictures, stickers and videos on top
          Text    - words and captions
          Sound   - extra sounds
        The preview is an approximation made in the window; the PC renders the real file
        (shortsforge/editor.py). "Quick preview" shows the real result.
   HOW TO IMPROVE: thumbnails and sound waves on the timeline, selecting several items. */
(() => {
  const SF = window.SF, $ = s => document.querySelector(s), esc = SF.esc;
  const video = $('#eVideo'), layers = $('#eLayers'), tracks = $('#eTracks'), scroller = $('#eScroll');
  const EMPTY = () => ({ aspect: '9:16', fit: 'crop', resolution: 1080, fps: 30, transition: { type: 'none', seconds: 0.5 }, segments: [], overlays: [], texts: [], audio: [], music: null, range: null });
  const SEG = { speed: 1, volume: 1, filter: 'none', effect: 'none', brightness: 0, contrast: 1, saturation: 1, zoom: 1, pan_x: 0, pan_y: 0, rotate: 0, mirror: false, reverse: false, fade_in: 0, fade_out: 0, freeze: 0, disabled: false, keyframes: [] };
  const CSS = { 'black and white': 'grayscale(1)', warm: 'sepia(.25) saturate(1.2)', cool: 'hue-rotate(10deg) saturate(.95)', vivid: 'saturate(1.55) contrast(1.1)',
    cinematic: 'contrast(1.12) saturate(.92)', vintage: 'sepia(.45) contrast(.95)', faded: 'contrast(.85) saturate(.75) brightness(1.06)', sepia: 'sepia(1)', negative: 'invert(1)' };
  const LIST = { v: 'segments', o: 'overlays', t: 'texts', a: 'audio' };
  const FRAME = 1 / 30;
  let line = EMPTY(), sel = null, undo = [], redo = [], choices = null, saveTimer = 0;
  let now = 0, playing = false, last = 0, pps = 40, snap = true, mode = 'select', clipboard = null, showingResult = false;
  const media = new Map();                  // preview elements of overlays and sounds

  const round = n => Math.round(n * 100) / 100;
  const name = p => String(p).split(/[\\/]/).pop();
  const fileUrl = p => '/api/video?path=' + encodeURIComponent(p) + '&t=' + encodeURIComponent(SF.token);
  const lenOf = s => s.freeze ? s.freeze : (s.end - s.start) / s.speed;
  const fade = () => line.transition.type === 'none' ? 0 : line.transition.seconds;
  // Where each main piece starts on the timeline.
  function layout() {
    let t = 0;
    return line.segments.map(s => { const o = { s, at: t, len: lenOf(s) }; if (!s.disabled) t += o.len - fade(); return o; });
  }
  const mainLength = () => { const used = layout().filter(o => !o.s.disabled); return used.length ? used[used.length - 1].at + used[used.length - 1].len : 0; };
  const span = (kind, item) => kind === 'v' ? (() => { const o = layout().find(x => x.s === item); return [o.at, o.at + o.len]; })() : [item.start, item.end];
  const current = () => sel && line[LIST[sel.k]][sel.i];

  // ---- history and saving ------------------------------------------------------------------
  function remember() { undo.push(JSON.stringify(line)); if (undo.length > 100) undo.shift(); redo = []; }
  function changed() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => SF.api('/api/editor', { action: 'save', timeline: line }).catch(() => {}), 600);
    if (showingResult) { showingResult = false; video.dataset.path = ''; }
    if (sel && !current()) sel = null;
    now = Math.min(now, mainLength());
    draw(); seek(now);
  }
  function step(from, to) {
    if (!from.length) return SF.toast('Nothing more to ' + (from === undo ? 'undo.' : 'redo.'));
    to.push(JSON.stringify(line)); line = JSON.parse(from.pop()); sel = null; changed();
  }
  const edit = fn => { remember(); fn(); changed(); };

  // ---- preview -------------------------------------------------------------------------------
  const activeAt = t => { const all = layout().filter(o => !o.s.disabled); return all.filter(o => t >= o.at - 0.001).pop() || all[0]; };
  function seek(t) {
    now = Math.max(0, Math.min(t, mainLength()));
    if (!showingResult) {
      const o = activeAt(now);
      if (!o) { video.removeAttribute('src'); video.load(); video.dataset.path = ''; }
      else {
        const s = o.s, into = Math.min(o.len, Math.max(0, now - o.at));
        const want = s.freeze ? s.start : s.reverse ? s.end - into * s.speed : s.start + into * s.speed;
        if (video.dataset.path !== s.source) {
          video.dataset.path = s.source; video.src = fileUrl(s.source);
          video.addEventListener('loadedmetadata', () => { video.currentTime = want; }, { once: true });
        } else if (!playing || s.freeze || s.reverse || Math.abs(video.currentTime - want) > 0.3) video.currentTime = want;
        const k = valueAt(s, into, { zoom: s.zoom, pan_x: s.pan_x, pan_y: s.pan_y });
        video.style.filter = `${CSS[s.filter] || ''} brightness(${1 + s.brightness}) contrast(${s.contrast}) saturate(${s.saturation}) ${s.effect === 'blur' ? 'blur(4px)' : ''}`;
        video.style.transform = `scale(${(s.mirror ? -1 : 1) * k.zoom}, ${k.zoom}) rotate(${s.rotate}deg)`;
        video.style.objectFit = line.fit === 'crop' ? 'cover' : 'contain';
        video.style.objectPosition = `${50 + 50 * k.pan_x}% ${50 + 50 * k.pan_y}%`;
        video.playbackRate = Math.min(4, Math.max(0.25, s.speed));
        video.volume = Math.min(1, s.volume);
        if (playing && !s.freeze && !s.reverse) video.play().catch(() => {}); else video.pause();
      }
    }
    drawLayers(); drawHead();
  }
  function valueAt(item, t, base) {            // keyframes: slide between the saved values
    const keys = item.keyframes || [];
    if (!keys.length) return base;
    if (t <= keys[0].t) return keys[0];
    for (let i = 1; i < keys.length; i++) if (t <= keys[i].t) {
      const a = keys[i - 1], b = keys[i], f = (t - a.t) / Math.max(0.001, b.t - a.t), out = {};
      for (const k in base) out[k] = a[k] + (b[k] - a[k]) * f;
      return out;
    }
    return keys[keys.length - 1];
  }
  function tick(time) {
    if (!playing) return;
    now += (time - last) / 1000; last = time;
    if (showingResult) now = video.currentTime;
    const end = showingResult ? (video.duration || 0) : mainLength();
    if (now >= end - 0.01) { now = end; play(false); } else if (!showingResult) seek(now); else drawHead();
    if (playing) requestAnimationFrame(tick);
  }
  function play(on = !playing) {
    playing = on && (mainLength() > 0 || showingResult);
    $('#ePlay').textContent = playing ? 'Pause' : 'Play';
    if (playing) {
      if (now >= mainLength() - 0.05) now = 0;
      last = performance.now(); requestAnimationFrame(tick);
      if (showingResult) video.play().catch(() => {});
    } else { video.pause(); media.forEach(el => el.pause && el.pause()); }
    if (!showingResult) seek(now);
  }
  const STICKER = { arrow: '<path d="M5 38h53V18l37 32-37 32V62H5z"/>', circle: '<circle cx="50" cy="50" r="42" fill="none" stroke-width="9"/>', box: '<path d="M8 8h84v84H8z" fill="none" stroke-width="9"/>', star: '<path d="M50 3l12 33h36L69 57l11 36-30-21-30 21 11-36L2 36h36z"/>', cross: '<path d="M10 10l80 80M90 10L10 90" fill="none" stroke-width="10"/>' };
  function element(key, make) { if (!media.has(key)) media.set(key, make()); return media.get(key); }
  function drawLayers() {
    const shown = [];
    if (!showingResult) {
      line.overlays.forEach((o, i) => {
        if (now < o.start || now > o.end) return;
        const el = element(o.kind + o.source + i + o.color, () => {
          if (o.kind === 'sticker') { const d = document.createElement('div'); d.innerHTML = `<svg viewBox="0 0 100 100" width="100%" style="display:block;fill:#${esc(o.color)};stroke:#${esc(o.color)}">${STICKER[o.source]}</svg>`; return d; }
          const m = document.createElement(o.kind === 'image' ? 'img' : 'video'); m.src = fileUrl(o.source); if (o.kind === 'video') m.playsInline = true; return m;
        });
        const k = valueAt(o, now - o.start, { x: o.x, y: o.y, scale: o.scale });
        Object.assign(el.style, { left: k.x * 100 + '%', top: k.y * 100 + '%', width: k.scale * 100 + '%', opacity: o.opacity, transform: `translate(-50%,-50%) rotate(${o.rotate}deg) scaleX(${o.mirror ? -1 : 1})` });
        if (o.kind === 'video') {
          const want = o.src_start + now - o.start;
          if (Math.abs(el.currentTime - want) > 0.3) el.currentTime = want;
          el.muted = !o.volume; if (playing) el.play().catch(() => {}); else el.pause();
        }
        el.dataset.k = 'o'; el.dataset.i = i; shown.push(el);
      });
      line.texts.forEach((t, i) => {
        if (now < t.start || now > t.end) return;
        const el = element('text' + i, () => document.createElement('div'));
        el.className = 'etext'; el.textContent = t.text;
        Object.assign(el.style, { left: t.x * 100 + '%', top: t.y * 100 + '%', color: t.color, fontSize: t.size / 19.2 + 'cqh', background: t.style === 'box' ? 'rgba(0,0,0,.7)' : 'transparent' });
        el.dataset.k = 't'; el.dataset.i = i; shown.push(el);
      });
    }
    shown.forEach(el => el.classList.toggle('sel', !!sel && sel.k === el.dataset.k && sel.i === +el.dataset.i));
    [...layers.children].forEach(el => { if (!shown.includes(el)) { el.pause && el.pause(); el.remove(); } });
    shown.forEach(el => { if (el.parentNode !== layers) layers.appendChild(el); });
    line.audio.forEach((a, i) => {
      const el = element('audio' + a.path + i, () => new Audio(fileUrl(a.path)));
      const on = playing && !showingResult && now >= a.start && now <= a.end;
      if (!on) return el.pause();
      const want = a.src_start + now - a.start;
      if (Math.abs(el.currentTime - want) > 0.4) el.currentTime = want;
      el.volume = Math.min(1, a.volume); el.play().catch(() => {});
    });
  }
  // drag text and overlays on the picture
  layers.addEventListener('pointerdown', e => {
    const el = e.target.closest('[data-k]'); if (!el) return;
    sel = { k: el.dataset.k, i: +el.dataset.i }; draw();
    const item = current(), box = layers.getBoundingClientRect();
    let moved = false;
    const move = ev => {
      if (!moved) { remember(); moved = true; }
      item.x = round(Math.min(1, Math.max(0, (ev.clientX - box.left) / box.width)));
      item.y = round(Math.min(1, Math.max(0, (ev.clientY - box.top) / box.height)));
      const k = (item.keyframes || []).find(k => Math.abs(k.t - (now - item.start)) < 0.05);
      if (k) { k.x = item.x; k.y = item.y; }
      drawLayers();
    };
    const up = () => { removeEventListener('pointermove', move); removeEventListener('pointerup', up); if (moved) changed(); };
    addEventListener('pointermove', move); addEventListener('pointerup', up);
  });

  // ---- timeline ------------------------------------------------------------------------------
  // A sound with end 600 means "until the video ends", so it does not make the timeline longer.
  const total = () => Math.max(mainLength(), ...['o', 't', 'a'].flatMap(k => line[LIST[k]].map(x => x.end < 600 ? x.end : x.start + 1)), 0);
  function bar(k, i, a, b, label, extra = '', row = 0) {
    const on = sel && sel.k === k && sel.i === i;
    return `<div class="item${on ? ' sel' : ''}${extra}" data-k="${k}" data-i="${i}" style="left:${a * pps}px;width:${Math.max(18, (b - a) * pps)}px;top:${3 + row * 30}px" title="${esc(label)}"><i class="l"></i>${esc(label)}<i class="r"></i></div>`;
  }
  // Items that overlap in time get their own row, so none of them hides another.
  function lane(title, k, list, until, label) {
    const ends = [], html = list.map((x, i) => {
      let row = ends.findIndex(end => end <= x.start + 0.001);
      if (row < 0) row = ends.length;
      ends[row] = until(x);
      return bar(k, i, x.start, until(x), label(x), '', row);
    }).join('');
    return `<div class="track" style="height:${Math.max(1, ends.length) * 30 + 4}px"><em>${title}</em>${html}</div>`;
  }
  function draw() {
    const width = Math.max(scroller.clientWidth - 2, (total() + 5) * pps);
    const every = [0.5, 1, 2, 5, 10, 30, 60].find(s => s * pps >= 60) || 120;
    let ruler = '';
    for (let t = 0; t * pps < width; t += every) ruler += `<span style="left:${t * pps}px">${SF.tc(t)}</span>`;
    const mark = line.range ? `<div class="mark" style="left:${line.range.in * pps}px;width:${Math.max(0, line.range.out - line.range.in) * pps}px"></div>` : '';
    tracks.style.width = width + 'px';
    tracks.innerHTML = `<div class="ruler">${ruler}</div>${mark}` +
      lane('Text', 't', line.texts, t => t.end, t => t.text) +
      lane('Overlay', 'o', line.overlays, o => o.end, o => o.kind === 'sticker' ? o.source : name(o.source)) +
      `<div class="track"><em>Video</em>${layout().map((o, i) => bar('v', i, o.at, o.at + o.len, (o.s.freeze ? '❄ ' : '') + name(o.s.source), o.s.disabled ? ' off' : '')).join('')}</div>` +
      lane('Sound', 'a', line.audio, a => Math.min(a.end, Math.max(total(), a.start + 1)), a => name(a.path)) +
      '<div class="playhead"></div>';
    $('#eTotal').textContent = line.segments.length ? `${round(mainLength())} s` : 'The timeline is empty. Add a video.';
    $('#eAspect').value = line.aspect; $('#eFit').value = line.fit; $('#eTrans').value = line.transition.type; $('#eTransSec').value = line.transition.seconds;
    $('#eRes').value = line.resolution; $('#eFps').value = line.fps;
    $('#eMusicName').textContent = line.music ? name(line.music.path) : 'No music';
    $('#eMusicVol').value = line.music ? line.music.volume : 0.35;
    $('#eStage').style.aspectRatio = line.aspect.replace(':', ' / ');
    inspector(); drawHead(); drawLayers();
  }
  function drawHead() {
    const head = tracks.querySelector('.playhead');
    if (head) head.style.left = now * pps + 'px';
    $('#eTime').textContent = SF.tc(now) + ' / ' + SF.tc(showingResult ? video.duration || 0 : mainLength());
  }
  function snapTo(t, skip) {
    if (!snap) return t;
    const points = [0, now, ...layout().flatMap(o => o.s === skip ? [] : [o.at, o.at + o.len]), ...['o', 't', 'a'].flatMap(k => line[LIST[k]].flatMap(x => x === skip ? [] : [x.start, x.end]))];
    const near = points.reduce((a, b) => Math.abs(b - t) < Math.abs(a - t) ? b : a, 1e9);
    return Math.abs(near - t) * pps < 8 ? near : t;
  }
  const timeAt = e => Math.max(0, (e.clientX - tracks.getBoundingClientRect().left) / pps);

  tracks.addEventListener('pointerdown', e => {
    const el = e.target.closest('.item');
    if (!el) {                                   // click on ruler or empty space = move playhead
      const go = ev => { showingResult = false; seek(snapTo(timeAt(ev))); };
      go(e); if (!e.target.closest('.ruler')) { sel = null; draw(); }
      const up = () => { removeEventListener('pointermove', go); removeEventListener('pointerup', up); };
      addEventListener('pointermove', go); addEventListener('pointerup', up);
      return;
    }
    e.preventDefault();
    const k = el.dataset.k, i = +el.dataset.i, item = line[LIST[k]][i], edge = e.target.closest('i');
    sel = { k, i };
    if (mode === 'split') { seek(timeAt(e)); return split(); }
    const x0 = e.clientX, before = JSON.stringify(line), orig = { ...item }, [from] = span(k, item);
    let moved = false;
    const move = ev => {
      const d = (ev.clientX - x0) / pps;
      if (!moved && Math.abs(ev.clientX - x0) < 4) return;
      moved = true;
      if (k === 'v') {
        if (edge) {                              // trim a main piece
          if (item.freeze) item.freeze = round(Math.min(30, Math.max(0.2, orig.freeze + (edge.className === 'r' ? d : -d))));
          else if (edge.className === 'l') item.start = round(Math.min(orig.end - 0.2, Math.max(0, orig.start + d * item.speed)));
          else item.end = round(Math.max(orig.start + 0.2, Math.min(orig.duration || 1e6, orig.end + d * item.speed)));
        } else el.style.transform = `translateX(${ev.clientX - x0}px)`;
        if (edge) el.style.width = Math.max(18, lenOf(item) * pps) + 'px';
      } else {
        const length = orig.end - orig.start;
        if (!edge) { item.start = round(Math.max(0, snapTo(orig.start + d, item))); item.end = round(item.start + length); }
        else if (edge.className === 'l') item.start = round(Math.min(orig.end - 0.2, Math.max(0, snapTo(orig.start + d, item))));
        else item.end = round(Math.max(orig.start + 0.2, snapTo(orig.end + d, item)));
        el.style.left = item.start * pps + 'px'; el.style.width = Math.max(18, (Math.min(item.end, 600) - item.start) * pps) + 'px';
      }
    };
    const up = ev => {
      removeEventListener('pointermove', move); removeEventListener('pointerup', up);
      if (!moved) return;
      if (k === 'v' && !edge) {                  // drop = new position among the pieces
        const middle = from + lenOf(item) / 2 + (ev.clientX - x0) / pps;
        const others = layout().filter(o => o.s !== item);
        const at = others.filter(o => o.at + o.len / 2 < middle).length;
        line.segments.splice(i, 1); line.segments.splice(at, 0, item); sel = { k, i: at };
      }
      undo.push(before); redo = []; changed();
    };
    addEventListener('pointermove', move); addEventListener('pointerup', up);
    // Only mark it as chosen: redrawing here would throw away the bar being dragged.
    if (document.activeElement) document.activeElement.blur();
    tracks.querySelectorAll('.item').forEach(x => x.classList.toggle('sel', x === el));
    inspector(); drawLayers();
  });

  // ---- editing commands ------------------------------------------------------------------------
  // Cut one item at timeline time t. Returns false when t is not inside it.
  function cut(k, i, t) {
    const list = line[LIST[k]], item = list[i], [a, b] = span(k, item);
    if (t <= a + 0.1 || t >= b - 0.1) return false;
    const left = JSON.parse(JSON.stringify(item)), right = JSON.parse(JSON.stringify(item));
    if (k === 'v') {
      if (item.freeze) { left.freeze = round(t - a); right.freeze = round(b - t); }
      else {
        const into = (t - a) * item.speed;
        if (item.reverse) { left.start = round(item.end - into); right.end = round(item.end - into); }
        else { left.end = round(item.start + into); right.start = round(item.start + into); }
      }
    } else {
      left.end = round(t); right.start = round(t);
      if ('src_start' in item) right.src_start = round(item.src_start + t - a);
    }
    const shift = t - a;
    if (item.keyframes) { left.keyframes = left.keyframes.filter(x => x.t <= shift); right.keyframes = right.keyframes.filter(x => x.t > shift).map(x => ({ ...x, t: round(x.t - shift) })); }
    list.splice(i, 1, left, right);
    return true;
  }
  function target() {                            // the selected item, else the main piece under the playhead
    if (sel) return sel;
    const o = activeAt(now);
    return o ? { k: 'v', i: line.segments.indexOf(o.s) } : null;
  }
  function split() {
    const t = target(); if (!t) return;
    remember(); if (!cut(t.k, t.i, now)) { undo.pop(); return SF.toast('Move the red line inside the item first.'); }
    sel = { k: t.k, i: t.i + 1 }; changed();
  }
  function splitAll() {
    remember(); let any = false;
    for (const k of ['v', 'o', 't', 'a']) for (let i = line[LIST[k]].length - 1; i >= 0; i--) any = cut(k, i, now) || any;
    if (!any) { undo.pop(); return; }
    sel = null; changed();
  }
  function cutSide(left) {                       // Q and W: remove what is left / right of the playhead
    const t = target(); if (!t) return;
    const item = line[LIST[t.k]][t.i], [a] = span(t.k, item);
    remember(); if (!cut(t.k, t.i, now)) { undo.pop(); return; }
    line[LIST[t.k]].splice(left ? t.i : t.i + 1, 1);
    if (left && t.k === 'v') now = a;
    sel = null; changed();
  }
  function remove() { if (!current()) return SF.toast('Click something on the timeline first.'); edit(() => { line[LIST[sel.k]].splice(sel.i, 1); sel = null; }); }
  function copy() { if (current()) clipboard = { k: sel.k, item: JSON.stringify(current()) }; }
  function paste() {
    if (!clipboard) return;
    edit(() => {
      const item = JSON.parse(clipboard.item), list = line[LIST[clipboard.k]];
      if (clipboard.k !== 'v') { const length = item.end - item.start; item.start = round(now); item.end = round(now + length); list.push(item); sel = { k: clipboard.k, i: list.length - 1 }; }
      else { const at = sel && sel.k === 'v' ? sel.i + 1 : list.length; list.splice(at, 0, item); sel = { k: 'v', i: at }; }
    });
  }
  function duplicate() { if (!current()) return; copy(); paste(); }
  function freeze() {
    const o = activeAt(now); if (!o) return;
    const i = line.segments.indexOf(o.s);
    edit(() => {
      const s = o.s, into = (now - o.at) * s.speed, at = round(s.freeze ? s.start : s.reverse ? s.end - into : s.start + into);
      const still = { ...JSON.parse(JSON.stringify(s)), start: at, end: round(at + 2), freeze: 2, speed: 1, reverse: false, keyframes: [] };
      const did = cut('v', i, now);
      line.segments.splice(did ? i + 1 : now <= o.at + 0.1 ? i : i + 1, 0, still);
    });
  }
  function extractAudio() {                      // move a piece's sound to its own track, or back
    const o = sel && sel.k === 'v' ? layout()[sel.i] : null;
    if (!o) return SF.toast('Select a video piece first.');
    edit(() => {
      const s = o.s, at = line.audio.findIndex(a => a.from === s.source && Math.abs(a.start - o.at) < 0.05);
      if (at >= 0) { line.audio.splice(at, 1); s.volume = 1; return; }
      line.audio.push({ path: s.source, from: s.source, start: round(o.at), end: round(o.at + o.len), src_start: s.start, volume: s.volume || 1, fade_in: 0, fade_out: 0 });
      s.volume = 0;
    });
  }
  function keyframe() {
    const item = current(); if (!item || (sel.k !== 'v' && sel.k !== 'o')) return SF.toast('Select a video piece or an overlay first.');
    const [a, b] = span(sel.k, item); if (now < a || now > b) return SF.toast('Move the red line inside it first.');
    edit(() => {
      const t = round(now - a), values = sel.k === 'v' ? { zoom: item.zoom, pan_x: item.pan_x, pan_y: item.pan_y } : { x: item.x, y: item.y, scale: item.scale };
      item.keyframes = (item.keyframes || []).filter(k => Math.abs(k.t - t) > 0.05);
      item.keyframes.push({ t, ...values }); item.keyframes.sort((p, q) => p.t - q.t);
    });
    SF.toast('Keyframe saved. Move the red line, change zoom or position, and save another.');
  }
  function jumpCut(direction) {
    const points = [...new Set([0, mainLength(), ...layout().map(o => o.at)])].sort((a, b) => a - b);
    const next = direction > 0 ? points.find(p => p > now + 0.02) : points.filter(p => p < now - 0.02).pop();
    if (next !== undefined) seek(next);
  }
  function zoom(factor) { pps = Math.min(400, Math.max(4, pps * factor)); draw(); }
  const fit = () => { pps = Math.min(400, Math.max(4, (scroller.clientWidth - 20) / Math.max(1, total()))); draw(); };
  function nudgeVolume(d) { const item = current(); if (!item || item.volume === undefined) return; edit(() => { item.volume = round(Math.min(3, Math.max(0, item.volume + d))); }); }
  function mark(which) {
    edit(() => {
      const r = line.range || { in: 0, out: mainLength() };
      r[which] = round(now);
      if (r.out <= r.in) { if (which === 'in') r.out = mainLength(); else r.in = 0; }
      line.range = r;
    });
  }
  function setMode(m) { mode = m; tracks.style.cursor = m === 'split' ? 'crosshair' : ''; SF.toast(m === 'split' ? 'Split mode: click a piece to cut it. Press A to stop.' : 'Select mode.'); }

  // ---- keyboard ------------------------------------------------------------------------------------
  const KEYS = [
    ['Space', 'Play / pause', () => play()], ['ArrowLeft', 'Back one frame', () => seek(now - FRAME)], ['ArrowRight', 'Forward one frame', () => seek(now + FRAME)],
    ['Shift+ArrowLeft', 'Back 10 frames', () => seek(now - 10 * FRAME)], ['Shift+ArrowRight', 'Forward 10 frames', () => seek(now + 10 * FRAME)],
    ['ArrowUp', 'Previous cut', () => jumpCut(-1)], ['ArrowDown', 'Next cut', () => jumpCut(1)], ['Home', 'Go to start', () => seek(0)], ['End', 'Go to end', () => seek(mainLength())],
    ['Ctrl+B', 'Split at red line', split], ['Ctrl+Shift+B', 'Split all tracks', splitAll], ['Q', 'Delete left of red line', () => cutSide(true)], ['W', 'Delete right of red line', () => cutSide(false)],
    ['Delete', 'Delete selected', remove], ['Backspace', 'Delete selected', remove], ['V', 'Switch piece off / on', () => { if (sel && sel.k === 'v') edit(() => { current().disabled = !current().disabled; }); }],
    ['A', 'Select mode', () => setMode('select')], ['B', 'Split mode', () => setMode('split')], ['I', 'Mark in', () => mark('in')], ['O', 'Mark out', () => mark('out')], ['Alt+X', 'Clear marks', () => edit(() => { line.range = null; })],
    ['Ctrl+C', 'Copy', copy], ['Ctrl+X', 'Cut', () => { copy(); remove(); }], ['Ctrl+V', 'Paste', paste], ['Ctrl+Z', 'Undo', () => step(undo, redo)], ['Ctrl+Shift+Z', 'Redo', () => step(redo, undo)],
    ['Ctrl+Shift+S', 'Extract / restore sound', extractAudio], ['Ctrl+R', 'Speed box', () => { const el = document.querySelector('[data-f="speed"]'); if (el) el.focus(); }],
    ['Ctrl+.', 'Volume up', () => nudgeVolume(0.1)], ['Ctrl+,', 'Volume down', () => nudgeVolume(-0.1)], ['Alt+K', 'Add keyframe', keyframe], ['N', 'Snapping on / off', () => $('#eSnap').click()],
    ['Ctrl+=', 'Zoom timeline in', () => zoom(1.4)], ['Ctrl+-', 'Zoom timeline out', () => zoom(1 / 1.4)], ['Shift+Z', 'Fit timeline', fit], ['Ctrl+Shift+F', 'Full screen preview', () => $('#eFull').click()],
    ['Ctrl+I', 'Add video', () => $('#eAdd').click()], ['Ctrl+N', 'New project', () => $('#eNew').click()], ['Ctrl+E', 'Export', () => $('#eExport').click()],
  ];
  const keyName = e => {
    let key = e.code === 'Space' ? 'Space' : e.key.length === 1 ? e.key.toUpperCase() : e.key;
    if (key === '+') key = '=';
    if (key === '_') key = '-';
    return (e.ctrlKey || e.metaKey ? 'Ctrl+' : '') + (e.altKey ? 'Alt+' : '') + (e.shiftKey && !['=', '-'].includes(key) ? 'Shift+' : '') + key;
  };
  addEventListener('keydown', e => {
    if ($('#view-editor').hidden || $('#eHelp').open || document.querySelector('dialog[open]')) return;
    const typing = e.target.closest('input, textarea, select');
    if (typing && !(e.ctrlKey && /^[bse]$/i.test(e.key))) return;
    const found = KEYS.find(k => k[0] === keyName(e));
    if (!found) return;
    if (e.target.tagName === 'BUTTON' && found[0] === 'Space') e.target.blur();
    e.preventDefault(); found[2]();
  });
  scroller.addEventListener('wheel', e => {
    if (e.ctrlKey) { e.preventDefault(); zoom(e.deltaY < 0 ? 1.2 : 1 / 1.2); }
    else if (e.altKey) { e.preventDefault(); scroller.scrollLeft += e.deltaY; }
  }, { passive: false });
  $('#eHelpTable').innerHTML = KEYS.map(k => `<tr><td><kbd>${esc(k[0])}</kbd></td><td>${esc(k[1])}</td></tr>`).join('');

  // ---- the settings panel of the selected item -------------------------------------------------------
  const num = (f, label, min, max, st) => `<label class="field"><span>${label}</span><input type="number" data-f="${f}" min="${min}" max="${max}" step="${st}"></label>`;
  const pick = (f, label, list) => `<label class="field"><span>${label}</span><select data-f="${f}">${list.map(v => `<option>${esc(v)}</option>`).join('')}</select></label>`;
  const check = (f, label) => `<label class="check"><input type="checkbox" data-f="${f}">${label}</label>`;
  const fades = num('fade_in', 'Fade in (s)', 0, 5, 0.1) + num('fade_out', 'Fade out (s)', 0, 5, 0.1);
  const place = num('x', 'Across (0-1)', -0.5, 1.5, 0.01) + num('y', 'Down (0-1)', -0.5, 1.5, 0.01);
  function panel() {
    const k = sel.k;
    if (k === 'v') return '<h2>Video piece</h2>' + (current().freeze ? num('freeze', 'Still for (s)', 0.2, 30, 0.5) : `<div class="grid4">${num('start', 'Start (s)', 0, 1e5, 0.1)}${num('end', 'End (s)', 0, 1e5, 0.1)}${num('speed', 'Speed', 0.25, 4, 0.25)}${num('volume', 'Volume', 0, 3, 0.1)}</div>`) +
      pick('filter', 'Filter', choices.filters) + pick('effect', 'Effect', choices.effects) +
      `<div class="grid4">${num('brightness', 'Brightness', -0.3, 0.3, 0.05)}${num('contrast', 'Contrast', 0.5, 2, 0.1)}${num('saturation', 'Colour', 0, 3, 0.1)}${num('zoom', 'Zoom', 1, 4, 0.1)}${num('pan_x', 'Pan across', -1, 1, 0.1)}${num('pan_y', 'Pan down', -1, 1, 0.1)}${fades}</div>` +
      pick('rotate', 'Rotate', ['0', '90', '180', '270']) + `<div class="wrap">${check('mirror', 'Mirror')}${check('reverse', 'Reverse')}<button type="button" data-do="key">Add keyframe</button><button type="button" data-do="audio">Extract / restore sound</button><button type="button" class="quiet" data-do="all">Use on all pieces</button></div>`;
    if (k === 't') return '<h2>Text</h2><label class="field"><span>Words</span><textarea data-f="text" rows="2" maxlength="200"></textarea></label>' +
      `<div class="grid4">${num('start', 'From (s)', 0, 600, 0.1)}${num('end', 'To (s)', 0, 605, 0.1)}${place}${num('size', 'Size', 20, 300, 5)}</div>` +
      '<label class="field"><span>Colour</span><input type="color" data-f="color"></label>' + pick('style', 'Style', ['outline', 'box', 'plain']) + pick('anim', 'Animation', choices.animations);
    if (k === 'a') return `<h2>Sound</h2><div class="grid4">${num('start', 'From (s)', 0, 600, 0.1)}${num('end', 'To (s)', 0, 605, 0.1)}${num('src_start', 'Skip first (s)', 0, 1e6, 0.5)}${num('volume', 'Volume', 0, 3, 0.1)}${fades}</div>`;
    const o = current();
    return `<h2>Overlay</h2><div class="grid4">${num('start', 'From (s)', 0, 600, 0.1)}${num('end', 'To (s)', 0, 605, 0.1)}${place}${num('scale', 'Size (0-3)', 0.03, 3, 0.05)}${num('opacity', 'Opacity', 0.05, 1, 0.05)}${num('rotate', 'Rotate (°)', -360, 360, 5)}${fades}</div>` +
      (o.kind === 'sticker' ? '<label class="field"><span>Colour</span><input type="color" data-f="color"></label>'
        : `<div class="wrap">${check('keyed', 'Green screen (make a colour see-through)')}</div><label class="field"><span>Colour to remove</span><input type="color" data-f="chroma"></label>${num('similarity', 'Strength', 0.01, 0.6, 0.01)}`) +
      (o.kind === 'video' ? `<div class="grid4">${num('src_start', 'Skip first (s)', 0, 1e6, 0.5)}${num('volume', 'Volume', 0, 2, 0.1)}</div>` : '') +
      `<div class="wrap">${check('mirror', 'Mirror')}<button type="button" data-do="key">Add keyframe</button></div>`;
  }
  function inspector() {
    const box = $('#eInspector'), item = current();
    if (!item || !choices) { box.innerHTML = '<p class="hint">Click a piece, text, overlay or sound on the timeline to change it.</p>'; return; }
    if (box.contains(document.activeElement) && box.dataset.for === sel.k + sel.i) return;
    box.dataset.for = sel.k + sel.i;
    box.innerHTML = panel() + (item.keyframes && item.keyframes.length ? `<p class="hint">${item.keyframes.length} keyframe(s). <button type="button" class="quiet" data-do="nokeys">Remove them</button></p>` : '');
    box.querySelectorAll('[data-f]').forEach(el => {
      const f = el.dataset.f;
      if (f === 'keyed') el.checked = !!item.chroma;
      else if (el.type === 'checkbox') el.checked = !!item[f];
      else if (el.type === 'color') el.value = item[f] ? '#' + String(item[f]).replace('#', '') : f === 'chroma' ? '#00ff00' : '#ffffff';
      else el.value = item[f] === undefined ? (f === 'anim' ? 'pop' : 0) : item[f];
    });
  }
  $('#eInspector').addEventListener('change', e => {
    const f = e.target.dataset.f, item = current(); if (!f || !item) return;
    edit(() => {
      const el = e.target;
      if (f === 'keyed') item.chroma = el.checked ? '00ff00' : '';
      else if (el.type === 'checkbox') item[f] = el.checked;
      else if (el.type === 'number' || f === 'rotate') item[f] = +el.value;
      else if (f === 'chroma' || (f === 'color' && sel.k === 'o')) item[f] = el.value.slice(1);
      else item[f] = el.value;
      // A value changed while the red line sits on a keyframe updates that keyframe.
      const [a] = span(sel.k, item), k = (item.keyframes || []).find(k => Math.abs(k.t - (now - a)) < 0.05);
      if (k && f in k) k[f] = item[f];
    });
  });
  $('#eInspector').addEventListener('click', e => {
    const b = e.target.closest('[data-do]'); if (!b) return;
    const what = b.dataset.do;
    if (what === 'key') keyframe();
    if (what === 'audio') extractAudio();
    if (what === 'nokeys') edit(() => { current().keyframes = []; });
    if (what === 'all') { const s = current(); edit(() => line.segments.forEach(p => { for (const k of Object.keys(SEG)) if (!['keyframes', 'freeze', 'disabled'].includes(k)) p[k] = s[k]; })); SF.toast('Settings copied to every piece.'); }
  });

  // ---- adding things -------------------------------------------------------------------------------
  async function probe(path) { return SF.api('/api/probe?path=' + encodeURIComponent(path)); }
  async function add(path) {
    if (!path) return;
    try {
      const info = await probe(path);
      edit(() => { line.segments.push({ ...SEG, keyframes: [], source: info.path, start: 0, end: round(Math.min(info.duration, 600)), duration: info.duration }); sel = { k: 'v', i: line.segments.length - 1 }; });
      if (line.segments.length === 1) fit();
    } catch (e) { SF.toast(e.message); }
  }
  async function browse(kind) {
    try {
      const r = await SF.api('/api/pick', { kind });
      if (r.path) return r.path;
      if (r.unsupported) return (prompt('Paste the full path of the file:') || '').trim().replace(/^"|"$/g, '');
    } catch (e) { SF.toast(e.message); }
    return '';
  }
  function addLayer(kind, source, extra = {}) {
    edit(() => {
      line.overlays.push({ kind, source, start: round(now), end: round(now + 3), src_start: 0, x: 0.5, y: 0.35, scale: 0.4, opacity: 1, rotate: 0, mirror: false, chroma: '', similarity: 0.18, color: 'ffe14d', volume: 0, fade_in: 0, fade_out: 0, keyframes: [], ...extra });
      sel = { k: 'o', i: line.overlays.length - 1 };
    });
  }
  $('#eAdd').addEventListener('click', async () => add(await browse('video')));
  $('#eKnown').addEventListener('change', e => { add(e.target.value); e.target.value = ''; });
  $('#eAddImage').addEventListener('click', async () => { const p = await browse('image'); if (p) addLayer('image', p); });
  $('#eAddOverlay').addEventListener('click', async () => {
    const p = await browse('video'); if (!p) return;
    try { const info = await probe(p); addLayer('video', info.path, { end: round(now + Math.min(info.duration, 10)) }); } catch (e) { SF.toast(e.message); }
  });
  $('#eSticker').addEventListener('change', e => { if (e.target.value) addLayer('sticker', e.target.value, { scale: 0.25 }); e.target.value = ''; e.target.blur(); });
  $('#eAddText').addEventListener('click', () => edit(() => { line.texts.push({ text: 'Your text', start: round(now), end: round(now + 3), x: 0.5, y: 0.2, size: 90, color: '#ffffff', style: 'outline', anim: 'pop' }); sel = { k: 't', i: line.texts.length - 1 }; }));
  $('#eAddAudio').addEventListener('click', async () => {
    const p = await browse('audio'); if (!p) return;
    edit(() => { line.audio.push({ path: p, start: round(now), end: 600, src_start: 0, volume: 1, fade_in: 0, fade_out: 0 }); sel = { k: 'a', i: line.audio.length - 1 }; });
  });
  $('#eCaptions').addEventListener('click', () => {
    if (!line.segments.length) return SF.toast('Add a video first.');
    SF.startTask('/api/editor', { action: 'captions', timeline: line }, r => {
      edit(() => { line.texts = line.texts.filter(t => !t.caption).concat(r.captions.map(c => ({ ...c, caption: true, x: 0.5, y: 0.75, size: 80, color: '#ffffff', style: 'outline', anim: 'pop' }))); sel = null; });
      SF.toast(`Added ${r.captions.length} caption lines. Click one to fix a word.`);
    }, 'Writing captions');
  });
  $('#eMusic').addEventListener('click', async () => { const p = await browse('audio'); if (p) edit(() => { line.music = { path: p, volume: +$('#eMusicVol').value, start: 0 }; }); });
  $('#eNoMusic').addEventListener('click', () => edit(() => { line.music = null; }));
  $('#eMusicVol').addEventListener('change', e => { if (line.music) edit(() => { line.music.volume = +e.target.value; }); });
  $('#eAspect').addEventListener('change', e => edit(() => { line.aspect = e.target.value; }));
  $('#eFit').addEventListener('change', e => edit(() => { line.fit = e.target.value; }));
  $('#eTrans').addEventListener('change', e => edit(() => { line.transition.type = e.target.value; }));
  $('#eTransSec').addEventListener('change', e => edit(() => { line.transition.seconds = +e.target.value; }));
  $('#eRes').addEventListener('change', e => edit(() => { line.resolution = +e.target.value; }));
  $('#eFps').addEventListener('change', e => edit(() => { line.fps = +e.target.value; }));

  $('#ePlay').addEventListener('click', () => play());
  $('#eFull').addEventListener('click', () => { if (document.fullscreenElement) document.exitFullscreen(); else $('#eStage').requestFullscreen().catch(() => {}); });
  $('#eUndo').addEventListener('click', () => step(undo, redo));
  $('#eRedo').addEventListener('click', () => step(redo, undo));
  $('#eSplit').addEventListener('click', split);
  $('#eDelLeft').addEventListener('click', () => cutSide(true));
  $('#eDelRight').addEventListener('click', () => cutSide(false));
  $('#eCopy').addEventListener('click', duplicate);
  $('#eDelete').addEventListener('click', remove);
  $('#eFreeze').addEventListener('click', freeze);
  $('#eSnap').addEventListener('click', e => { snap = !snap; $('#eSnap').textContent = snap ? 'Snap on' : 'Snap off'; $('#eSnap').setAttribute('aria-pressed', snap); });
  $('#eZoomIn').addEventListener('click', () => zoom(1.4));
  $('#eZoomOut').addEventListener('click', () => zoom(1 / 1.4));
  $('#eZoomFit').addEventListener('click', fit);
  $('#eKeysHelp').addEventListener('click', () => $('#eHelp').showModal());
  $('#eNew').addEventListener('click', () => { if (confirm('Clear the whole timeline?')) edit(() => { line = EMPTY(); sel = null; }); });

  function render(action) {
    if (!line.segments.some(s => !s.disabled)) return SF.toast('Add a video first.');
    play(false); $('#eMsg').textContent = '';
    SF.startTask('/api/editor', { action, timeline: line, title: $('#eTitle').value }, r => {
      showingResult = true; now = 0; video.dataset.path = ''; video.playbackRate = 1; video.volume = 1;
      video.style.cssText = '';
      video.src = '/files/' + r.file.split('/').map(encodeURIComponent).join('/') + '?t=' + encodeURIComponent(SF.token) + '&v=' + Date.now();
      drawLayers();
      $('#eMsg').textContent = action === 'preview' ? 'This is the real preview (small and fast). Press Export for full quality.' : 'Saved in the Clips tab, project "Edits".';
    }, action === 'preview' ? 'Making a preview' : 'Exporting your video');
  }
  $('#ePreview').addEventListener('click', () => render('preview'));
  $('#eExport').addEventListener('click', () => render('export'));

  // Older drafts do not have the new lists: fill in what is missing.
  function upgrade(draft) {
    const out = { ...EMPTY(), ...draft };
    out.segments = (out.segments || []).map(s => ({ ...SEG, keyframes: [], ...s }));
    for (const k of ['overlays', 'texts', 'audio']) out[k] = out[k] || [];
    return out;
  }
  async function open() {
    if (!choices) {
      const got = await SF.api('/api/editor');
      const fill = (id, list) => { $(id).innerHTML = list.map(v => `<option>${esc(v)}</option>`).join(''); };
      fill('#eTrans', got.transitions); fill('#eAspect', got.aspects);
      $('#eSticker').innerHTML = '<option value="">Add sticker...</option>' + got.stickers.map(v => `<option>${esc(v)}</option>`).join('');
      choices = got;
      if (got.draft && got.draft.segments && !line.segments.length) { line = upgrade(got.draft); fit(); }
    }
    draw(); seek(now);
    try {
      const { videos } = await SF.api('/api/videos');
      $('#eKnown').innerHTML = '<option value="">Add a video found on this PC...</option>' + videos.map(v => `<option value="${esc(v.path)}">${esc(v.name)}</option>`).join('');
    } catch (e) { /* not important */ }
  }
  addEventListener('sf:view', e => { if (e.detail === 'editor') open().catch(err => SF.toast(err.message)); else play(false); });
  SF.editorAdd = async path => { SF.setView('editor'); await open(); await add(path); };
})();
