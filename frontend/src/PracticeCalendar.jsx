import React, {useEffect, useRef, useState} from 'react';
import {CalendarDots, CaretLeft, CaretRight, CheckCircle, DownloadSimple, Plus, Play} from '@phosphor-icons/react';
import {api, post, Panel, stamp, ErrorText} from './workspace-ui';

const weekdays = ['一','二','三','四','五','六','日'];
const frequencies = [[0], [1,4], [0,2,4], [0,2,4,6], [0,1,2,3,4], [0,1,2,3,4,5], [0,1,2,3,4,5,6]];
const dateKey = date => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
function parseDate(value) {
  const [year,month,day] = value.split('-').map(Number);
  return new Date(year,month - 1,day);
}
const weekdayIndex = date => (date.getDay() + 6) % 7;
const describeDays = days => days?.length ? days.map(day => '周' + weekdays[day]).join('、') : '每个练习日';

function DayChoices({value, onChange, disabled, label = '练习星期（留空则跟随每周安排）'}) {
  return <fieldset className="practice-weekdays" disabled={disabled}><legend>{label}</legend><div>
    {weekdays.map((day,index) => <button key={day} type="button" aria-pressed={value.includes(index)}
      className={value.includes(index) ? 'selected' : ''} onClick={() => onChange(value.includes(index)
        ? value.filter(item => item !== index) : [...value,index].sort())}>周{day}</button>)}
  </div></fieldset>;
}

function PracticeSuggestions({draft, busy, onConfirm}) {
  const [items,setItems] = useState(() => draft.items.map(item => ({...item, weekdays:[], selected:true, editing:false})));
  const update = (index, changes) => setItems(values => values.map((item,position) => position === index ? {...item,...changes} : item));
  const selected = items.filter(item => item.selected);
  return <Panel title="AI 建议 · 待你确认" className="practice-suggestions-panel">
    <p className="subtle">根据全曲评价生成。勾选要采用的项目，可以编辑目标和练习星期，确认后会显示在日历。</p>
    <div className="practice-suggestion-list">{items.map((item,index) => <article className="practice-suggestion-item" key={index}>
      <label className="practice-task-check"><input type="checkbox" checked={item.selected} disabled={busy}
        onChange={event => update(index, {selected:event.target.checked})}/><strong>{item.title || '练习项目'}</strong></label>
      {item.editing ? <div className="practice-suggestion-edit">
        <label>练习名称<input maxLength={120} value={item.title} disabled={busy} onChange={event => update(index,{title:event.target.value})}/></label>
        <label>练习目标<textarea maxLength={1200} value={item.detail} disabled={busy} onChange={event => update(index,{detail:event.target.value})}/></label>
        <DayChoices value={item.weekdays} disabled={busy} onChange={days => update(index,{weekdays:days})}/>
      </div> : <><p>{item.detail}</p><small>{describeDays(item.weekdays)}</small></>}
      <button className="text-button" disabled={busy} onClick={() => update(index,{editing:!item.editing})}>{item.editing ? '完成编辑' : '编辑建议'}</button>
    </article>)}</div>
    <button className="primary" disabled={busy || !selected.length || selected.some(item => !item.title.trim())}
      onClick={() => onConfirm(draft.id, selected.map(({title,detail,weekdays}) => ({title,detail,weekdays})))}>
      {busy ? '正在保存…' : `确认加入计划（${selected.length} 项）`}
    </button>
  </Panel>;
}

