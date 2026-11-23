# 钢琴 AI 教练前端

React、Vite 和 Phosphor Icons。页面包括首页、登录注册、演奏分析、AI 教练、练习计划、曲库、模型与数据和个人中心。

演奏分析统一上传俯拍视频与五线谱或参考 MIDI，自动定位琴键。结果先显示全曲 AI 评价，再提供带手指标记的回看、逐音和时间段问答。PDF、图片识谱由 Python 后端调用本机 Audiveris。

从项目根启动后端后，在此目录运行 `npm run dev`。Vite 将 `/api` 转发到 127.0.0.1:8000。

运行 `npm run build` 生成页面到 `dist/client`，Python 服务直接提供这份构建。运行 `npm run test:sites` 检查前端的静态包装。账号、MySQL 与分析任务需要 Python 服务。

样式保留原有的钢琴背景、深蓝与淡紫玻璃卡片。演奏、问答和练习数据来自当前账号的 API。
