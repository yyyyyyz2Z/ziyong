import React, {useEffect, useState} from 'react';
import {ArrowRight, Books, CalendarDots, ChatCircleText, Cube, Hand, House, MonitorPlay, MusicNotes, UploadSimple, UserCircle, Waveform} from '@phosphor-icons/react';
import {AnalysisWorkspace} from './AnalysisWorkspace';
import {SegmentCoach} from './SegmentCoach';
import {AccountPage, AuthPage, LibraryPage, PracticePage} from './WorkspacePages';
import {api, post, Panel, ErrorText} from './workspace-ui';

const pages = [
  ['home','首页',House], ['analysis','演奏分析',MusicNotes], ['coach','AI 教练',ChatCircleText],
  ['practice','练习计划',CalendarDots], ['library','曲库管理',Books], ['model','模型与数据',Cube],
];
const descriptions = {
  analysis: '上传演奏视频，查看手部回放、逐音指法或音频转录结果。',
  coach: '选择真实演奏片段，回看证据、提问或安排练习。',
  practice: '整理练习片段，记下每次完成情况。',
  library: '导入参考 MIDI，随时用于音频对照。',
  model: '查看分析方法、数据来源和当前识别范围。',
  account: '查看账号信息、历史演奏和练习记录。',
  auth: '登录后可保存分析、教练问答和练习。',
};
const features = [
  ['analysis','演奏分析','骨架回放、逐音指法与音频转录',MonitorPlay],
  ['coach','AI 教练','带着音符和时间戳提问',ChatCircleText],
  ['practice','练习计划','把回看的片段变成练习任务',CalendarDots],
  ['library','曲库管理','保存和复用参考 MIDI',Books],
];

function currentPage() {
  const key = window.location.hash.slice(1);
  if (key === 'admin') return 'account';
  return ['account','auth'].includes(key) || pages.some(([id]) => id === key) ? key : 'home';
}

function Home({open,onVideo}) {
  return <>
    <section className="hero">
      <h1>钢琴 AI 教练</h1>
      <p>回看每一次演奏，找到下一段要练的地方。</p>
      <div className="features">
        <span><Hand/>手部骨架</span><span><MusicNotes/>逐音指法</span><span><Waveform/>音频转录</span>
      </div>
      <div className="hero-actions">
        <label className="primary workflow-file-button"><UploadSimple/>上传演奏视频
          <input aria-label="上传演奏视频" type="file" accept="video/*" onChange={e => {
            if (e.target.files[0]) onVideo(e.target.files[0]);
          }}/>
        </label>
        <button className="glass-button" onClick={() => open('coach')}><ChatCircleText/>打开 AI 教练</button>
      </div>
    </section>
    <main className="home-workflow">
      <div className="feature-cards">
        {features.map(([key,title,detail,Icon]) => <button key={key} className={'feature-card ' + (key === 'analysis' ? 'selected' : '')} onClick={() => open(key)}>
          <Icon size={38} weight="light"/><div><h2>{title}</h2><p>{detail}</p></div>
        </button>)}
      </div>
      <div className="home-next">
        <Panel title="从视频开始"><p>只有视频时可以生成骨架回放。手上还有同次演奏的 MIDI 时，可以定位到逐个音符。</p>
          <button className="text-button" onClick={() => open('analysis')}>创建或打开分析 <ArrowRight/></button>
        </Panel>
        <Panel title="把片段留到下一次练习"><p>在分析结果里打开教练，选一段视频，保存问题或添加到练习清单。</p>
          <button className="text-button" onClick={() => open('practice')}>查看练习清单 <ArrowRight/></button>
        </Panel>
      </div>
    </main>
  </>;
}

function ModelStatus() {
  return <div className="workflow-stack">
    <div className="capability-grid">
      {[
        ['手部骨架','MediaPipe 逐帧提取手部关键点，生成五指分色的骨架回放。'],
        ['逐音指法','MIDI 提供时间和待比较的琴键。多帧几何匹配产生指法候选，低支持度样本自动拒识。'],
        ['转录与参考对齐','Basic Pitch 将视频音轨转为候选音符，可与参考 MIDI 局部对齐。低覆盖时隐藏差异统计。'],
        ['AI 教练','教练可以读取所选片段的分析摘要、部分音符证据和匹配的练习资料。管理员配置模型后可发送问题。'],
      ].map(([title,detail]) => <Panel key={title} title={title}><p>{detail}</p></Panel>)}
    </div>
    <Panel title="验收与配置">
      <p>指法准确率需要人工标注验证。页面提供候选覆盖率和片段观察，不计算能力评分。</p>
    </Panel>
  </div>;
}