export function PracticePage({onOpenClip, notice, onDismissNotice}) {
  const today = dateKey(new Date());
  const defaultEnd = new Date();
  defaultEnd.setDate(defaultEnd.getDate() + 27);
  const [month,setMonth] = useState(() => new Date(new Date().getFullYear(), new Date().getMonth(), 1));
  const [selected,setSelected] = useState(today);
  const [tasks,setTasks] = useState([]);
  const [checks,setChecks] = useState([]);
  const [schedule,setSchedule] = useState({weekdays:[0,2,4], start_date:today, end_date:dateKey(defaultEnd)});
  const [draftDays,setDraftDays] = useState([0,2,4]);
  const [startDate,setStartDate] = useState(today);
  const [endDate,setEndDate] = useState(dateKey(defaultEnd));
  const [hasSchedule,setHasSchedule] = useState(false);
  const [loading,setLoading] = useState(true);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const [message,setMessage] = useState('');
  const [title,setTitle] = useState('');
  const [detail,setDetail] = useState('');
  const [taskDays,setTaskDays] = useState([]);
  const [drafts,setDrafts] = useState([]);
  const [editing,setEditing] = useState(null);
  const [removing,setRemoving] = useState(null);
  const taskForm = useRef(null);
  useEffect(() => {
    let live = true;
    Promise.all([api('/practice'), api('/practice/calendar'), api('/practice/drafts')]).then(([items,calendar,suggestions]) => {
      if (!live) return;
      setTasks(items); setChecks(calendar.checks);
      setDrafts(suggestions);
      if (calendar.schedule) {
        setSchedule(calendar.schedule); setDraftDays(calendar.schedule.weekdays);
        setStartDate(calendar.schedule.start_date); setHasSchedule(true);
        setEndDate(calendar.schedule.end_date || '');
      }
    }).catch(failure => {if (live) setError(failure.message);})
      .finally(() => {if (live) setLoading(false);});
    return () => {live = false;};
  }, []);

  const completed = new Set(checks.map(check => `${check.practice_date}:${check.task_id}`));
  const isPracticeDay = day => day >= schedule.start_date && (!schedule.end_date || day <= schedule.end_date)
    && schedule.weekdays.includes(weekdayIndex(parseDate(day)));
  const tasksOn = day => tasks.filter(task => completed.has(`${day}:${task.id}`) || (isPracticeDay(day)
    && (!task.weekdays?.length || task.weekdays.includes(weekdayIndex(parseDate(day))))));
  const doneOn = day => tasksOn(day).filter(task => completed.has(`${day}:${task.id}`)).length;
  const firstCell = new Date(month.getFullYear(), month.getMonth(), 1 - weekdayIndex(month));
  const days = Array.from({length:42}, (_,index) => new Date(firstCell.getFullYear(), firstCell.getMonth(), firstCell.getDate() + index));
  const selectedDone = doneOn(selected);
  const selectedTasks = tasksOn(selected);
  const selectedIsPractice = isPracticeDay(selected);
  const dirty = !hasSchedule || startDate !== schedule.start_date || endDate !== (schedule.end_date || '')
    || draftDays.join(',') !== schedule.weekdays.join(',');

  function moveMonth(step) {
    const next = new Date(month.getFullYear(), month.getMonth() + step, 1);
    setMonth(next); setSelected(dateKey(next));
  }
  function selectDay(date) {
    setSelected(dateKey(date)); setMonth(new Date(date.getFullYear(),date.getMonth(),1));
  }
  async function saveSchedule(event) {
    event.preventDefault(); setBusy(true); setError(''); setMessage('');
    try {
      const updated = await post('/practice/schedule', {weekdays:draftDays, start_date:startDate, end_date:endDate || null});
      setSchedule(updated); setHasSchedule(true); setMessage('练习安排已保存，日历已更新。');
    } catch (failure) {setError(failure.message);}
    finally {setBusy(false);}
  }
  async function toggle(task) {
    const day = selected;
    const checked = !completed.has(`${day}:${task.id}`);
    setBusy(true); setError('');
    try {
      const updated = await post('/practice/' + task.id + '/check', {date:day, completed:checked});
      setChecks(values => [...values.filter(check => check.task_id !== task.id || check.practice_date !== day),
        ...(checked ? [updated] : [])]);
    } catch (failure) {setError(failure.message);}
    finally {setBusy(false);}
  }
  async function saveTask(event) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const updated = await post(editing ? '/practice/' + editing + '/edit' : '/practice', {title,detail,weekdays:taskDays});
      setTasks(values => editing ? values.map(task => task.id === editing ? updated : task) : [...values,updated]);
      setEditing(null); setTitle(''); setDetail(''); setTaskDays([]);
      setMessage('练习项目已确认保存。');
    } catch (failure) {setError(failure.message);}
    finally {setBusy(false);}
  }
  async function remove(task) {
    setBusy(true); setError('');
    try {
      await post('/practice/' + task.id + '/remove', {});
      setTasks(values => values.filter(item => item.id !== task.id));
      setChecks(values => values.filter(check => check.task_id !== task.id));
      setRemoving(null);
      if (editing === task.id) {setEditing(null); setTitle(''); setDetail(''); setTaskDays([]);}
    } catch (failure) {setError(failure.message);}
    finally {setBusy(false);}
  }
  async function confirmSuggestions(identifier, items) {
    setBusy(true); setError('');
    try {
      await post('/practice/drafts/' + identifier + '/confirm', {items});
      setTasks(await api('/practice'));
      setDrafts(values => values.filter(draft => draft.id !== identifier));
      setMessage('已确认加入练习计划，可在对应日期查看。');
      onDismissNotice?.();
    } catch (failure) {setError(failure.message);}
    finally {setBusy(false);}
  }
  function editTask(task) {
    setEditing(task.id); setTitle(task.title); setDetail(task.detail); setTaskDays(task.weekdays || []);
    taskForm.current?.scrollIntoView({behavior:'smooth', block:'center'});
  }
  return <div className="workflow-stack practice-workspace">
    {notice && <div className="practice-notice" role="status"><CheckCircle size={22}/>
      <span>{notice.confirmed ? '本次演奏的练习建议已确认，可在日历中查看。' : `AI 已准备 ${notice.generatedCount} 项建议。可先编辑，再确认加入计划。`}</span>
      <button className="text-button" onClick={onDismissNotice}>关闭</button></div>}
    <ErrorText error={error}/>
    {drafts.map(draft => <PracticeSuggestions key={draft.id} draft={draft} busy={busy} onConfirm={confirmSuggestions}/>)}
    <Panel title="每周练习安排" className="practice-schedule-panel" action={hasSchedule && !dirty &&
      <a className="text-button" href="/api/practice/calendar.ics" download="钢琴练习计划.ics"><DownloadSimple/>导出到个人日历</a>}>
      <form onSubmit={saveSchedule} className="practice-schedule-form">
        <label>每周练几次<select value={draftDays.length || ''} disabled={loading || busy} onChange={event => {
          setDraftDays(frequencies[Number(event.target.value) - 1]); setMessage('');
        }}>
          <option value="" disabled>请选择次数</option>
          {frequencies.map((_,index) => <option key={index} value={index + 1}>每周 {index + 1} 次</option>)}
        </select></label>
        <DayChoices value={draftDays} disabled={loading || busy} label="每周练习日" onChange={days => {setDraftDays(days); setMessage('');}}/>
        <label>起始日期<input type="date" value={startDate} disabled={loading || busy} onChange={event => setStartDate(event.target.value)}/></label>
        <label>截止日期<input type="date" min={startDate} value={endDate} disabled={loading || busy} onChange={event => setEndDate(event.target.value)}/></label>
        <button className="primary" disabled={loading || busy || !dirty || !draftDays.length || !startDate || (endDate && endDate < startDate)}>确认安排</button>
      </form>
      <p className="subtle" role="status">{message || (dirty ? '选择次数和星期后保存，日历会按每周安排重复显示。' : `每周 ${schedule.weekdays.length} 次 · ${schedule.weekdays.map(day => '周' + weekdays[day]).join('、')}`)}</p>
      {hasSchedule && !dirty && <p className="subtle">可将 .ics 文件导入个人日历，按全天日程每周重复，包含当前练习内容。计划调整后可重新导出。</p>}
    </Panel>
    <div className="practice-calendar-layout">
      <Panel title={<span className="practice-calendar-title"><CalendarDots size={23}/>{month.getFullYear()} 年 {month.getMonth() + 1} 月</span>}
        className="practice-calendar-panel" action={<div className="practice-month-controls">
          <button className="calendar-icon-button" aria-label="上个月" onClick={() => moveMonth(-1)}><CaretLeft/></button>
          <button className="text-button" onClick={() => selectDay(parseDate(today))}>今天</button>
          <button className="calendar-icon-button" aria-label="下个月" onClick={() => moveMonth(1)}><CaretRight/></button>
        </div>}>
        <div className="practice-calendar-week" aria-hidden="true">{weekdays.map(day => <span key={day}>{day}</span>)}</div>
        <div className="practice-calendar-grid" aria-label="练习日历">
          {days.map(date => {
            const key = dateKey(date);
            const training = isPracticeDay(key);
            const daily = tasksOn(key);
            const count = doneOn(key);
            const allDone = daily.length > 0 && count === daily.length;
            return <button key={key} type="button" aria-label={`${key}${training ? ' 练习日' : ''}${count ? ` 已完成 ${count} 项` : ''}`}
              aria-pressed={selected === key} aria-current={key === today ? 'date' : undefined}
              className={['practice-calendar-day', date.getMonth() !== month.getMonth() ? 'outside' : '', training ? 'training' : '',
                allDone ? 'done' : '', key === selected ? 'selected' : '', key === today ? 'today' : ''].join(' ')}
              onClick={() => selectDay(date)}>
              <span className="calendar-day-number">{date.getDate()}</span>
              {training && <span className="calendar-day-label">{allDone ? '已完成' : daily.length ? `${daily.length} 项练习` : '练习日'}</span>}
              {count > 0 && <span className="calendar-day-progress">{count}/{daily.length}</span>}
            </button>;
          })}
        </div>
        <div className="practice-calendar-legend"><span><i/>练习日</span><span><i className="done"/>已完成</span></div>
      </Panel>
      <Panel title={parseDate(selected).toLocaleDateString('zh-CN', {month:'long', day:'numeric', weekday:'long'})}
        action={<span className="status-pill">{selectedIsPractice || selectedTasks.length ? `${selectedDone}/${selectedTasks.length} 项完成` : '休息日'}</span>} className="practice-day-panel">
        <p className="subtle">{selectedIsPractice ? '每次练习按以下项目进行，完成后逐项勾选。' : '可以回看练习项目，或调整上方安排，将这一天设为练习日。'}</p>
        {loading ? <p role="status">正在读取练习安排…</p> : selectedTasks.length ? <div className="practice-day-tasks">
          {selectedTasks.map(task => <article key={task.id} className={'practice-day-task' + (completed.has(`${selected}:${task.id}`) ? ' completed' : '')}>
            <label className="practice-task-check"><input type="checkbox" checked={completed.has(`${selected}:${task.id}`)}
              disabled={busy || (!selectedIsPractice && !completed.has(`${selected}:${task.id}`))}
              aria-label={`${selected} 完成 ${task.title}`} onChange={() => toggle(task)}/><strong>{task.title}</strong></label>
            <p>{task.detail}</p>
            <div className="workflow-actions">
              {task.job_id && <button className="text-button" disabled={busy} onClick={async () => {
                setBusy(true); setError('');
                try {await onOpenClip(task);} catch (failure) {setError(failure.message);} finally {setBusy(false);}
              }}><Play/>回看演奏 {stamp(task.start_seconds)}</button>}
            </div>
          </article>)}
        </div> : <div className="workflow-empty"><CalendarDots size={32}/><p>{tasks.length ? '这一天暂未安排练习项目，可在下方调整项目的练习星期。' : '可以手动添加每周练习，也可以确认采用 AI 建议。'}</p></div>}
      </Panel>
    </div>
    <Panel title="每周练习项目">
      <div className="practice-project-list">{tasks.map(task => <article className="practice-project-row" key={task.id}>
        <div><strong>{task.title}</strong><p>{describeDays(task.weekdays)}</p></div><div className="workflow-actions">
          <button className="text-button" disabled={busy} onClick={() => editTask(task)}>编辑</button>
          {removing === task.id ? <><button className="text-button danger" disabled={busy} onClick={() => remove(task)}>确认删除</button>
            <button className="text-button" onClick={() => setRemoving(null)}>取消</button></>
            : <button className="text-button danger" disabled={busy} onClick={() => setRemoving(task.id)}>删除</button>}
        </div></article>)}</div>
      <div ref={taskForm}><h4>{editing ? '编辑练习项目' : '添加自己的练习'}</h4></div>
      <form className="practice-task-form" onSubmit={saveTask}>
        <label>练习名称<input maxLength={120} value={title} onChange={event => setTitle(event.target.value)} placeholder="例如，右手换指慢练"/></label>
        <label>练习目标<textarea maxLength={1200} value={detail} onChange={event => setDetail(event.target.value)} placeholder="记录每次练习的方法和完成目标"/></label>
        <DayChoices value={taskDays} disabled={busy} onChange={setTaskDays}/>
        <div className="workflow-actions"><button className="primary" disabled={loading || busy || !title.trim()}><Plus/>{editing ? '确认修改' : '确认添加'}</button>
          {editing && <button className="text-button" type="button" onClick={() => {setEditing(null); setTitle(''); setDetail(''); setTaskDays([]);}}>取消编辑</button>}</div>
      </form>
    </Panel>
  </div>;
}
