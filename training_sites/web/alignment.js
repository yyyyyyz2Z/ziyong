import {get, post, readJson, filePayload, downloadJson, status, chart, chartLine, chartText, svgElement, ticks, pitchName} from '/common.js';

const state = {mode: 'train', dataset: null, source: '', synthetic: false, demo: null, report: null,
  pair: null, model: null, modelName: '', busy: false};
const percent = value => `${(value * 100).toFixed(1)}%`;
const message = get('align-status');
const sample = get('sample');
const inputs = [get('dataset-file'), get('reference-file'), get('performance-file'), get('model-file')];
const modes = {fixed: '固定偏移', default: '默认自适应', adaptive: '训练后自适应'};

function controls() {
  get('train').disabled = state.busy || !state.dataset;
  get('align').disabled = state.busy || !get('reference-file').files.length || !get('performance-file').files.length;
  for (const control of [...inputs, get('demo-dataset'), get('mode-train'), get('mode-pair')]) control.disabled = state.busy;
  get('download-dataset').disabled = state.busy;
}

async function perform(action, label) {
  if (state.busy) return;
  state.busy = true;
  controls();
  status(message, label);
  try { await action(); }
  catch (error) { status(message, error.message, true); }
  finally { state.busy = false; controls(); }
}

async function demoDataset() {
  if (!state.demo) {
    const response = await fetch('/api/demo-dataset');
    if (!response.ok) throw new Error('无法载入示例训练集');
    state.demo = await response.json();
  }
  return state.demo;
}

function setDataset(dataset, name, synthetic) {
  if (dataset?.version !== 1 || !Array.isArray(dataset.examples)) throw new Error('请选择 version 为 1 的训练集 JSON');
  state.dataset = dataset;
  state.source = name;
  state.synthetic = synthetic || dataset.synthetic === true;
  state.report = null;
  const count = dataset.examples.length;
  const pieces = new Set(dataset.examples.map(example => example?.piece_id).filter(Boolean)).size;
  get('dataset-summary').textContent = `${name} · ${count} 个片段 · ${pieces} 首曲目${state.synthetic && !synthetic ? ' · 合成示例' : ''}`;
  renderReport();
  status(message, '');
}

function setModel(model, name) {
  state.model = model;
  state.modelName = name;
  state.pair = null;
  get('model-summary').textContent = model ? `当前参数来源 · ${name}` : '使用默认参数。';
}

function mode(next) {
  state.mode = next;
  const training = next === 'train';
  get('mode-train').setAttribute('aria-pressed', String(training));
  get('mode-pair').setAttribute('aria-pressed', String(!training));
  get('train-panel').hidden = !training;
  get('pair-panel').hidden = training;
  get('validation-panel').hidden = !training;
  status(message, '');
  renderCase();
  controls();
}

function renderReport() {
  const report = state.report;
  const panel = get('validation-bars');
  panel.replaceChildren();
  get('train-results').hidden = !report;
  get('validation-empty').hidden = Boolean(report);
  get('result-source').hidden = !report;
  get('split-summary').textContent = report
    ? `逐音匹配 F1 · 训练 ${report.training_pieces.length} 首 / ${report.training_count} 段 · 验证 ${report.validation_pieces.length} 首 / ${report.validation_count} 段`
    : '同一曲目的不同演奏会留在同一组。';
  sample.replaceChildren();
  if (report) {
    get('result-source').textContent = state.synthetic ? '合成示例' : '导入数据';
    for (const [key, name] of Object.entries(modes)) {
      const scores = report.validation[key];
      const row = document.createElement('div');
      row.className = `metric-line ${key}`;
      const title = document.createElement('span');
      title.textContent = name;
      const bar = document.createElement('progress');
      bar.max = 1;
      bar.value = scores.f1;
      bar.setAttribute('aria-label', `${name} F1`);
      const value = document.createElement('span');
      value.className = 'metric-value';
      value.textContent = percent(scores.f1);
      const detail = document.createElement('span');
      detail.className = 'metric-detail';
      detail.textContent = `精确率 ${percent(scores.precision)} · 召回率 ${percent(scores.recall)}`;
      row.append(title, bar, value, detail);
      panel.append(row);
    }
    const {chord_window_ms, anchor_similarity, tolerance_ms} = report.model.parameters;
    get('parameter-summary').textContent = `已选和弦窗口 ${chord_window_ms} ms · 锚点相似度 ${anchor_similarity} · 时间容差 ${tolerance_ms} ms。以训练集 F1 筛选。`;
    const rows = [...report.trials].sort((a, b) => b.f1 - a.f1).map(trial => {
      const row = document.createElement('tr');
      for (const value of [trial.parameters.chord_window_ms, trial.parameters.anchor_similarity, trial.parameters.tolerance_ms, percent(trial.f1)]) {
        const cell = document.createElement('td'); cell.textContent = value; row.append(cell);
      }
      return row;
    });
    get('trial-rows').replaceChildren(...rows);
    for (const [index, item] of report.examples.entries()) sample.add(new Option(`${item.id} · ${item.piece_id}`, index));
  }
  renderCase();
}

