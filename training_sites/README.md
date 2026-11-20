# 钢琴研究工作台

两个工具分别占用一个本机地址，可以同时打开。文件和训练计算留在本机。

## 启动

在项目根目录使用 Python 3.9–3.12 安装依赖并启动。已有虚拟环境时，用该环境里的 Python 执行这两条命令。

```bash
python3 -m venv .venv-training
source .venv-training/bin/activate
python -m pip install -r training_sites/requirements.txt
python -m training_sites.server
```

Windows PowerShell 可沿用现有虚拟环境，用 `.\.venv\Scripts\python.exe` 执行安装和启动命令。

- [乐谱选段](http://127.0.0.1:8761/)
- [演奏对齐训练](http://127.0.0.1:8762/)

端口被占用时，可给第二条命令加 `--score-port 其他端口 --alignment-port 其他端口`。按 Ctrl+C 停止服务。

## 乐谱选段

导入 `.pdf`、`.musicxml`、`.mxl` 或 `.xml`，按顺序点选起止小节，也可以输入小节位置。点击「生成参考 MIDI」会显示钢琴卷帘、音符数量、音轨、时长和速度。下载的 `.mid` 可以直接作为对齐网站的参考文件。谱面上的反复按书面顺序走一遍，弱起小节占一个位置。

### PDF 识谱

PDF 识谱由本机 Audiveris 完成。Windows 可从官方发布页安装 `windowsConsole-x86_64.msi`。网站在启动时会检查系统 PATH 和常见 Windows 安装位置。若安装在自定义目录，直接传入可执行文件的完整路径。 [Audiveris 官方发布](https://github.com/Audiveris/audiveris/releases) · [安装文档](https://audiveris.github.io/audiveris/_pages/tutorials/install/binaries/)

```powershell
.\.venv\Scripts\python.exe -m training_sites.server --audiveris 'C:\Program Files\Audiveris\Audiveris.exe'
```

WSL 内运行时，安装与 Ubuntu 版本匹配的 Audiveris `.deb`，随后用 `command -v audiveris` 检查。如果启动时未自动检测到，用 `--audiveris` 传入 Linux 可执行文件路径。 [Audiveris 安装文档](https://audiveris.github.io/audiveris/_pages/tutorials/install/binaries/)

页面提示 PDF 识谱已启用后，选择 10 MB 以内的印刷五线谱 PDF。Audiveris 输出 MusicXML 后，页面会列出识别的小节，并提供「下载识谱结果」。请对照原 PDF 核对小节、升降号、左右手声部和时值。如果发现识别错误，可以在乐谱编辑器中修订 MusicXML，再导入修订版选段。当前每次导入处理一份单乐章谱面。识谱和导出都在本机完成。

## 演奏对齐训练

1. 准备同一片段的参考 MIDI 和实际演奏 MIDI。在「两份 MIDI 对齐」进行一次对齐，下载待标注模板。演奏优先用电钢琴实录 MIDI，也可用项目音频转录产生的 MIDI。参考侧先核对 PDF 的识谱结果。
2. 核对模板的 `suggested_matches`，将确认的匹配写入 `matches`。将鼠标悬停在对照卷帘上的音符，可以查看 ID、音高和原始起音时间。比如谱面 `r0003` 和演奏 `p0004` 是同一次应弹的 C4，就填 `{"reference_id":"r0003","performance_id":"p0004"}`。重复音按上下文和实际起音区分。每个 ID 最多出现一次。算法漏配的正确对应可以手动补上，漏弹、额外演奏音和错音保留在各自音符列表中，`matches` 里不给它们配对。
3. 给每段取唯一 `id`，给同一曲目的所有片段和录制遍次使用相同 `piece_id`。至少准备两个不同的 `piece_id`，合并到一个 `examples` 数组。
4. 在「训练与验证」导入 JSON 并点击「开始训练与验证」。网站按曲目分组，依据训练集逐音匹配 F1 从 18 组候选参数中选一组，再在留出的曲目上比较固定偏移、默认自适应和校准后自适应。结果显示精确率、召回率、F1、时间映射与逐音对照。
5. 下载模型参数 JSON 和验证结果 JSON。模型文件可以重新导入「两份 MIDI 对齐」。验证文件包含曲目分组、每组参数的训练指标和留出片段的标签、预测与指标。

`onset` 和 `duration` 的单位是秒，`pitch` 是 MIDI 音高，音符 ID 在各自数组内唯一。训练标签须覆盖该片段内所有确认的同音高匹配。下面展示一个片段的结构，正式训练需要在 `examples` 中加入其他曲目的样本。页面也可下载完整的合成示例格式。

```json
{
  "version": 1,
  "examples": [
    {
      "id": "take-a",
      "piece_id": "piece-a",
      "reference": [{"id": "r1", "pitch": 60, "onset": 0.0, "duration": 0.5}],
      "performance": [{"id": "p1", "pitch": 60, "onset": 0.7, "duration": 0.45}],
      "matches": [{"reference_id": "r1", "performance_id": "p1"}]
    }
  ]
}
```

当前训练是**有监督的参数搜索**。合成示例供演示界面、数据格式和评估流程，正式展示时用实际采集的曲目和核对过的标签。单次训练支持 2 至 80 段，每段参考和演奏各至多 1000 个音符，较密的资料可先分成短片段再导入。
