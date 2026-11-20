import React, {useEffect, useState} from 'react';
import {ArrowRight, CheckCircle, DownloadSimple, MagnifyingGlass, MusicNotes, Plus, ShieldCheck, SignIn, SignOut, UserCircle} from '@phosphor-icons/react';
import {api, post, uploadAsset, Panel, Stats, stamp, ErrorText} from './workspace-ui';

export function PracticePage({onOpenClip}) {
  const [tasks,setTasks] = useState([]);
  const [title,setTitle] = useState('');
  const [detail,setDetail] = useState('');
  const [editing,setEditing] = useState(null);
  const [removing,setRemoving] = useState(null);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  useEffect(() => {
    api('/practice').then(setTasks).catch(e => setError(e.message));
  }, []);
  const complete = tasks.filter(task => task.completed_at).length;

  async function add(event) {
    event.preventDefault();
    setError(''); setBusy(true);
    try {
      const task = await post(editing ? '/practice/' + editing + '/edit' : '/practice',{title,detail});
      setTasks(items => editing ? items.map(item => item.id === editing ? task : item) : [task,...items]);
      setTitle(''); setDetail('');
      setEditing(null);
    } catch (e) {setError(e.message);}
    finally {setBusy(false);}
  }

  async function toggle(task) {
    setError(''); setBusy(true);
    try {
      const updated = await post('/practice/' + task.id + '/complete',{completed: !task.completed_at});
      setTasks(items => items.map(item => item.id === task.id ? updated : item));
    } catch (e) {setError(e.message);}
    finally {setBusy(false);}
  }

  async function remove(task) {
    setError(''); setBusy(true);
    try {
      await post('/practice/' + task.id + '/remove',{});
      setTasks(items => items.filter(item => item.id !== task.id));
      setRemoving(null);
      if (editing === task.id) {setEditing(null); setTitle(''); setDetail('');}
    } catch (e) {setError(e.message);}
    finally {setBusy(false);}
  }

  return <div className="workflow-stack">
    <ErrorText error={error}/>
    <div className="analysis-grid">
      <Panel title="练习清单">
        <Stats items={[[ '待练习',tasks.length - complete],['已完成',complete]]}/>
        {tasks.length ? <div className="workflow-list">{tasks.map(task => <article className="workflow-row practice-row" key={task.id}>
          <input type="checkbox" aria-label={'完成 ' + task.title} checked={!!task.completed_at} disabled={busy} onChange={() => toggle(task)}/>
          <div><strong>{task.title}</strong><p>{task.detail}</p>
            {task.completed_at && <small>完成于 {new Date(task.completed_at).toLocaleDateString('zh-CN')}</small>}
            <div className="workflow-actions">
              {task.job_id && <button className="text-button" disabled={busy} onClick={async () => {
                setError(''); setBusy(true);
                try {await onOpenClip(task);}
                catch (e) {setError(e.message);}
                finally {setBusy(false);}
              }}>回看 {stamp(task.start_seconds)} <ArrowRight/></button>}
              <button className="text-button" disabled={busy} onClick={() => {setEditing(task.id); setTitle(task.title); setDetail(task.detail);}}>编辑</button>
              {removing === task.id
                ? <><button className="text-button danger" disabled={busy} onClick={() => remove(task)}>确认删除</button><button className="text-button" onClick={() => setRemoving(null)}>取消</button></>
                : <button className="text-button danger" disabled={busy} onClick={() => setRemoving(task.id)}>删除</button>}
            </div>
          </div>
        </article>)}</div> : <div className="workflow-empty"><CheckCircle size={32}/><p>添加自己的练习，也可以从教练页把演奏片段加入清单。</p></div>}
      </Panel>
      <Panel title={editing ? '编辑练习' : '添加练习'}>
        <form onSubmit={add}>
          <label>练习名称<input maxLength={120} value={title} onChange={e => setTitle(e.target.value)} placeholder="例如，右手换指慢练"/></label>
          <label>练习目标<textarea className="workflow-textarea" maxLength={1200} value={detail} onChange={e => setDetail(e.target.value)} placeholder="记录片段、目标速度或复练方法"/></label>
          <div className="workflow-actions">
            <button className="primary" disabled={busy || !title.trim()}><Plus/>{editing ? '保存修改' : '加入清单'}</button>
            {editing && <button type="button" className="text-button" onClick={() => {setEditing(null); setTitle(''); setDetail('');}}>取消编辑</button>}
          </div>
        </form>
      </Panel>
    </div>
  </div>;
}

