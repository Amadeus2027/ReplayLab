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

每次分析最多发送 32 张 1280 像素宽画面，使用单次模型请求、不自动重试。请先确认该服务的图片数/上下文限制和计费方式。未配置模型时，抽帧可以保留，但不会生成替代或模拟工作流。

## 分析、审核、执行

```bash
replaylab analyze /absolute/path/demo.mp4 --start-url https://你的复现网页
# 也可以将视频路径替换为 yt-dlp 支持的公开链接。
replaylab serve
```

打开 `http://127.0.0.1:8765`。按终端提示，从本机 `.replaylab/token` 文件取出令牌填入工作台。令牌只在浏览器当前会话中保存，不通过 URL 传递。

1. 选择任务，点击节点查看视频证据。
2. 修改步骤后点击“应用步骤编辑”，再“保存修改”。可展开完整工作流编辑器调整顺序、前置条件和最终断言。
3. 补齐缺失内容，解决后移除对应的待确认项。核对所有步骤及允许网站后点击“审核通过”。
4. 填写参数，例如 `{"project_name":"我的项目"}`。若有已获授权的敏感操作，勾选本次确认。
5. 点击执行，查看通过、失败或暂停结果。只有当前版本执行通过才能导出 Skill。

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
- `timings.json`：获取、抽帧、编译和总分析耗时。
- `execution/report.json` / `execution/*.png`：执行耗时、步骤结果及截图。
- 导出目录：`SKILL.md`、`workflow.json`、`verification.json`、`scripts/run.py`。

任务目录、截图、参数文件和令牌可能包含私人内容；本地任务目录与 `.env` 已排除出 Git。请将自行创建的参数文件放在任务目录等不会提交的位置。

前端开发可在 `apps/web-workbench` 运行 `npm run dev`，同时启动 `replaylab serve`。API 固定监听 loopback，开发服务通过 Vite 代理访问 API；默认只允许本机 5173 的开发来源和同源工作台。
