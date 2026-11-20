# 钢琴 AI 教练

上传演奏视频可生成手部骨架回放、逐音指法候选或音频转录。登录后可回看历史任务、在 AI 教练中选择片段提问，并把练习草案加入自己的计划。

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

视频逐帧检测和逐键轮廓导出见 [pianoCV 测试台](pianocv_lab/README.md)。
