# YouTubeLocalSubtitles

为没有可用字幕的 YouTube 视频生成本地字幕。用户可以选择英文、中文或双语显示。

**当前阶段：扩展 0.1.1 开发预览。** 页面入口、音频捕获、本地识别、中文翻译和字幕叠加已实现。受控浏览器链路已通过测试；真实 YouTube 连续观看和完整质量验收尚未完成。

0.1.1 修复了“自动字幕记录存在、但播放器明确标记不可用”时仍显示已有字幕的问题。仅仅关闭 CC 不会被当成无字幕。已安装用户需重新加载扩展并刷新视频页，无需重新下载模型。

- [产品需求 PRD](docs/PRD.md)：产品行为、第一版范围、界面流程和验收标准。
- [技术方案 SPEC](docs/TECH_SPEC.md)：技术栈、音频获取、模型、通信、状态管理和实施顺序。
- [使用说明](docs/USER_GUIDE.md)：本机启动、扩展加载、配对和更新。
- [验证记录](docs/VERIFICATION.md)：已验证范围、实测数字及限制。

第一版面向 Windows + Chrome，以英语点播视频为主要验收场景。播放器旁的“本地字幕”按钮是主要入口，用户不必寻找扩展工具栏图标。首次启动音频捕获可能需要在 Chrome 共享选择框中选择当前标签页并共享音频。

已有 YouTube 字幕时默认不运行本地识别，包括 YouTube 自动生成的字幕；用户可手动强制开启。字幕切换只作用于本地生成的字幕，不会默认替换已有字幕。

采用 TypeScript / Vite / Chrome Manifest V3 扩展、Python 3.12 / FastAPI 本地服务、Qwen3-ASR-0.6B INT8 / sherpa-onnx CPU 识别，以及 llama.cpp / Qwen3-4B-Instruct-2507 Q4_K_M GPU 翻译。

安装时联网下载模型；识别和翻译期间不调用云端 AI 服务。模型、虚拟环境、音频、个人配置均不提交到 Git。

## 本机开始使用

1. 已安装本地依赖和模型时，双击 `Start.cmd`。新克隆的仓库先运行 `Install.cmd`，需要 uv、Node.js LTS 和可用的 NVIDIA 驱动。
2. 打开 Chrome 的 `chrome://extensions`，开启开发者模式，加载项目的 `dist` 文件夹。
3. 在 `http://127.0.0.1:18765/setup` 点击“连接 Chrome 扩展”。
4. 刷新 YouTube 视频页，在播放器右上角点击“本地字幕”。首次共享时选择当前标签页并开启音频共享。

更新源码并重新构建后，必须在扩展管理页点击“重新加载”，再刷新 YouTube。Chrome 可能继续使用旧版后台脚本，仅刷新网页不够。

## 开发验证

```powershell
uv sync --frozen --group dev
npm ci
npm run build
uv run pytest -q
npm test
```

浏览器集成测试使用独立 Chrome for Testing 配置和原创英语音频，**先核验测试浏览器已在 Windows 音量混合器静音，再播放素材；无法确认静音则直接中止**。它不会修改日常浏览器音量。

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\runtime\browsers"
uv run playwright install chromium
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\Start.ps1 -NoBrowser
uv run python -m scripts.browser_smoke
```

完整 PRD 中的延迟、WER、翻译质量和 20 分钟连续运行是验收目标。当前小样本结果不代表这些指标已经达标。
