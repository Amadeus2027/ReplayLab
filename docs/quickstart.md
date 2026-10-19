# 快速开始

当前支持从源码运行。Python 3.11+、Node.js 20.19+ / 22.12+ 和系统 FFmpeg（包含 ffprobe）是前置条件。建议先用 30–90 秒、画面文字清晰、单网页单标签页的视频。

## 安装

```bash
git clone https://github.com/Amadeus2027/ReplayLab.git
cd ReplayLab
uv sync --extra dev --locked
source .venv/bin/activate
playwright install chromium ffmpeg
cd apps/web-workbench
npm ci
npm run build
cd ../..
```

无 uv 时可以使用 `python -m venv .venv` 和 `pip install -e '.[dev]'`；此方式按 pyproject 约束解析，未锁定到 uv.lock。FFmpeg 的系统安装方式依操作系统而异，例如 Ubuntu `apt install ffmpeg`。

## 模型配置

```bash
export REPLAYLAB_BASE_URL='https://你的兼容服务地址/v1'
export REPLAYLAB_API_KEY='你的密钥'
export REPLAYLAB_MODEL='你的视觉模型名称'
```

需要支持 Chat Completions、图片 data URL 和 `response_format=json_object` 的视觉模型。可以接入具备这些接口的华为云端点；本项目尚未验证具体华为云模型，不能假定所有端点兼容。`.env.example` 仅作说明，程序不会自动加载 `.env`。

v0.1.1 已用 DeepSeek 官方接口完成一次受控真实录屏的端到端验证：设置 `REPLAYLAB_BASE_URL=https://api.deepseek.com`、`REPLAYLAB_MODEL=deepseek-flash`，再通过环境安全配置密钥。最小样本、实际结果与复现命令见 [v0.1.1 实验](validation/v0.1.1/README.md)。

每次分析最多发送 32 张 1280 像素宽画面，使用单次模型请求、不自动重试。请先确认该服务的图片数/上下文限制和计费方式。未配置模型时，抽帧可以保留，但不会生成替代或模拟工作流。

