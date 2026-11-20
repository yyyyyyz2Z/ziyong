import {get, post, filePayload, download, chart, chartLine, chartText, svgElement, ticks, pitchName, status} from '/common.js';

const fileInput = get('score-file');
const first = get('first');
const last = get('last');
const state = {file: null, name: '', recognition: null, score: null, excerpt: null, busy: false, choosingEnd: false};
const trackColors = ['#624bd1', '#147b98', '#b95177', '#2b8061', '#906028', '#657692'];

function actions() {
  const locked = state.busy || !state.score;
  for (const control of [first, last, get('generate')]) control.disabled = locked;
  for (const control of [fileInput, get('demo-score')]) control.disabled = state.busy;
  for (const control of get('measures').children) control.disabled = locked;
  get('download-midi').disabled = state.busy || !state.excerpt;
  get('download-recognition').disabled = state.busy;
  get('download-recognition').hidden = !state.recognition;
}

function showRange() {
  if (!state.score) return;
  const start = first.valueAsNumber;
  const stop = last.valueAsNumber;
  const a = state.score.measures[start - 1];
  const b = state.score.measures[stop - 1];
  for (const button of get('measures').children) {
    const position = +button.dataset.position;
    button.setAttribute('aria-pressed', String(position >= start && position <= stop));
    button.classList.toggle('edge', start <= stop && (position === start || position === stop));
  }
  get('range-note').textContent = state.choosingEnd ? '已选起点，请点选结束小节。'
    : a && b && start <= stop ? `所选谱面编号 ${a.label} 至 ${b.label} · 共 ${stop - start + 1} 小节`
    : '选择有效的起止位置。';
}

function pick(position) {
  if (state.choosingEnd) {
    last.value = Math.max(position, first.valueAsNumber);
    first.value = Math.min(position, first.valueAsNumber);
  } else {
    first.value = position;
    last.value = position;
  }
  state.choosingEnd = !state.choosingEnd;
  clearExcerpt();
  showRange();
}

function clearExcerpt() {
  state.excerpt = null;
  for (const id of ['score-metrics', 'score-chart']) get(id).hidden = true;
  get('score-empty').hidden = false;
  get('tempo-summary').textContent = '';
  get('excerpt-caption').textContent = '每条横线代表一个音符。';
  actions();
}

async function readScore(source, demo = false) {
  if (state.busy) return false;
  state.busy = true;
  actions();
  status(get('score-status'), '正在读取乐谱…');
  try {
    const file = await source();
    const isPdf = file.name.toLowerCase().endsWith('.pdf');
    let payload = await filePayload(file, isPdf ? 10 : 5);
    state.recognition = null;
    if (isPdf) {
      status(get('score-status'), 'Audiveris 正在识别 PDF 五线谱…');
      const result = await post('/api/recognize', {file: payload});
      payload = result.file;
      state.recognition = {...payload, name: file.name.replace(/\.pdf$/i, `-识谱${payload.name.slice(payload.name.lastIndexOf('.'))}`)};
      status(get('score-status'), '识谱完成，正在读取小节…');
    }
    const score = await post('/api/score', {file: payload});
    state.file = payload;
    state.name = file.name;
    state.score = score;
    state.choosingEnd = false;
    first.max = last.max = score.measures.length;
    first.value = demo ? 2 : 1;
    last.value = Math.min(demo ? 5 : 4, score.measures.length);
    get('score-source').textContent = `${file.name} · ${score.measures.length} 小节${isPdf ? ' · Audiveris 识谱' : demo ? ' · 合成示例' : ''}`;
    get('part-count').hidden = false;
    get('part-count').textContent = `${score.parts} 个谱表声部`;
    get('measures').replaceChildren(...score.measures.map(measure => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'measure';
      button.textContent = measure.label;
      button.dataset.position = measure.position;
      button.setAttribute('aria-label', `第 ${measure.position} 个小节，谱面编号 ${measure.label}`);
      button.addEventListener('click', () => pick(measure.position));
      return button;
    }));
    clearExcerpt();
    showRange();
    status(get('score-status'), isPdf ? '请对照原 PDF 检查小节、音高和时值后导出。' : '');
    return true;
  } catch (error) {
    status(get('score-status'), error.message, true);
    return false;
  } finally {
    state.busy = false;
    actions();
  }
}

async function loadExample(preview = false) {
  const loaded = await readScore(async () => {
    const response = await fetch('/api/demo-score');
    if (!response.ok) throw new Error('无法载入本地示例');
    return new File([await response.blob()], '示例旋律.musicxml');
  }, true);
  if (preview && loaded) await generate();
}

