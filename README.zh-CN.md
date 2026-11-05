# IT Companion：员工 IT 支持 Agent

本项目面向有 IT 问题的员工，通过多轮对话、工具调查、批准知识库步骤及人工交接提供支持。**员工、后台系统和执行动作均为合成或模拟；模型调用使用运行者自行配置的 API。**

## 安装与启动

需要 Python 3.11+，已使用 Python 3.13 验证。请在解压后的项目根目录运行。

macOS / Linux：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
cp .env.example .env
```

打开 `.env`，填写自己的 API key：

```dotenv
OPENAI_API_KEY=填写服务商签发的key
OPENAI_BASE_URL=https://api.anzhelyu.com/v1
OPENAI_MODEL=gpt-6.1-sol
AGENT_MODE=openai
```

然后启动：

```bash
.venv/bin/python scripts/run.py
```

打开 **http://127.0.0.1:8765**。终端按 Ctrl+C 停止服务；修改配置后需重启。

Windows PowerShell 使用 `py -3 -m venv .venv`、`.\.venv\Scripts\python.exe -m pip install -r requirements.lock`、`Copy-Item .env.example .env`，再运行 `.\.venv\Scripts\python.exe scripts/run.py`。

压缩包只提供空白 key 模板，不含 `.env` 或任何真实凭据。默认地址与 `gpt-6.1-sol` 是已验证的 OpenAI 兼容服务配置；请使用该服务签发的 key。也可以同时替换地址、模型、key，连接其他支持 Responses 与严格 JSON schema 输出的服务。不要假定不同供应商均支持相同模型名称。

本应用独立读取项目 `.env`，不读取 Codex 的全局配置或认证。项目配置优先于同名进程环境变量，空 key 也不会回退使用其他 key。未配置模型时可保存问题和创建本地交接，但不能智能诊断；`AGENT_MODE=offline` 可明确使用此模式。

## 使用流程

1. 左侧选择合成员工，点击“＋ 新会话”。切换员工时必须再次创建会话。
2. 在中间输入问题并发送。系统查询员工资料、相关状态，并选择后续知识库、历史或变更工具。
3. 聊天里先显示“当前判断 · 待验证”，再提供批准步骤、适用条件和结果检查方式。右侧可展开证据和交接记录。
4. 修复步骤完成后点击“已恢复”或“仍然失败”；仅收集信息的步骤等待继续补充，不要求虚假的恢复确认。
5. 出现申请卡片时，先核对操作、目标范围和用途，再点击“确认执行”或“取消”。提交权限申请后等待审批，不等于授予权限。
6. 需要人工时点击“人工协助”。交接保存已有上下文，但接收队列是本地模拟，无真实 IT 人员接收。
7. 同一员工的另一件问题使用“＋ 新问题”。通过“恢复会话”和“当前问题”找回历史，或“导出记录”下载原始 JSON。

## 功能与支持范围

- VPN：区分客户端、网络、认证和服务故障，结合已批准文档提供排查步骤。
- Okta：登录失败、重复重置无效、丢失 MFA 与可疑验证请求；高风险身份恢复转人工。
- 权限：检查本人已有权限，准备 Snowflake 生产只读或 Grafana viewer 的模拟审批申请。
- Salesforce：结合员工地点和多人受影响范围关联共享事件。
- Jenkins–Tableau：将上下游症状作为关联事件调查，核对维护变更，不擅自回滚生产。

知识库操作步骤按英文原文呈现，模型提问及判断可使用中文或英文。详细示例见 [使用手册](docs/user-guide.md)。

## 技术与执行边界

单 Agent 有界编排，模型负责选择下一步，程序负责工具、权限和状态。每轮最多 5 次模型决策、8 次工具调用、70 秒总预算。工具失败会保留缺失证据；拒绝的决策可在原预算内重新规划，不能绕过授权。

SQLite 保存案件与事件，FTS5/BM25 与术语别名支持小规模检索。五类数据包括知识库、状态、目录、解决历史和策略，另含维护变更。对员工已反馈失败的步骤保留关联记录，防止重复推荐。

浏览器的 HttpOnly cookie 提供本地会话隔离，演示身份选择不是企业 SSO。仅监听本地回环，使用单 worker。所有写入都是本地模拟；没有生产 SQL、shell、MFA 重置或直接授予权限工具。

## 测试与评测

```bash
.venv/bin/python -m pytest -q
# 以下真实模型命令需要配置 key，并会消耗 API 额度：
.venv/bin/python evals/run.py --live --case EVAL-001 --repeat 3
.venv/bin/python evals/run.py --live --repeat 3 --jobs 4
```

最终可见场景集为 40 场景各 3 次，共 120/120 检查通过；这不是任意现实问题的 100% 解决率。工程测试 87 项通过，真实模型浏览器流程 8 项通过。实测单轮耗时中位数约 13.237 秒，P95 约 23.827 秒。完整口径见 [评测说明](docs/evaluation.md)。

可选浏览器测试需另安装 `playwright` 并执行 `python -m playwright install chromium`；命令见英文 README。

## 假设、取舍和局限

合成场景时钟为 2026-11-04 09:00（Asia/Shanghai），上周五维护对应 2026-10-30。审计时间使用实际 UTC。数据、角色与权限均为虚构，不连接真实公司账号。

本期采用轻量模块、单进程 SQLite、词法检索和轮询，减少本地运行依赖。引用有效不代表语义一定正确；部分文档前提仍需模型及人工核对。长历史仅提供有限窗口，没有语义摘要；脱敏是尽力规则匹配，不是完整 DLP。`store:false` 不等于第三方承诺不保留请求。未提供企业级高可用、真实审批回调或真实人工工单接收。

后续优先完善独立评测与适用条件验证，再接入真实 SSO、只读 IT 数据源、审批回执、人工系统与监控。见 [架构说明](docs/architecture.md) 和 [生产化路线](docs/productionization.md)。