function currentCase() {
  return state.mode === 'train' ? state.report?.examples[Number(sample.value)] : state.pair;
}

function bounds(values) {
  const low = Math.min(0, ...values);
  return [low, Math.max(low + .25, ...values)];
}

function gridX(plot, x, lower, upper, title) {
  const {svg, top, bottom, right, height, width} = plot;
  for (const tick of ticks(upper - lower, width < 450 ? 4 : 7)) {
    const time = lower + tick;
    chartLine(svg, x(time), top, x(time), bottom);
    chartText(svg, x(time), bottom + 16, +time.toFixed(2), 'middle');
  }
  chartText(svg, right, height - 2, title, 'end', 'axis-label');
}

function drawMapping(item) {
  const plot = chart(get('mapping'), 254, {left: 39, bottom: 38});
  if (!plot) return;
  const {svg, left, right, top, bottom} = plot;
  const matches = item.truth || [];
  const ref = new Map(item.reference.map(note => [note.id, note]));
  const perf = new Map(item.performance.map(note => [note.id, note]));
  const last = Math.max(.25, ...item.reference.map(note => note.onset));
  const [low, high] = bounds([...item.performance.map(note => note.onset),
    ...Object.values(item.fixed.projected), ...Object.values(item.adaptive.projected)]);
  const x = time => left + time / last * (right - left);
  const y = time => bottom - (time - low) / (high - low) * (bottom - top);
  gridX(plot, x, 0, last, '谱面时间（秒）');
  for (const tick of ticks(high - low, 4)) {
    const time = low + tick;
    chartLine(svg, left, y(time), right, y(time));
    chartText(svg, left - 7, y(time) + 4, +time.toFixed(1), 'end');
  }
  chartText(svg, left, 13, '演奏时间（秒）', 'start', 'axis-label');
  for (const key of ['fixed', 'adaptive']) {
    const points = item.reference.map(note => `${x(note.onset)},${y(item[key].projected[note.id])}`);
    svg.append(svgElement('polyline', {points: points.join(' '), class: `${key}-line`}));
  }
  for (const [referenceId, performanceId] of matches) {
    const a = ref.get(referenceId);
    const b = perf.get(performanceId);
    const dot = svgElement('circle', {cx: x(a.onset), cy: y(b.onset), r: 2.4, class: 'truth'});
    dot.append(svgElement('title', {}, `${pitchName(a.pitch)} · 谱面 ${a.onset.toFixed(2)} 秒 · 演奏 ${b.onset.toFixed(2)} 秒`));
    svg.append(dot);
  }
  for (const [source, target] of item.adaptive.anchors) {
    const dot = svgElement('circle', {cx: x(source), cy: y(target), r: 3.2, class: 'anchor'});
    dot.append(svgElement('title', {}, `锚点 · 谱面 ${source.toFixed(2)} 秒 · 演奏 ${target.toFixed(2)} 秒`));
    svg.append(dot);
  }
}

function drawRoll(item) {
  const plot = chart(get('matched-roll'), 233, {left: 39, top: 27, bottom: 37});
  if (!plot) return;
  const {svg, left, right, top, bottom} = plot;
  const predicted = item.adaptive.projected;
  const [low, high] = bounds([...item.performance.map(note => note.onset + note.duration),
    ...item.reference.flatMap(note => [predicted[note.id], predicted[note.id] + note.duration])]);
  const x = time => left + (time - low) / (high - low) * (right - left);
  const pitches = [...item.reference, ...item.performance].map(note => note.pitch);
  const min = Math.min(...pitches) - 1;
  const max = Math.max(...pitches) + 1;
  const half = (bottom - top - 21) / 2;
  const matched = [new Set(item.adaptive.pairs.map(pair => pair[0])), new Set(item.adaptive.pairs.map(pair => pair[1]))];
  gridX(plot, x, low, high, '演奏时间（秒）');
  for (const [index, notes] of [item.reference, item.performance].entries()) {
    const rail = top + index * (half + 21);
    chartText(svg, left, rail - 7, index === 0 ? '参考' : '演奏', 'start', 'axis-label');
    chartLine(svg, left, rail + half, right, rail + half);
    for (const note of notes) {
      const start = index === 0 ? predicted[note.id] : note.onset;
      const hit = matched[index].has(note.id);
      const mark = svgElement('rect', {x: x(start), y: rail + half - (note.pitch - min) * half / (max - min) - 2.2,
        width: Math.max(1, x(start + note.duration) - x(start)), height: 4.4, rx: 1.8,
        class: hit ? 'note-matched' : 'note-unmatched'});
      mark.append(svgElement('title', {}, `${note.id} · ${pitchName(note.pitch)} · 原起音 ${note.onset.toFixed(2)} 秒 · ${hit ? '算法已匹配' : '未匹配'}`));
      svg.append(mark);
    }
  }
}

