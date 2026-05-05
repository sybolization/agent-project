# Agent 项目架构技术报告

> 基于 Anthropic《Scaling Managed Agents: Decoupling the brain from the hands》三层架构范式

---

## 目录

1. [概述与背景](#1-概述与背景)
2. [三层架构映射：Session 层](#2-三层架构映射session-层)
3. [三层架构映射：Harness 层](#3-三层架构映射harness-层)
4. [三层架构映射：Sandbox / Tool 层](#4-三层架构映射sandbox--tool-层)
5. [Phase 层与错误层级体系](#5-phase-层与错误层级体系)
6. [架构进化时间线](#6-架构进化时间线)
7. [关键架构决策 (ADR)](#7-关键架构决策-adr)
8. [架构健康度评估与未来方向](#8-架构健康度评估与未来方向)

---

## 1. 概述与背景

### 1.1 项目目标

本项目是一个基于 LLM 的通用 Agent 系统，核心理念来源于 Anthropic 在《[Scaling Managed Agents: Decoupling the brain from the hands](https://www.anthropic.com/engineering/managed-agents)》一文中提出的 Managed Agents 三层架构设计。项目在 Session / Harness / Sandbox 三层模型基础上，扩展了 Phase（阶段）系统作为配置 + 策略中间层，并引入 Hook 系统和容器化 Subagent 机制。

自项目启动以来，经历了 9 轮架构级改进（对应 `agent/.trae/specs/` 下 9 个 spec 目录），核心目标是使项目架构逐步对齐 Anthropic 文章的三层范式。

### 1.2 Anthropic 文章核心架构原理

Anthropic 文章的核心洞察：将 Agent 系统虚拟化为三个稳定接口，使每层的实现可独立替换而不影响其他层。

| 层 | 接口 | 职责 | 不变性 |
|---|---|---|---|
| **Session** | `getSession(id)` / `emitEvent(id, event)` | 追加式事件日志，持久化存储 | 接口不变，存储方式可变 |
| **Harness** | `wake(sessionId)` / `run()` | 唯一执行循环，协调 LLM ↔ Tool | 接口不变，循环逻辑可变 |
| **Sandbox (Tool)** | `execute(name, input) → string` | 纯执行单元，无状态 | 接口不变，执行器可变 |

**关键架构原则**：

1. **Session 在 Harness 外部** — Session 是独立持久化存储，不随 Harness 崩溃而丢失
2. **Harness 是唯一的执行循环** — 所有 LLM 调用、Tool 调用、Session 写入都通过 Harness
3. **Tool 是纯执行单元** — `execute(name, input) → string`，不应持有或写入 Session
4. **Harness 是无状态的** — 崩溃后可用 `wake(sessionId)` 从 Session 恢复
5. **"Pets vs Cattle"** — Harness 和 Sandbox 都应该是 Cattle（可替换），Session 使其可恢复

### 1.3 本报告目的与结构

本报告系统性地记录：

- 项目对 Managed Agents 三层架构的实现与映射（第 2-4 章）
- Phase 层与错误层级体系的设计（第 5 章）
- 所有架构改进的生命周期（第 6 章）
- 关键设计决策与代码证据（第 7 章）
- 架构健康度评估与未来方向（第 8 章）

所有架构论断附带具体的代码文件路径和行号引用，格式为 `[file.py:L123](file:///...)`，可直接跳转验证。

---

## 2. 三层架构映射：Session 层

### 2.1 组件映射

Session 层负责事件的持久化存储和会话恢复，是使 Harness "无状态可恢复"的关键基础设施。

| 组件 | 文件 | 与文章接口的映射 |
|---|---|---|
| `InteractionLogger` | [session/logger.py](file:///d:/Pycharm/project/agent/session/logger.py) | `emitEvent(id, event)` — 追加式 JSONL 事件日志 |
| `SessionMemory` | [session/memory.py](file:///d:/Pycharm/project/agent/session/memory.py) | 会话记忆持久化（TODO 状态、阶段信息） |

### 2.2 `InteractionLogger.emit()` — 事件追加写入

[logger.py:L409-L450](file:///d:/Pycharm/project/agent/session/logger.py#L409-L450)

`emit(event_type, data)` 是 Session 层的核心写入接口，构造标准事件并实时持久化：

```python
event = {
    "event_id": event_id,        # 自增序号: evt_000001
    "event_type": event_type,    # llm_call / tool_call / tool_result / state_change / phase_transition
    "timestamp": datetime.now().isoformat(),
    "session_id": self.session_id,
    "agent_id": ...,             # Agent 标识
    "iteration": ...,            # 当前迭代轮次
    "phase": ...,                # 当前阶段
    "parent_agent_id": ...,      # 父 Agent（Subagent 场景）
    "parent_session_id": ...,    # 父 Session（Subagent 场景）
    "data": data
}
```

**崩溃安全机制**：事件写入内存缓存 `self.events` 的同时，通过 `_jsonl_file` 句柄实时追加到 JSONL 文件，并调用 `flush()` 确保操作系统级持久化，使得即使进程崩溃，已写入的事件也不会丢失。

### 2.3 `InteractionLogger.emit_error()` — 错误链持久化

[logger.py:L452-L497](file:///d:/Pycharm/project/agent/session/logger.py#L452-L497)

`emit_error(error)` 处理异常记录，核心逻辑：

1. 判断 `error` 是否为 `AgentError` 实例，是则调用 `error.to_dict()` 获取包含完整 `error_chain` 的字典
2. 遍历 `__cause__` 链构建多层级错误上下文
3. 写入完整 traceback
4. 所有异常被 try/except 包裹，写入失败时 fallback 到 `logging.exception()`，不阻断主流程

### 2.4 `AgentLoop.wake()` — 会话恢复

[agent_loop.py:L97-L166](file:///d:/Pycharm/project/agent/agent_loop.py#L97-L166)

`wake(session_id)` 类方法从 JSONL 文件恢复完整会话状态：

1. 读取 `{session_id}.jsonl`，反序列化所有事件
2. 逆序遍历查找最后的 `state_change` 事件，恢复 `AgentState`
3. 验证关联的 Task 状态有效性
4. 构造新的 `AgentLoop` 实例，实现 Harness "无状态可恢复"

### 2.5 事件类型体系

[logger.py:L17-L29](file:///d:/Pycharm/project/agent/session/logger.py#L17-L29)

| 事件常量 | 含义 | 触发时机 |
|---|---|---|
| `EVENT_AGENT_STARTED` | Agent 启动 | `run()` 开始时 |
| `EVENT_AGENT_COMPLETED` | Agent 完成 | `run()` finally 块 |
| `EVENT_ITERATION_START` | 迭代开始 | 每轮循环开始时 |
| `EVENT_ITERATION_END` | 迭代结束 | `_run_post_step()` 中 |
| `EVENT_LLM_CALL` | LLM 调用 | `_handle_llm_call()` 中 |
| `EVENT_TOOL_CALL` | 工具调用 | `_handle_tool_execution()` 中 |
| `EVENT_TOOL_RESULT` | 工具结果 | 工具执行完成后 |
| `EVENT_STATE_CHANGE` | 状态变更 | `_transition_to()` 中 |
| `EVENT_THINKING` | 思考过程 | `_handle_text_response()` 中 |
| `EVENT_SPAWN_AGENTS_STARTED` | Subagent 启动 | `_run_subagents_with_containers()` 中 |

---

## 3. 三层架构映射：Harness 层

### 3.1 组件映射

Harness 层是系统的"大脑"，负责唯一的执行循环和 LLM ↔ Tool 协调。

| 组件 | 文件 | 与文章接口的映射 |
|---|---|---|
| `AgentLoop` | [agent_loop.py](file:///d:/Pycharm/project/agent/agent_loop.py) | Harness — 唯一执行循环 |
| `HookRunner` | [hooks/runner.py](file:///d:/Pycharm/project/agent/hooks/runner.py) | 扩展点 — PreToolUse / PostPhaseExecute 拦截 |

### 3.2 `AgentLoop.run()` — 唯一执行循环

[agent_loop.py:L359-L481](file:///d:/Pycharm/project/agent/agent_loop.py#L359-L481)

`run(user_input)` 是 831 行的主循环方法，内部实现 5 步执行管道：

```
┌──────────────────────────────────────────────────────────────┐
│  1. Build — 构建 system_prompt、获取可用工具列表                │
│  2. Compress — 按需压缩上下文 (compress_if_needed)             │
│  3. LLM Call — 调用 LLM (_handle_llm_call)                   │
│     ├── 返回 tool_calls → 进入第 4 步                          │
│     └── 返回纯文本 → _handle_text_response → 进入第 5 步       │
│  4. Tool Execution — 执行工具调用 (_handle_tool_execution)    │
│     ├── Phase 处理结果 (handle_tool_result / format_tool_result)│
│     ├── 状态更新 (_apply_tool_state_updates)                  │
│     └── 循环检测 / 阶段转换 / 任务完成                          │
│  5. Post Step — Hook 后处理 (_run_post_step)                  │
│     └── CONTINUE → 下一轮 / BLOCK → 终止 / INJECT → 注入输入   │
└──────────────────────────────────────────────────────────────┘
```

### 3.3 `_handle_llm_call()` — LLM 调用与错误处理

[agent_loop.py:L518-L554](file:///d:/Pycharm/project/agent/agent_loop.py#L518-L554)

核心逻辑：
- 调用 `self.llm.chat_interleaved(messages, system_prompt, tools)` 进行 LLM 推理
- 失败时构造 `LLMError` → `emit_error()` → 传入 Post Phase Hook 处理
- 成功时返回 `StepResult(llm_result=...)`

### 3.4 `_handle_text_response()` — 纯文本响应处理

[agent_loop.py:L556-L585](file:///d:/Pycharm/project/agent/agent_loop.py#L556-L585)

当 LLM 返回纯文本（无 tool_calls）时：
- 将 content 和 reasoning 追加到 `_context`
- 调用 `current_phase.build_no_tool_reminder()` 生成渐进式提醒
- 检测模型是否陷入循环（连续相同响应 → 强制终止）

### 3.5 `_handle_tool_execution()` — 工具调用执行

[agent_loop.py:L587-L689](file:///d:/Pycharm/project/agent/agent_loop.py#L587-L689)

遍历所有 tool_calls，逐项执行：

1. **循环检测**：`current_phase.check_command_loop()` 检查重复调用
2. **执行**：`self.tool_executor.execute_single()` 委托 Tool 层
3. **异常处理**：捕获 `ToolError` → `emit_error()` → 按 `fatal` 决定是否终止
4. **状态更新**：`_apply_tool_state_updates()` 执行指令模式状态修改
5. **结果格式化**：`current_phase.format_tool_result()` 生成 LLM 上下文消息
6. **阶段处理**：`current_phase.handle_tool_result()` 判断 TRANSITION / COMPLETE / ERROR

### 3.6 `on_child_event` — Subagent 事件回传

[agent_loop.py:L225-L230](file:///d:/Pycharm/project/agent/agent_loop.py#L225-L230)

```python
def on_child_event(event_type: str, data: dict) -> None:
    self._interaction_logger.emit(event_type, data,
        agent_id=self.state.agent_id,
        iteration=self.state.iteration_count,
        phase=self.state.phase.value)
self._on_child_event = on_child_event
```

此回调传递给 `ToolExecutor.execute_single()`，再传递给子 Agent。子 Agent 的所有事件通过此回调写入父 Harness 的 Session，实现事件流集中管理。

### 3.7 Hook 系统：CONTINUE / BLOCK / INJECT 控制流

[hooks/types.py:L9-L33](file:///d:/Pycharm/project/agent/hooks/types.py#L9-L33)

| 退出码 | 含义 | Harness 行为 |
|---|---|---|
| `CONTINUE (0)` | 正常继续 | 进入下一轮迭代 |
| `BLOCK (1)` | 阻止当前动作 | 终止循环，返回消息 |
| `INJECT (2)` | 注入补充消息 | 将消息作为下一轮输入 |

Hook 注册在 [agent_loop.py:L253-L286](file:///d:/Pycharm/project/agent/agent_loop.py#L253-L286)，5 个内置 Hook 处理器按优先级注册：
1. `CompleteStatusHook` — 处理 complete 状态
2. `TransitionStatusHook` — 处理阶段转换
3. `ErrorStatusHook` — 处理错误状态
4. `NeedsConfirmationStatusHook` — 处理确认需求
5. `DefaultStatusHook` — 默认兜底处理

---

## 4. 三层架构映射：Sandbox / Tool 层

### 4.1 组件映射

Tool 层是系统的"双手"，负责纯执行操作，不持有状态。

| 组件 | 文件 | 与文章接口的映射 |
|---|---|---|
| `ToolExecutor` | [tools/executors/executor.py](file:///d:/Pycharm/project/agent/tools/executors/executor.py) | `execute(name, input) → string` — 外观模式 |
| `ToolRegistry` | [tools/registry.py](file:///d:/Pycharm/project/agent/tools/registry.py) | 工具路由表 |
| `CommandExecutor` | [tools/lib/command_lib.py](file:///d:/Pycharm/project/agent/tools/lib/command_lib.py) | 命令执行子单元 |
| `CdpExecutor` | [tools/lib/cdp_lib.py](file:///d:/Pycharm/project/agent/tools/lib/cdp_lib.py) | CDP 操作子单元 |
| `SkillExecutor` | [tools/lib/skill_lib.py](file:///d:/Pycharm/project/agent/tools/lib/skill_lib.py) | 技能加载子单元 |
| `SubagentExecutor` | [tools/lib/subagent_lib.py](file:///d:/Pycharm/project/agent/tools/lib/subagent_lib.py) | 子代理子单元 |
| `TaskExecutor` | [tools/lib/task_lib.py](file:///d:/Pycharm/project/agent/tools/lib/task_lib.py) | 任务管理子单元 |

### 4.2 `ToolExecutor` 外观模式

[executor.py:L46-L55](file:///d:/Pycharm/project/agent/tools/executors/executor.py#L46-L55)

构造器不持有 `InteractionLogger`，仅持有：
- `skill_manager` — 技能管理
- `opencli_client` — 浏览器客户端
- `llm_client` — LLM 客户端（Subagent 场景使用）
- `state` — AgentState 引用（用于 `_register_tools()` 依赖注入）

这与 Round 2 的 "Tool 去 Session 化" 决策一致。

### 4.3 `execute_single()` — 执行流程

[executor.py:L144-L214](file:///d:/Pycharm/project/agent/tools/executors/executor.py#L144-L214)

单工具调用的完整执行管道：

```
验证 (阶段/权限) → PRE_TOOL_USE Hook → Registry 路由 → 子执行器执行 → 返回结果
```

关键设计：
- **阶段验证**：`validate_tool_for_phase()` 确保工具在当前阶段可用
- **Hook 拦截**：`PRE_TOOL_USE` Hook 可 BLOCK / INJECT
- **路由表**：`ToolRegistry` 按工具名分发到对应子执行器
- **event_callback 注入**：将 `event_callback` 注入到 handler，供 `spawn_agents` 使用

### 4.4 指令模式状态修改

Tool 层不直接修改 `AgentState`，而是返回带指令 key 的结果字典。由 Harness 层的 `_apply_tool_state_updates()` 统一执行。

支持的指令 key（[agent_loop.py:L691-L746](file:///d:/Pycharm/project/agent/agent_loop.py#L691-L746)）：

| 指令 Key | 触发动作 |
|---|---|
| `should_update_todo` | 更新单个 TODO 状态 |
| `should_set_todos` | 设置 TODO 列表 |
| `should_record` | 记录操作到 action_history |
| `should_complete_todos` | 批量完成 TODO |
| `should_transition_to_report` | 转换到 REPORT 阶段 |
| `should_stop` | 仅记录日志 |

示例 — `_execute_update_todo()` 返回结果（[executor.py:L297-L313](file:///d:/Pycharm/project/agent/tools/executors/executor.py#L297-L313)）：

```python
return {
    "type": "todo_updated",
    "todo_id": todo_id,
    "old_status": old_status,
    "new_status": status,
    "content": todo_content,
    "progress": progress,
    "should_update_todo": True,   # 指令: 更新 TODO
    "should_record": True,        # 指令: 记录操作
    "record_data": {
        "tool_name": "update_todo",
        "arguments": {"todo_id": todo_id, "status": status},
        "result_summary": f"TODO [{todo_id}] {old_status} -> {status}"
    },
    "message": f"TODO [{todo_id}] {todo_content}: {old_status} -> {status}"
}
```

### 4.5 Container 系统 — 容器化 Subagent 执行

[executor.py:L485-L616](file:///d:/Pycharm/project/agent/tools/executors/executor.py#L485-L616)

`_run_subagents_with_containers()` 使用 `ContainerManager` 管理容器的创建与销毁：

1. 根据任务数量创建容器池
2. `asyncio.gather()` 并行执行所有子任务
3. 通过 `event_callback` 回传 `spawn_agents_started` 事件
4. 聚合所有子 Agent 结果，返回 `completed / failed` 统计

这是项目对文章 Sandbox 可替换性原则的具体实现。

### 4.6 工具定义与注册

工具通过 `ToolManager` 统一管理定义（[tools/manager/manager.py](file:///d:/Pycharm/project/agent/tools/manager/manager.py)），`ToolExecutor._register_tools()` 通过 `setattr` 依赖注入将子执行器注入工具实例（[executor.py:L112-L140](file:///d:/Pycharm/project/agent/tools/executors/executor.py#L112-L140)）。

---

## 5. Phase 层与错误层级体系

### 5.1 Phase 层概述

Phase 层是项目特有的（Anthropic 文章中无此概念），作为 Harness 与 Tool 之间的"配置 + 策略"中间层。

### 5.2 Phase 架构

| 组件 | 文件 | 角色 |
|---|---|---|
| `BasePhase` | [phases/base.py](file:///d:/Pycharm/project/agent/phases/base.py) | 抽象基类，定义新接口 |
| `DefaultPhase` | [phases/default_phase.py](file:///d:/Pycharm/project/agent/phases/default_phase.py) | 默认模式阶段 |
| `CollectPhase` | [phases/collect_phase.py](file:///d:/Pycharm/project/agent/phases/collect_phase.py) | 信息收集阶段 |
| `PlanPhase` | [phases/plan_phase.py](file:///d:/Pycharm/project/agent/phases/plan_phase.py) | 计划制定阶段 |
| `ExecutePhase` | [phases/execute_phase.py](file:///d:/Pycharm/project/agent/phases/execute_phase.py) | 任务执行阶段 |
| `ReportPhase` | [phases/report_phase.py](file:///d:/Pycharm/project/agent/phases/report_phase.py) | 结果汇报阶段 |

### 5.3 关键演进：从"影子 Harness"到配置提供者

Phase 最初持有 LLM、ToolExecutor 和 InteractionLogger 引用，创建了"影子 Harness"。经过 Round 2 重构后，退化为纯粹的配置 + 策略提供者。

当前 `BasePhase.__init__()` 仅接受两个参数：

[base.py:L22-L31](file:///d:/Pycharm/project/agent/phases/base.py#L22-L31)

```python
def __init__(self, prompt_builder, state):
    self.prompt_builder = prompt_builder
    self.state = state
    self._no_tool_call_rounds = 0
    self._handlers: dict[str, ToolResultHandler] = {}
    self._formatters: dict[str, ToolResultFormatter] = {}
    self._register_default_handlers()
```

### 5.4 新接口方法

#### `handle_tool_result(tool_name, result, state) → PhaseStatus`

[base.py:L42-L54](file:///d:/Pycharm/project/agent/phases/base.py#L42-L54)

处理工具执行结果并返回阶段状态。由 Harness 在每次工具执行后调用（[agent_loop.py:L665](file:///d:/Pycharm/project/agent/agent_loop.py#L665)），返回 `PhaseStatus.CONTINUE / TRANSITION / COMPLETE / ERROR`。

#### `format_tool_result(tool_name, result) → str`

[base.py:L56-L68](file:///d:/Pycharm/project/agent/phases/base.py#L56-L68)

格式化工具结果为 LLM 上下文消息。由 Harness 在每次工具执行后调用（[agent_loop.py:L657](file:///d:/Pycharm/project/agent/agent_loop.py#L657)），结果写入 `_context` 供后续 LLM 调用使用。

#### `build_no_tool_reminder() → str`

[base.py:L134-L157](file:///d:/Pycharm/project/agent/phases/base.py#L134-L157)

渐进式提醒：当 LLM 多轮不调用工具时，生成逐步升级的提醒消息。

#### `cleanup_context()`

[base.py:L166-L172](file:///d:/Pycharm/project/agent/phases/base.py#L166-L172)

阶段转换前的清理逻辑。由 Harness 在 `_transition_to()` 中调用（[agent_loop.py:L778-L780](file:///d:/Pycharm/project/agent/agent_loop.py#L778-L780)）。

#### `check_command_loop(tool_name, args, history, max_repeat) → PhaseResult | None`

[base.py:L174-L195](file:///d:/Pycharm/project/agent/phases/base.py#L174-L195)

命令循环检测：使用 `tool_name:args` 作为 key 跟踪重复调用次数，超过阈值时返回错误 PhaseResult。由 Harness 在每次工具执行前调用（[agent_loop.py:L609](file:///d:/Pycharm/project/agent/agent_loop.py#L609)）。

#### `available_tools → list[dict]`

[base.py:L203-L207](file:///d:/Pycharm/project/agent/phases/base.py#L203-L207)

抽象属性，返回当前阶段可用的工具列表，由子类实现。

### 5.5 渐进式提醒机制

Phase 维护 `_no_tool_call_rounds` 计数器：

- **第 1 轮**：温和提醒 — "请使用工具来完成你的任务。"
- **第 2 轮**：具体指导 — 带工具建议，如 "如果你需要搜索信息，请使用 web_search 工具"
- **第 3+ 轮**：紧急警告 — "⚠ 你已经连续 N 轮没有调用任何工具了！…否则任务将被终止。"

代码引用：[base.py:L134-L157](file:///d:/Pycharm/project/agent/phases/base.py#L134-L157)

计数器在 Harness 每次成功调用工具后通过 `current_phase.note_tool_called()` 清零（[agent_loop.py:L655](file:///d:/Pycharm/project/agent/agent_loop.py#L655) 和 [base.py:L159-L164](file:///d:/Pycharm/project/agent/phases/base.py#L159-L164)）。

### 5.6 Handler/Formatter 分发机制

Phase 持有 `_handlers: dict[str, ToolResultHandler]` 和 `_formatters: dict[str, ToolResultFormatter]`，分发优先级为：

```
Phase 本地注册 → ToolManager 工具自带 → 默认 handler/formatter
```

代码引用：

- `_dispatch_tool_result()`：[base.py:L86-L108](file:///d:/Pycharm/project/agent/phases/base.py#L86-L108)
- `_dispatch_format_result()`：[base.py:L110-L132](file:///d:/Pycharm/project/agent/phases/base.py#L110-L132)

### 5.7 错误层级体系

完整的异常类型体系定义在 [errors.py](file:///d:/Pycharm/project/agent/errors.py)，涵盖 5 个层级共 14 个异常类型（含基类）。

| 层级 | 异常类型 | 关键字段 |
|---|---|---|
| LLM | `LLMError(AgentError)` | `layer="llm"`, `provider`, `status_code`, `response_body` |
| Tool | `ToolError(AgentError)` + 5 个子类 | `layer="tool"`, `tool_name`, `arguments` |
| Harness | `HarnessError(AgentError)` + 3 个子类 | `layer="harness"`, `iteration`, `phase` |
| Session | `SessionError(AgentError)` + 1 个子类 | `layer="session"` |
| Container | `ContainerError(AgentError)` + 2 个子类 | `layer="tool"`, `container_id` |

**Tool 层子类**（[errors.py:L131-L148](file:///d:/Pycharm/project/agent/errors.py#L131-L148)）：
- `CommandExecutionError` — 命令执行失败
- `CdpExecutionError` — CDP 操作失败
- `SubagentExecutionError` — 子代理执行失败
- `SkillLoadError` — 技能加载失败
- `ToolNotFoundError` — 工具未找到

**Harness 层子类**（[errors.py:L197-L206](file:///d:/Pycharm/project/agent/errors.py#L197-L206)）：
- `PhaseExecutionError` — 阶段执行异常
- `ContextCompressionError` — 上下文压缩失败
- `LoopDetectionError` — 循环检测

**Session 层子类**（[errors.py:L226-L227](file:///d:/Pycharm/project/agent/errors.py#L226-L227)）：
- `LogPersistenceError` — 日志写入失败

**Container 层子类**（[errors.py:L250-L254](file:///d:/Pycharm/project/agent/errors.py#L250-L254)）：
- `ContainerStartupError` — 容器启动失败
- `ContainerStateError` — 容器状态异常

### 5.8 错误传播契约

```
Tool 层失败 → raise ToolError 子类
    ↓
Harness 捕获 → enrich context (iteration/phase/agent_id) → emit_error()
    ↓                                      ↕
    ├── fatal=True → re-raise PhaseExecutionError
    └── fatal=False → 记录错误后继续执行
    ↓
Session 层: emit_error() 遍历 __cause__ 链，持久化完整 error_chain 到 JSONL
```

代码引用：

- Tool 层失败处理：[agent_loop.py:L633-L645](file:///d:/Pycharm/project/agent/agent_loop.py#L633-L645)
- Harness 层异常捕获：[agent_loop.py:L451-L458](file:///d:/Pycharm/project/agent/agent_loop.py#L451-L458)
- 非 AgentError 包装：[agent_loop.py:L459-L471](file:///d:/Pycharm/project/agent/agent_loop.py#L459-L471)
- `AgentError` 基类设计：[errors.py:L13-L106](file:///d:/Pycharm/project/agent/errors.py#L13-L106) — 含 `add_context()` 链式追加、`capture_traceback()`、`_chain_errors()` 遍历 `__cause__` 链、`to_dict()` 序列化

---

## 6. 架构进化时间线

本项目自启动以来，已完成 9 轮架构级改进，按时间顺序记录如下：

### Round 1: `uv-install-deps` — 基础设施搭建

- **目标**：通过 `uv` 包管理器安装项目依赖
- **架构意义**：建立可复现的开发环境，为后续所有架构工作提供基础
- **Spec**：`agent/.trae/specs/uv-install-deps/`

### Round 2: `fix-session-harness-architecture` — 核心架构对齐 ⭐（里程碑）

- **目标**：消除"影子 Harness"问题，使架构对齐 Anthropic 文章
- **诊断**：发现系统存在 3 条并行的 Session 写入路径（Harness / Phase / ToolExecutor），LLM 402 错误等异常不被记录
- **解决方案**：
  - Phase 层去执行化 → 退化为配置 + 策略提供者
  - Tool 层去 Session 化 → 移除 `InteractionLogger` 引用，改为 `event_callback` 回传
  - Harness 层集中化 → `AgentLoop.run()` 成为唯一执行循环和 Session 写入者
  - 新增 `LLMError` 异常类型、`PhaseStatus` 枚举、`EventCallback` 类型
- **影响范围**：7 个文件，含 Phase 层全面接口重构
- **验证**：pytest 151 测试通过，架构写入约束 8 项全部通过
- **Spec**：`agent/.trae/specs/fix-session-harness-architecture/`

### Round 3: `agent-loop-decoupling-analysis` — 代码整洁度提升

- **目标**：在不改变架构骨架的前提下清理技术债务
- **发现问题**：
  - `_execute_tool()` 和 `_is_tool_available()` 为死代码（107 行）
  - `_handle_tool_execution` 131 行承担 8+ 职责
  - 状态更新逻辑在两处重复
- **解决方案（方案 A — 最小化清理）**：
  - 删除弃用代码
  - 提取 `_apply_tool_state_updates()` 消除重复
  - 提取 `_log_tool_result()` 简化循环体
  - 阶段清理逻辑移入 Phase 子类的 `cleanup_context()`
- **效果**：`agent_loop.py` 从 941 → 771 行，`_handle_tool_execution` 从 131 → 97 行
- **Spec**：`agent/.trae/specs/agent-loop-decoupling-analysis/`

### Round 4: `fix-test-imports` — 测试基础设施修复

- **目标**：修复测试文件的导入路径（`src.agent.*` → `agent.*`）
- **架构意义**：清理历史遗留的 `src/` 前缀和孤立测试文件，使测试套件可运行
- **Spec**：`agent/.trae/specs/fix-test-imports/`

### Round 5: `fix-tool-circular-import` — 循环导入修复

- **目标**：修复 Tool 架构改进引入的循环导入
- **根因**：`phases/__init__.py` → Phase 文件 → `from ..tools import get_tool_manager` → 触发 `tools/__init__.py`（未完成初始化）
- **解决方案**：4 个 Phase 文件改为直接路径导入 `from ..tools.manager.manager import get_tool_manager`
- **Spec**：`agent/.trae/specs/fix-tool-circular-import/`

### Round 6: `fix-context-and-prompt-delivery` — 上下文与 Prompt 传递修复

- **目标**：修复架构重构后的 3 个关键缺陷
- **缺陷**：
  1. LLM 适配器忽略 `system_prompt`，导致 LM Studio 返回 "Context history must not be empty"
  2. 用户输入未写入 `_context`
  3. `_handle_llm_call` 中 `current_input` 为死代码
- **解决方案**：适配器注入 `system_prompt` 为 system 消息；AgentLoop 写入用户输入到 context
- **Spec**：`agent/.trae/specs/fix-context-and-prompt-delivery/`

### Round 7: `fix-logging-and-tool-availability` — 日志与工具可用性修复

- **目标**：修复 LLM 响应日志缺失和工具阶段可用性
- **缺陷**：
  1. `reasoning_content` 和 `content` 未记录到 JSONL
  2. `load_skill` 仅在 COLLECT 阶段可用但 agent 默认在 DEFAULT 阶段运行
  3. 工具结果日志中错误字段名不一致（`message` vs `error`）
- **解决方案**：日志增强、阶段可用性扩展、字段兼容
- **Spec**：`agent/.trae/specs/fix-logging-and-tool-availability/`

### Round 8: `fix-progressive-skill-loading` — 渐进式技能加载优化

- **目标**：修复技能加载流程中的信息截断和错误恢复不完整
- **缺陷**：
  1. Formatter 返回 200 字符预览导致信息不一致
  2. `load_skill` 错误仅返回 "not found"，无可用技能列表
  3. `load_reference` 错误同理
- **解决方案**：Formatter 返回完整内容；错误信息包含可用列表
- **Spec**：`agent/.trae/specs/fix-progressive-skill-loading/`

### Round 9: `fix-hidden-context-truncation` — 隐形上下文截断排查

- **目标**：全面排查并修复写入 LLM 上下文时的隐藏截断点
- **发现**：11 处截断点分三个严重级别
  - 致命级（4 处）：思考内容截断 1000 字符、参考文档截断 300 字符、命令输出截断 3000 字符、网页内容截断 8000 字符
  - 高危级（5 处）：子 agent 摘要 200 字符、行动历史摘要 200 字符、CDP 结果截断等
  - 中危级（2 处）：错误信息截断 800 字符、子 agent 结果截断 2000 字符
- **解决方案**：11 处截断限制全部提高或移除
- **Spec**：`agent/.trae/specs/fix-hidden-context-truncation/`

---

## 7. 关键架构决策 (ADR)

### ADR 1: Phase 去执行化（Round 2）

- **问题**：Phase 类同时持有 LLM、ToolExecutor、InteractionLogger 引用，创建了"影子 Harness"，导致错误绕过 Session 写入
- **决策**：Phase 退化为纯配置 + 策略提供者，不持有执行权。Harness 统一执行 LLM + Tool + Session 写入
- **证据**：[agent_loop.py:L359-L481](file:///d:/Pycharm/project/agent/agent_loop.py#L359-L481) — `run()` 是唯一执行循环；[phases/base.py:L22-L31](file:///d:/Pycharm/project/agent/phases/base.py#L22-L31) — `BasePhase.__init__()` 只接受 `prompt_builder` 和 `state`

### ADR 2: Tool 去 Session 化 + event_callback 模式（Round 2）

- **问题**：`ToolExecutor._run_subagents_with_containers()` 直接持有并写入 `InteractionLogger`，子 Agent 创建时传递 logger 引用 — 形成"影子 Harness #2"
- **决策**：ToolExecutor 移除 `_interaction_logger`。子 Agent 事件通过 `event_callback(event_type, data)` 回传父 Harness 统一写入
- **证据**：[executor.py:L46-L55](file:///d:/Pycharm/project/agent/tools/executors/executor.py#L46-L55) — 构造器无 `interaction_logger` 参数；[agent_loop.py:L225-L230](file:///d:/Pycharm/project/agent/agent_loop.py#L225-L230) — `on_child_event` 回调定义

### ADR 3: 指令模式状态修改（Round 2 + Round 3）

- **问题**：ToolExecutor 直接修改 `AgentState`，违反了"Tool 是纯执行单元"的原则
- **决策**：Tool 返回带指令 key 的结果（`should_update_todo` / `should_set_todos` / `should_record` / `should_complete_todos` / `should_transition_to_report`），由 Harness 的 `_apply_tool_state_updates()` 统一执行所有状态变更
- **证据**：[agent_loop.py:L691-L746](file:///d:/Pycharm/project/agent/agent_loop.py#L691-L746) — `_apply_tool_state_updates()`；[executor.py:L297-L313](file:///d:/Pycharm/project/agent/tools/executors/executor.py#L297-L313) — `_execute_update_todo()` 返回 `should_update_todo: True`

### ADR 4: Handler/Formatter 分发机制（Round 2）

- **问题**：Phase 需要根据工具名分发到不同的处理逻辑和格式化逻辑
- **决策**：Phase 持有 `_handlers: dict[str, ToolResultHandler]` 和 `_formatters: dict[str, ToolResultFormatter]`，优先级为 Phase 本地 → ToolManager → 默认
- **证据**：[base.py:L86-L132](file:///d:/Pycharm/project/agent/phases/base.py#L86-L132) — `_dispatch_tool_result()` 和 `_dispatch_format_result()`

### ADR 5: 渐进式无工具调用提醒（Round 2）

- **问题**：LLM 多轮不调用工具时，需要有逐步升级的提醒机制
- **决策**：Phase 维护 `_no_tool_call_rounds` 计数器，根据轮次返回不同紧迫度的提醒消息（第 1 轮温和，第 2 轮具体指导，第 3+ 轮警告终止）
- **证据**：[base.py:L134-L157](file:///d:/Pycharm/project/agent/phases/base.py#L134-L157) — `build_no_tool_reminder()`

### ADR 6: LLMError 异常类型（Round 2）

- **问题**：LLM API 错误（402 余额不足等）需要在本层级被正确分类和记录
- **决策**：新增 `LLMError(AgentError)`，`layer="llm"`，包含 `provider`、`status_code`、`response_body` 字段。默认 `fatal=False`（可重试）
- **证据**：[errors.py:L155-L173](file:///d:/Pycharm/project/agent/errors.py#L155-L173) — `LLMError` 定义；[agent_loop.py:L536-L547](file:///d:/Pycharm/project/agent/agent_loop.py#L536-L547) — LLM 失败时构造并 `emit_error`

### ADR 7: 上下文压缩作为架构中间件（贯穿所有轮次）

- **问题**：上下文窗口有限，大型任务可能导致越界
- **决策**：`ContextCompressor.compress_if_needed()` 在每次迭代前评估 token 使用量，超过阈值时触发压缩。压缩是架构横切关注点，不属于 Session / Harness / Tool 任何一层
- **证据**：[agent_loop.py:L393-L401](file:///d:/Pycharm/project/agent/agent_loop.py#L393-L401) — 压缩在 iteration 循环中作为前置步骤执行

### ADR 8: 完整上下文信息保留策略（Round 8 + Round 9）

- **问题**：多处 Formatter 和消息构造中存在隐藏的字符截断，导致 LLM 看到残缺信息做出错误决策
- **决策**：直接写入 LLM 上下文的所有信息不再截断；仅日志层保留合理截断（500 字符）
- **证据**：[agent_loop.py:L427-L428](file:///d:/Pycharm/project/agent/agent_loop.py#L427-L428) — 日志截断 500 字符；[agent_loop.py:L563](file:///d:/Pycharm/project/agent/agent_loop.py#L563) — 思考内容完整写入 `_context`（无截断）

---

## 8. 架构健康度评估与未来方向

### 8.1 接口隔离度验证

| 维度 | 状态 | 证据 |
|---|---|---|
| Phase 不持有 LLM | ✅ 已达标 | `grep "self.llm" phases/` → 0 matches |
| Phase 不持有 ToolExecutor | ✅ 已达标 | `grep "tool_executor.execute" phases/` → 0 matches |
| Phase 不持有 InteractionLogger | ✅ 已达标 | `grep "_interaction_logger" phases/` → 0 matches |
| ToolExecutor 不持有 InteractionLogger | ✅ 已达标 | 构造器无 `interaction_logger` 参数 |
| 唯一 Harness 执行循环 | ✅ 已达标 | `run()` 独占执行权 |
| 唯一 Session 写入者 | ✅ 已达标 | `emit`/`emit_error` 调用收敛到 `agent_loop.py` |

### 8.2 代码规模指标

| 指标 | 值 |
|---|---|
| `agent_loop.py` 总行数 | 831（Round 3 后从 941 缩减） |
| Phase 文件数 | 6（含 base.py） |
| Tool 子执行器文件数 | 5（lib/ 目录下） |
| 异常类型数 | 14（含基类） |
| 内置 Hook 处理器数 | 5 |
| Phase 5 子类全部实现新接口 | ✅ |
| pytest 测试可收集数 | 151 |

### 8.3 与文章架构的偏差

| 偏差项 | 说明 | 评估 |
|---|---|---|
| Phase 层 | 文章无此概念；项目特有的"配置 + 策略"中间层 | 合理扩展 |
| Hook 系统 | 文章未提及；属于 Harness 扩展点 | 合理扩展 |
| Container 系统 | 项目提供了容器化的 Sandbox 实现（`ContainerManager`） | 符合文章 Sandbox 可替换原则 |
| 上下文压缩 | 文章提及 "context resets" 应对 "context anxiety"；项目有完整实现 | 对齐 |
| Subagent 系统 | 容器内直接创建 AgentLoop（不同于文章 `execute(name, input) → string` 模式） | 已通过 `event_callback` 对齐 |

### 8.4 未来架构方向

1. **Sandbox 容器化深化**：当前 `_run_subagents_with_containers` 内联创建 `AgentLoop`，可进一步抽象为 `provision({resources})` + `execute(name, input) → string` 模式，更贴近文章接口设计

2. **Harness 恢复机制增强**：当前 `wake()` 已实现 Session 恢复，但压缩后的摘要可能丢失细节。可考虑保存压缩前的完整 transcript

3. **Hook 系统扩展**：当前 Hook 集中处理 `PostPhaseExecute`，可扩展到 `PreToolUse` / `PostToolUse` 拦截，提供更精细的执行控制

4. **Phase 动态注册**：当前 Phase 在 `_init_phases()` 中硬编码 5 个阶段类（[agent_loop.py:L303-L341](file:///d:/Pycharm/project/agent/agent_loop.py#L303-L341)），可改为插件式注册以支持自定义阶段扩展

---

> **报告生成日期**：2026-05-03
> **基于 Spec**：`agent/.trae/specs/architecture-technical-report/`