公开视频链接目前只接受可直接下载的 HTTP(S) 视频格式：入口、重定向和后续请求均过滤内网地址；累计读取上限 200 MB，整个获取任务上限 120 秒。不支持代理、HLS/DASH、压缩 HTTP 响应或依赖外部下载器/JavaScript 的站点；这些情况请上传本地视频，不要移除环境代理来绕过网络限制。详见 [媒体获取边界](review-fixes.md#fix-3有界媒体获取)。

## 分析、审核、执行

```bash
replaylab analyze /absolute/path/demo.mp4 --start-url https://你的复现网页
# 也可以将视频路径替换为 yt-dlp 支持的公开链接。
replaylab serve
```

打开 `http://127.0.0.1:8765`，在侧栏“设置”中连接本机服务。按终端提示，从本机 `.replaylab/token` 文件取出连接令牌；令牌只在当前浏览器会话中保存，不通过 URL 传递，也不常驻主页面。

1. 点击“新建视频流程”，粘贴公开视频链接或上传视频，再填写 Agent 应在哪个网站操作。上传支持 MP4、MOV、WebM、MKV、AVI、M4V，最大 200 MB。
2. 在黑色流程画布中查看视频还原的步骤，也可切换“步骤列表”。右侧展示选中步骤的画面、时间范围、操作内容与完成检查。
3. 有原视频时点击画面上的播放按钮，播放器会跳转到当前步骤时间点。可以编辑当前步骤的描述、输入内容和授权要求；元素文字定位收在高级设置中。
4. 核对待确认项，补全后明确标记“已核对”。点击“让 Agent 执行”，在确认窗口填写需要的参数，核对运行条件和敏感操作，授权本次执行。
5. Agent 执行期间，画布根据后端真实步骤状态显示进度。完成后可以查看执行后的截图；失败时停止并显示原因。
6. 当前版本执行通过后，点击“保存为 Skill”下载 ZIP，其中包含使用说明、工作流、验证报告和运行脚本。

其他页面或 CLI 更新同一流程时，工作台会同步新版本；若正在编辑/确认则提示冲突，要求“加载最新流程”后重新核对。保存、审核、执行都绑定所见版本，后端拒绝旧版本请求。人工导入、视频分析生成、人工修改与来源未核验使用明确标签，生成来源不代表执行验收通过。

用户界面不要求手写 JSON、选择器或任务 ID。高级的流程结构、最终断言等调整仍可通过本地 `workflow.json` 和 CLI 完成。初版原视频播放器点击后会读取本地服务上的视频到浏览器内存，尚未优化大文件流式播放。

运行环境中安装了 Chromium 时，可设置 `REPLAYLAB_BROWSER_EXECUTABLE=/usr/bin/chromium` 使用它。默认无头浏览器；CLI `--headed` 可显示浏览器窗口（需要图形环境）。

也可只使用 CLI；用实际任务 ID 替换 TASK_ID：

```bash
replaylab visualize TASK_ID
# 先查看/编辑 .replaylab/TASK_ID/workflow.json，再审核。
replaylab approve TASK_ID
replaylab execute TASK_ID --params-file /path/to/parameters.json
# 存在敏感动作且你已明确授权时，再添加 --confirm-sensitive。
replaylab export-skill TASK_ID ./exports/my-workflow
python ./exports/my-workflow/scripts/run.py --params-file /path/to/parameters.json
```

没有参数时省略 `--params-file`。目录名称须符合 Agent Skills 名称约束：1–64 位小写字母、数字和单连字符。导出的 Skill 依赖已安装的 ReplayLab 运行时，不包含浏览器二进制或模型。

模型调用失败后，已有帧会保留。修正配置后可复用证据，不重新下载：

```bash
replaylab compile TASK_ID --start-url https://你的复现网页
```

每次重放打开新的隔离会话，不自动读取用户 Cookie；当前不支持登录态导入、跨标签页任务或断点恢复。暂停后重新执行从第一步开始，提交操作前应核对外部系统状态，避免重复提交。审核后直接手工改 JSON 的 CLI 用户须重新审核；工作台保存会自动使审核失效。

## 无模型本地演示

```bash
python -m http.server 8877 --bind 127.0.0.1 --directory examples/demo
# 在另一个终端、同一个项目根目录：
replaylab import-workflow examples/demo/workflow.json
replaylab serve
```

示例是手工编写的 5 步工作流，明确标注没有视频证据。审核后执行，授权本地“创建项目”动作，再导出重放。它验证执行器和编辑器，不代表视频识别已通过。

开发期间需要一次必要的录制/抽帧/执行/导出重放检查时，可以运行：

```bash
python scripts/smoke_demo.py
```

该脚本自己启动临时演示服务并录制真实浏览器视频，使用手工流程核对基础链路，不调用模型。临时服务在脚本结束时关闭，任务中的临时 URL 之后不能直接重放。产物保留在 `.replaylab/TASK_ID/`。

## 产物与开发

- `workflow.json`：唯一工作流协议；JSON Schema 位于 `schemas/workflow.schema.json`。
- `frames.json` / `frames/`：时间戳及画面证据。
- `model-response.txt`：实际模型原始输出，供定位协议错误。
- `inference.json` / `inference-attempts/`：当前及历史调用的响应 ID、模型、耗时、token 用量与证据摘要，不含密钥。
- `workflow.generated.json`：模型首次生成的流程快照；审核修改 `workflow.json`，不要改写该快照。
- `timings.json`：获取、抽帧、编译和总分析耗时。
- `execution/report.json` / `execution/*.png`：执行耗时、步骤结果及截图。
- 导出目录：`SKILL.md`、`workflow.json`、`verification.json`、`scripts/run.py`。

`replaylab validation-report TASK_ID` 汇总模型证据、人工修改与实际执行。`replaylab execute` / `run-workflow` 支持可选 `--expect-file`，用外部提供的 Assertion 数组检查独立最终状态。实验工具只有在真实模型溯源、新会话执行和 Skill 重放都有效，且均通过独立断言时才报告完整通过；普通执行报告不自动代表真实视频逆向验收通过。

任务目录、截图、参数文件和令牌可能包含私人内容；本地任务目录与 `.env` 已排除出 Git。请将自行创建的参数文件放在任务目录等不会提交的位置。

前端开发可在 `apps/web-workbench` 运行 `npm run dev`，同时启动 `replaylab serve`。API 固定监听 loopback，开发服务通过 Vite 代理访问 API；默认只允许本机 5173 的开发来源和同源工作台。