function drawExcerpt() {
  const excerpt = state.excerpt;
  if (!excerpt) return;
  const plot = chart(get('score-chart'), 247, {left: 38, bottom: 36});
  if (!plot) return;
  const {svg, left, right, top, bottom, width, height} = plot;
  const low = Math.min(...excerpt.notes.map(note => note.pitch)) - 1;
  const high = Math.max(...excerpt.notes.map(note => note.pitch)) + 1;
  const x = time => left + time / excerpt.duration * (right - left);
  const y = pitch => bottom - (pitch - low) / (high - low) * (bottom - top);
  const bar = Math.min(9, Math.max(3, (bottom - top) / (high - low) * .68));
  const pitchStep = high - low > 30 ? 12 : Math.max(1, Math.ceil((high - low) / 6));
  for (let pitch = Math.ceil(low / pitchStep) * pitchStep; pitch <= high; pitch += pitchStep) {
    chartLine(svg, left, y(pitch), right, y(pitch));
    chartText(svg, left - 8, y(pitch) + 4, pitchName(pitch), 'end');
  }
  for (const time of ticks(excerpt.duration, width < 450 ? 4 : 7)) {
    chartLine(svg, x(time), top, x(time), bottom);
    chartText(svg, x(time), bottom + 16, time, 'middle');
  }
  chartText(svg, left, 13, '音高', 'start', 'axis-label');
  chartText(svg, right, height - 2, '片段时间（秒）', 'end', 'axis-label');
  for (const note of excerpt.notes) {
    const rect = svgElement('rect', {x: x(note.onset), y: y(note.pitch) - bar / 2,
      width: Math.max(1, x(Math.min(excerpt.duration, note.onset + note.duration)) - x(note.onset)),
      height: bar, fill: trackColors[note.track % trackColors.length], rx: 2});
    rect.append(svgElement('title', {}, `${pitchName(note.pitch)} · ${note.onset.toFixed(2)} 秒 · 音轨 ${note.track + 1}`));
    svg.append(rect);
  }
}

async function generate() {
  if (!state.file || state.busy) return;
  const start = first.valueAsNumber;
  const stop = last.valueAsNumber;
  if (!Number.isInteger(start) || !Number.isInteger(stop) || start < 1 || start > stop || stop > state.score.measures.length) {
    status(get('score-status'), '请选择有效的起止小节。', true);
    return;
  }
  state.busy = true;
  actions();
  status(get('score-status'), '正在生成参考 MIDI…');
  try {
    const excerpt = await post('/api/export', {file: state.file, first: start, last: stop});
    state.excerpt = {...excerpt, start, stop};
    get('score-empty').hidden = true;
    get('score-chart').hidden = false;
    const metrics = get('score-metrics');
    metrics.hidden = false;
    metrics.replaceChildren(...[[excerpt.notes.length, '音符'], [excerpt.tracks, '音轨'], [`${excerpt.duration.toFixed(2)} 秒`, '片段时长']].map(([value, label]) => {
      const item = document.createElement('div');
      const number = document.createElement('strong');
      const name = document.createElement('span');
      number.textContent = value;
      name.textContent = label;
      item.append(number, name);
      return item;
    }));
    get('excerpt-caption').textContent = '颜色区分 MIDI 音轨，时间从选段起点开始。';
    const tempos = excerpt.tempos.slice(0, 6).map(tempo => `${tempo.time.toFixed(2)} 秒 · ${tempo.bpm} BPM`);
    get('tempo-summary').textContent = `速度 ${tempos.join(' / ')}${excerpt.tempos.length > 6 ? ' …' : ''}`;
    drawExcerpt();
    status(get('score-status'), '参考 MIDI 已生成。');
  } catch (error) {
    status(get('score-status'), error.message, true);
  } finally {
    state.busy = false;
    actions();
  }
}

fileInput.addEventListener('change', () => {
  const file = fileInput.files[0];
  if (file) readScore(() => file);
});
get('demo-score').addEventListener('click', () => loadExample());
get('excerpt-form').addEventListener('submit', event => { event.preventDefault(); generate(); });
for (const field of [first, last]) {
  field.addEventListener('input', () => { state.choosingEnd = false; clearExcerpt(); showRange(); });
}
get('download-midi').addEventListener('click', () => {
  const {midi, start, stop} = state.excerpt;
  const data = Uint8Array.from(atob(midi), letter => letter.charCodeAt(0));
  const basename = state.name.replace(/\.[^.]+$/, '');
  download(new Blob([data], {type: 'audio/midi'}), `${basename}-${start}-${stop}.mid`);
});
get('download-recognition').addEventListener('click', () => {
  const data = Uint8Array.from(atob(state.recognition.data), letter => letter.charCodeAt(0));
  download(new Blob([data]), state.recognition.name);
});
fetch('/api/score-capabilities').then(response => response.json()).then(capabilities => {
  get('pdf-capability').textContent = capabilities.pdf_recognition
    ? 'PDF 识谱已启用，支持 10 MB 以内的印刷五线谱。'
    : 'PDF 识谱需要 Audiveris。安装后重启，或启动时用 --audiveris 指定路径。';
}).catch(() => {});
new ResizeObserver(drawExcerpt).observe(get('score-chart'));
loadExample(true);