export function LibraryPage({onReference}) {
  const [assets,setAssets] = useState([]);
  const [query,setQuery] = useState('');
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  useEffect(() => {
    api('/library').then(setAssets).catch(e => setError(e.message));
  }, []);
  const visible = assets.filter(asset => asset.name.toLowerCase().includes(query.trim().toLowerCase()));

  async function upload(event) {
    const file = event.target.files[0];
    event.target.value = '';
    if (!file) return;
    setError(''); setBusy(true);
    try {
      const asset = await uploadAsset('midi',file,true);
      setAssets(items => [asset,...items]);
    } catch (e) {setError(e.message);}
    finally {setBusy(false);}
  }

  return <div className="workflow-stack">
    <Panel title="MIDI 曲库">
      <div className="workflow-actions library-search">
        <label className="search"><MagnifyingGlass/><input aria-label="搜索曲库" value={query} onChange={e => setQuery(e.target.value)} placeholder="按文件名搜索"/></label>
        <label className="primary workflow-file-button"><Plus/>{busy ? '正在导入…' : '导入 MIDI'}
          <input aria-label="导入 MIDI" type="file" accept=".mid,.midi" disabled={busy} onChange={upload}/>
        </label>
      </div>
      <ErrorText error={error}/>
      {!!visible.length && <div className="library-grid">
        {visible.map(asset => <article className="library-card" key={asset.id}>
          <MusicNotes size={29}/><h4>{asset.name}</h4>
          <p>{asset.notes} 个音符 · {stamp(asset.duration)} · 音域 {asset.minimum}–{asset.maximum}</p>
          <div className="workflow-actions">
            <button className="text-button" onClick={() => onReference(asset)}>用作对照乐谱 <ArrowRight/></button>
            <a className="text-button" href={'/api/assets/' + asset.id + '/midi'} download={asset.name}><DownloadSimple/>下载</a>
          </div>
        </article>)}
      </div>}
      {!visible.length && <div className="workflow-empty"><MusicNotes size={34}/><p>{assets.length ? '没有匹配的曲目。' : '导入 MIDI 后，可在音频转录中用作参考乐谱。'}</p></div>}
    </Panel>
  </div>;
}

function AdminSettings() {
  const [form,setForm] = useState(null);
  const [key,setKey] = useState('');
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const [notice,setNotice] = useState('');
  useEffect(() => {
    api('/admin/coach').then(setForm).catch(e => setError(e.message));
  }, []);

  async function saveConfig(event, disable = false) {
    event.preventDefault();
    setError(''); setNotice(''); setBusy(true);
    try {
      const data = disable ? {disable: true} : {endpoint: form.endpoint, model: form.model};
      if (!disable && key) data.api_key = key;
      setForm(await post('/admin/coach',data));
      setKey('');
      setNotice(disable ? 'AI 服务已停用。问答记录仍可查看。' : 'AI 配置已保存。可以转到教练页发送测试问题。');
    } catch (e) {setError(e.message);}
    finally {setBusy(false);}
  }

  return <Panel title="全站 AI 设置" action={<ShieldCheck size={25}/>}>
      <p className="subtle account-note">所有账号的教练共用该模型服务。地址使用兼容 Chat Completions 的完整接口。</p>
      {form && <form onSubmit={saveConfig}>
        <label>完整接口地址<input value={form.endpoint} maxLength={2000} onChange={e => setForm({...form,endpoint: e.target.value})} placeholder="https://服务地址/v1/chat/completions" required/></label>
        <label>模型名称<input value={form.model} maxLength={200} onChange={e => setForm({...form,model: e.target.value})} required/></label>
        <label>API 密钥<input type="password" autoComplete="new-password" value={key} onChange={e => setKey(e.target.value)} placeholder={form.has_key ? '已保存，留空沿用' : '服务需要时填写'}/></label>
        <div className="workflow-actions">
          <button className="primary" disabled={busy}>保存配置</button>
          {form.configured && <button type="button" className="text-button" disabled={busy} onClick={e => saveConfig(e,true)}>停用并清除配置</button>}
        </div>
      </form>}
      <ErrorText error={error}/>
      {notice && <p role="status" className="subtle">{notice}</p>}
    </Panel>;
}

