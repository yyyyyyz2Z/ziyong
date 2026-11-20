import React, {useEffect, useRef, useState} from 'react';
import {ArrowRight, Hand, MusicNotes, Waveform, UploadSimple, DownloadSimple, Play} from '@phosphor-icons/react';
import {api, post, uploadAsset, modes, jobStates, statuses, stamp, videoUrl, Panel, Stats, ErrorText} from './workspace-ui';

const modeOptions = [
  ['skeleton_only', Hand, '视频回放与手部关键点'],
  ['fingering', MusicNotes, '视频、对应 MIDI 与键床四角'],
  ['audio', Waveform, '从视频音轨估计音符'],
];

const fingeringReasons = {
  outside_video: '起音超出视频',
  no_hand: '未检测到手',
  outside_key: '指尖远离目标琴键',
  insufficient_frames: '接触帧太少',
  weak_contact: '触键证据较弱',
  ambiguous_fingers: '多个指法接近',
  chord_conflict: '和弦内手指冲突',
};

function Calibration({video, frame, setFrame, corners, setCorners, ready, setReady, low, high, setLow, setHigh}) {
  const [draft, setDraft] = useState(String(frame));
  const [suggestion, setSuggestion] = useState([]);
  const [waiting, setWaiting] = useState(false);
  const [info, setInfo] = useState('');
  const [frameError, setFrameError] = useState('');
  const [revision, setRevision] = useState(0);
  const requestId = useRef(0);
  const max = Math.max(0, video.duration - 1 / video.fps);
  const imageUrl = '/assets/' + video.id;

  function load() {
    requestId.current++;
    setWaiting(false);
    setCorners([]);
    setSuggestion([]);
    setInfo('');
    setFrameError('');
    setReady(false);
    setFrame(Number(draft));
    setRevision(n => n + 1);
  }

  async function estimate() {
    const id = ++requestId.current;
    setWaiting(true);
    setSuggestion([]);
    setInfo('');
    try {
      const hint = await api(imageUrl + '/calibration-hint?time=' + frame);
      if (requestId.current !== id) return;
      setSuggestion(hint.corners);
      setInfo(hint.corners.length ? '虚线为试算范围。请检查四角是否贴合完整键床。' : '没有找到合适的范围，请手动选择四角。');
    } catch (error) {
      if (requestId.current === id) setInfo(error.message);
    } finally {
      if (requestId.current === id) setWaiting(false);
    }
  }

  return <Panel title="标定键床" className="calibration-panel">
    <p className="subtle">依次点击左上、右上、右下、左下，填写画面中可见的最低和最高白键。请保持固定机位。</p>
    <div className="time-inputs">
      <label>最低白键 MIDI<input type="number" min="21" max="108" value={low} onChange={e => setLow(e.target.value)}/></label>
      <label>最高白键 MIDI<input type="number" min="21" max="108" value={high} onChange={e => setHigh(e.target.value)}/></label>
    </div>
    <div className="workflow-inline">
      <label>画面时间（秒）<input type="number" min="0" max={max} step="any" value={draft} onChange={e => setDraft(e.target.value)}/></label>
      <button className="glass-button" disabled={draft === '' || !(Number(draft) >= 0 && Number(draft) <= max)} onClick={load}>加载画面</button>
    </div>
    <ErrorText error={frameError}/>
    <div className="calibration-image">
      <img key={revision} alt={'键床标定画面，视频第 ' + stamp(frame)} src={'/api' + imageUrl + '/frame?time=' + frame + '&v=' + revision}
        onLoad={() => {setReady(true); setFrameError('');}}
        onError={() => {setReady(false); setFrameError('读取画面失败，请换一个时间点。');}}
        onClick={e => {
          if (!ready || corners.length === 4) return;
          const box = e.currentTarget.getBoundingClientRect();
          setCorners([...corners, [(e.clientX - box.left) / box.width * video.width, (e.clientY - box.top) / box.height * video.height]]);
        }}/>
      <svg aria-hidden="true" viewBox={`0 0 ${video.width} ${video.height}`}>
        {suggestion.length === 4 && <polygon points={suggestion.map(p => p.join(',')).join(' ')} fill="none" stroke="#f9d986" strokeWidth="5" strokeDasharray="12 9"/>}
        {corners.length === 4
          ? <polygon points={corners.map(p => p.join(',')).join(' ')} fill="#b48dff22" stroke="#a5f4db" strokeWidth="5"/>
          : <polyline points={corners.map(p => p.join(',')).join(' ')} fill="none" stroke="#a5f4db" strokeWidth="5"/>}
        {corners.map(([x,y],i) => <g key={i}><circle cx={x} cy={y} r="10" fill="#b58aff"/><text x={x+14} y={y} fill="white" fontSize="28">{i+1}</text></g>)}
      </svg>
    </div>
    <div className="workflow-actions calibration-actions">
      <button className="text-button" disabled={!ready || waiting} onClick={estimate}>{waiting ? '正在估计…' : '试算四角'}</button>
      {!!suggestion.length && <button className="text-button" onClick={() => {setCorners(suggestion); setSuggestion([]); setInfo('');}}>采用试算范围</button>}
      <button className="text-button" disabled={!corners.length} onClick={() => setCorners(corners.slice(0,-1))}>撤销一点</button>
      <button className="text-button" disabled={!corners.length && !suggestion.length} onClick={() => {setCorners([]); setSuggestion([]); setInfo('');}}>重置</button>
      <span className="status-pill">{corners.length} / 4 点</span>
    </div>
    {info && <p className="subtle" role="status">{info}</p>}
  </Panel>;
}

