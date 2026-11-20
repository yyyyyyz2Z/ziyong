export const get = id => document.getElementById(id);

export async function post(path, data) {
  const response = await fetch(path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '处理失败');
  return result;
}

export async function readJson(file) {
  if (file.size > 15 * 1024 * 1024) throw new Error('JSON 文件须在 15 MB 以内');
  try {
    return JSON.parse((await file.text()).replace(/^\uFEFF/, ''));
  } catch {
    throw new Error('无法读取 JSON，请检查文件格式');
  }
}

export function filePayload(file, maxMb = 5) {
  if (!file) return Promise.reject(new Error('请先选择文件'));
  if (file.size > maxMb * 1024 * 1024) return Promise.reject(new Error(`${file.name} 超过 ${maxMb} MB`));
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve({name: file.name, data: reader.result.split(',')[1]});
    reader.onerror = () => reject(new Error(`无法读取 ${file.name}`));
    reader.readAsDataURL(file);
  });
}

export function download(blob, name) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function downloadJson(value, name) {
  download(new Blob([JSON.stringify(value, null, 2)], {type: 'application/json'}), name);
}

export function status(node, text, error = false) {
  node.textContent = text;
  node.classList.toggle('error', error);
}

export function svgElement(name, attributes, text) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  if (text !== undefined) node.textContent = text;
  return node;
}

export function chart(container, height, padding = {}) {
  const width = container.clientWidth;
  if (width < 180) return null;
  const margins = {left: 37, right: 15, top: 24, bottom: 31, ...padding};
  const svg = svgElement('svg', {viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': container.getAttribute('aria-label')});
  container.replaceChildren(svg);
  return {svg, width, height, left: margins.left, right: width - margins.right, top: margins.top, bottom: height - margins.bottom};
}

export function chartLine(svg, x1, y1, x2, y2, css = 'grid') {
  svg.append(svgElement('line', {x1, y1, x2, y2, class: css}));
}

export function chartText(svg, x, y, value, align = 'start', css = '') {
  svg.append(svgElement('text', {x, y, 'text-anchor': align, class: css}, value));
}

export function ticks(max, target = 5) {
  const roughStep = max / target;
  const unit = 10 ** Math.floor(Math.log10(roughStep));
  const step = ([1, 2, 2.5, 5, 10].find(candidate => candidate * unit >= roughStep) || 10) * unit;
  return Array.from({length: Math.floor(max / step + 1e-9) + 1}, (_, index) => +(index * step).toFixed(3));
}

export function pitchName(pitch) {
  return `${['C','C♯','D','E♭','E','F','F♯','G','A♭','A','B♭','B'][pitch % 12]}${Math.floor(pitch / 12) - 1}`;
}
