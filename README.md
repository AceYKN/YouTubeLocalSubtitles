# YouTubeLocalSubtitles

为没有可用字幕的 YouTube 视频生成本地字幕。用户可以选择英文、中文或双语显示。

**当前阶段：0.2.0 开发预览。** 默认提前读取当前视频音轨，后台生成字幕缓存，再按播放器时间显示。普通方式不采集画面，不为字幕暂停视频或改变播放速度。

0.2.0 针对卡顿和错位改用音轨预读取，限制推理线程与忙等，并移除默认路径的画面采集。0.1.1 的字幕可用性修复继续保留。已安装用户需重新加载扩展并刷新视频页，无需重新下载模型。

- [产品需求 PRD](docs/PRD.md)：产品行为、第一版范围、界面流程和验收标准。
- [技术方案 SPEC](docs/TECH_SPEC.md)：技术栈、音频获取、模型、通信、状态管理和实施顺序。
- [使用说明](docs/USER_GUIDE.md)：本机启动、扩展加载、配对和更新。
- [验证记录](docs/VERIFICATION.md)：已验证范围、实测数字及限制。

面向 Windows + Chrome，以英语点播视频为主要验证场景。播放器旁的“本地字幕”按钮是主要入口，默认不需要共享框；兼容方式才使用标签页音频采集，并明确保留处理延迟说明。

已有 YouTube 字幕时默认不运行本地识别，包括 YouTube 自动生成的字幕；用户可手动强制开启。字幕切换只作用于本地生成的字幕，不会默认替换已有字幕。

采用 TypeScript / Vite / Chrome Manifest V3 扩展、Python 3.12 / FastAPI 本地服务、yt-dlp / PyAV 音轨读取、Qwen3-ASR-0.6B INT8 / sherpa-onnx CPU 识别，以及 llama.cpp / Qwen3-4B-Instruct-2507 Q4_K_M GPU 翻译。

安装时联网下载模型；识别和翻译期间不调用云端 AI 服务。模型、虚拟环境、音频、个人配置均不提交到 Git。

## 本机开始使用

1. 已安装本地依赖和模型时，双击 `Start.cmd`。新克隆的仓库先运行 `Install.cmd`，需要 uv、Node.js LTS 和可用的 NVIDIA 驱动。
2. 打开 Chrome 的 `chrome://extensions`，开启开发者模式，加载项目的 `dist` 文件夹。
3. 在 `http://127.0.0.1:18765/setup` 点击“连接 Chrome 扩展”。
4. 刷新 YouTube 视频页，在播放器右上角点击“本地字幕”，选择显示模式并开始。

更新源码并重新构建后，必须在扩展管理页点击“重新加载”，再刷新 YouTube。Chrome 可能继续使用旧版后台脚本，仅刷新网页不够。

## 开发验证

```powershell
uv sync --frozen --group dev
npm ci
npm run build
uv run pytest -q
npm test
```

默认同步方式的集成测试使用独立、静音的 Chrome for Testing 和原创 720p 音视频，检查真实模型、媒体时钟调度和帧统计。独立测试后端位于 18775，不占用日常识别会话。

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\runtime\browsers"
uv run playwright install chromium
uv run python -m scripts.sync_smoke
```

兼容采集另用 `scripts.capture_smoke` 检查释放视频轨道后音频仍继续；它在播放前核验测试进程系统静音，失败就中止，不加载模型、不修改日常浏览器音量。

真实 BBC 音轨的三个区间已验证中英字幕均提前准备好；受控播放中 98 次采样没有越过对应字幕区间。首次后台准备仍需时间。完整质量样本集和 20 分钟连续运行仍待验收。

音轨解析采用本地 BgUtils 播放验证助手处理所遇到的 YouTube 403，使用固定源码版本，缓存留在 E 盘项目内。安装要求 Node.js 22+，不需要 Docker 或导出浏览器登录信息；受限来源仍可能无法读取。
