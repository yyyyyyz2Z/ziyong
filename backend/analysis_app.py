"""Local end-to-end UI for video/MIDI analysis, calibration and traceable results."""
from __future__ import annotations

import json, subprocess, sys, tempfile
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import streamlit as st
import pretty_midi


st.set_page_config(page_title="钢琴演奏分析", layout="wide")
st.title("钢琴演奏分析")
st.caption("固定俯拍机位 · 视频 + 对应 MIDI · 自动指法候选与拒识")
st.info("本工具不提供教师或演奏者人工审核流程。低置信度结果会标为无法判断；当前不计算未经验证的演奏能力分数。")

video_file=st.file_uploader("演奏视频",type=["mp4","mov","m4v","avi"])
midi_file=st.file_uploader("对应演奏 MIDI",type=["mid","midi"])
offset=st.number_input("MIDI 时间偏移（秒；加到 MIDI 时间）",value=0.0,step=0.05,help="视频有片头空白或已知同步偏移时调整")

def make_mapping(frame: np.ndarray, corners: list[list[float]]) -> dict:
    pts=np.asarray(corners,dtype=np.float32)
    if not cv2.isContourConvex(pts.astype(np.int32).reshape(-1,1,2)) or cv2.contourArea(pts)<5000:
        raise ValueError("四角无效。请按左上、右上、右下、左下顺序圈住完整琴键区域。")
    H=cv2.getPerspectiveTransform(np.array([[0,0],[1,0],[1,1],[0,1]],np.float32),pts)
    white_classes={0,2,4,5,7,9,11}
    white_pitches=[pitch for pitch in range(21,109) if pitch%12 in white_classes]
    positions={pitch:index+.5 for index,pitch in enumerate(white_pitches)}
    keys=[]
    for pitch in range(21,109):
        if pitch in positions:u=positions[pitch]/52
        else:
            low=pitch-1;high=pitch+1
            while low>=21 and low not in positions:low-=1
            while high<=108 and high not in positions:high+=1
            u=((positions[low]+positions[high])/2)/52
        x,y=cv2.perspectiveTransform(np.array([[[u,.68]]],np.float32),H)[0,0]
        keys.append({"midi_pitch":pitch,"x":round(float(x),3),"y":round(float(y),3),"u":round(float(u),6)})
    return {"video":"uploaded-video","corners":pts.tolist(),"key_count":88,"white_key_count":52,"key_centers":keys}

if video_file:
    suffix=Path(video_file.name).suffix
    tmp_video=Path(tempfile.gettempdir())/f"piano-analysis-input{suffix}"
    tmp_video.write_bytes(video_file.getbuffer())
    cap=cv2.VideoCapture(str(tmp_video));fps=cap.get(cv2.CAP_PROP_FPS);count=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));ok,frame=cap.read()
    duration=count/fps if fps else 0
    st.write(f"视频时长：{duration:.2f}s · {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}×{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))} · {fps:.2f} FPS")
    if ok:
        st.subheader("固定机位琴键校准")
        st.caption("在下方图像上确定琴键矩形四角，顺序：左上、右上、右下、左下。建议输入图像上的像素坐标。")
        st.image(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB),caption="首帧；若琴键暂时被遮挡，可先调整后续版本选帧")
        h,w=frame.shape[:2]
        defaults=[(int(w*.08),int(h*.55)),(int(w*.92),int(h*.55)),(int(w*.92),int(h*.9)),(int(w*.08),int(h*.9))]
        cols=st.columns(4);corners=[]
        for i,(label,(dx,dy)) in enumerate(zip(("左上","右上","右下","左下"),defaults)):
            with cols[i]:
                st.markdown(f"**{label}**")
                x=st.number_input(f"{label} X",0,w-1,dx,key=f"x{i}")
                y=st.number_input(f"{label} Y",0,h-1,dy,key=f"y{i}")
                corners.append([x,y])
        preview=frame.copy();cv2.polylines(preview,[np.asarray(corners,np.int32).reshape(-1,1,2)],True,(0,255,80),4)
        for i,pt in enumerate(corners):cv2.circle(preview,tuple(map(int,pt)),9,(0,0,255),-1);cv2.putText(preview,str(i+1),tuple(map(int,pt)),cv2.FONT_HERSHEY_SIMPLEX,1,(255,255,255),2)
        st.image(cv2.cvtColor(preview,cv2.COLOR_BGR2RGB),caption="校准预览；确认边框只覆盖键床")
        mapping_path=Path(tempfile.gettempdir())/"piano-analysis-keyboard.json"
        try:
            mapping=make_mapping(frame,corners);mapping["video"]=video_file.name
            mapping_path.write_text(json.dumps(mapping,indent=2),encoding="utf-8")
            st.success("键盘映射预览通过。映射仅适用于同一机位、构图和画面尺寸。")
        except ValueError as exc:
            st.error(str(exc));mapping=None
    else:mapping=None;st.error("无法解码该视频，请换用标准 MP4/MOV 文件。")
