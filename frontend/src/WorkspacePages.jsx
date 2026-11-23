import React, {useEffect, useRef, useState} from 'react';
import {ArrowRight, Books, CalendarDots, CheckCircle, Clock, DownloadSimple, Eye, EyeSlash, LockKey,
  MagnifyingGlass, MusicNotes, Plus, ShieldCheck, SignIn, SignOut, UploadSimple, UserCircle, X} from '@phosphor-icons/react';
import {api, post, uploadAsset, Panel, Stats, stamp, ErrorText} from './workspace-ui';

export {PracticePage} from './PracticeCalendar';

export function LibraryPage({onReference}) {
  const [assets,setAssets] = useState([]);
  const [query,setQuery] = useState('');
  const [loading,setLoading] = useState(true);
  const [loadError,setLoadError] = useState('');
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  useEffect(() => {
    let live = true;
    api('/library').then(items => {if (live) setAssets(items);})
      .catch(e => {if (live) setLoadError(e.message);})
      .finally(() => {if (live) setLoading(false);});
    return () => {live = false;};
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

  return <Panel title={<span className="library-heading"><Books size={23} weight="duotone"/>参考 MIDI</span>} className="library-panel"
    action={<label className="primary workflow-file-button library-import"><UploadSimple/>{busy ? '正在导入…' : '导入 MIDI'}
      <input aria-label="导入 MIDI" type="file" accept=".mid,.midi" disabled={loading || busy} onChange={upload}/>
    </label>}>
      <div className="library-search">
        <label className="search"><MagnifyingGlass size={19}/><input type="search" aria-label="搜索曲库" value={query} onChange={e => setQuery(e.target.value)} placeholder="按文件名搜索"/></label>
        {!loading && !loadError && <span className="library-count" role="status">{query.trim() ? `${visible.length} / ${assets.length} 首曲目` : `${assets.length} 首曲目`}</span>}
      </div>
      <ErrorText error={loadError}/>
      <ErrorText error={error}/>
      {visible.length > 0 && <div className="library-grid">
        {visible.map(asset => <article className="library-card" key={asset.id}>
          <div className="library-card-heading"><span className="library-icon"><MusicNotes size={24} weight="duotone"/></span><h4>{asset.name}</h4></div>
          <dl className="library-meta">
            <div><dt>时长</dt><dd>{stamp(asset.duration)}</dd></div>
            <div><dt>音符数</dt><dd>{asset.notes}</dd></div>
            <div><dt>音域</dt><dd>{asset.minimum}–{asset.maximum}</dd></div>
          </dl>
          <div className="library-card-actions">
            <button className="text-button" onClick={() => onReference(asset)}>用作对照 <ArrowRight size={15}/></button>
            <a className="text-button" href={'/api/assets/' + asset.id + '/midi'} download={asset.name} aria-label={'下载 ' + asset.name}><DownloadSimple size={17}/>下载</a>
          </div>
        </article>)}
      </div>}
      {loading && <div className="workflow-empty library-empty" role="status">正在读取曲库…</div>}
      {!loading && !loadError && !visible.length && <div className="workflow-empty library-empty">
        {query.trim() ? <MagnifyingGlass size={34}/> : <MusicNotes size={34} weight="duotone"/>}
        <strong>{query.trim() ? '没有匹配的曲目' : '曲库还没有曲目'}</strong>
        <p>{query.trim() ? '试试更短的文件名关键词。' : '导入 .mid 或 .midi 文件，即可在音频转录中用作参考乐谱。'}</p>
        {query.trim() && <button className="text-button" onClick={() => setQuery('')}>清除搜索</button>}
      </div>}
    </Panel>;
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

export function AccountDrawer({account,logout,onClose,onNavigate,onHistory}) {
  const [error,setError] = useState('');
  const [busy,setBusy] = useState(false);
  const dialog = useRef(null);
  const closeButton = useRef(null);
  useEffect(() => {
    const element = dialog.current;
    element.showModal();
    closeButton.current.focus();
    return () => element.close();
  }, []);
  const shortcuts = [
    [Clock, '历史演奏', '打开分析记录和回放', onHistory],
    [CalendarDots, '我的练习', '管理练习清单和完成记录', () => onNavigate('practice')],
    [Books, '我的曲库', '查看已导入的参考 MIDI', () => onNavigate('library')],
  ];

  return <dialog ref={dialog} className="account-drawer" aria-labelledby="account-drawer-title"
    onCancel={event => {event.preventDefault(); onClose();}}
    onClick={event => {if (event.target === event.currentTarget) onClose();}}>
    <div className="drawer-shell">
      <div className="drawer-heading">
        <h2 id="account-drawer-title">个人中心</h2>
        <button ref={closeButton} className="drawer-close" aria-label="关闭个人中心" onClick={onClose}><X size={20}/></button>
      </div>
      <div className="drawer-body">
        <div className="account-identity">
          <span className="account-avatar" aria-hidden="true">{account.username[0]?.toUpperCase()}</span>
          <div><strong>{account.username}</strong><span className="status-pill">{account.role === 'admin' ? '管理员' : '普通用户'}</span></div>
        </div>
        <div className="account-links">
          {shortcuts.map(([Icon,title,detail,action]) => <button key={title} onClick={action}>
            <span className="account-link-icon"><Icon size={20} weight="duotone"/></span>
            <span><strong>{title}</strong><small>{detail}</small></span><ArrowRight size={16}/>
          </button>)}
        </div>
        {account.role === 'admin' && <AdminSettings/>}
      </div>
      <div className="drawer-footer">
        <ErrorText error={error}/>
        <button disabled={busy} onClick={async () => {
          setError(''); setBusy(true);
          try {await logout();}
          catch (e) {setError(e.message);}
          finally {setBusy(false);}
        }}><SignOut size={19}/>{busy ? '正在退出…' : '退出登录'}</button>
      </div>
    </div>
  </dialog>;
}

function AuthField({name,label,icon: Icon,type = 'text',value,onChange,onBlur,autoComplete,hint,error,disabled}) {
  const [revealed,setRevealed] = useState(false);
  const password = type === 'password';
  return <div className="auth-field">
    <label htmlFor={'auth-' + name}>{label}</label>
    <div className="auth-control">
      <Icon size={19} aria-hidden="true"/>
      <input id={'auth-' + name} name={name} type={revealed ? 'text' : type} value={value} autoComplete={autoComplete}
        autoCapitalize={password ? undefined : 'none'} spellCheck={false} required disabled={disabled}
        aria-invalid={Boolean(error)} aria-describedby={'auth-' + name + '-feedback'} onChange={onChange} onBlur={onBlur}/>
      {password && <button type="button" aria-label={(revealed ? '隐藏' : '显示') + label} disabled={disabled} onClick={() => setRevealed(!revealed)}>
        {revealed ? <EyeSlash size={19}/> : <Eye size={19}/>}
      </button>}
    </div>
    <p id={'auth-' + name + '-feedback'} className={error ? 'auth-feedback invalid' : 'auth-feedback'} aria-live="polite">{error || hint}</p>
  </div>;
}

export function AuthPage({onAccount}) {
  const [type,setType] = useState('login');
  const [username,setUsername] = useState('');
  const [password,setPassword] = useState('');
  const [confirm,setConfirm] = useState('');
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const [touched,setTouched] = useState({});
  const registering = type === 'register';
  const usernameRule = '3–32 个字符，支持字母、数字、下划线和短横线';
  const passwordRule = '8–128 个字符';
  const passwordLength = Array.from(password).length;
  const errors = {
    username: !username.trim() ? '请输入用户名。' : /^[A-Za-z0-9_-]{3,32}$/.test(username.trim()) ? '' : '用户名需要 ' + usernameRule + '。',
    password: !password ? '请输入密码。' : passwordLength < 8 || passwordLength > 128 ? '密码长度需要 ' + passwordRule + '。' : '',
    confirm: !registering ? '' : !confirm ? '请再次输入密码。' : confirm !== password ? '两次输入的密码不一致。' : '',
  };
  function switchType(next) {
    if (next === type) return;
    setType(next); setError(''); setTouched({}); setPassword(''); setConfirm('');
  }
  function field(name, value, setValue) {
    return {
      name, value, disabled: busy,
      onChange: event => {setValue(event.target.value); setError('');},
      onBlur: () => setTouched(previous => ({...previous, [name]: true})),
      error: touched[name] ? errors[name] : '',
    };
  }

  async function submit(event) {
    event.preventDefault();
    setError('');
    const invalid = Object.keys(errors).find(name => errors[name]);
    if (invalid) {
      setTouched({username: true, password: true, confirm: true});
      event.currentTarget.elements.namedItem(invalid)?.focus();
      return;
    }
    setBusy(true);
    try {onAccount((await post('/auth/' + type,{username: username.trim(),password})).account);}
    catch (e) {setError(e.message);}
    finally {setBusy(false);}
  }

  return <div className="auth-layout">
    <div className="auth-image" aria-hidden="true">
      <div><MusicNotes size={31} weight="duotone"/><strong>钢琴 AI 教练</strong></div>
      <p>保存演奏记录，接着上一次练习。</p>
    </div>
    <section className="panel workflow-panel auth-panel">
      <div className="auth-switch" role="group" aria-label="账号操作">
        <button aria-pressed={!registering} disabled={busy} onClick={() => switchType('login')}>登录</button>
        <button aria-pressed={registering} disabled={busy} onClick={() => switchType('register')}>注册</button>
      </div>
      <h1>{registering ? '创建账号' : '登录账号'}</h1>
      <form noValidate onSubmit={submit}>
        <AuthField {...field('username',username,setUsername)} label="用户名" icon={UserCircle} autoComplete="username" hint={usernameRule}/>
        <AuthField key={type} {...field('password',password,setPassword)} label="密码" icon={LockKey}
          type="password" autoComplete={registering ? 'new-password' : 'current-password'} hint={passwordRule}/>
        {registering && <AuthField {...field('confirm',confirm,setConfirm)} label="确认密码" icon={LockKey}
          type="password" autoComplete="new-password" hint="再次输入密码"/>}
        <ErrorText error={error}/>
        <button className="primary wide" disabled={busy}><SignIn size={19}/>{busy ? '处理中…' : registering ? '创建账号' : '登录'}</button>
      </form>
    </section>
  </div>;
}
