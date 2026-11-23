import React, {useEffect, useState} from 'react';
import {api, post, Panel, ErrorText} from './workspace-ui';

export function PerformanceOverview({jobId, initial, onReady}) {
  const [overview, setOverview] = useState(initial || {status: 'available'});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {onReady?.(overview.status === 'answered');}, [overview.status, onReady]);
  useEffect(() => {
    if (overview.status !== 'pending') return;
    let live = true;
    let timer;
    const poll = async () => {
      try {
        const value = await api('/jobs/' + jobId + '/overview');
        if (!live) return;
        setOverview(value);
        if (value.status === 'pending') timer = setTimeout(poll, 1800);
      } catch (failure) {if (live) {setError(failure.message); timer = setTimeout(poll, 4000);}}
    };
    timer = setTimeout(poll, 1000);
    return () => {live = false; clearTimeout(timer);};
  }, [jobId, overview.status]);
  async function generate() {
    setBusy(true); setError('');
    try {setOverview(await post('/jobs/' + jobId + '/overview', {}));}
    catch (failure) {setError(failure.message);}
    finally {setBusy(false);}
  }
  return <Panel title="全曲弹奏评价">
    {overview.answer ? <p className="coach-text coach-answer">{overview.answer}</p> : <>
      <p role="status">{overview.status === 'pending' || busy ? 'AI 正在结合整段演奏，整理整体表现和练习重点…'
        : overview.status === 'configuration_required' ? '演奏分析已保存。请管理员在个人中心连接 AI 服务，即可生成全曲评价并继续追问。'
        : overview.status === 'failed' ? '全曲评价生成暂时中断，可以重新生成。' : '结合全曲的音符、指法与节奏，生成本次弹奏评价。'}</p>
      <button className="primary" disabled={busy || overview.status === 'pending'} onClick={generate}>
        {overview.status === 'failed' ? '重新生成评价' : '生成全曲评价'}
      </button>
    </>}
    <ErrorText error={error}/>
  </Panel>;
}