else:mapping=None

if midi_file and video_file:
    midi_path=Path(tempfile.gettempdir())/f"piano-analysis-input-{midi_file.name}"
    midi_path.write_bytes(midi_file.getbuffer())
    try:
        midi=pretty_midi.PrettyMIDI(str(midi_path));midi_duration=midi.get_end_time();notes=[n for i in midi.instruments for n in i.notes]
        pitches=[n.pitch for n in notes]
        st.write(f"MIDI：{len(notes)} 个音符 · {midi_duration:.2f}s · 音域 {min(pitches) if pitches else '—'}–{max(pitches) if pitches else '—'}")
        if notes and (min(pitches)<21 or max(pitches)>108):st.error("MIDI 含钢琴 88 键范围外的音符。")
        if duration and notes and abs(midi_duration+offset-duration)>max(10,duration*.35):st.warning("视频与 MIDI 时长差异较大，请确认曲目相同并调整偏移。")
    except Exception as exc:st.error(f"MIDI 无法读取：{exc}")
    if st.button("开始分析",type="primary",disabled=not mapping):
        out=Path("outputs")/"web_session";out.mkdir(parents=True,exist_ok=True)
        mapping_path.write_text(json.dumps(mapping,indent=2),encoding="utf-8")
        cmd=[sys.executable,str(Path(__file__).with_name("pipeline.py")),"--video",str(tmp_video),"--midi",str(midi_path),"--mapping",str(mapping_path),"--output-dir",str(out),"--offset",str(offset)]
        with st.spinner("正在提取手部关键点并分析音符…"):
            try:
                run=subprocess.run(cmd,capture_output=True,text=True,encoding="utf-8",errors="replace")
                if run.returncode:st.error(run.stderr[-2500:] or run.stdout[-2500:])
                else:st.success(run.stdout);st.session_state["analysis_dir"]=str(out.resolve())
            except Exception as exc:st.error(f"分析启动失败：{exc}")

if st.session_state.get("analysis_dir"):
    out=Path(st.session_state["analysis_dir"])
    summary=json.loads((out/"analysis_summary.json").read_text(encoding="utf-8"))
    st.subheader("分析摘要（统计结果，不是技巧评分）")
    a,b,c,d=st.columns(4);a.metric("音符总数",summary["notes"]);b.metric("有候选",summary["status_counts"]["matched"]);c.metric("不确定",summary["status_counts"]["uncertain"]);d.metric("未匹配",summary["status_counts"]["unmatched"])
    st.warning(summary["score_note"])
    pred=pd.read_csv(out/"fingering_predictions.csv",encoding="utf-8-sig").fillna("")
    st.subheader("逐音符时间定位")
    selected=st.selectbox("选择音符（选中后回放会从该音符前 1 秒开始）",range(len(pred)),format_func=lambda i:f"#{i+1} · {pred.iloc[i]['note_name']} · {float(pred.iloc[i]['start_seconds']):.2f}s · {pred.iloc[i]['status']}")
    st.video(str(out/"fingering_replay.mp4"),start_time=max(0,float(pred.iloc[selected]["start_seconds"])-1))
    st.dataframe(pred,use_container_width=True,height=350)
    for name in ("analysis_summary.json","fingering_predictions.csv","aligned_landmarks.jsonl"):
        st.download_button(f"下载 {name}",(out/name).read_bytes(),file_name=name)