function draw() {
  const item = currentCase();
  if (item) { drawMapping(item); drawRoll(item); }
}

function renderCase() {
  const item = currentCase();
  const training = state.mode === 'train';
  get('sample-label').hidden = !state.report || !training;
  get('example-plots').hidden = !item;
  get('example-empty').hidden = Boolean(item);
  get('truth-key').hidden = !item?.truth;
  get('pair-results').hidden = training || !item;
  get('example-caption').textContent = training ? '选择验证曲目查看时间映射与逐音匹配。'
    : state.model ? `参数来源 · ${state.modelName}` : '使用默认参数比较两个录音时间轴。';
  if (!item) return;
  const count = item.adaptive.pairs.length;
  const fallback = item.adaptive.anchors.length < 2 ? ' · 锚点不足，已用固定偏移' : '';
  get('match-summary').textContent = `匹配 ${count} 对 · 参考侧未匹配 ${item.reference.length - count} · 演奏侧未匹配 ${item.performance.length - count}${fallback}`
    + (item.metrics ? ` · 片段 F1 ${percent(item.metrics.adaptive.f1)}` : '');
  draw();
}

get('demo-dataset').addEventListener('click', () => perform(async () => {
  setDataset(await demoDataset(), '合成演奏示例', true);
}, '正在载入示例…'));
get('download-dataset').addEventListener('click', () => perform(async () => {
  downloadJson(await demoDataset(), 'alignment-dataset-example.json');
  status(message, '示例格式已下载。');
}, '正在读取示例格式…'));
get('dataset-file').addEventListener('change', event => {
  const file = event.target.files[0];
  if (file) perform(async () => setDataset(await readJson(file), file.name, false), '正在读取训练集…');
});
get('train').addEventListener('click', () => perform(async () => {
  const report = await post('/api/train', state.dataset);
  state.report = report;
  setModel(report.model, state.synthetic ? '合成示例训练参数' : `本次训练 · ${state.source}`);
  renderReport();
  status(message, '参数搜索和留出曲目验证已完成。');
}, '正在用训练曲目搜索参数，并评估留出曲目…'));
get('mode-train').addEventListener('click', () => mode('train'));
get('mode-pair').addEventListener('click', () => mode('pair'));
sample.addEventListener('change', renderCase);
for (const id of ['reference-file', 'performance-file']) {
  get(id).addEventListener('change', () => { state.pair = null; controls(); renderCase(); status(message, ''); });
}
get('model-file').addEventListener('change', event => {
  const file = event.target.files[0];
  if (file) perform(async () => {
    const model = await readJson(file);
    if (model?.method !== 'piecewise-onset-alignment' || model.version !== 1 || !model.parameters) {
      throw new Error('请选择本工具保存的模型 JSON');
    }
    setModel(model, file.name);
    renderCase();
    status(message, '模型已载入。');
  }, '正在读取模型…');
});
get('align').addEventListener('click', () => perform(async () => {
  const [reference, performance] = await Promise.all(['reference-file', 'performance-file'].map(id => filePayload(get(id).files[0])));
  state.pair = await post('/api/align', {reference, performance, model: state.model});
  renderCase();
  status(message, '已完成单段对齐。');
}, '正在匹配和弦与起音…'));
get('download-model').addEventListener('click', () => downloadJson(state.report.model, 'alignment-model.json'));
get('download-report').addEventListener('click', () => downloadJson({...state.report, source: state.source, synthetic: state.synthetic}, 'alignment-validation.json'));
get('download-pair').addEventListener('click', () => downloadJson({...state.pair, model: state.model}, 'alignment-result.json'));
get('download-template').addEventListener('click', () => {
  const id = get('reference-file').files[0].name.replace(/\.[^.]+$/, '');
  downloadJson({version: 1, examples: [{id, piece_id: id,
    reference: state.pair.reference, performance: state.pair.performance, matches: [],
    suggested_matches: state.pair.adaptive.pairs.map(([reference_id, performance_id]) => ({reference_id, performance_id}))}]}, 'alignment-label-template.json');
});
new ResizeObserver(draw).observe(get('mapping'));
controls();
