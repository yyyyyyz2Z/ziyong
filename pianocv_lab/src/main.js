import './styles.css';
import {detectFrame} from './detector.js';

const get = id => document.getElementById(id);
const video = get('video');
const stage = get('stage');
const overlay = get('overlay');
const ctx = overlay.getContext('2d');
const picker = get('video-file');
const seek = get('seek');
const play = get('play');
const analyze = get('analyze');
const save = get('export');
const firstPitch = get('first-pitch');
const outlines = get('outlines');
const labels = get('labels');
const names = ['C', 'C♯', 'D', 'E♭', 'E', 'F', 'F♯', 'G', 'A♭', 'A', 'B♭', 'B'];
const colors = {white: '#77e6e3', black: '#c9b9ff'};
const state = {url: null, name: '', busy: false, ready: false, result: null, hovered: -1};

function timecode(seconds) {
  const ms = Math.max(0, Math.round((Number.isFinite(seconds) ? seconds : 0) * 1000));
  const pad = (value, width = 2) => String(value).padStart(width, '0');
  return `${pad(Math.floor(ms / 60000))}:${pad(Math.floor(ms / 1000) % 60)}.${pad(ms % 1000, 3)}`;
}

function status(message, kind = '') {
  const node = get('status');
  node.textContent = message;
  node.className = `status ${kind}`;
}

function numbering() {
  const result = state.result;
  if (!result) return {base: null, source: 'relative'};
  if (firstPitch.value !== '' || firstPitch.validity.badInput) {
    const base = firstPitch.valueAsNumber;
    if (!Number.isInteger(base) || base < 0 || base + result.keys.at(-1).semitone > 127) {
      return {base: null, source: 'relative', error: '最低键及全段 MIDI 编号必须在 0–127 之间。'};
    }
    return {base, source: 'manual'};
  }
  if (result.keys.length === 88 && result.fit.phase === 'A' && result.keys.at(-1).semitone === 87) {
    return {base: 21, source: 'assumed-standard-88'};
  }
  return {base: null, source: 'relative'};
}

function noteName(pitch) {
  return `${names[pitch % 12]}${Math.floor(pitch / 12) - 1}`;
}

function keyLabel(key, index, base) {
  return base === null ? `#${index + 1}` : noteName(base + key.semitone);
}

function actionState() {
  picker.disabled = state.busy;
  seek.disabled = play.disabled = state.busy || !state.ready;
  analyze.disabled = state.busy || !state.ready || video.seeking || video.readyState < 2;
  save.disabled = state.busy || !state.result || Boolean(numbering().error);
}

function canDraw() {
  return state.result && video.paused && !video.seeking && Math.abs(video.currentTime - state.result.time) < .018;
}

function polygon(points, width, height) {
  ctx.beginPath();
  for (const [index, {x, y}] of points.entries()) {
    if (index) ctx.lineTo(x * width, y * height);
    else ctx.moveTo(x * width, y * height);
  }
  ctx.closePath();
}

function drawOverlay() {
  overlay.hidden = !canDraw();
  stage.classList.toggle('overlay-key', !overlay.hidden);
  if (overlay.hidden) return;
  const {width, height, keys} = state.result;
  const {base} = numbering();
  ctx.clearRect(0, 0, width, height);
  const mediaScale = Math.min(stage.clientWidth / width, stage.clientHeight / height);
  ctx.lineJoin = 'round';
  ctx.lineWidth = 1.18 / Math.max(.1, mediaScale);

  function drawKey(key) {
    polygon(key.bar, width, height);
    ctx.strokeStyle = key.black ? colors.black : colors.white;
    ctx.fillStyle = key.black ? '#b19af533' : '#53daca19';
    ctx.fill();
    ctx.stroke();
  }

  if (outlines.checked) {
    for (const key of keys) if (!key.black) drawKey(key);
    ctx.save();
    ctx.globalCompositeOperation = 'destination-out';
    ctx.fillStyle = '#000';
    for (const key of keys) if (key.black) { polygon(key.bar, width, height); ctx.fill(); }
    ctx.restore();
    for (const key of keys) if (key.black) drawKey(key);
  }

  const focused = keys[state.hovered];
  if (focused) {
    polygon(focused.bar, width, height);
    ctx.fillStyle = '#fae39369';
    ctx.strokeStyle = '#ffed9c';
    ctx.fill();
    ctx.stroke();
  }
  if (labels.checked || focused) {
    ctx.font = `600 ${Math.round(10 / Math.max(.1, mediaScale))}px Consolas, monospace`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    for (const [index, key] of keys.entries()) {
      if (!labels.checked && index !== state.hovered) continue;
      const [a, b, c, d] = key.top;
      const weight = key.black ? .45 : .85;
      const x = ((a.x + b.x) * (1 - weight) + (c.x + d.x) * weight) * width / 2;
      const y = ((a.y + b.y) * (1 - weight) + (c.y + d.y) * weight) * height / 2;
      const text = keyLabel(key, index, base);
      ctx.strokeStyle = '#141225'; ctx.lineWidth = 2.5 / Math.max(.1, mediaScale);
      ctx.fillStyle = index === state.hovered ? '#ffed9c' : '#fff';
      ctx.strokeText(text, x, y);
      ctx.fillText(text, x, y);
    }
  }
}

