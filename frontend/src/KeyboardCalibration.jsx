import React, {useEffect, useRef, useState} from 'react';
import {ErrorText, Panel, stamp} from './workspace-ui';

const angleError = '当前拍摄角度不适合识别琴键。请从正上方固定拍摄，完整拍到键盘两端，并尽量减少遮挡。';

export function KeyboardCalibration({video, mirrored, keyboard, onKeyboard}) {
  const [phase, setPhase] = useState('auto');
  const [retry, setRetry] = useState(0);
  const [progress, setProgress] = useState('');
  const [error, setError] = useState('');
  const [frame, setFrame] = useState(0);
  const [draft, setDraft] = useState('0');
  const [corners, setCorners] = useState([]);
  const [ready, setReady] = useState(false);
  const request = useRef(null);
  const max = Math.max(0, video.duration - 1 / video.fps);
  const busy = phase === 'auto' || phase === 'crop';
  const manual = phase === 'manual' || phase === 'crop';
  const selectedTime = keyboard?.time ?? frame;
  const image = '/api/assets/' + video.id + '/frame?time=' + selectedTime;

  useEffect(() => {
    if (keyboard) return;
    const controller = new AbortController();
    request.current = controller;
    setPhase('auto');
    setError('');
    async function recognize() {
      const {locateKeyboard, sampleTimes} = await import('./pianocv/keyboard');
      const times = sampleTimes(video);
      for (const [index, time] of times.entries()) {
        controller.signal.throwIfAborted();
        setProgress('正在自动识别键盘画面 ' + (index + 1) + ' / ' + times.length);
        const result = await locateKeyboard(video, time, mirrored, null, controller.signal);
        controller.signal.throwIfAborted();
        if (result) {
          onKeyboard(result);
          setPhase('done');
          return;
        }
      }
      setFrame(times[0]);
      setDraft(String(times[0]));
      setPhase('manual');
    }
    recognize().catch(() => {
      if (!controller.signal.aborted) {
        setError('自动识别服务未能读取画面或加载模型，请重试。');
        setPhase('error');
      }
    });
    return () => request.current?.abort();
  }, [video, mirrored, retry]);

  async function recognizeCrop() {
    const controller = new AbortController();
    request.current = controller;
    setError('');
    setPhase('crop');
    try {
      const {locateKeyboard} = await import('./pianocv/keyboard');
      const result = await locateKeyboard(video, frame, mirrored, corners, controller.signal);
      controller.signal.throwIfAborted();
      if (result) {
        onKeyboard(result);
        setPhase('done');
      } else {
        setError(angleError);
        setPhase('manual');
      }
    } catch (failure) {
      if (!controller.signal.aborted) {
        setError(failure.message.startsWith('请按顺序') ? failure.message : '读取画面或加载模型失败，请重试。');
        setPhase('manual');
      }
    }
  }

  function changeFrame(event) {
    event.preventDefault();
    if (frame === Number(draft)) return;
    setFrame(Number(draft));
    setReady(false);
    setCorners([]);
    setError('');
  }

  function addCorner(event) {
    if (!manual || busy || !ready || corners.length === 4) return;
    const box = event.currentTarget.getBoundingClientRect();
    setCorners([...corners, [
      (event.clientX - box.left) / box.width * video.width,
      (event.clientY - box.top) / box.height * video.height,
    ]]);
  }

  return <Panel title="键盘识别" className="calibration-panel"
    action={<span className="status-pill">{keyboard ? '88 键已识别' : busy ? '识别中' : manual ? '需框选' : '待重试'}</span>}>
    {phase === 'auto' && !keyboard && <p className="keyboard-instructions" role="status">{progress || '正在加载 pianoCV 模型…'}</p>}
    {phase === 'error' && <button type="button" className="glass-button" onClick={() => setRetry(value => value + 1)}>重试自动识别</button>}
    {keyboard && <p className="keyboard-instructions" role="status">
      {keyboard.source === 'pianocv_crop' ? '已从框选区域识别' : '已自动识别'}琴键位置（A0–C8）。画面取自 {stamp(keyboard.time)}。
    </p>}
    {manual && <React.Fragment>
      <p className="keyboard-instructions">自动识别未找到完整键盘。请在清楚的画面上依次点击键床左上、右上、右下、左下。</p>
      <form className="workflow-inline" onSubmit={changeFrame}>
        <label>画面时间（秒）<input type="number" min="0" max={max} step="any" value={draft}
          disabled={busy} onChange={event => setDraft(event.target.value)}/></label>
        <button className="glass-button" disabled={busy || draft === '' || !(Number(draft) >= 0 && Number(draft) <= max)}>加载画面</button>
      </form>
    </React.Fragment>}
    {(manual || keyboard) && <div className={'calibration-image' + (manual ? ' picking' : '')}>
      <img src={image} alt={'视频键盘画面，' + stamp(selectedTime)} onClick={addCorner}
        onLoad={() => setReady(true)} onError={() => {setReady(false); setError('读取画面失败，请换一个时间点。');}}/>
      <svg aria-hidden="true" viewBox={`0 0 ${video.width} ${video.height}`}>
        {keyboard && keyboard.keys.map(key => <polygon key={key.midi_pitch} points={key.outline.map(point => point.join(',')).join(' ')}
          fill="#9ee9d02c" stroke="#a5f4db" strokeWidth={Math.max(1, video.width / 900)}/>)}
        {manual && corners.length > 0 && <polyline points={(corners.length === 4 ? [...corners, corners[0]] : corners).map(point => point.join(',')).join(' ')}
          fill="none" stroke="#a5f4db" strokeWidth={video.width / 400}/>}
        {manual && corners.map(([x, y], index) => <circle key={index} cx={x} cy={y} r={video.width / 200} fill="#b58aff"/>)}
      </svg>
    </div>}
    {manual && <div className="workflow-actions calibration-actions">
      <button type="button" className="glass-button" disabled={busy || !ready || corners.length !== 4}
        onClick={recognizeCrop}>{busy ? '正在识别框内琴键…' : '识别框内琴键'}</button>
      <button type="button" className="text-button" disabled={busy || !corners.length}
        onClick={() => {setCorners(corners.slice(0, -1)); setError('');}}>撤销一点</button>
      <span className="status-pill">{corners.length} / 4 点</span>
    </div>}
    <ErrorText error={error}/>
  </Panel>;
}
