import React from 'react';
import {ChatCircleText, Play} from '@phosphor-icons/react';
import {stamp} from './workspace-ui';

export function GraphRules({rules, references = []}) {
  const byId = new Map(references.map(reference => [reference.id, reference]));
  return <div className="graph-rules">
    {rules.map(rule => <details key={rule.id}>
      <summary>{rule.label}</summary>
      {rule.logic && <p>{rule.logic}</p>}
      {rule.metrics?.some(metric => typeof metric === 'object') && <dl>
        {rule.metrics.map(metric => <React.Fragment key={metric.id}>
          <dt>{metric.label}</dt><dd>{metric.definition}</dd>
        </React.Fragment>)}
      </dl>}
      {rule.advice?.map(advice => <p key={advice}>{advice}</p>)}
      {rule.reference_ids?.map(id => {
        const source = byId.get(id);
        return source && <div className="graph-source" key={id}>
          <a href={source.url} target="_blank" rel="noreferrer">{source.title}</a>
          {source.limit && <p>{source.limit}</p>}
        </div>;
      })}
    </details>)}
  </div>;
}

function MotionEvidence({attempt, target}) {
  const motion = attempt.motion || attempt.thumb;
  const finger = attempt.expected_fingers[1] === 1 ? '拇指' : '中指';
  const angle = motion.joint_angle_2d_deg ?? motion.thumb_ip_angle_2d_deg;
  if (motion.status === 'fingering_unconfirmed') return <p>换指与参考指法的一致性待复核，暂不估计准备动作。</p>;
  if (motion.status === 'insufficient_landmarks') return <p>可跟踪 {motion.usable_frames}/{motion.expected_frames} 帧，动作证据不足。</p>;
  if (motion.status === 'outside_selection') return <p>当前选区内没有对应的指尖测量。</p>;
  return <p>
    {stamp(motion.sample_seconds)}时，{finger}尖横向距 {target} 中心 {motion.distance_white_keys} 个白键宽度
    {angle != null ? '，图像中的关节投影夹角 ' + angle + '°' : ''}。
    {motion.preparation_estimate_ms != null
      ? '估计提前 ' + motion.preparation_estimate_ms + ' 毫秒开始向目标键移动。'
      : motion.preparation_before_selection ? '准备动作早于当前选区。' : '准备动作起点待复核。'}
  </p>;
}

export function TechniqueEvidence({attempts, taskLabel, repeatability, rules, references, total, onPlay, onAsk}) {
  return <details className="technique-evidence">
    <summary>{taskLabel || '基础音阶'} · 换指证据 · {total ?? attempts.length} 遍</summary>
    {!attempts.length && <p>没有在同期 MIDI 中找到该练习完整、连续的八个音。请核对音高、方向和练习选项。</p>}
    {!!attempts.length && <p>换指间隔以同遍其余音符的间隔中位数为基准。</p>}
    {repeatability && <p>
      {repeatability.count} 遍的间隔比例中位数为 {repeatability.median_ratio} 倍，
      中位绝对偏差 {repeatability.ratio_mad}。各遍基准间隔 {repeatability.baseline_range_ms.join('–')} 毫秒。
    </p>}
    {!!total && total > attempts.length && <p>显示并发送前 {attempts.length} 遍。</p>}
    <div className="workflow-list">
      {attempts.map(attempt => {
        const names = attempt.note_names || ['E4', 'F4'];
        return <article className="technique-attempt" key={attempt.note_ids.join('-')}>
          <div className="workflow-actions">
            <button type="button" className="segment-reference" onClick={() => onPlay(attempt.start, attempt.end)}>
              <Play/>{names.join(' → ')} · {stamp(attempt.start)}–{stamp(attempt.end)}
            </button>
            {onAsk && <button type="button" className="text-button" onClick={() => onAsk(attempt.start, attempt.end)}>
              <ChatCircleText/>问这个换指
            </button>}
          </div>
          <p>打键间隔 {attempt.interval_ms} 毫秒，同遍基准 {attempt.baseline_ms} 毫秒（{attempt.ratio} 倍）。</p>
          <p>参考指法 {attempt.expected_fingers.join(' → ')}。观察候选 {attempt.fingers.map(finger => finger ?? '未知').join(' → ')}。</p>
          <MotionEvidence attempt={attempt} target={names[1]}/>
        </article>;
      })}
    </div>
    {rules?.length > 0 && <GraphRules rules={rules} references={references}/>}
  </details>;
}