function showResult() {
  const result = state.result;
  const selected = numbering();
  const pitchHint = get('pitch-hint');
  pitchHint.classList.toggle('error', Boolean(selected.error));
  pitchHint.textContent = selected.error || (selected.source === 'assumed-standard-88'
    ? '识别为标准 88 键，按 A0–C8 编号。'
    : selected.source === 'manual' ? `从 ${noteName(selected.base)} 开始编号。`
    : '局部键盘可手动指定识别范围的最低音。');
  const black = result ? result.keys.filter(key => key.black).length : 0;
  get('key-total').textContent = result?.keys.length ?? '—';
  get('key-white').textContent = result ? result.keys.length - black : '—';
  get('key-black').textContent = result ? black : '—';
  get('result-frame').textContent = result ? timecode(result.time) : '';
  const key = result?.keys[state.hovered];
  get('key-detail').textContent = key ? `${keyLabel(key, state.hovered, selected.base)} · ${key.black ? '黑键' : '白键'}${selected.base === null ? '' : ` · MIDI ${selected.base + key.semitone}`}`
    : result && !canDraw() ? '轮廓对应上方时间点。'
    : '识别后可悬停查看单键。';
  actionState();
  drawOverlay();
}

function updateTime() {
  if (!video.seeking) seek.value = video.currentTime;
  get('timestamp').textContent = `${timecode(video.currentTime)} / ${timecode(video.duration)}`;
  play.textContent = video.paused ? '播放' : '暂停';
  play.setAttribute('aria-label', video.paused ? '播放视频' : '暂停视频');
  showResult();
}

function openVideo(file) {
  if (!file || state.busy) return;
  if (file.type && !file.type.startsWith('video/') && !/\.(mp4|m4v|webm|mov|mkv|avi)$/i.test(file.name)) {
    status('请选择一个视频文件。', 'error');
    return;
  }
  video.pause();
  if (state.url) URL.revokeObjectURL(state.url);
  Object.assign(state, {url: URL.createObjectURL(file), name: file.name, result: null, ready: false, hovered: -1});
  firstPitch.value = '';
  get('file-name').textContent = file.name;
  get('resolution').textContent = '';
  get('empty-stage').hidden = false;
  get('transport').hidden = video.hidden = true;
  status('正在读取视频…');
  video.src = state.url;
  showResult();
}

async function inspect() {
  if (analyze.disabled) return;
  video.pause();
  const time = video.currentTime;
  const size = {width: video.videoWidth, height: video.videoHeight};
  const frame = document.createElement('canvas');
  // Keep the same aspect ratio as the source when handing the image to pianoCV.
  frame.width = Math.min(size.width, 1920);
  frame.height = Math.max(1, Math.round(size.height * frame.width / size.width));
  frame.getContext('2d').drawImage(video, 0, 0, frame.width, frame.height);

  state.busy = true;
  state.result = null;
  state.hovered = -1;
  status('正在加载 pianoCV KeyNet…');
  showResult();
  try {
    const observed = await detectFrame(frame, size, (attempt, backend) => {
      get('engine').textContent = backend === 'webgpu' ? 'WebGPU' : 'WASM';
      status(attempt < 4 ? '正在定位键床…' : '正在拟合琴键轮廓…');
    });
    if (!observed.keys.length) {
      status('这一帧未拟合出键盘。请换到两端更完整、键缝和黑键更清晰的位置。');
      return;
    }
    overlay.width = size.width;
    overlay.height = size.height;
    state.result = {...observed, ...size, time};
    status(`已识别 ${observed.keys.length} 个琴键${observed.fit.lift ? '，使用黑键顶面拟合' : '，黑键按键床平面投影'}。`, 'success');
  } catch (error) {
    console.error('pianoCV inference failed', error);
    status('pianoCV 加载或推理失败。请刷新本地页面后重试，错误详情可在浏览器控制台查看。', 'error');
  } finally {
    state.busy = false;
    showResult();
  }
}

