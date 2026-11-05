# 使用手册 / User Guide

## 页面操作

- **演示员工身份 → ＋ 新会话**：创建与该合成员工绑定的会话；单独更换下拉选项不会改变已有会话。
- **＋ 新问题**：同一员工的另一件问题。不要把独立问题混在一个案件中。
- **发送 ↑**：提交描述或回答必要追问。示例按钮仅填入文字，仍需发送。
- **调查工作区**：查看工具活动、来源、候选判断和人工交接。窗口宽度大于 1150px 可同时显示侧栏。
- **确认执行 / 取消**：在模拟申请卡片上核对用途及范围后操作。
- **已恢复 / 仍然失败**：提交员工验证反馈；仅在需要验证的状态出现。
- **人工协助**：创建本地交接记录，供后续分享，不向真实 IT 团队发送消息。
- **恢复会话 / 当前问题**：恢复持久化上下文。建议固定使用同一浏览器和 `127.0.0.1` 地址。
- **导出记录**：下载原始案件记录供审阅。

聊天中的“当前判断 · 待验证”是候选解释。其后步骤来自批准知识库，具体操作前应检查适用条件。记录中没有真实软件入口地址时，页面会说明这一点，不提供臆造下载链接。

## 示例问题

| 员工 | 可输入的问题 |
|---|---|
| Alex Chen | My VPN drops every 15 minutes. Normal internet is stable. |
| Alex Chen | My internet and VPN both disconnect on home Wi-Fi. What should I check? |
| Alex Chen | I forgot my Okta password and have not tried a reset. Please help. |
| Alex Chen | I already reset my Okta password, but login still fails. Please do not repeat that step. |
| Alex Chen | I lost my phone and cannot complete Okta MFA. What should I do? |
| Alex Chen | I keep receiving unexpected MFA prompts even though I am not signing in. |
| Alex Chen | I need Snowflake production reader access for a reporting project. Please submit an approval request. |
| Morgan Lee | I need Grafana viewer access for our team's monitoring dashboards. |
| Morgan Lee | Salesforce has been slow since yesterday for my Chicago coworkers as well. Is this a local issue? |
| Alex Chen | Since Friday maintenance, Jenkins jobs time out and downstream Tableau reports are stale. Investigate dependencies without rolling back production. |

Alex 的合成 VPN 版本为 5.0，已有 Grafana viewer 权限。Morgan 位于 Chicago，其地区存在合成 Salesforce 事件，且没有 Grafana viewer 权限。所有背景均可在 `data/fixtures.json` 审阅。

## 典型流程

VPN：选择 Alex、新会话、描述断连。查看目录、状态与 KB 证据；按批准步骤处理后反馈结果。未真实执行操作时，不应将界面反馈当成真实设备恢复。

权限：新问题描述 Snowflake 生产只读的业务用途。核对模拟申请并确认，状态进入等待审批，不代表已授予权限。

地区事件：选择 Morgan 并新建会话，描述 Chicago 多人 Salesforce 变慢。查看地区 incident，可能进入等待服务恢复；无恢复时间时不会承诺时间。

复杂故障：描述 Jenkins 与下游 Tableau 的同一时间线。可提供 job 名、首次失败时间和非敏感错误；相关变更只是候选关联。需要人工时交接保存上下文。

## 常见情况

- 已解决、已升级或等待审批后输入框禁用：用“＋ 新问题”处理另一件事。
- 有待确认动作时不能切换问题：先确认或取消。
- 模型询问问题：补充缺失的可观察事实，不提供密码、验证码、令牌或客户数据。
- 模型或中转接口不可用：上下文保留，可稍后重试或选择人工协助。
- 页面显示调查中：等待当前轮结束，不要反复发送；刷新可恢复持久化进度。
- 数据重置：停止服务器后删除本地 `var/`，再次启动会初始化新库。该操作会删除本机会话。
