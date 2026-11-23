import React, {useEffect, useMemo, useRef, useState} from 'react';
import {ArrowRight, ChatCircleText, Clock, MusicNotes, PaperPlaneTilt, Play, CalendarDots} from '@phosphor-icons/react';
import {api, post, modes, stamp, Panel, Stats, ErrorText} from './workspace-ui';
import {TechniqueEvidence} from './TechniqueEvidence';
import {ScoreEvidence} from './ScoreEvidence';
import {PerformanceOverview} from './PerformanceOverview';

const suggestions = [
  '这段应该怎么安排慢练？',
  '这几个音的指法怎样衔接更顺畅？',
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
  const [selection,setSelection] = useState(initial?.noteIds?.length ? 'notes' : 'time');
  const [ids,setIds] = useState(initial?.noteIds || []);
  const [page,setPage] = useState(0);
  const [messages,setMessages] = useState([]);
  const [question,setQuestion] = useState('');
  const [configured,setConfigured] = useState(false);
  const [error,setError] = useState('');
  const [notice,setNotice] = useState('');
  const [busy,setBusy] = useState(false);
  const [overviewReady,setOverviewReady] = useState(initial?.result.overview?.status === 'answered');
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
    setOverviewReady(false);
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
  const canAsk = (!jobId || valid) && !!question.trim() && !busy;
  const techniqueAttempts = (context?.result.summary.technique?.attempts || []).filter(attempt =>
    valid && attempt.start >= start - .001 && attempt.end < end &&
    (selection !== 'notes' || attempt.note_ids.every(id => ids.includes(id))));

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
    if (!context || !overviewReady || busy) return;
    setNotice(''); setError(''); setBusy(true);
    try {
      const plan = await post('/jobs/' + jobId + '/practice-plan', {scope:'full'});
      onPractice({generatedCount:plan.items.length, draftId:plan.id, confirmed:plan.status === 'confirmed'});
    } catch (e) {setError(e.message);}
    finally {setBusy(false);}
  }

  return <div className="workflow-stack coach-workspace">
    {context && <>
      <PerformanceOverview key={jobId} jobId={jobId} initial={context.result.overview} onReady={setOverviewReady}/>
      <div className="coach-plan-prompt">
        <CalendarDots size={28}/>
        <div><strong>让 AI 为你安排练习</strong>
          <p>根据全曲评价生成练习建议，编辑并确认后安排到日历。</p></div>
        <button className="primary" disabled={!configured || !overviewReady || busy} onClick={generatePlan}>
          {busy ? '正在处理…' : '生成练习建议'}
        </button>
        {!overviewReady && <small>全曲评价完成后即可生成练习计划。</small>}
      </div>
    </>}
    <div className="coach-grid">
      <Panel title="选择演奏与片段" action={context && <span className="status-pill">{modes[context.job.mode || 'fingering']}</span>}>
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
      <Panel title="片段分析" action={<span className={'status-pill ' + (configured ? '' : 'planned')}>{configured ? 'AI 已连接' : '可保存草稿'}</span>}>
        {valid && <Stats items={[[ '片段音符',segmentNotes.length],['片段时长',stamp(end - start)]]}/>}
        <div className="question-chips">{suggestions.map(value => <button type="button" key={value} onClick={() => setQuestion(value)}>{value}</button>)}</div>
        <div className="segment-messages" aria-live="polite">
          {!messages.length && <div className="conversation-empty"><ChatCircleText size={34}/><p>你想问哪一段演奏？</p></div>}
          {messages.map(message => <article className="question-draft" key={message.id}>
            <span>{message.status === 'answered' ? '我的问题' : '我的草稿'}</span>
            <p className="coach-text">{message.question}</p>
            {message.evidence && <button className="segment-reference" onClick={() => play(message.evidence.start,message.evidence.end)}>
              <Play/>{stamp(message.evidence.start)} — {stamp(message.evidence.end)}<small>{message.evidence.total} 个音符</small>
            </button>}
            {message.evidence?.technique && <TechniqueEvidence attempts={message.evidence.technique.attempts}
              rules={message.evidence.technique.rules} total={message.evidence.technique.total_attempts}
              taskLabel={message.evidence.technique.task} repeatability={message.evidence.technique.repeatability}
              references={message.evidence.technique_references}
              onPlay={(first,last) => play(first, Math.min(message.evidence.end, last + .15))}/>}
            {message.evidence?.score_alignment && <ScoreEvidence report={message.evidence.score_alignment}
              duration={duration} references={message.evidence.score_references}
              onPlay={time => play(Math.max(message.evidence.start, time - .15), Math.min(message.evidence.end, time + .45))}/>}
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
          {configured && <p className="subtle">发送时，模型服务会收到问题、片段音符、可用的换指指标和练习资料。</p>}
          {techniqueAttempts.length > 0 && <p className="subtle" role="status">所选片段含 {techniqueAttempts.length} 遍可引用的换指数据。</p>}
        </form>
      </Panel>
    </div>
    <ErrorText error={error}/>
    {notice && <p role="status" className="evidence-banner">{notice}<button className="text-button" onClick={() => setNotice('')}>关闭</button></p>}
  </div>;
}