function contains(points, x, y) {
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const a = points[i];
    const b = points[j];
    if ((a.y > y) !== (b.y > y) && x < (b.x - a.x) * (y - a.y) / (b.y - a.y) + a.x) inside = !inside;
  }
  return inside;
}

function hoverKey(event) {
  if (!canDraw()) return;
  const bounds = stage.getBoundingClientRect();
  const {width, height, keys} = state.result;
  const scale = Math.min(bounds.width / width, bounds.height / height);
  const x = (event.clientX - bounds.left - (bounds.width - width * scale) / 2) / (width * scale);
  const y = (event.clientY - bounds.top - (bounds.height - height * scale) / 2) / (height * scale);
  const black = keys.findIndex(key => key.black && contains(key.bar, x, y));
  const index = black >= 0 ? black : keys.findIndex(key => !key.black && contains(key.bar, x, y));
  if (index !== state.hovered) { state.hovered = index; showResult(); }
}

function exportResult() {
  if (!state.result || save.disabled) return;
  const {width, height, time, keys, fit, backend} = state.result;
  const {base, source} = numbering();
  const round = value => Math.round(value * 1000) / 1000;
  const pixel = point => ({x: round(point.x * width), y: round(point.y * height)});
  const data = {version: 1, engine: 'pianoCV KeyNet', backend, video: state.name,
    time_seconds: round(time), frame_size: {width, height}, coordinates: 'video_pixels_xy_top_left',
    numbering: source, first_midi: base, black_key_height_fitted: Boolean(fit.lift),
    keys: keys.map((key, index) => ({index: index + 1, color: key.black ? 'black' : 'white',
      relative_semitone: key.semitone, midi: base === null ? null : base + key.semitone,
      note: base === null ? null : noteName(base + key.semitone),
      outline: key.bar.map(pixel), top: key.top.map(pixel)}))};
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'}));
  const link = document.createElement('a');
  link.href = url;
  link.download = `${state.name.replace(/\.[^.]+$/, '')}-${Math.round(time * 1000)}ms-keys.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}

picker.addEventListener('change', () => { openVideo(picker.files[0]); picker.value = ''; });
stage.addEventListener('dragover', event => { event.preventDefault(); if (!state.busy) stage.classList.add('dragging'); });
stage.addEventListener('dragleave', () => stage.classList.remove('dragging'));
stage.addEventListener('drop', event => {
  event.preventDefault(); stage.classList.remove('dragging'); openVideo(event.dataTransfer.files[0]);
});
stage.addEventListener('pointermove', hoverKey);
stage.addEventListener('pointerleave', () => { state.hovered = -1; showResult(); });
for (const event of ['timeupdate', 'play', 'pause', 'seeking', 'seeked', 'ended']) video.addEventListener(event, updateTime);
video.addEventListener('loadeddata', () => {
  if (!video.videoWidth || !Number.isFinite(video.duration)) {
    status('无法读取视频时长和画面。请尝试普通的 MP4 或 WebM 视频。', 'error');
    return;
  }
  state.ready = true;
  seek.max = video.duration;
  get('resolution').textContent = `${video.videoWidth} × ${video.videoHeight}`;
  get('transport').hidden = video.hidden = false;
  get('empty-stage').hidden = true;
  status('拖到键盘清晰的时间点，点击「识别当前帧」。');
  updateTime();
});
video.addEventListener('error', () => { state.ready = false; status('浏览器无法播放这个文件。请尝试 H.264 MP4 或 WebM。', 'error'); actionState(); });
seek.addEventListener('input', () => { video.pause(); video.currentTime = +seek.value; state.hovered = -1; updateTime(); });
play.addEventListener('click', () => {
  if (video.paused) video.play().catch(() => status('播放失败，请重新选择文件。', 'error'));
  else video.pause();
});
firstPitch.addEventListener('input', showResult);
outlines.addEventListener('change', drawOverlay);
labels.addEventListener('change', drawOverlay);
analyze.addEventListener('click', inspect);
save.addEventListener('click', exportResult);
new ResizeObserver(drawOverlay).observe(stage);
actionState();
