# 钢琴 AI 教练

上传带琴声的固定俯拍视频，以及曲目对应的五线谱或 MIDI，系统自动生成弹奏分析与全曲 AI 评价。随后可选择视频段落或单个音符继续提问，并把练习建议加入计划。

## 主站分析流程

1. 上传完整拍到 88 键与双手的俯拍视频。浏览器使用 pianoCV 定位琴键，自动定位失败时可框选键盘。
2. 上传 PDF、PNG、JPG、MusicXML 或参考 MIDI。PDF 和图片通过 Audiveris 转为 MusicXML，保留小节、拍点、音高、时值及谱面指法。有 MIDI 时可直接上传。
3. Basic Pitch 从视频音轨提取实际演奏的起音，与参考谱面自适应对齐。按“同一曲目、完整对应”处理，参考 MIDI 可以来自曲谱，无须另录同期 MIDI。
4. MediaPipe 跟踪双手关键点，结合 pianoCV 的逐键轮廓和对齐后的起音，计算逐音指法。音轨测得的时间与谱面推算的定位时间分别保存在产物中。
5. 构建本次演奏的知识图谱，关联演奏、谱面音符、视频时间、琴键、手指及练习规则。对全部音符汇总统计，再均匀选取全曲样本和重点位置送给 AI。
6. 分析结束后自动生成全曲评价。结果页先展示评价，再提供回看、片段选择、逐音提问和资料下载。AI 服务暂时中断时可重试评价，分析资料仍会保存。

AI 使用自然的教师语气，围绕观察、回看重点与具体练法回答。管理员在个人中心配置 Chat Completions 服务后启用评价与问答。

### 练习计划与日历

AI 教练页统一使用片段分析，支持按时间或音符追问。通过“生成练习建议”读取全曲评价，进入练习计划页后可勾选、编辑并确认采用。建议在确认前保存为账号下的待确认内容，刷新后可继续处理。

练习项目支持手动添加和修改，每项可选择练习星期。每周总安排可设置 1–7 次、具体星期、起始与截止日期。网站月历按日期显示当天项目，并分别记录每次完成情况。初始界面预填每周三次、四周，用户确认安排后保存。

保存安排后可下载 `.ics`，包含每项练习的星期、起止日期和目标，默认作为全天重复日程导入个人日历。修改计划后可重新导出。

### 五线谱识别依赖