function AnalysisResult({job, result, onCoach}) {
  const {summary, notes} = result;
  const mode = summary.mode || job.mode || 'fingering';
  const isFingering = mode === 'fingering';
  const isAudio = mode === 'audio';
  const [overlay, setOverlay] = useState(true);
  const [filter, setFilter] = useState('all');
  const [page, setPage] = useState(0);
  const player = useRef();
  const pendingSeek = useRef(null);
  const filtered = notes.filter(n => filter === 'all' || n.status === filter);
  const comparison = summary.comparison;
  const files = [['analysis_summary.json','摘要 JSON']];
  if (isAudio) {
    files.push(['transcribed.mid','转录 MIDI'], ['notes.csv','转录音符 CSV']);
    if (comparison) files.push(['comparison.csv','对齐明细 CSV']);
  } else {
    files.push(['aligned_landmarks.jsonl','关键点 JSONL']);
    if (isFingering) files.push(['fingering_predictions.csv','指法 CSV'], ['mapping.json','键盘标定 JSON']);
  }

  function noteTime(note) {
    return Number(note.start_seconds) + (summary.offset_seconds || 0);
  }
  function jump(index) {
    const video = player.current;
    video.currentTime = Math.max(0, index - .2);
    video.scrollIntoView({behavior:'smooth', block:'center'});
    video.play().catch(() => {});
  }

  return <Panel title={modes[mode] + '结果'} action={<span className="status-pill">{job.id.slice(0,8)}</span>}>
    {isFingering && <>
      <Stats items={[[ '音符事件',summary.notes],['有候选',summary.status_counts.matched],['无法确定',summary.status_counts.uncertain],['未匹配',summary.status_counts.unmatched]]}/>
      <p className="subtle">候选覆盖率 {(summary.coverage * 100).toFixed(1)}%。几何支持度用于筛选候选，准确率需另用人工标签测量。</p>
    </>}
    {mode === 'skeleton_only' && <Stats items={[[ '视频帧',summary.frames],['检测帧',summary.sampled_frames],['检出手部的帧',summary.frames_with_hands]]}/>}
    {isAudio && <>
      <Stats items={[[ '转录音符',summary.notes],['视频时长',stamp(summary.video_duration_seconds)]]}/>
      {comparison && <>
        <p className="subtle">以下仅统计找到的局部对齐片段。差异可能来自转录或对齐误差。</p>
        <Stats items={[[ '匹配音高',comparison.correct],['音高差异',comparison.wrong_pitch],['缺少候选',comparison.missed],['额外候选',comparison.extra]]}/>
      </>}
      {summary.comparison_status === 'insufficient' && <p className="validation">参考与转录的对齐证据不足，请核对曲目和音轨，暂不显示差异统计。</p>}
      {summary.comparison_status === 'too_large' && <p className="validation">音符数量超出本地对齐上限。转录文件可继续下载。</p>}
    </>}
    <div className="workflow-actions result-toolbar">
      {!isAudio && <label className="workflow-check"><input type="checkbox" checked={overlay} onChange={e => {pendingSeek.current = player.current?.currentTime; setOverlay(e.target.checked);}}/>骨架叠加</label>}
      <button className="primary" onClick={() => onCoach(job, result, player.current?.currentTime || 0)}>在 AI 教练中打开 <ArrowRight/></button>
    </div>
    <video ref={player} className="workflow-video" controls preload="metadata" src={overlay ? result.replay : videoUrl(job)}
      onLoadedMetadata={e => {
        if (pendingSeek.current !== null) {
          e.currentTarget.currentTime = pendingSeek.current;
          pendingSeek.current = null;
        }
      }}/>
    {isFingering && <>
      {overlay && summary.algorithm_version === 'key-region-v1' &&
        <p className="subtle">黄色轮廓是目标琴键，白圈标出待核对的指尖。</p>}
      <div className="workflow-actions table-controls">
        <select aria-label="筛选识别状态" value={filter} onChange={e => {setFilter(e.target.value); setPage(0);}}>
          <option value="all">全部音符</option>
          {Object.entries(statuses).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <button className="text-button" disabled={page === 0} onClick={() => setPage(page - 1)}>上一页</button>
        <span>{page + 1} / {Math.max(1, Math.ceil(filtered.length / 30))}</span>
        <button className="text-button" disabled={(page + 1) * 30 >= filtered.length} onClick={() => setPage(page + 1)}>下一页</button>
      </div>
      <div className="table-wrap"><table><thead><tr>{['音符','视频时间','手','指','支持度','状态','原因','定位'].map(x => <th key={x}>{x}</th>)}</tr></thead>
        <tbody>{filtered.slice(page * 30, page * 30 + 30).map(n => <tr key={n.note_index}>
          <td>{n.note_name}</td><td>{n.start_frame !== '' ? stamp(noteTime(n)) : '—'}</td><td>{{left:'左',right:'右'}[n.hand] || '—'}</td>
          <td>{n.finger || '—'}</td><td>{n.confidence}</td><td>{statuses[n.status]}</td>
          <td>{fingeringReasons[n.reason] || '—'}</td>
          <td><button className="text-button" disabled={n.start_frame === '' || noteTime(n) < 0 || noteTime(n) >= summary.video_duration_seconds} onClick={() => jump(noteTime(n))}><Play/>回放</button></td>
        </tr>)}</tbody>
      </table></div>
    </>}
    <div className="workflow-actions download-row">
      {files.map(([file,label]) => <a key={file} className="text-button" href={'/api/jobs/' + job.id + '/' + file} download><DownloadSimple/>{label}</a>)}
    </div>
  </Panel>;
}

export function AnalysisWorkspace({initialVideo, onInitialUpload, initialReference, onCoach}) {
  const [video,setVideo] = useState(null);
  const [midi,setMidi] = useState(null);
  const [reference,setReference] = useState(initialReference || null);
  const [mode,setMode] = useState(initialReference ? 'audio' : 'skeleton_only');
  const [corners,setCorners] = useState([]);
  const [frame,setFrame] = useState(0);
  const [ready,setReady] = useState(false);
  const [low,setLow] = useState('21');
  const [high,setHigh] = useState('108');
  const [offset,setOffset] = useState('0');
  const [mirrored,setMirrored] = useState(false);
  const [confirm,setConfirm] = useState(false);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const [job,setJob] = useState(null);
  const [result,setResult] = useState(null);
  const [history,setHistory] = useState([]);
  const jobRequest = useRef(0);
  const initialUpload = useRef(null);
  const historyPanel = useRef(null);
  const running = ['queued','running'].includes(job?.status);

  function refresh() {
    return api('/jobs').then(setHistory).catch(e => setError(e.message));
  }
  useEffect(() => {refresh();}, []);
  useEffect(() => {
    if (initialVideo && initialUpload.current !== initialVideo) {
      initialUpload.current = initialVideo;
      upload('video', initialVideo).finally(onInitialUpload);
    }
  }, [initialVideo]);
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
        if (current.status === 'failed') setError(current.error || '任务失败');
        if (!['queued','running'].includes(current.status)) {refresh(); return;}
      } catch (e) {
        if (live) setError(e.message);
      }
      if (live) timer = setTimeout(poll, 1200);
    }
    timer = setTimeout(poll, 900);
    return () => {live = false; clearTimeout(timer);};
  }, [job?.id, running]);

  async function upload(kind, file) {
    if (!file) return;
    setBusy(true);
    setError('');
    try {
      const asset = await uploadAsset(kind === 'video' ? 'video' : 'midi', file);
      if (kind === 'video') {
        setVideo(asset); setCorners([]); setFrame(0); setReady(false);
      } else if (kind === 'midi') setMidi(asset);
      else setReference(asset);
      setConfirm(false);
    } catch (e) {setError(e.message);}
    finally {setBusy(false);}
  }

  async function submit() {
    ++jobRequest.current;
    setBusy(true); setError(''); setResult(null);
    try {
      setJob(await post('/jobs', {
        mode, video_id: video.id, midi_id: midi?.id, reference_id: reference?.id, corners,
        offset: Number(offset), first: Number(low), last: Number(high), mirrored,
        calibration_time: frame, confirm_duration: confirm,
      }));
      refresh();
    } catch (e) {setError(e.message);}
    finally {setBusy(false);}
  }

  async function restore(current) {
    const request = ++jobRequest.current;
    setResult(null); setJob(current); setError(current.error || '');
    if (current.status !== 'succeeded') return;
    try {
      const data = await api('/jobs/' + current.id + '/result');
      if (request === jobRequest.current) setResult(data);
    } catch (e) {
      if (request === jobRequest.current) setError(e.message);
    }
  }

  const calibrated = midi && ready && corners.length === 4 && offset !== '' && low !== '' && high !== '';
  return <div className="workflow-stack">
    <div className="analysis-grid">
      <Panel title="新建分析" action={<button className="text-button" onClick={() => historyPanel.current?.scrollIntoView({behavior:'smooth'})}>历史演奏</button>}>
        <label className="upload-tile">
          <UploadSimple size={27}/>
          <span><strong>{video?.name || '选择演奏视频'}</strong>
            <small>{video ? stamp(video.duration) + ' · ' + video.width + ' × ' + video.height : '推荐固定机位俯拍，上传带声音的 MP4'}</small></span>
          <input aria-label="演奏视频" type="file" accept="video/*" disabled={busy} onChange={e => upload('video', e.target.files[0])}/>
        </label>
        <div className="mode-options" aria-label="分析方式">
          {modeOptions.map(([value,Icon,description]) => <button key={value} type="button" aria-pressed={mode === value} onClick={() => setMode(value)}>
            <Icon size={23}/><strong>{modes[value]}</strong><small>{description}</small>
          </button>)}
        </div>
        {mode === 'fingering' && <div className="workflow-fields">
          <label>同一次演奏的 MIDI<input type="file" accept=".mid,.midi" disabled={busy} onChange={e => upload('midi', e.target.files[0])}/></label>
          {midi && <p className="subtle">{midi.name} · {midi.notes} 音符 · {stamp(midi.duration)} · 音域 {midi.minimum}–{midi.maximum}</p>}
          <label>对齐偏移（加到 MIDI 时间，秒）<input type="number" min="-120" max="120" step=".05" value={offset} onChange={e => setOffset(e.target.value)}/></label>
          <label className="workflow-check"><input type="checkbox" checked={confirm} onChange={e => setConfirm(e.target.checked)}/>我已核对视频和 MIDI，可接受较大的时长差</label>
        </div>}
        {mode === 'audio' && <div className="workflow-fields">
          <label>参考乐谱 MIDI（可选）<input type="file" accept=".mid,.midi" disabled={busy} onChange={e => upload('reference', e.target.files[0])}/></label>
          {reference && <div className="workflow-inline"><span>{reference.name}</span><button className="text-button" onClick={() => setReference(null)}>移除参考</button></div>}
        </div>}
        {mode !== 'audio' && <label className="workflow-check"><input type="checkbox" checked={mirrored} onChange={e => setMirrored(e.target.checked)}/>视频已水平镜像</label>}
        <button className="primary wide" disabled={busy || !video || (mode === 'fingering' && !calibrated)} onClick={submit}>{busy ? '处理中…' : '提交' + modes[mode] + '任务'}<ArrowRight/></button>
        <ErrorText error={error}/>
      </Panel>
      {mode === 'fingering' && video
        ? <Calibration key={video.id} {...{video,frame,setFrame,corners,setCorners,ready,setReady,low,high,setLow,setHigh}}/>
        : <Panel title="当前任务与回放" action={<span className="status-pill">{job ? jobStates[job.status] : '待提交'}</span>}>
          {video ? <video className="workflow-video" controls preload="metadata" src={'/api/assets/' + video.id + '/video'}/>
            : <div className="workflow-empty"><MusicNotes size={32}/><p>上传视频后可预览原片。</p></div>}
          {job && <p role="status" className="subtle">任务 {job.id.slice(0,8)} · {job.stage}</p>}
        </Panel>}
    </div>
    {mode === 'fingering' && job && <div className="evidence-banner" role="status">{jobStates[job.status]} · {job.stage}</div>}
    {result && job && <AnalysisResult key={job.id} {...{result,job,onCoach}}/>}
    <div ref={historyPanel}><Panel title="历史演奏" action={<button className="text-button" onClick={refresh}>刷新</button>}>
      {history.length ? <div className="workflow-list">{history.map(item => <button key={item.id} onClick={() => restore(item)} className="workflow-row">
        <span><strong>{item.title || '历史演奏'}</strong><small>{modes[item.mode || 'fingering']} · {item.created_at ? new Date(item.created_at).toLocaleDateString('zh-CN') + ' · ' : ''}{item.id.slice(0,8)}</small></span>
        <span className="status-pill">{jobStates[item.status]}</span><ArrowRight/>
      </button>)}</div> : <p className="subtle">提交后可在这里重新打开结果。</p>}
    </Panel></div>
  </div>;
}
