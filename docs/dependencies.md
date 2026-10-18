# 开源复用决策

| 依赖 | 上游 | 当前用途 |
| --- | --- | --- |
| yt-dlp | https://github.com/yt-dlp/yt-dlp | 直接调用 Python API 获取支持站点的公开媒体 |
| FFmpeg | https://ffmpeg.org/ | 直接调用系统 CLI 解码、scene 检测和定点抽帧 |
| Playwright | https://github.com/microsoft/playwright-python | 浏览器定位、动作、自动等待、断言、截图与演示录制 |
| React Flow | https://github.com/xyflow/xyflow | 直接使用节点画布、连线、缩放控件 |
| Lucide | https://github.com/lucide-icons/lucide | 深色工作台的动作、导航及状态图标，避免自绘图标体系 |
| React / Vite | https://github.com/facebook/react / https://github.com/vitejs/vite | 工作台与构建 |
| FastAPI / Pydantic | https://github.com/fastapi/fastapi / https://github.com/pydantic/pydantic | 本机服务、输入约束与协议 Schema |
| OpenAI Python SDK | https://github.com/openai/openai-python | OpenAI 兼容视觉接口，不重复实现 HTTP SDK |
| Typer | https://github.com/fastapi/typer | CLI 参数、帮助和审核提示 |
| python-multipart | https://github.com/Kludex/python-multipart | FastAPI 视频上传表单解析 |

交互参考 [n8n](https://n8n.io/) 的流程画布和 [Gumloop](https://www.gumloop.com/) 的 Agent/工作流呈现。借鉴信息层级与交互模式，没有复制其品牌资源或业务源码。

自研范围仅为证据选取与关联、视觉编译提示和校验、语义目标适配、受约束工作流解释器、审核状态和验证后导出。没有复制上游项目源码。

初版直接复用 FFmpeg scene 滤镜，不再同时引入 PySceneDetect；未来只有当现有滤镜不能解决实际样本问题时再评估。语音、视觉执行回退和扩展尚未实现，不提前安装相应依赖。

Python 依赖固定在 `uv.lock`，前端固定在 `package-lock.json`。FFmpeg 与浏览器是外部运行时。对外分发前应按实际安装包核对许可义务，尤其是 yt-dlp 的打包发行物及 FFmpeg 构建选项；本仓库目前没有打包这些二进制，也没有完成发行物许可审计。