export function App() {
  const [page,setPage] = useState(currentPage);
  const [pendingVideo,setPendingVideo] = useState(null);
  const [reference,setReference] = useState(null);
  const [coachContext,setCoachContext] = useState(null);
  const [account,setAccount] = useState(null);
  const [checking,setChecking] = useState(true);
  const [authError,setAuthError] = useState('');

  useEffect(() => {
    const update = () => setPage(currentPage());
    window.addEventListener('hashchange',update);
    window.addEventListener('popstate',update);
    return () => {
      window.removeEventListener('hashchange',update);
      window.removeEventListener('popstate',update);
    };
  }, []);
  useEffect(() => {
    api('/auth/me').then(value => setAccount(value.account))
      .catch(e => setAuthError(e.message))
      .finally(() => setChecking(false));
  }, []);

  function open(key) {
    setPage(key);
    if (currentPage() !== key) window.history.pushState(null,'','#' + key);
    window.scrollTo(0,0);
  }
  function openCoach(job,result,start,end) {
    setCoachContext({job,result,start,end});
    open('coach');
  }
  async function openClip(task) {
    const path = '/jobs/' + task.job_id;
    const [job,result] = await Promise.all([api(path),api(path + '/result')]);
    openCoach(job,result,task.start_seconds,task.end_seconds);
  }
  async function logout() {
    await post('/auth/logout',{});
    setCoachContext(null); setReference(null); setPendingVideo(null);
    setAccount(null); open('home');
  }
  const screen = page === 'home' ? 'home' : !account ? 'auth' : page === 'auth' ? 'account' : page;
  const title = pages.find(([key]) => key === screen)?.[1] || (screen === 'auth' ? '登录 / 注册' : '个人中心');

  return <div className={'app ' + (page === 'home' ? 'home' : 'inside')}>
    <div className="scene" aria-hidden="true"/>
    <header>
      <button className="brand" onClick={() => open('home')}><MusicNotes size={39}/><span>钢琴 AI 教练<small>Piano AI Coach</small></span></button>
      <nav aria-label="主导航">{pages.map(([key,label,Icon]) => <button className={page === key ? 'active' : ''} aria-current={page === key ? 'page' : undefined} key={key} onClick={() => open(key)}><Icon size={20}/>{label}</button>)}</nav>
      <div className="account"><button aria-label={account ? '个人中心' : '登录或注册'} onClick={() => open(account ? 'account' : 'auth')}><UserCircle size={26}/><span>{account ? '个人中心' : '登录 / 注册'}</span></button></div>
    </header>
    {page === 'home' ? <Home open={open} onVideo={file => {setPendingVideo(file); open('analysis');}}/>
      : <main className="workspace">
        <div className="page-title">
          <div><h1>{title}</h1><p>{descriptions[screen]}</p></div>
          {account && <span className="mode">演奏工作台</span>}
        </div>
        {checking ? <Panel title="正在检查登录状态"/> : <>
          <ErrorText error={authError}/>
          {screen === 'auth' && <AuthPage onAccount={value => {setAccount(value); setAuthError('');}}/>}
          {screen === 'analysis' && <AnalysisWorkspace initialVideo={pendingVideo} onInitialUpload={() => setPendingVideo(null)} initialReference={reference} onCoach={openCoach}/>}
          {screen === 'coach' && <SegmentCoach initial={coachContext} openAnalysis={() => open('analysis')} onPractice={() => open('practice')}/>}
          {screen === 'practice' && <PracticePage onOpenClip={openClip}/>}
          {screen === 'library' && <LibraryPage onReference={asset => {setReference(asset); open('analysis');}}/>}
          {screen === 'model' && <ModelStatus/>}
          {screen === 'account' && <AccountPage {...{account,logout,open}}/>}
        </>}
      </main>}
    <footer><span>Piano AI Coach</span></footer>
  </div>;
}
