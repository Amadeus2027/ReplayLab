# v0.1.1：真实视频到可执行 Skill

2026-10-19 完成一个受控网页场景的最小端到端验证。**使用真实 DeepSeek API 从录屏画面恢复工作流，未以手工步骤或模拟响应替代推理。**

## 实际结果

| 项目 | 结果 |
| --- | --- |
| 视频 | [41.08 秒录屏](../../../examples/real-video/source.webm)，1280×1200，16 帧 |
| 模型 | DeepSeek 官方 `deepseek-flash`；响应也返回该别名 |
| 原始步骤 | 5 步；顺序、动作、界面目标文字与输入值和独立参考一致（单个例子的精确匹配，不是总体准确率） |
| 人工处理 | 核对并清除 5 项不确定内容；0 个操作步骤改写；批准执行 |
| 分析耗时 | 19.89 秒，其中抽帧 4.797 秒、编译 15.089 秒（API 收据约 15.033 秒） |
| 首次执行 | 1.971 秒，5 步通过；3 项独立终态检查通过 |
| Skill 重放 | 实际运行导出的 `scripts/run.py`，1.717 秒；3 项独立检查再次通过 |
| 修正后调用用量 | 16,519 输入 / 3,119 输出，共 19,638 tokens，包含服务报告的推理用量 |
| 本轮真实 API 调用总数 | 2 次，共 37,379 tokens，含首轮失败；没有自动重试 |

分析时间不包含录制和人工审核时间，不能据此宣称完整用户任务快于视频两倍。没有查询账户账单，故只报告实际 token 用量，不把价目表估算当作实扣费用。

[官方模型说明](https://api-docs.deepseek.com/quick_start/pricing/)与[视觉接口](https://api-docs.deepseek.com/guides/vision/)说明 `deepseek-flash` 支持图像和 JSON 输出；2026-10-19 文档对应 DeepSeek V4.1 Flash。别名可能随服务更新，本报告保留服务实际返回的模型名。

## 输入与证据

模型只收到系统提示、输出 Schema、目标网址、视频长度、16 张带时间戳的画面。**没有收到录制脚本、参考动作、目标页面 DOM 或最终参考断言。**

- [完整调用收据](passed/inference.json)：响应 ID、耗时、token 用量、输入帧与输出摘要；不含密钥和 HTTP 头。
- [原始模型输出](passed/model-response.txt)与[首次生成的工作流](passed/workflow.generated.json)。
- [16 帧清单](passed/frames.json)及 `passed/frames/` 中的实际画面。
- [审核记录](passed/review-notes.json)与[审核后的工作流](passed/workflow.reviewed.json)。
- [独立参考对照](passed/reference-comparison.json)、[执行报告](passed/execution.json)、[Skill 重放报告](passed/skill-replay.json)。
- [本次实际导出的 Skill ZIP](passed/verified-skill.zip)，只适用于这个本地示例；执行需启动同一演示页面和已安装的 ReplayLab 运行时。
- [汇总验收报告](passed/validation.json)与[两个真实调用的汇总](model-calls.json)。

人工确认包括：本例保留视频中的字面项目名；连续输入按最终值合并；只需复现已出现的下拉选项；本地“创建”操作保留敏感标记并确认授权；列表条目只用于文本验证，无需推断点击角色。没有把原始输出中的待确认项静默删除。

独立检查验证创建的项目名称、优先级与提醒状态，搜索框中的名称，以及只创建一个项目。即使模型自己的断言全部通过，任一独立检查失败也会使执行报告失败。

## 首轮失败与必要修正

[失败调用收据](failed-protocol/inference.json)和[原始输出](failed-protocol/model-response.txt)保留了第一次实际推理。该次恢复了动作，但两处 `text` 断言使用了 `target:null`，被 Pydantic 拒绝，没有执行。

发现 Schema 当时只把 `target` 声明为可空，而真正的运行约束要求非 URL 断言具有目标。现已把条件约束写入 Schema，并补充提示。同时首段录屏采用了 Playwright 默认 800×562 视频尺寸，最终列表被裁切；改为显式 1280×1200 原生录制，完整呈现结果后重新录制和调用。第二次使用了新随机项目名，因此两次不算同一视频上的独立准确率样本。

失败视频亦保留在 `failed-protocol/source.webm`。没有修改失败输出使其“看起来成功”，也没有自动补造操作。

## 最小复现

按 [快速开始](../../quickstart.md) 安装依赖，在 shell 中配置下列变量；密钥通过本机环境管理，不放进文件或提交：

```bash
export REPLAYLAB_BASE_URL=https://api.deepseek.com
export REPLAYLAB_MODEL=deepseek-flash
# 在环境中安全配置 REPLAYLAB_API_KEY。

replaylab analyze examples/real-video/source.webm --start-url http://127.0.0.1:8891
```

记下任务 ID，检查实际 `workflow.json` 和帧证据。解决待确认项，保持原始 `workflow.generated.json` 不变，再批准：

```bash
replaylab approve TASK_ID
python scripts/validate_real_video.py verify TASK_ID --sample examples/real-video --confirm-sensitive
replaylab validation-report TASK_ID
```

`verify` 自己在 127.0.0.1:8891 临时启动受控示例页，在新会话执行并导出 Skill，再通过导出脚本重放；结束后关闭服务。若端口已占用，先停止冲突服务，不要把验证指向未知页面。它要求模型证据与视频摘要一致、流程已审核，不会自动替换工作流或跳过待确认项。

要新录制一个随机值样本（约 40 秒，仅在必要时执行），使用新的输出目录：

```bash
python scripts/validate_real_video.py record --output .replaylab/new-sample
```

之后按输出提示分析新视频，`verify --sample` 指向该目录。复现模型可能产生不同步骤或待确认项，需要如实审核。不要把参考答案传给模型。

## 深色界面后的复现

示例页与工作台已统一深色玻璃样式。历史视频不改色、不重新制作模型输出；将上述同一份已审核工作流在新的深色示例页执行，并实际运行之前导出的 Skill 脚本。两次均为 5 步通过、3 项独立检查通过，分别耗时 3.154 秒与 2.486 秒，新增模型调用为 0。

[汇总](dark-theme-replay/summary.json)、[执行报告](dark-theme-replay/execution.json)、[Skill 报告](dark-theme-replay/skill-replay.json)与[实际最终截图](dark-theme-replay/final-screen.png)单独保存，未覆盖原始验收记录。这仅证明同一个页面改版后的语义定位仍有效，不代表任意网站间迁移。

[必要界面检查](ui-checks.json)记录了 Chromium 桌面与 390px 窄屏的按钮、弹窗和步骤列表操作；不涉及新的模型调用或任务执行，不属于完整浏览器兼容测试。

## 验收边界

仅一个可控网页样本通过，不代表任意视频、登录态、跨网站或生产系统可靠。没有训练模型、增加桌面控制或运行大规模评测。必要检查是 3 项编译/溯源用例，以及一次实际浏览器的独立断言反例；模拟 API 的单元用例不计入上述真实调用证据。