在运行 Python 后端的机器上安装 [Audiveris](https://github.com/Audiveris/audiveris/releases/tag/5.11.0)。后端会检查 PATH 和常见 Windows 安装位置，自定义位置可用 `PIANO_AUDIVERIS` 指定。PDF 识别在本机执行，单次最多 10 MB，支持一份单乐章印刷谱。容器运行时也需在镜像内提供 Audiveris 可执行文件。MusicXML 与 MIDI 可直接解析。

每个新任务保存 `reference_passage.json`、`aligned_reference.mid`、`fingering_predictions.csv`、`performance_graph.json`、`score_alignment.json` 和 `overview.json`。原有算法命令与历史任务继续兼容。

## 项目目录

| 目录 | 内容 |
| --- | --- |
| `backend/` | Python HTTP 接口、MySQL 数据层、视频与 MIDI 分析、离线验收脚本 |
| `frontend/` | React 页面、Vite 构建、页面样式和静态素材 |
| `deploy/` | 应用镜像、MySQL 和 Caddy 的 Compose 配置及环境变量示例 |
| `tests/` | 带本地模型模拟服务的 MySQL 和 HTTP 集成测试 |
| `docs/` | 数据库与部署说明、接口与测试说明、人工验收报告 |
| `training_sites/` | PDF / MusicXML 乐谱选段、演奏对齐训练与验证两个本地工具 |
| `pianocv_lab/` | 视频逐帧琴键轮廓测试台 |
| `data/`、`outputs/` | 运行时在本地准备或生成的素材、输出与历史任务 |

### 后端分层

| 目录 | 职责 |
| --- | --- |
| `backend/api/` | HTTP 路由、请求解析、会话 Cookie、响应和文件传输 |
| `backend/services/` | 账号、素材、分析任务、AI 教练和练习的业务流程 |
| `backend/repositories/` | MySQL 数据访问、资源归属和分析产物读写 |
| `backend/analysis/` | 键盘校准、音频转录、MIDI 对齐、手部跟踪和指法算法 |

`backend/api_server.py` 组装各层并启动服务。请求从 API 进入业务服务，再访问存储或调用分析算法。修改接口、业务规则或数据读写时，可直接找到对应目录。

## 启动

有 Docker Compose 时，从项目根目录执行以下命令。在启动前填写 `deploy/.env` 里的两个数据库密码、初始管理员密码和加密密钥。

```bash
cp deploy/.env.example deploy/.env
python3 -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Windows PowerShell 可用 `Copy-Item deploy/.env.example deploy/.env`，并用 `python` 执行同一条密钥生成命令。填好 `deploy/.env` 后启动。

```bash
docker compose --env-file deploy/.env -f deploy/compose.yml up -d --build
```

本地入口是 [http://localhost:8080](http://localhost:8080)。普通用户可注册。管理员用启动时创建的管理员账号登录，从「个人中心」配置全站 AI 接口。

- [数据库与部署说明](docs/数据库与部署.md)
- [人工验收与交接报告](docs/人工验收报告.md)
- [接口与测试说明](docs/后端接入与测试说明.md)

算法开发可以直接运行 `backend/pipeline.py`、`backend/audio_analysis.py` 或 `backend/evaluate_fingering.py`。需要独立的本地分析界面时，先运行 `python -m pip install streamlit pandas`，再运行 `python -m streamlit run backend/analysis_app.py`。

其他算法工具从项目根目录以模块方式运行，例如 `python -m backend.analysis.auto_keyboard --help`。

### 乐谱选段导出

安装 `backend/requirements.txt` 中的依赖后，可以把 `.musicxml`、`.xml` 或 `.mxl` 的连续小节导出为参考 MIDI。

```powershell
python -m backend.analysis.score_excerpt score.musicxml --first 17 --last 24 --output outputs/reference_excerpt.mid
```

起止位置按谱面出现顺序从 1 计数，包含两端。弱起小节占一个位置，反复记号按书面顺序走一遍。导出的 MIDI 从选段起点计时，保留双手音符、休止、速度变化和落在选段内的延音。可以将产物上传到演奏分析的「参考乐谱 MIDI」。

本地网页演示和对齐训练工具的启动方法、标注格式见 [钢琴研究工作台](training_sites/README.md)。

## 琴键与技巧知识图谱

前端首次启动或构建时自动下载并校验 pianoCV KeyNet 模型。独立测试和轮廓导出见 [pianoCV 测试台](pianocv_lab/README.md)。主站的骨架与琴键叠图位于分析结果的“显示手指与琴键标记”。

每次演奏生成独立的 `performance_graph.json`，包含音符事件、谱面音符、琴键几何、手指、手部观测索引、练习规则与参考资料。全曲统计聚合全部音符，问答按选择范围检索。谱面推算的起音用于回放定位，节奏指标采用音轨匹配到的起音。

“模型与数据”还可查看基础音阶知识图谱。独立音阶算法保留三种练习定义，用于采集和标注研究。

| 练习 | 音域 | 换指 | 准备动作观测 |
| --- | --- | --- | --- |
| 右手 C 大调上行 | C4–C5 | E4→F4，3→1 | 拇指朝 F4 靠近 |
| 右手 C 大调下行 | C5–C4 | F4→E4，1→3 | 中指朝 E4 靠近 |
| 右手 G 大调上行 | G4–G5，含 F♯5 | B4→C5，3→1 | 拇指朝 C5 靠近 |

图谱定义与资料来源见 [图谱 JSON](backend/analysis/piano_technique_graph.json)。教学判定阈值需通过不同演奏者的实录和人工标签校准，指法准确率可用 `backend/evaluate_fingering.py` 计算。

## 验证

运行 `python -m unittest discover -s tests -v` 检查算法和格式。MySQL 集成测试需要设置 `PIANO_TEST_DB_PORT`，请使用一次性数据库实例。前端通过 `npm --prefix frontend run build` 和 `npm --prefix frontend run test:sites` 检查构建与打包。

本次本机验证中，Audiveris 从 PDF 识别出 32 小节。K.545 的 12 秒片段完成 107 个音符的关联与手指分析。全曲评价和精确单音问答的接口通过本地模拟模型验证，真实 AI 服务的措辞与教学质量需连接供应商后核验。
