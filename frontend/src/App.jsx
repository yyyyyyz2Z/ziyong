import React, {useEffect, useState} from 'react';
import {ArrowRight, Books, CalendarDots, ChatCircleText, Cube, Hand, House, MonitorPlay, MusicNotes, UploadSimple, UserCircle, Waveform} from '@phosphor-icons/react';
import {AnalysisWorkspace} from './AnalysisWorkspace';
import {SegmentCoach} from './SegmentCoach';
import {GraphRules} from './TechniqueEvidence';
import {AccountDrawer, AuthPage, LibraryPage, PracticePage} from './WorkspacePages';
import {api, post, Panel, ErrorText} from './workspace-ui';

const pages = [
  ['home','首页',House], ['analysis','演奏分析',MusicNotes], ['coach','AI 教练',ChatCircleText],
  ['practice','练习计划',CalendarDots], ['library','曲库管理',Books], ['model','模型与数据',Cube],
];
const descriptions = {
  analysis: '上传俯拍视频与对应乐谱，获得全曲评价，再逐段向 AI 追问。',
  coach: '选择真实演奏片段，回看证据、提问或安排练习。',
  practice: '选择每周练习次数，在日历上安排和记录每次练习。',
  library: '保存曲目 MIDI，随时用于弹奏分析。',
  model: '查看分析方法、数据来源和当前识别范围。',
};
const features = [
  ['analysis','弹奏 AI 分析','上传视频和乐谱，获得全曲评价',MonitorPlay],
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
      <h1>钢琴弹奏 AI 分析</h1>
      <p>上传演奏与乐谱，让每一段练习都有方向。</p>
      <div className="features">
        <span><MusicNotes/>全曲评价</span><span><Hand/>指法分析</span><span><ChatCircleText/>片段追问</span>
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
          <span className="feature-icon"><Icon size={25} weight="duotone"/></span>
          <div><h2>{title}</h2><p>{detail}</p></div><ArrowRight className="feature-arrow" size={18}/>
        </button>)}
      </div>
      <div className="home-next">
        <Panel title="上传演奏与曲目"><p>准备一段带琴声的俯拍视频，以及对应五线谱或 MIDI。系统自动结合琴键、手指动作和谱面生成分析。</p>
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
  const [catalog, setCatalog] = useState(null);
  const [exercise, setExercise] = useState('');
  const [error, setError] = useState('');
  useEffect(() => {
    let live = true;
    api('/technique/exercises').then(data => {
      if (!live) return;
      setCatalog(data);
      setExercise(data.exercises[0]?.id || '');
    }).catch(e => {if (live) setError(e.message);});
    return () => {live = false;};
  }, []);
  const selected = catalog?.exercises.find(item => item.id === exercise);
  return <div className="workflow-stack">
    <div className="capability-grid">
      {[
        ['乐谱转换','Audiveris 识别 PDF 和印刷谱图片，保留 MusicXML 的小节和音符。已有 MIDI 可直接用于分析。'],
        ['手指与琴键','MediaPipe 跟踪手指动作，pianoCV 定位每个琴键，将动作关联到曲目音符。'],
        ['演奏知识图谱','音轨起音与谱面自适应对齐，关联音符、时间、手指、琴键和练习规则。'],
        ['评价与追问','AI 先结合全曲数据给出弹奏评价，再围绕选定段落或音符提供练习建议。'],
      ].map(([title,detail]) => <Panel key={title} title={title}><p>{detail}</p></Panel>)}
    </div>
    <Panel title="基础音阶知识图谱" className="graph-catalog"
      action={catalog && <span className="status-pill">版本 {catalog.version}</span>}>
      {!catalog && !error && <p role="status">正在读取图谱…</p>}
      <ErrorText error={error}/>
      {selected && <>
        <label>练习<select value={exercise} onChange={e => setExercise(e.target.value)}>
          {catalog.exercises.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
        </select></label>
        <ol className="graph-notes" aria-label="音符及参考指法">
          {selected.note_names.map((note, index) => <li key={note}
            className={[selected.step, selected.step + 1].includes(index) ? 'graph-transition-note' : ''}>
            <strong>{note}</strong><span>{selected.fingers[index]} 指</span>
          </li>)}
        </ol>
        <p className="graph-transition">{selected.transition}</p>
        <GraphRules rules={selected.rules} references={selected.references}/>
      </>}
    </Panel>
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
  const [drawerOpen,setDrawerOpen] = useState(() => currentPage() === 'account');
  const [historyRequested,setHistoryRequested] = useState(false);
  const [practiceNotice,setPracticeNotice] = useState(null);
  const [checking,setChecking] = useState(true);
  const [authError,setAuthError] = useState('');

  useEffect(() => {
    const update = () => {
      const next = currentPage();
      setPage(next);
      setDrawerOpen(next === 'account');
    };
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
    setDrawerOpen(false);
    setPage(key);
    if (currentPage() !== key) window.history.pushState(null,'','#' + key);
    window.scrollTo(0,0);
  }
  function closeDrawer() {
    setDrawerOpen(false);
    if (page === 'account') {
      window.history.replaceState(null,'','#home');
      setPage('home');
    }
  }
  function openCoach(job,result,start,end,noteIds = []) {
    setCoachContext({job,result,start,end,noteIds});
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
    setPracticeNotice(null);
    setAccount(null); open('home');
  }
  const screen = page === 'home' || (account && ['account','auth'].includes(page)) ? 'home' : !account ? 'auth' : page;
  const title = pages.find(([key]) => key === screen)?.[1];

  return <div className={'app ' + (screen === 'home' ? 'home' : 'inside')}>
    <div className="scene" aria-hidden="true"/>
    <header>
      <button className="brand" onClick={() => open('home')}><MusicNotes size={39}/><span>钢琴 AI 教练<small>Piano AI Coach</small></span></button>
      <nav aria-label="主导航">{pages.map(([key,label,Icon]) => <button className={screen === key ? 'active' : ''} aria-current={screen === key ? 'page' : undefined} key={key} onClick={() => open(key)}><Icon size={20}/>{label}</button>)}</nav>
      <div className="account"><button aria-label={account ? '个人中心' : '登录或注册'} aria-haspopup={account ? 'dialog' : undefined}
        onClick={() => account ? setDrawerOpen(true) : open('auth')}><UserCircle size={22}/><span>{account ? '个人中心' : '登录 / 注册'}</span></button></div>
    </header>
    {screen === 'home' ? <Home open={open} onVideo={file => {setPendingVideo(file); open('analysis');}}/>
      : <main className={'workspace' + (screen === 'auth' ? ' auth-workspace' : '')}>
        {screen !== 'auth' && <div className="page-title"><h1>{title}</h1><p>{descriptions[screen]}</p></div>}
        {checking ? <Panel title="正在检查登录状态"/> : <>
          <ErrorText error={authError}/>
          {screen === 'auth' && <AuthPage onAccount={value => {setAccount(value); setAuthError('');}}/>}
          {screen === 'analysis' && <AnalysisWorkspace initialVideo={pendingVideo} onInitialUpload={() => setPendingVideo(null)}
            initialReference={reference} onCoach={openCoach} historyRequested={historyRequested} onHistoryShown={() => setHistoryRequested(false)}/>}
          {screen === 'coach' && <SegmentCoach initial={coachContext} openAnalysis={() => open('analysis')} onPractice={notice => {setPracticeNotice(notice); open('practice');}}/>}
          {screen === 'practice' && <PracticePage onOpenClip={openClip} notice={practiceNotice} onDismissNotice={() => setPracticeNotice(null)}/>}
          {screen === 'library' && <LibraryPage onReference={asset => {setReference(asset); open('analysis');}}/>}
          {screen === 'model' && <ModelStatus/>}
        </>}
      </main>}
    <footer><span>Piano AI Coach</span></footer>
    {account && drawerOpen && <AccountDrawer account={account} logout={logout} onClose={closeDrawer} onNavigate={open}
      onHistory={() => {open('analysis'); setHistoryRequested(true);}}/>}
  </div>;
}
