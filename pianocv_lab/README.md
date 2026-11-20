# pianoCV 琴键轮廓测试台

从本地选择或拖入钢琴视频，将进度条停在键盘完整、键缝清晰的位置，然后点击「识别当前帧」。页面区分黑白键，可悬停查看单键，或下载原视频像素坐标的 JSON。移动进度条时，叠图只在与识别结果匹配的时间点显示。

## 启动

在项目根目录使用 Node.js 22 或 24 运行：

```bash
npm --prefix pianocv_lab ci
npm --prefix pianocv_lab run dev
```

打开 [http://127.0.0.1:8763/](http://127.0.0.1:8763/)。第一次启动自动下载并校验 KeyNet 模型。模型和 WebAssembly 加载后，视频解码、识别和导出都在浏览器内完成。

构建静态版本可使用 `npm --prefix pianocv_lab run build`。随后用 `npm --prefix pianocv_lab run preview` 预览构建结果。

视频能否读取取决于浏览器支持的编码。遇到无法播放的 HEVC（H.265）MP4，可以先导出 H.264 副本。

```bash
ffmpeg -i input.mp4 -c:v libx264 -pix_fmt yuv420p -c:a aac -movflags +faststart output-h264.mp4
```

## 结果

- 每个键包含颜色、相对半音编号、`outline` 轮廓多边形和 `top` 顶面。黑键拟合时会覆盖相邻白键的一部分。叠图按前后关系显示，JSON 保留 pianoCV 的原始几何结果。
- 坐标为原视频像素，左上角为原点。JSON 还保存识别时间和视频尺寸。
- 识别为 88 键且最低音类为 A 时，页面按标准 A0–C8 编号。其他布局默认显示相对键序，可在「最低键 MIDI 编号」填写实际最低键再导出绝对音名。
- 建议先用固定机位的俯视或轻微侧视清晰帧对照原视频校验。键盘被裁切或大面积遮挡时，可能出现拟合失败或误判键数。

本工具使用 `pianocv` 的 npm 发布包、KeyNet 模型及其几何核心。 [pianoCV 上游项目](https://github.com/matheusfillipe/pianoCV) · [KeyNet 模型说明](https://huggingface.co/mattf/pianoCV)
