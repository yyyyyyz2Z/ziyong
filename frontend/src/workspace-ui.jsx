import React from 'react';

export async function api(path, options) {
  const response = await fetch('/api' + path, options);
  const data = await response.json().catch(() => null);
  if (!response.ok || data === null) {
    throw new Error(data?.error || '无法访问本地服务，请确认后端已启动。');
  }
  return data;
}

export function post(path, data, headers = {}) {
  return api(path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json', ...headers},
    body: JSON.stringify(data),
  });
}

export function uploadAsset(kind, file, library = false) {
  return api('/upload/' + kind + (library ? '?library=1' : ''), {
    method: 'POST',
    headers: {'Content-Type': 'application/octet-stream', 'X-File-Name': encodeURIComponent(file.name)},
    body: file,
  });
}

export const modes = {
  performance: '弹奏 AI 分析',
  skeleton_only: '手部骨架',
  fingering: '逐音指法',
  audio: '音频转录',
};
export const statuses = {matched: '有候选', uncertain: '无法确定', unmatched: '未匹配'};
export const jobStates = {queued: '排队中', running: '分析中', succeeded: '已完成', failed: '失败'};
export const stamp = seconds => Number(seconds).toFixed(2) + ' 秒';
export const videoUrl = job => '/api/assets/' + job.video_id + '/video';

export function Panel({title, action, children, className = ''}) {
  return <section className={'panel workflow-panel ' + className}>
    <div className="panel-heading"><h3>{title}</h3>{action}</div>
    {children}
  </section>;
}

export function Stats({items}) {
  return <div className="snapshot-stats workflow-stats">
    {items.map(([label, value]) => <div key={label}><strong>{value}</strong><span>{label}</span></div>)}
  </div>;
}

export function ErrorText({error}) {
  return error && <p role="alert" className="validation workflow-error">{error}</p>;
}
