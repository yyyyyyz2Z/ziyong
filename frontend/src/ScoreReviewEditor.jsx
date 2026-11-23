import React, {useState} from 'react';
import {ErrorText, post, stamp, uploadAsset} from './workspace-ui';

export const reviewLabels = {
  unreviewed: '待人工复核',
  confirmed: '人工确认',
  misaligned: '对齐偏了',
  variant: '装饰音或版本差异',
  unclear: '看不清或听不清',
};

export function ScoreReferenceEditor({jobId, report, onSaved}) {
  const [asset, setAsset] = useState(null);
  const [first, setFirst] = useState(1);
  const [last, setLast] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  async function upload(file) {
    if (!file) return;
    setAsset(null); setBusy(true); setError(''); setNotice('');
    try {
      const score = await uploadAsset('score', file);
      setAsset(score); setFirst(1); setLast(score.measures.length);
    } catch (failure) {setError(failure.message);}
    finally {setBusy(false);}
  }

  async function submit(event) {
    event.preventDefault();
    if (!asset || busy || first > last) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await post('/jobs/' + jobId + '/score-reference', {
        score_id: asset.id, measure_first: first, measure_last: last, revision: report?.revision || 0,
      });
      onSaved(result);
      setNotice(result.status === 'aligned' ? '曲目对齐已更新。' : '已保存乐谱，请复核选段和 MIDI。');
    } catch (failure) {setError(failure.message);}
    finally {setBusy(false);}
  }

  return <details className="technique-evidence score-reference-editor">
    <summary>{report ? '更换或补传乐谱' : '补传乐谱，生成曲目对齐'}</summary>
    <p>复用这条演奏的同期 MIDI、指法和回放。更换谱面或小节范围时，旧复核记录会随旧版对齐存档。</p>
    <form onSubmit={submit}>
      <label>MusicXML 乐谱<input type="file" accept=".musicxml,.xml,.mxl" disabled={busy}
        onChange={event => upload(event.target.files[0])}/></label>
      {asset && <>
        <p>{asset.name}</p>
        <div className="time-inputs">
          <label>起始小节<select value={first} onChange={event => setFirst(Number(event.target.value))}>
            {asset.measures.map(item => <option key={item.position} value={item.position}>{item.label}</option>)}
          </select></label>
          <label>结束小节<select value={last} onChange={event => setLast(Number(event.target.value))}>
            {asset.measures.map(item => <option key={item.position} value={item.position}>{item.label}</option>)}
          </select></label>
        </div>
        <button type="submit" className="glass-button" disabled={busy || first > last}>用已有演奏生成对齐</button>
      </>}
      {busy && <p role="status">正在处理乐谱…</p>}
      {notice && <p role="status">{notice}</p>}
      <ErrorText error={error || (first > last ? '结束小节须等于或晚于起始小节。' : '')}/>
    </form>
  </details>;
}

export function ScoreReviewEditor({row, notes, report, offset, onSave, onCancel}) {
  const [verdict, setVerdict] = useState(row.manual_review || 'unreviewed');
  const [manual, setManual] = useState(row.reference_finger_source === 'manual');
  const [fingers, setFingers] = useState(row.reference_fingers || []);
  const [pairing, setPairing] = useState('keep');
  const [actual, setActual] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const assigned = new Set(report.rows.filter(item => item.score_note_id).map(item => item.performance_id));
  const eligible = notes.filter(note => !assigned.has(note.note_index) && note.start_frame !== '' && note.start_frame != null)
    .map(note => ({...note, time: Number(note.start_seconds) + offset}))
    .sort((a, b) => Math.abs(a.time - row.time) - Math.abs(b.time - row.time));
  const canSave = !busy && (!manual || fingers.length) && (pairing !== 'replace' || actual);

  async function submit(event) {
    event.preventDefault();
    if (!canSave) return;
    const edit = {row_id: row.id, verdict};
    if (row.score_note_id) edit.fingers = manual ? fingers : null;
    if (pairing === 'replace') edit.performance_id = actual;
    if (pairing === 'missing') edit.performance_id = null;
    if (pairing === 'restore') edit.restore_pairing = true;
    setBusy(true); setError('');
    try {await onSave(edit);}
    catch (failure) {setError(failure.message);}
    finally {setBusy(false);}
  }

  return <form className="score-review-form" onSubmit={submit}>
    <p><strong>{row.expected_note || row.played_note} · {stamp(row.time)}</strong></p>
    <div className="time-inputs">
      <label>复核结论<select value={verdict} disabled={pairing !== 'keep' || busy} onChange={event => setVerdict(event.target.value)}>
        {Object.entries(reviewLabels).map(([id, title]) => <option key={id} value={id}>{title}</option>)}
      </select></label>
      {!!row.score_note_id && <label>实际音对应<select value={pairing} disabled={busy} onChange={event => setPairing(event.target.value)}>
        <option value="keep">保留当前对应</option>
        <option value="replace">选择其他实际音</option>
        <option value="missing">确认该谱音漏弹</option>
        {row.pairing_overridden && <option value="restore">恢复自动对应</option>}
      </select></label>}
    </div>
    {pairing === 'replace' && <label>实际音符（未与其他谱音对应）<select value={actual} onChange={event => setActual(event.target.value)}>
      <option value="">选择实际音符</option>
      {eligible.map(note => <option key={note.note_index} value={note.note_index}>{note.note_name} · {stamp(note.time)}</option>)}
    </select></label>}
    {!!row.score_note_id && <>
      <label className="workflow-check"><input type="checkbox" checked={manual} onChange={event => setManual(event.target.checked)}/>手动设置参考指法</label>
      {manual && <fieldset className="review-finger-options">
        <legend>参考手指，可选多个备选</legend>
        {[1, 2, 3, 4, 5].map(finger => <label key={finger} className="workflow-check">
          <input type="checkbox" checked={fingers.includes(finger)} onChange={event => setFingers(event.target.checked
            ? [...fingers, finger].sort() : fingers.filter(value => value !== finger))}/>{finger} 指
        </label>)}
      </fieldset>}
    </>}
    <div className="workflow-actions">
      <button type="submit" className="glass-button" disabled={!canSave}>{busy ? '保存中…' : '保存复核'}</button>
      <button type="button" className="text-button" disabled={busy} onClick={onCancel}>取消</button>
    </div>
    <ErrorText error={error}/>
  </form>;
}
