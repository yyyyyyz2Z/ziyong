import React, {useEffect, useRef, useState} from 'react';
import {UploadSimple, MusicNotes, Play, ChatCircleText, DownloadSimple} from '@phosphor-icons/react';
import {api, post, uploadAsset, modes, jobStates, stamp, videoUrl, Panel, Stats, ErrorText} from './workspace-ui';
import {KeyboardCalibration} from './KeyboardCalibration';
import {ScoreEvidence} from './ScoreEvidence';
import {PerformanceOverview} from './PerformanceOverview';

function AnalysisResult({job, result, onCoach}) {
  const [overlay, setOverlay] = useState(false);
  const [page, setPage] = useState(0);
  const player = useRef();
  const pendingSeek = useRef(null);
  const {summary, notes, score_alignment: score} = result;
  const unified = job.mode === 'performance';
  const ask = (time, end, ids = []) => onCoach(job, result, Math.max(0, time - .15),
    Math.min(summary.video_duration_seconds, end || time + 1.5), ids);
  const files = [['analysis_summary.json', '分析摘要']];
  if (unified) files.push(['performance_graph.json', '演奏知识图谱'], ['aligned_reference.mid', '对齐 MIDI']);
  if (notes.length) files.push(['fingering_predictions.csv', '音符与指法']);
  if (score) files.push(['score_alignment.json', '谱面关联']);
  if (job.mode === 'audio' || unified) files.push(['transcribed.mid', '音轨转录 MIDI']);
  const offset = summary.offset_seconds || 0;
  function play(time) {
    player.current.currentTime = Math.max(0, time - .2);
    player.current.play().catch(() => {});
  }
  return <div className="workflow-stack">
    <PerformanceOverview jobId={job.id} initial={result.overview}/>
    <Panel title="演奏回看与追问" action={<button className="primary" onClick={() => ask(0, summary.video_duration_seconds)}>选取片段向 AI 提问</button>}>
      <Stats items={[[ '分析音符',summary.notes || 0],['演奏时长',stamp(summary.video_duration_seconds)]]}/>
      {job.mode !== 'audio' && <label className="workflow-check"><input type="checkbox" checked={overlay}
        onChange={event => {pendingSeek.current = player.current?.currentTime; setOverlay(event.target.checked);}}/>显示手指与琴键标记</label>}
      <video ref={player} className="workflow-video" controls preload="metadata" src={overlay ? result.replay : videoUrl(job)}
        onLoadedMetadata={event => {
          if (pendingSeek.current !== null) {event.currentTarget.currentTime = pendingSeek.current; pendingSeek.current = null;}
        }}/>
      {score && <ScoreEvidence report={score} duration={summary.video_duration_seconds} onPlay={play}
        onAsk={(time, id) => ask(time, undefined, id ? [id] : [])}/>}
      {notes.length > 0 && <details className="technique-evidence" open={!score}>
        <summary>逐音查看与提问</summary>
        <div className="table-wrap"><table><thead><tr>{['音符','视频时间','手指','操作'].map(label => <th key={label}>{label}</th>)}</tr></thead>
          <tbody>{notes.slice(page * 30, (page + 1) * 30).map(note => {
            const time = Number(note.start_seconds) + offset;
            return <tr key={note.note_index}><td>{note.note_name}</td><td>{stamp(time)}</td>
              <td>{note.finger ? ({left:'左手',right:'右手'}[note.hand] + ' ' + note.finger + ' 指') : '结合相邻音组练习'}</td>
              <td><div className="workflow-actions"><button className="text-button" onClick={() => play(time)}><Play/>回看</button>
                <button className="text-button" onClick={() => ask(time, Number(note.end_seconds) + offset, [note.note_index])}><ChatCircleText/>问这个音</button></div></td></tr>;
          })}</tbody></table></div>
        <div className="workflow-actions"><button className="text-button" disabled={!page} onClick={() => setPage(page - 1)}>上一页</button>
          <span>{page + 1} / {Math.ceil(notes.length / 30)}</span>
          <button className="text-button" disabled={(page + 1) * 30 >= notes.length} onClick={() => setPage(page + 1)}>下一页</button></div>
      </details>}
      <details className="technique-evidence"><summary>下载分析资料</summary><div className="workflow-actions download-row">
        {files.map(([file,label]) => <a key={file} className="text-button" href={'/api/jobs/' + job.id + '/' + file} download><DownloadSimple/>{label}</a>)}
      </div></details>
    </Panel>
  </div>;
}

