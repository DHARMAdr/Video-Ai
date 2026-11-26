/* voice.js - talk instead of typing (the microphone button in the chat).
   WHY: you asked to give commands by voice. The recording is turned into text on your PC
        (Whisper), so nothing is sent to the internet.
   HOW: record the microphone, stop after a short silence (or a second press), send the sound to
        /api/voice, put the words in the box and (optionally) send them.
   HOW TO IMPROVE: a push-to-talk keyboard shortcut; a wake word like "Hey Forge". */
(() => {
  const SF = window.SF, $ = s => document.querySelector(s);
  const mic = $('#mic'), input = $('#chatInput'), state = $('#micState');
  let recorder = null, stream = null, audio = null, timer = 0;
  mic.hidden = false;

  const say = text => { state.textContent = text; state.hidden = !text; };
  const store = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } };
  for (const [id, key] of [['#vSend', 'sf-vsend'], ['#vSpeak', 'sf-vspeak']]) {
    const box = $(id), saved = store(key);
    if (saved !== null && saved !== undefined) box.checked = saved === '1';
    box.addEventListener('change', () => { store(key, box.checked ? '1' : '0'); if (!box.checked && window.speechSynthesis) speechSynthesis.cancel(); });
  }

  function stop() { if (recorder && recorder.state !== 'inactive') recorder.stop(); }

  async function start() {
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      say('This browser does not allow the microphone here (phones need a secure address). Use the microphone key on your phone keyboard instead.');
      return;
    }
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
    catch (e) {
      say(e.name === 'NotFoundError' ? 'No microphone was found.' : 'Microphone blocked. Press Allow when asked, and check Windows Settings > Privacy > Microphone.');
      return;
    }
    if (window.speechSynthesis) speechSynthesis.cancel();
    const chunks = [];
    recorder = new MediaRecorder(stream);
    recorder.ondataavailable = e => chunks.push(e.data);
    recorder.onstop = async () => {
      clearInterval(timer); stream.getTracks().forEach(t => t.stop()); if (audio) audio.close();
      mic.textContent = '🎤'; mic.setAttribute('aria-pressed', 'false'); recorder = null;
      say('Writing down what you said...');
      try {
        const res = await fetch('/api/voice', { method: 'POST', headers: { 'X-Token': SF.token }, body: new Blob(chunks) });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || res.statusText);
        if (!data.text) return say('I did not catch any words. Try again, a bit closer to the microphone.');
        say('');
        input.value = (input.value ? input.value + ' ' : '') + data.text;
        input.dispatchEvent(new Event('input'));
        if ($('#vSend').checked) { const text = input.value; SF.send(text); } else input.focus();
      } catch (e) { say(e.message); }
    };
    recorder.start();
    mic.textContent = '■'; mic.setAttribute('aria-pressed', 'true');
    say('Listening... press ■ when you are done.');
    // stop by itself: 2 seconds of quiet after you have spoken, or 60 seconds in total
    audio = new AudioContext();
    const meter = audio.createAnalyser(); meter.fftSize = 1024;
    audio.createMediaStreamSource(stream).connect(meter);
    const samples = new Float32Array(meter.fftSize);
    let spoke = false, quiet = 0, total = 0;
    timer = setInterval(() => {
      meter.getFloatTimeDomainData(samples);
      const level = Math.sqrt(samples.reduce((s, x) => s + x * x, 0) / samples.length);
      if (level > 0.025) { spoke = true; quiet = 0; } else quiet += 0.2;
      total += 0.2;
      if ((spoke && quiet > 2) || total > 60) stop();
    }, 200);
  }
  mic.addEventListener('click', () => (recorder ? stop() : start()));

  // read answers aloud (uses the voices that come with Windows)
  addEventListener('sf:reply', e => {
    if (!$('#vSpeak').checked || !window.speechSynthesis) return;
    speechSynthesis.cancel();
    speechSynthesis.speak(new SpeechSynthesisUtterance(String(e.detail).replace(/[*_`#]/g, '').slice(0, 500)));
  });
})();
