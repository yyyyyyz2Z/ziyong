import React, {useEffect, useMemo, useRef, useState} from 'react';
import {ArrowRight, ChatCircleText, Clock, MusicNotes, PaperPlaneTilt, Play, Plus, Target} from '@phosphor-icons/react';
import {api, post, modes, stamp, Panel, Stats, ErrorText} from './workspace-ui';

const suggestions = [
  '这段应该怎么安排慢练？',
  '哪些音符没有识别出指法？',
  '练习这一段时怎么保持节奏稳定？',
];

function initialRange(start, duration, end) {
  const first = Math.max(0, Math.min(start || 0, Math.max(0, duration - (end ? .001 : 1))));
  const last = end > first ? end : first + 5;
  return [String(Number(first.toFixed(2))), String(Number(Math.min(duration, last).toFixed(3)))];
}

export function SegmentCoach({initial, openAnalysis, onPractice}) {
  const [jobs,setJobs] = useState([]);
  const [context,setContext] = useState(initial || null);
  const [jobId,setJobId] = useState(initial?.job.id || '');
  const [range,setRange] = useState(() => initialRange(initial?.start, initial?.result.summary.video_duration_seconds || 0, initial?.end));
  const [tab,setTab] = useState('chat');
  const [selection,setSelection] = useState('time');
  const [ids,setIds] = useState([]);
  const [page,setPage] = useState(0);
  const [messages,setMessages] = useState([]);
  const [question,setQuestion] = useState('');
  const [configured,setConfigured] = useState(false);
  const [error,setError] = useState('');
  const [notice,setNotice] = useState('');
  const [busy,setBusy] = useState(false);
  const [plan,setPlan] = useState(null);
  const [savedIndex,setSavedIndex] = useState([]);
  const player = useRef(null);
  const stopAt = useRef(null);
  const navigation = useRef(0);
  const historyRoute = jobId ? '/jobs/' + jobId + '/coach' : '/coach';
  const duration = context?.result.summary.video_duration_seconds || 0;
  const offset = context?.result.summary.offset_seconds || 0;

  useEffect(() => {
    let live = true;
    Promise.all([api('/jobs'), api('/coach/status')])
      .then(([values,status]) => {
        if (!live) return;
        setJobs(values.filter(j => j.status === 'succeeded'));
        setConfigured(status.configured);
      })
      .catch(e => {if (live) setError(e.message);});
    return () => {live = false;};
  }, []);

  useEffect(() => {
    let live = true;
    api(historyRoute).then(items => {if (live) setMessages(items);})
      .catch(e => {if (live) setError(e.message);});
    return () => {live = false;};
  }, [historyRoute]);

  async function selectJob(id) {
    const request = ++navigation.current;
    setJobId(id); setMessages([]); setError(''); setNotice(''); setContext(null);
    setIds([]); setPage(0); setSelection('time');
    setPlan(null); setSavedIndex([]);
    if (!id) return;
    const job = jobs.find(item => item.id === id);
    try {
      const result = await api('/jobs/' + id + '/result');
      if (request !== navigation.current) return;
      setContext({job,result});
      setRange(initialRange(0,result.summary.video_duration_seconds));
    } catch (e) {if (request === navigation.current) setError(e.message);}
  }

  const notes = useMemo(() => (context?.result.notes || [])
    .map(note => ({
      ...note,
      time: Number(note.start_seconds) + offset,
      end: Math.min(duration, Math.max(Number(note.start_seconds) + .08, Number(note.end_seconds)) + offset),
    }))
    .filter(note => note.time >= 0 && note.time < duration), [context,offset,duration]);
  const chosen = notes.filter(n => ids.includes(n.note_index));
  const start = selection === 'notes' && chosen.length ? Math.min(...chosen.map(n => n.time)) : Number(range[0]);
  const end = selection === 'notes' && chosen.length ? Math.max(...chosen.map(n => n.end)) : Number(range[1]);
  const valid = !!context && start >= 0 && end > start && end <= duration + .001
    && (selection === 'time' ? range.every(value => value !== '') : chosen.length > 0);
  const segmentNotes = selection === 'notes' ? chosen : notes.filter(note => note.time >= start && note.time < end);
  const candidateCount = segmentNotes.filter(note => note.status === 'matched').length;
  const canAsk = (!jobId || valid) && !!question.trim() && !busy;

  function play(first, last) {
    if (!player.current) return;
    stopAt.current = last;
    player.current.currentTime = first;
    player.current.play().catch(() => setNotice('请按播放器的播放按钮。'));
  }

  async function submit(event, send) {
    event.preventDefault();
    if (!canAsk) return;
    setError(''); setNotice(''); setBusy(true);
    try {
      const message = await post(historyRoute, {
        question: question.trim(), start, end, send,
        note_ids: selection === 'notes' ? ids : [],
      });
      setMessages(items => [...items,message]);
      setQuestion('');
    } catch (e) {setError(e.message);}
    finally {setBusy(false);}
  }

  async function generatePlan() {
    if (!valid) return;
    setNotice(''); setError(''); setBusy(true); setPlan(null); setSavedIndex([]);
    try {
      setPlan(await post('/jobs/' + jobId + '/practice-plan',{start,end,note_ids: selection === 'notes' ? ids : []}));
    } catch (e) {setError(e.message);}
    finally {setBusy(false);}
  }

  async function addPractice(item,index) {
    setNotice(''); setError(''); setBusy(true);
    try {
      await post('/practice', {
        title: item?.title || '片段慢练 · ' + (context.job.title || '演奏 ' + jobId.slice(0,8)).slice(0,85),
        detail: item?.detail || '先回看片段，选一处换指或节奏难点。低速分手练，稳定后合手，最后录一次对照。',
        job_id: jobId, start: item ? plan.start : start, end: item ? plan.end : end,
      });
      if (item) setSavedIndex(values => [...values,index]);
      setNotice('已加入练习计划。');
    } catch (e) {setError(e.message);}
    finally {setBusy(false);}
  }

  return <div className="workflow-stack coach-workspace">
    <div className="workflow-actions coach-tabs">
      <button className={tab === 'chat' ? 'selected' : ''} onClick={() => setTab('chat')}><ChatCircleText/>片段问答</button>
      <button className={tab === 'review' ? 'selected' : ''} onClick={() => setTab('review')}><Target/>片段分析与练习</button>
    </div>
    <div className="coach-grid">
      <Panel title="演奏证据" action={context && <span className="status-pill">{modes[context.job.mode || 'fingering']}</span>}>
        <label>选择分析任务<select value={jobId} disabled={busy} onChange={e => selectJob(e.target.value)}>
          <option value="">通用钢琴问题</option>
          {jobs.map(job => <option key={job.id} value={job.id}>{job.title || '历史演奏'} · {job.id.slice(0,8)}</option>)}
        </select></label>
        {context ? <>
          <video key={jobId} ref={player} className="workflow-video" controls preload="metadata" src={context.result.replay}
            onTimeUpdate={e => {
              if (stopAt.current !== null && e.currentTarget.currentTime >= stopAt.current) {
                e.currentTarget.pause(); stopAt.current = null;
              }
            }}/>
          <div className="review-filters">
            <button className={selection === 'time' ? 'selected' : ''} onClick={() => setSelection('time')}><Clock/>按时间</button>
            <button disabled={!notes.length} className={selection === 'notes' ? 'selected' : ''} onClick={() => setSelection('notes')}><MusicNotes/>按音符</button>
          </div>
          {selection === 'time' ? <>
            <div className="time-inputs">
              <label>开始秒数<input type="number" min="0" max={duration} step="any" value={range[0]} onChange={e => setRange([e.target.value,range[1]])}/></label>
              <label>结束秒数<input type="number" min="0" max={duration} step="any" value={range[1]} onChange={e => setRange([range[0],e.target.value])}/></label>
            </div>
            <div className="time-tools">
              <button onClick={() => setRange([String((player.current?.currentTime || 0).toFixed(2)),range[1]])}>用播放位置设为开始</button>
              <button onClick={() => setRange([range[0],String((player.current?.currentTime || 0).toFixed(2))])}>用播放位置设为结束</button>
            </div>
          </> : <>
            <div className="note-picker">{notes.slice(page * 24,page * 24 + 24).map(note =>
              <button key={note.note_index} aria-pressed={ids.includes(note.note_index)} className={ids.includes(note.note_index) ? 'selected' : ''}
                onClick={() => setIds(ids.includes(note.note_index) ? ids.filter(id => id !== note.note_index) : [...ids,note.note_index])}>
                <strong>{note.note_name}</strong><small>{stamp(note.time)}</small>
              </button>)}</div>
            <div className="workflow-actions">
              <button className="text-button" disabled={!page} onClick={() => setPage(page - 1)}>上一组</button>
              <button className="text-button" disabled={(page + 1) * 24 >= notes.length} onClick={() => setPage(page + 1)}>下一组</button>
              <button className="text-button" disabled={!ids.length} onClick={() => setIds([])}>清空（{ids.length}）</button>
            </div>
          </>}
          <div className="segment-selection">
            <div><strong>{valid ? stamp(start) + ' — ' + stamp(end) : '选择视频内的有效片段'}</strong>
              <p>{valid ? '关联 ' + segmentNotes.length + ' 个指法分析音符' : '结束时间须大于开始时间'}</p></div>
            <button className="text-button" disabled={!valid} onClick={() => play(start,end)}><Play/>播放片段</button>
          </div>
        </> : <div className="workflow-empty">
          <MusicNotes size={39}/><p>{jobId ? '正在读取演奏结果…' : '可先提通用问题，也可选一条分析记录回看片段。'}</p>
          <button className="text-button" onClick={openAnalysis}>前往演奏分析 <ArrowRight/></button>
        </div>}
      </Panel>
      {tab === 'review' ? <Panel title="片段分析与练习">
        {valid ? <>
          <Stats items={[[ '音符事件',segmentNotes.length],['几何候选',candidateCount],['未确定',segmentNotes.length - candidateCount]]}/>
          <p className="subtle">{segmentNotes.length ? '未确定音符适合优先回看，也可能来自遮挡或校准偏差。' : '当前片段没有逐音指法证据，可回放画面制定练习目标。'}</p>
          <div className="practice-suggestion"><Target size={26}/><div><h4>慢速拆段练习</h4><p>选一处换指或节奏难点，低速分手练，稳定后合手。最后再录一次用于对照。</p></div></div>
          <div className="workflow-actions">
            {configured && <button className="primary" disabled={busy} onClick={generatePlan}><Target/>{busy ? '处理中…' : '生成 AI 练习草案'}</button>}
            <button className="text-button" disabled={busy} onClick={() => addPractice()}><Plus/>加入慢练</button>
            <button className="text-button" onClick={onPractice}>查看计划 <ArrowRight/></button>
          </div>
          {plan && <div className="workflow-list generated-plan">
            <p className="subtle">AI 练习草案 · {stamp(plan.start)} — {stamp(plan.end)}</p>
            {plan.items.map((item,index) => <article key={index} className="workflow-row draft-plan-row">
              <div><strong>{item.title}</strong><p>{item.detail}</p></div>
              <button className="text-button" disabled={busy || savedIndex.includes(index)} onClick={() => addPractice(item,index)}>{savedIndex.includes(index) ? '已加入' : '加入计划'}</button>
            </article>)}
          </div>}
        </> : <div className="workflow-empty"><Target size={36}/><p>选择演奏任务和片段后，即可查看证据和添加练习。</p></div>}
      </Panel> : <Panel title="AI 教练" action={<span className={'status-pill ' + (configured ? '' : 'planned')}>{configured ? '模型已配置' : '可保存草稿'}</span>}>
        <div className="question-chips">{suggestions.map(value => <button type="button" key={value} onClick={() => setQuestion(value)}>{value}</button>)}</div>
        <div className="segment-messages" aria-live="polite">
          {!messages.length && <div className="conversation-empty"><ChatCircleText size={34}/><p>你想问哪一段演奏？</p></div>}
          {messages.map(message => <article className="question-draft" key={message.id}>
            <span>{message.status === 'answered' ? '我的问题' : '我的草稿'}</span>
            <p className="coach-text">{message.question}</p>
            {message.evidence && <button className="segment-reference" onClick={() => play(message.evidence.start,message.evidence.end)}>
              <Play/>{stamp(message.evidence.start)} — {stamp(message.evidence.end)}<small>{message.evidence.total} 个音符</small>
            </button>}
            {message.answer && <div className="coach-answer">
              <p className="coach-text">{message.answer}</p>
              <details><summary>提供给模型的练习资料</summary>
                {message.references.map(ref => <a key={ref.id} href={ref.url} target="_blank" rel="noreferrer">{ref.title}</a>)}
              </details>
            </div>}
            {configured && message.status === 'draft' && <button className="text-button" onClick={() => {
              setQuestion(message.question);
              if (message.evidence) {
                const selected = message.evidence.selected_note_ids || [];
                setIds(selected);
                setSelection(selected.length ? 'notes' : 'time');
                setRange([String(message.evidence.start),String(message.evidence.end)]);
              }
            }}>继续编辑</button>}
          </article>)}
        </div>
        <form onSubmit={e => submit(e,configured)}>
          <label>你的问题<textarea maxLength={2000} value={question} onChange={e => setQuestion(e.target.value)} placeholder="例如，这几个音的换指可以怎么练？"/></label>
          <div className="composer-footer">
            {configured && <button className="text-button" type="button" disabled={!canAsk} onClick={e => submit(e,false)}>保存草稿</button>}
            <button className="primary" disabled={!canAsk}><PaperPlaneTilt/>{busy ? '处理中…' : configured ? '发送问题' : '保存问题草稿'}</button>
          </div>
          {configured && <p className="subtle">发送时，模型服务会收到问题、所选片段的音符摘要和练习资料。</p>}
        </form>
      </Panel>}
    </div>
    <ErrorText error={error}/>
    {notice && <p role="status" className="evidence-banner">{notice}<button className="text-button" onClick={() => setNotice('')}>关闭</button></p>}
  </div>;
}