export function AnalysisWorkspace({initialVideo, onInitialUpload, initialReference, onCoach, historyRequested, onHistoryShown}) {
  const [video, setVideo] = useState(null);
  const [reference, setReference] = useState(initialReference || null);
  const [score, setScore] = useState(null);
  const [first, setFirst] = useState(1);
  const [last, setLast] = useState(1);
  const [keyboard, setKeyboard] = useState(null);
  const [mirrored, setMirrored] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [job, setJob] = useState(null);
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);
  const initialUpload = useRef(null);
  const navigation = useRef(0);
  const historyPanel = useRef(null);
  const running = ['queued','running'].includes(job?.status);
  const refresh = () => api('/jobs').then(setHistory).catch(failure => setError(failure.message));
  useEffect(() => {refresh();}, []);
  useEffect(() => {
    if (initialVideo && initialUpload.current !== initialVideo) {
      initialUpload.current = initialVideo;
      upload('video', initialVideo).finally(onInitialUpload);
    }
  }, [initialVideo]);
  useEffect(() => {
    if (historyRequested) {historyPanel.current?.scrollIntoView({behavior:'smooth'}); onHistoryShown();}
  }, [historyRequested, onHistoryShown]);
  useEffect(() => {
    if (!running) return;
    let live = true;
    let timer;
    async function poll() {
      try {
        const current = await api('/jobs/' + job.id);
        const data = current.status === 'succeeded' ? await api('/jobs/' + job.id + '/result') : null;
        if (!live) return;
        setJob(current);
        if (data) setResult(data);
        if (current.status === 'failed') setError(current.error || '分析中断，请重新提交。');
        if (!['queued','running'].includes(current.status)) {refresh(); return;}
      } catch (failure) {if (live) setError(failure.message);}
      if (live) timer = setTimeout(poll, 1500);
    }
    timer = setTimeout(poll, 900);
    return () => {live = false; clearTimeout(timer);};
  }, [job?.id, running]);
  async function upload(kind, file) {
    if (!file) return;
    setBusy(true); setError('');
    try {
      const isMidi = /\.midi?$/i.test(file.name);
      const asset = await uploadAsset(kind === 'video' ? 'video' : isMidi ? 'midi' : 'score', file);
      if (kind === 'video') {setVideo(asset); setKeyboard(null);}
      else if (isMidi) {setReference(asset); setScore(null);}
      else {setScore(asset); setReference(null); setFirst(1); setLast(asset.measures.length);}
    } catch (failure) {setError(failure.message);}
    finally {setBusy(false);}
  }
  async function submit() {
    ++navigation.current;
    setBusy(true); setError(''); setResult(null);
    try {
      setJob(await post('/jobs', {mode:'performance', video_id:video.id, keyboard, mirrored,
        score_id:score?.id, reference_id:reference?.id, measure_first:first, measure_last:last}));
      refresh();
    } catch (failure) {setError(failure.message);}
    finally {setBusy(false);}
  }
  async function restore(current) {
    const request = ++navigation.current;
    setResult(null); setJob(current); setError(current.error || '');
    if (current.status !== 'succeeded') return;
    try {
      const data = await api('/jobs/' + current.id + '/result');
      if (request === navigation.current) setResult(data);
    } catch (failure) {if (request === navigation.current) setError(failure.message);}
  }
  return <div className="workflow-stack">
    <div className="analysis-grid">
      <Panel title="钢琴弹奏 AI 分析" action={<button className="text-button" onClick={() => historyPanel.current?.scrollIntoView({behavior:'smooth'})}>历史演奏</button>}>
        <label className="upload-tile"><UploadSimple size={27}/><span><strong>{video?.name || '上传俯拍演奏视频'}</strong>
          <small>{video ? stamp(video.duration) : '带琴声，固定机位，完整拍到键盘和双手'}</small></span>
          <input type="file" aria-label="演奏视频" accept="video/*" disabled={busy || running} onChange={event => upload('video', event.target.files[0])}/></label>
        <label className="upload-tile"><MusicNotes size={27}/><span><strong>{score?.name || reference?.name || '上传对应五线谱或 MIDI'}</strong>
          <small>{score ? score.measures.length + ' 小节' : reference ? reference.notes + ' 个音符' : 'PDF、PNG、JPG、MusicXML、MID'}</small></span>
          <input type="file" aria-label="曲目乐谱或 MIDI" accept=".pdf,.png,.jpg,.jpeg,.musicxml,.xml,.mxl,.mid,.midi" disabled={busy || running}
            onChange={event => upload('reference', event.target.files[0])}/></label>
        {score && <details className="technique-evidence"><summary>分析小节范围</summary><div className="time-inputs">
          <label>起始小节<select value={first} onChange={event => setFirst(Number(event.target.value))}>
            {score.measures.map(item => <option key={item.position} value={item.position}>{item.label}</option>)}</select></label>
          <label>结束小节<select value={last} onChange={event => setLast(Number(event.target.value))}>
            {score.measures.map(item => <option key={item.position} value={item.position}>{item.label}</option>)}</select></label>
        </div></details>}
        <p className="keyboard-instructions">视频与谱面请使用同一曲目和完整对应的演奏范围。系统会结合音轨、手指动作与琴键位置，先生成全曲评价，再支持逐段追问。</p>
        <label className="workflow-check"><input type="checkbox" checked={mirrored} disabled={running}
          onChange={event => {setKeyboard(null); setMirrored(event.target.checked);}}/>视频已水平镜像</label>
        <button className="primary wide" disabled={busy || running || !video || !keyboard || (!score && !reference) || first > last} onClick={submit}>
          {busy ? '正在处理上传资料…' : running ? '正在分析演奏…' : '开始 AI 弹奏分析'}</button>
        <ErrorText error={error}/>
      </Panel>
      {video ? <KeyboardCalibration key={video.id + ':' + mirrored} {...{video, mirrored, keyboard}} onKeyboard={setKeyboard}/>
        : <Panel title="拍摄与上传"><div className="workflow-empty"><MusicNotes size={36}/>
          <p>从键盘正上方固定拍摄，完整拍到 88 个琴键与双手，并保留清晰琴声。</p>
          <p>上传视频和曲目资料后，自动定位琴键并准备分析。</p></div></Panel>}
    </div>
    {job && <p className="evidence-banner" role="status">{jobStates[job.status]} · {job.stage}</p>}
    {result && job && <AnalysisResult key={job.id} {...{job, result, onCoach}}/>}
    <div ref={historyPanel} tabIndex={-1}><Panel title="历史演奏" action={<button className="text-button" onClick={refresh}>刷新</button>}>
      {history.length ? <div className="workflow-list">{history.map(item => <button key={item.id} className="workflow-row" onClick={() => restore(item)}>
        <span><strong>{item.title || '历史演奏'}</strong><small>{modes[item.mode] || '演奏分析'} · {new Date(item.created_at).toLocaleDateString('zh-CN')}</small></span>
        <span className="status-pill">{jobStates[item.status]}</span></button>)}</div> : <p className="subtle">分析结果和全曲评价会保存在这里。</p>}
    </Panel></div>
  </div>;
}
