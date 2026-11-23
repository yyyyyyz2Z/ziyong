import React, {useState} from 'react';
import {ChatCircleText, Play} from '@phosphor-icons/react';
import {GraphRules} from './TechniqueEvidence';
import {ScoreReviewEditor, reviewLabels} from './ScoreReviewEditor';
import {stamp} from './workspace-ui';

const labels = {
  score_linked: '谱面关联',
  matched_pitch: '音高匹配',
  pitch_candidate: '疑似音高差异',
  missing_candidate: '疑似漏音',
  extra_candidate: '疑似多弹',
  pitch_confirmed: '已确认音高差异',
  missing_confirmed: '已确认漏音',
  extra_confirmed: '已确认多弹',
  review: '待复核',
};

export function ScoreEvidence({report, references, onPlay, onAsk, duration, notes = [], offset = 0, onReview}) {
  const [measure, setMeasure] = useState('');
  const [onlyReview, setOnlyReview] = useState(false);
  const [page, setPage] = useState(0);
  const [editId, setEditId] = useState(null);
  const [notice, setNotice] = useState('');
  const rows = (report.rows || []).filter(row => (!measure || String(row.measure) === measure)
    && (!onlyReview || !['matched_pitch', 'score_linked'].includes(row.status) || row.fingering_difference));
  const count = Math.max(1, Math.ceil(rows.length / 28));
  const displayedPage = Math.min(page, count - 1);
  const measureInfo = report.measures?.find(item => String(item.position) === measure);

  return <details className="technique-evidence score-evidence" open={onAsk ? true : undefined}>
    <summary>乐谱与演奏 · {report.title}</summary>
    {report.status === 'too_long' && <p>演奏 MIDI 超过 1000 个音符。请截取与视频和谱面对应的短片段重试。</p>}
    {report.status === 'insufficient' && <p>对齐证据不足。请核对乐谱版本、小节范围和同期 MIDI。</p>}
    {report.status === 'aligned' && <>
      <p>{report.measures?.length > 0 && <>第 {report.measures[0]?.label}–{report.measures.at(-1)?.label} 小节 · </>}
        {Object.entries(labels).filter(([key]) => report.counts[key]).map(([key, label]) =>
          label + ' ' + report.counts[key]).join(' · ')}
      </p>
      {report.reference_coverage != null && <p>自动对齐的谱面音高匹配覆盖 {(report.reference_coverage * 100).toFixed(1)}%，
        实际演奏音高匹配覆盖 {(report.played_coverage * 100).toFixed(1)}%。起音偏差以拟合的局部速度为基准。</p>}
      {!!report.ornament_measures?.length && <p>谱面含装饰音的小节 {report.measures
        .filter(item => report.ornament_measures.includes(item.position)).map(item => item.label).join('、')}，未配对音符供回看。</p>}
      {report.total > report.rows.length && <p>展示并发送片段内 {report.rows.length} 条记录，优先包含人工复核，共 {report.total} 条。</p>}
      {notice && <p role="status">{notice}</p>}
      {report.measures && <div className="workflow-actions table-controls">
        <select aria-label="定位谱面小节" value={measure} onChange={event => {setMeasure(event.target.value); setPage(0);}}>
          <option value="">全部小节</option>
          {report.measures.map(item => <option key={item.position} value={item.position}>第 {item.label} 小节</option>)}
        </select>
        <label className="workflow-check"><input type="checkbox" checked={onlyReview} onChange={event => {
          setOnlyReview(event.target.checked); setPage(0);
        }}/>只看差异与待复核</label>
        {measureInfo?.bpm != null && <span>该小节估计 {measureInfo.bpm} 个四分音符/分钟</span>}
      </div>}
      <div className="table-wrap"><table>
        <thead><tr>{['谱面位置', '谱音', '实际音', '视频时间', '起音偏差', '指法候选 / 参考', '对齐结果', '操作'].map(label =>
          <th key={label} scope="col">{label}</th>)}</tr></thead>
        <tbody>{rows.slice(displayedPage * 28, (displayedPage + 1) * 28).map(row => {
          const playable = row.time >= 0 && row.time < duration;
          return <React.Fragment key={row.id}><tr>
            <td>{row.measure_label != null ? '第 ' + row.measure_label + ' 小节' : '待定位'}
              {row.beat != null && <> · {Number(row.beat.toFixed(2))} 拍</>}</td>
            <td>{row.expected_note || '—'}</td><td>{row.played_note || '—'}</td>
            <td>{playable ? stamp(row.time) : '—'}{playable && !row.performance_id && '（估计）'}</td>
            <td>{row.timing_delta_ms != null ? row.timing_delta_ms + ' ms' : '—'}</td>
            <td>{row.finger || '—'} / {row.reference_fingers?.join('、') || '—'}
              {row.reference_finger_source === 'manual' && '（人工）'}</td>
            <td>{labels[row.status]}{row.fingering_difference && ' · 指法候选有差异'}
              {row.manual_review && !row.status.endsWith('_confirmed') && ' · ' + reviewLabels[row.manual_review]}</td>
            <td><div className="workflow-actions">
              <button type="button" className="text-button" disabled={!playable} onClick={() => onPlay(row.time)}><Play/>回放</button>
              {onAsk && <button type="button" className="text-button" disabled={!playable} onClick={() => onAsk(row.time, row.performance_id)}><ChatCircleText/>问 AI</button>}
              {onReview && <button type="button" className="text-button" aria-expanded={editId === row.id}
                onClick={() => {setEditId(editId === row.id ? null : row.id); setNotice('');}}>复核</button>}
            </div></td>
          </tr>
          {editId === row.id && <tr><td colSpan={8}>
            <ScoreReviewEditor row={row} notes={notes} report={report} offset={offset} onCancel={() => setEditId(null)}
              onSave={async edit => {
                await onReview(edit, report.revision || 0);
                setEditId(null);
                setNotice('复核已保存。下次向 AI 提问时会使用当前结果。');
              }}/>
          </td></tr>}
          </React.Fragment>;
        })}</tbody>
      </table></div>
      {!rows.length && <p>当前筛选没有记录。</p>}
      {count > 1 && <div className="workflow-actions table-controls">
        <button type="button" className="text-button" disabled={!displayedPage} onClick={() => setPage(displayedPage - 1)}>上一页</button>
        <span>{displayedPage + 1} / {count}</span>
        <button type="button" className="text-button" disabled={displayedPage + 1 >= count} onClick={() => setPage(displayedPage + 1)}>下一页</button>
      </div>}
    </>}
    {!!report.rules?.length && <GraphRules rules={report.rules} references={references}/>}
  </details>;
}
