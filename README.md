# ReplayLab 0.1

从操作视频恢复带证据的浏览器工作流，经人工审核和执行验证后导出 Agent Skill。

开发中。已实现本地视频 / 公开媒体链接 → FFmpeg 抽帧 → 视觉模型接口 → React Flow 编辑 → Playwright 执行 → Skill 导出的首轮代码。

**已验证本地手工工作流的执行、断言失败停止、Skill 导出及脚本重放；尚未接入实际视觉模型验证视频识别。**

```bash
uv sync --extra dev --locked
source .venv/bin/activate
playwright install chromium ffmpeg
cd apps/web-workbench && npm ci && npm run build
cd ../..
replaylab serve
```

另需系统 `ffmpeg` / `ffprobe`。工作台默认地址为 `http://127.0.0.1:8765`，令牌位于 `.replaylab/token`。无模型演示和真实分析命令见快速开始。

完整安装、模型配置和演示见 [快速开始](docs/quickstart.md)。开发边界见 [实施状态](docs/status.md)。

- [开源依赖复用](docs/dependencies.md)
- [必要验证记录](docs/validation.md)
- [延期测试清单](docs/testing-backlog.md)

遵循 [Karpathy 开发约定](AGENTS.md)，仅做当前改动必要的验证；全面测试由项目所有者主动提出后开展。

MIT License。外部运行时与依赖遵循各自许可证。