export function AccountPage({account,logout,open}) {
  const [error,setError] = useState('');
  const [busy,setBusy] = useState(false);
  return <div className="admin-grid">
    <Panel title="我的账号" action={<UserCircle size={28}/>}>
      <div className="account-identity">
        <strong>{account.username}</strong><span className="status-pill">{account.role === 'admin' ? '管理员' : '普通用户'}</span>
      </div>
      <div className="workflow-actions account-links">
        <button className="text-button" onClick={() => open('analysis')}>历史演奏 <ArrowRight/></button>
        <button className="text-button" onClick={() => open('practice')}>我的练习 <ArrowRight/></button>
      </div>
      <button className="glass-button" disabled={busy} onClick={async () => {
        setError(''); setBusy(true);
        try {await logout();}
        catch (e) {setError(e.message);}
        finally {setBusy(false);}
      }}><SignOut/>退出登录</button>
      <ErrorText error={error}/>
    </Panel>
    {account.role === 'admin' && <AdminSettings/>}
  </div>;
}

export function AuthPage({onAccount}) {
  const [type,setType] = useState('login');
  const [username,setUsername] = useState('');
  const [password,setPassword] = useState('');
  const [confirm,setConfirm] = useState('');
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const registering = type === 'register';

  async function submit(event) {
    event.preventDefault();
    setError('');
    if (registering && confirm !== password) {setError('两次输入的密码不一致。'); return;}
    setBusy(true);
    try {onAccount((await post('/auth/' + type,{username,password})).account);}
    catch (e) {setError(e.message);}
    finally {setBusy(false);}
  }

  return <div className="auth-layout">
    <div className="auth-image" aria-hidden="true"/>
    <Panel title={registering ? '创建账号' : '登录钢琴 AI 教练'} className="auth-panel">
      <div className="review-filters auth-tabs">
        <button className={!registering ? 'selected' : ''} disabled={busy} onClick={() => {setType('login'); setError('');}}>登录</button>
        <button className={registering ? 'selected' : ''} disabled={busy} onClick={() => {setType('register'); setError('');}}>注册</button>
      </div>
      <form onSubmit={submit}>
        <label>用户名<input autoComplete="username" maxLength={32} value={username} onChange={e => setUsername(e.target.value)} placeholder={registering ? '至少 3 个字母、数字或 _ -' : '输入用户名'} required/></label>
        <label>密码<input type="password" autoComplete={registering ? 'new-password' : 'current-password'} minLength={registering ? 8 : undefined} maxLength={128} value={password} onChange={e => setPassword(e.target.value)} placeholder={registering ? '至少 8 个字符' : '输入密码'} required/></label>
        {registering && <label>确认密码<input type="password" autoComplete="new-password" maxLength={128} value={confirm} onChange={e => setConfirm(e.target.value)} required/></label>}
        <button className="primary wide" disabled={busy}><SignIn/>{busy ? '处理中…' : registering ? '创建账号' : '登录'}</button>
      </form>
      <ErrorText error={error}/>
    </Panel>
  </div>;
}
