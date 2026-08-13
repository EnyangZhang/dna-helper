# DNA Helper 架构说明

本文描述当前实现，而不是未来设计。用户安装和操作说明见项目根目录的 [README](../README.md)，已知问题与修复状态见 [2026-08-11 审计报告](audit-2026-08-11.md)。

## 系统边界

DNA Helper 由四层组成：

1. **MXU v2.1.3**：读取 Project Interface v2 配置，提供控制器、配置、任务列表、启动/停止、日志和截图界面。
2. **MaaFramework v5.10.4**：负责截图、模板识别、Pipeline 调度和 Win32 输入。
3. **Pipeline JSON**：描述页面状态、识别优先级、点击链、技能链和长期监控。
4. **Python Agent**：处理 Pipeline 不适合表达的窗口焦点恢复、动态轮次日志、运行时重开决策、共享进度状态和 Telegram 后台监听。

普通识别与点击应优先留在 Pipeline；只有需要系统 API、动态文本或运行时图修改时才使用 Agent。

## 桌面接口

`assets/interface.json` 声明：

- 一个 `Win32-Foreground` 控制器。
- 窗口类名正则 `^UnrealWindow$`。
- 窗口标题正则 `^\s*二重螺旋\s*$`。
- 截图方式 `PrintWindow`。
- 鼠标、键盘输入方式 `Seize`。
- “日常挂机”和“监控”两个任务分组。
- Python Agent 启动命令 `python agent/main.py`。

`permission_required: true` 表示桌面版需要管理员权限。项目没有 `run.py` 旁路入口；所有依赖自定义动作的任务都必须让 MXU 启动 AgentServer。

当前桌面包仍依赖系统 PATH 中的 `python` 和已安装的 `maa` Python 包。复制 `dist/DNAHelper` 到一台没有相同 Python 环境的电脑，UI 可以启动，但 Agent 自定义动作不可用。

## 用户任务和预设

当前有三个用户任务：两个游戏任务位于“日常挂机”分组，一个可独立保活或自动让行的监听启动任务位于“监控”分组：

| 任务 | 模式 | 轮次 | 技能 | 高台判断 |
|---|---|---:|---:|---:|
| 密函无尽加速 | 无尽 | 无 | 无 | 无 |
| 密函无尽加速 | 驱离 | 1–9999，默认 1 | 可选 | 可选 |
| 普通无尽加速 | 扼守 | 1–999，默认 1 | 可选 | 无 |
| 普通无尽加速 | 无尽 | 无 | 无 | 无 |
| 普通无尽加速 | 驱离 | 1–9999，默认 1 | 可选 | 可选 |
| 进度监控 | 无 | 无 | 无 | 无 |

新建配置提供两个互斥用途的独立预设：

- `CipherAFK` / “密函挂机”：先加入 `ProgressMonitor`，再加入 `CipherEndlessBoost`。
- `NormalAFK` / “普通挂机”：先加入 `ProgressMonitor`，再加入 `NormalEndlessBoost`。

`ProgressMonitor` 在预设中必须排在对应游戏任务之前。MXU 会先把每项 `Calling post_task: entry=...` 与返回的 `task_id` 写入当前 `debug/mxu-tauri.log`；Agent 用自身 `task_id` 定位本轮监控提交记录，并在最多 500ms 的只读重试窗口内检查其后的已提交入口。若存在 `RewardConfirmEntry` 或 `NormalEndlessEntry`，它把 `ProgressMonitorLog.next` 动态覆盖为空；否则保留基础 Pipeline 的保活路径。该判断不调用 `MaaTaskerGetTaskDetail`、不访问不存在的 Maa 任务 ID、不依赖任务选项，因此已保存的旧预设无需迁移。预设仍不得同时启用两个游戏任务，否则排在第一位的长期任务不会自然结束。预设定义在 `resource/tasks/preset/AFK.json`，不得通过修改用户生成的 `config/` 实现。

用户可见的新能力必须：

- 加入用户指定的任务分组；游戏任务使用 `DailyAFK` / “日常挂机”，监听启动任务使用 `Monitor` / “监控”。
- 使用正式中文名称和清晰的中文说明。
- 不显示未解析的本地化键。
- 不通过 `default_check: true` 绕过新建配置的预设选择。

## Pipeline 资源组织

```text
assets/resource/base/pipeline/
  RewardConfirm.json          # 密函无尽、密函驱离结算
  NormalEndlessBoost.json     # 普通扼守、无尽、驱离和轮次重开
  CharacterControl.json       # HUD、高台判断、E/Q 与输入代理
  ProgressMonitor.json        # 启动 Telegram 监听并按队列自动保活/让行

assets/resource/tasks/
  CipherEndlessBoost.json     # 密函模式和技能开关覆盖
  NormalEndlessBoost.json     # 普通模式、轮次和技能覆盖
  ProgressMonitor.json        # “监控”分组的正式任务定义
  LiseExpelSkillCast.json     # 共享技能选项
  preset/AFK.json             # 监控在前、游戏任务在后的两个挂机预设
```

基础 Pipeline 提供可复用节点；任务选项通过 `pipeline_override` 替换 `next`、`on_error`、`enabled`、延迟、重复次数和日志。维护时必须按“基础节点 + 当前模式覆盖 + 当前子选项覆盖”的最终结果分析，不能只阅读基础文件。

## 进度监控启动任务

UI 的“监控”分组提供正式任务“进度监控”，它会自动选择两种运行方式：

- 独立运行：`ProgressMonitorLog` 转入自循环的 `ProgressMonitorKeepAlive`，任务保持运行，直到 UI 停止。
- 队列引导：Agent 从 MXU 的当前提交日志确认后续 `RewardConfirmEntry` 或 `NormalEndlessEntry`，把 `ProgressMonitorLog.next` 覆盖为空并完成当前任务。

两个内置预设都把它作为第一个启用任务，后面才是对应的密函或普通长期任务：

```text
ProgressMonitorEntry
→ Agent 自定义动作 progress_monitor_start
→ 启动 Telegram 长轮询、发送与 30 分钟定时状态线程（已启动时保持幂等）
→ ProgressMonitorLog
→ 检测到后续游戏任务：当前任务结束，继续预设中的游戏任务
→ 未检测到后续游戏任务：进入 ProgressMonitorKeepAlive，等待 UI 停止
```

独立运行且监听成功启动时，Agent 把 `DNA Helper 监控已开启\n无任务` 放入非阻塞发送队列。队列引导模式不发送该消息，避免在紧接着的正式游戏任务启动通知前误报“无任务”。

`agent/main.py` 只注册 Agent 动作，不在 UI 启动时自动开启 Telegram；监听生命周期由“进度监控”任务显式启动。缺少有效本机配置或启动异常时，该任务记录“已跳过”；队列引导仍成功结束且不得阻塞后续游戏任务，独立运行则保留 UI 停止能力。Token 和 Chat ID 只从环境变量或 Git 忽略的 `config/telegram.json` 读取。

## 局内 / 局外状态边界

左下角角色血条 `combat_health_bar.png` 是单向局内证据。局外或边界未知监控先检查血条；连续 3 帧命中后确认局内。血条消失不能单独确认局外，因为 Q 动画等战斗状态可能临时隐藏 HUD。局内业务监控在血条缺失后进入无超时的边界未知等待：候选顺序为“血条、该模式合法的局内按钮、局外专属按钮、空闲兜底”。合法局内按钮可以继续当前局内流程，只有局外专属按钮命中后才进入局外动作链。候选是在同一 Pipeline 轮询中的优先级列表，不是真正的多线程。

| 功能 | 局内候选 | 局外候选 |
|---|---|---|
| 密函无尽 | 第一页确认、继续挑战、Space 确认 | 无 |
| 密函驱离＋技能开启 | 血条、高台小地图、第一页确认 | 再次进行、Space 确认 |
| 密函驱离＋技能关闭 | 第一页确认 | 再次进行、Space 确认 |
| 普通无尽 | 继续挑战、确认选择 | 无 |
| 普通扼守＋技能开启 | 血条、继续挑战、确认选择 | 再次进行、开始挑战 |
| 普通扼守＋技能关闭 | 继续挑战、确认选择 | 再次进行、开始挑战 |
| 普通驱离＋技能开启 | 血条、高台小地图 | 再次进行、开始挑战 |
| 普通驱离＋技能关闭 | 无 | 再次进行、开始挑战 |

密函驱离和普通扼守/驱离支持从局内或局外任意页面启动。任务入口在状态未知时允许一次性同时探测血条和结算按钮；完成首次分类后严格使用分区监控。边界未知节点只能加入当前模式合法的局内按钮：普通扼守保留“继续挑战 / 确认选择”，普通驱离不加入任何扼守按钮，密函驱离保留第一页确认。技能结束后使用独立的 post-skill 边界节点并保留本副本技能锁：血条重新出现只恢复监控，不会再次进入技能链。密函无尽和普通无尽本身没有局外流程，保持原有纯局内链。

## 密函状态机

### 无尽

```text
RewardConfirmEntry
→ 第一页“确认选择”三连击
→ “继续挑战”三连击
→ 第三页“Space 确认选择”三连击
→ RewardConfirmEntry
```

三个识别区域和点击坐标：

| 页面 | 模板 | ROI | 点击坐标 |
|---|---|---|---|
| 第一奖励页 | `confirm_choice.png` | `(500,520,300,130)` | `(620,607)` |
| 继续挑战 | `continue_challenge.png` | `(700,400,420,150)` | `(900,500)` |
| 第三奖励页 | `space_confirm_choice.png` | `(760,380,360,150)` | `(920,480)` |

每个按钮执行三次输入，间隔 50ms。第三页点击完成后重新进入第一页监听，任务由用户手动停止。

### 驱离

`CipherMode=Expel` 将入口改为一次性状态路由：

```text
CipherExpelEntryMonitor
├─ 连续 3 帧血条 → CipherExpelMonitor（局内）
├─ 第一奖励页 → 完成局内结算后进入局外
└─ 再次进行 / Space 确认 → CipherExpelOutsideMonitor（局外）

CipherExpelMonitor（局内）
├─ 第一奖励页 → 结算链
├─ 技能开启且连续确认 HUD → 本副本唯一一次技能链
└─ 血条消失 → 边界未知等待
   ├─ 血条恢复 → 返回 CipherExpelMonitor
   └─ 再次进行 / Space 确认 → 确认局外并进入局外动作链

技能链结束
→ CipherExpelSettlementMonitor
→ 第一奖励页“确认选择”
→ CipherPostSkillOutsideMonitor

局外监控
├─ “再次进行”三连击 (920,640)
├─ Space 确认三连击
└─ 连续 3 帧血条 → 返回对应局内监控
```

技能关闭时，`CipherExpelMonitor` 的局内业务按钮候选只有第一奖励页，血条门控只负责确认局内，不进入技能节点；血条缺失后只用“再次进行 / Space 确认”确认局外。技能开启时每个副本只执行一次；`LiseSkillCastEnd` 转入 post-skill 状态，因此角色血条持续存在、短暂消失后恢复或按键失败都不会在同一副本重新触发。

密函驱离的“副本轮次”与普通驱离使用相同的完成轮次语义，但使用独立节点和计数器：

```text
检测到“再次进行”
→ CipherExpelRoundQuota 的 hit_count +1
→ 记录“已完成第 N / 总轮数”
→ N >= 总轮数：CipherExpelFinished 停止任务
→ N < 总轮数：点击“再次进行”
                → 点击副本外 Space 确认
                → 进入下一轮
```

任务入口、血条确认、技能释放、第一页确认和 Space 确认都不计数。只有局外识别到“再次进行”才表示完成一轮。

## 普通状态机

### 完成轮次语义

普通扼守和普通驱离的“副本轮次”表示**已完成副本数**，唯一计数触发点是识别到“再次进行”：

两者使用独立输入约束：普通扼守为 1–999，普通驱离为 1–9999；范围差异不得改变下述完成轮次语义。

```text
NormalEndlessAgainDetected
→ 对应 RoundQuota 的 hit_count +1
→ Agent 写入“已完成第 N / 总轮数”
→ Agent 选择下一节点
   ├─ N >= 总轮数 → StopTask
   └─ N < 总轮数 → “再次进行”三连击
                       → 等待“开始挑战”
                       → “开始挑战”三连击
```

任务入口、HUD 三帧确认、技能释放和“开始挑战”均不计数。技能开关不得改变轮次定义。

`NormalOutsideMonitor` 和重开阶段的 `NormalEndlessWaitStartChallenge` 都只包含局外候选与血条边界。前一步点击未生效时会重试；“开始挑战”被手动点击或漏识别但游戏已加载时，三帧血条链会恢复到当前模式的局内节点。

`round_logger.py` 使用：

- `context.get_hit_count(...)` 读取完成轮数。
- `context.override_pipeline(...)` 动态写入当前日志。
- `context.override_pipeline(...)` 将决策节点的 `next` 改为重开链或结束节点。

### 扼守

`NormalMode=Endless` 在代码中代表界面上的“扼守”：

- `NormalEndlessMonitor` 只监控局内“继续挑战”和“确认选择”。
- `NormalOutsideMonitor` 只监控局外“再次进行”和“开始挑战”。
- 血条门控只负责确认局内；血条缺失后的边界未知状态仍轮询“继续挑战 / 确认选择”，并只由局外专属按钮确认是否真的进入局外。
- 技能开启时，局外到局内的三帧血条确认进入本副本唯一一次技能链。

未达到轮次上限时依次点击“再次进行”和“开始挑战”。技能开启后，新一轮必须重新连续确认 HUD 才能进入技能延迟；技能结束后进入 `NormalHoldPostSkillInsideGate` / `NormalHoldPostSkillMonitor`。这组节点及其边界未知空闲节点都处理局内按钮；局外专属按钮命中后才进入重开链。血条恢复只回到 post-skill 节点，因此同一副本不会再次释放。完成重开后才重新允许释放。

任务入口先进入局外分类监控，因此从“再次进行”页面启动时仍优先进入完成轮次与重开流程；若实际已在副本中，连续三帧血条会切入局内。

### 无尽

`NormalMode=Infinite` 是纯局内按钮模式：

- 只识别“继续挑战”和“确认选择”。
- 每次由 `focus_guard_action` 一次完成三连击。
- 不识别“再次进行”。
- 不统计局外副本轮次，但持续累计局内逻辑轮次。
- 不进入 HUD 或技能链。
- 没有自然结束节点；`progress_state.increment_stage()` 只在本次任务的局内计数首次到达 99 时返回里程碑信号，由 Agent 发送一次通知，Pipeline 和监控继续运行。

### 驱离

`NormalMode=Expel` 的局内没有确认按钮：

- 技能关闭：局内没有业务按钮；血条缺失后进入边界未知等待，只有“再次进行”或“开始挑战”命中才确认局外。
- 技能开启：连续三帧血条进入本副本唯一一次技能链；技能结束后转入 post-skill 状态，血条恢复不会重新释放。
- 局外识别“再次进行”后按完成轮次语义计数。
- 未达到配额时复用普通重开链，等待并点击“开始挑战”。

## 技能状态机

技能入口适用于密函驱离、普通扼守和普通驱离。共同流程：

```text
Frame1: combat_health_bar.png
→ 50ms
Frame2: combat_health_bar.png
→ 50ms
Frame3: combat_health_bar.png
→ 战斗 HUD 就绪
→ 普通延迟或高台分支
→ 技能顺序路由
  ├─ 默认：E（可禁用）→ Q（可禁用）
  └─ Q 在前：Q（可禁用）→ Q 后触发间隔 → E 连点（可禁用）
→ LiseSkillCastEnd
```

战斗 HUD 模板参数：

- 模板：`CharacterControl/combat_health_bar.png`，尺寸 `146×17`。
- ROI：`(90,675,180,40)`。
- 阈值：`0.85`。
- 原始战斗截图中的匹配位置为窗口坐标约 `(98,684)`；ROI 留有少量窗口捕获偏差余量。

默认技能参数：

| 参数 | 密函驱离 | 普通扼守 | 普通驱离 |
|---|---:|---:|---:|
| 技能触发延迟 | 2000ms | 2000ms | 2000ms |
| E 开关 | 开 | 开 | 开 |
| E 次数 | 2 | 2 | 2 |
| E 间隔 | 1000ms | 1250ms | 1000ms |
| Q 开关 | 开 | 开 | 开 |
| Q 在 E 前释放 | 默认关 | 默认关 | 默认关 |
| Q 后触发间隔 | 2000ms | 2000ms | 2000ms |
| 仅高台 E | 默认关 | 不提供 | 默认关 |

顶层“是否开启技能”默认关闭；表中的 E/Q 默认值只在用户开启技能后生效。

三帧血条识别只负责确认战斗 HUD 已就绪；Q 图标不再参与触发或复核。一旦进入技能链，E/Q 是否执行只由选项开关决定。

每个 Q 节点都会通过焦点保护动作连续发送 3 次 Q，发送间隔固定为 100ms；前置和后置 Q 使用同一机制。

E 连续点击的每次底层按键成功后都会记录 `第 N / 总次数`，序列级日志仍负责标记整组 E 的开始和结束。

技能顺序默认是 `E → E 间隔 → Q`。只有 E、Q 都开启时才显示“Q 在 E 前释放”；开启后才继续显示“Q 后触发间隔”，执行顺序变为 `Q → Q 后触发间隔 → E 连点`。E 连点间隔与 Q 后等待分别配置，最后一个 E 后不再增加无用途的等待。

### 高台分支

密函驱离和普通驱离可以开启“仅高台释放 E”：

1. 连续确认 HUD 后立刻进入 300ms 高台识别窗口。
2. 命中模板则锁定高台；超时则锁定非高台。
3. 锁定结果后才等待完整的用户配置延迟。
4. 高台执行已开启的 E/Q；非高台跳过 E，只执行已开启的 Q。

高台模板参数：

- 模板：`CharacterControl/high_platform_map.png`，尺寸 `146×146`。
- ROI：`(15,48,165,165)`。
- 阈值：`0.75`。
- `green_mask: true`。

当前分支在延迟结束后不会重新确认页面或 Q 状态，这是审计中的未解决项，不得在文档中描述成已有保护。

## 输入和焦点恢复

所有实际输入最终仍由 MaaFramework 的原生 `Click` 或 `ClickKey` 完成。页面三连击通常采用：

1. 前两次由普通 Pipeline 节点执行。
2. 第三次进入 `focus_guard_action`。
3. Agent 通过 `Context.run_action(proxy_node)` 调用一个原生输入代理。
4. 前台监控线程持续记录最近的非游戏窗口和鼠标虚拟屏幕坐标；输入后调用 `ClipCursor(None)`，再尝试恢复该窗口。
5. 仅当窗口恢复成功时调用 `SetCursorPos` 恢复鼠标位置；坐标允许为负数，以支持主屏左侧或上方的显示器。

E/Q 也由 `focus_guard_action` 分别调用 `FocusGuardEKeyProxy` 和 `FocusGuardQKeyProxy`。

这些代理节点虽然不一定从任务入口的静态 `next` 图可达，却是 Agent 的真实动态入口，不能作为死节点删除。普通重开链的 `NormalEndlessRestartByClick` 同样由 `round_logger.py` 动态选择。

焦点恢复属于尽力执行：

- Windows 可能拒绝 `SetForegroundWindow`。
- 只维护一组最近候选窗口和对应鼠标位置。
- 短暂弹窗可能覆盖原恢复目标。
- 恢复过程会暂时禁止监控线程刷新候选快照，避免窗口刚切回时用游戏点击位置覆盖用户原坐标。
- 窗口恢复失败时不会移动鼠标，避免游戏仍在前台时产生意外指针跳转。
- 当前返回值只反映游戏输入是否成功，恢复失败不会使自定义动作失败。

## 进度状态与 Telegram 查询

`progress_state.py` 是 Maa 自定义动作和 Telegram 后台线程共享的进度源。状态通过 `RLock` 保护，并尽力原子替换到 `config/progress_status.json`；持久化失败不得中断自动化。

进度维度遵循 README 的业务定义：

- 局内轮次由成功完成的逻辑“继续挑战”或密函无尽结算循环推进，每组三连击只记录一次。
- 局外副本轮次是“已完成副本数”，只由普通扼守、普通驱离和密函驱离原有的 `RoundLogger` 在识别到“再次进行”后写入。
- `Start Challenge` 成功后只把状态切回运行并清零局内进度，不增加局外副本轮次。
- 密函驱离的 Space 确认只表示已重新进入下一轮，不重复增加已完成数。

`focus_guard_start` 从任务和轮次选项接收 `progress_mode`、`progress_total`、`progress_stage_total`。密函无尽循环会重复进入任务入口，因此使用 Maa `task_id` 去重初始化和启动通知。密函无尽和普通无尽没有自然成功事件：`advance_cipher_cycle()` / `increment_stage()` 仅在对应局内计数由 98 增至 99 时返回 `True`，`focus_guard_action` 据此调用 `notify_infinite_99_completed()`；计数继续到 100 及以后时不再触发，且不停止游戏任务或 Telegram。

`telegram_bot.py` 仅在 `ProgressMonitorStart` 被执行且存在有效 `config/telegram.json` 或对应环境变量时启动。打开或重启 UI 本身不会启动监听。接收轮询、消息发送和定时调度使用三个独立守护线程；定时线程第一次等待 1800 秒后把 `progress_state.format_status()` 的结果放入现有发送队列，之后每 1800 秒重复。它不直接调用网络接口也不修改进度。网络失败采用退避重试，不得阻塞 Pipeline 输入。只响应 `allowed_chat_id`，Token 与状态文件都位于已被 Git 忽略的 `config/`。

`ProgressMonitorLifecycle` 通过 MaaFramework 的 `TaskerEventSink` 接收 UI 任务生命周期。独立运行时，`ProgressMonitorEntry` 收到 `Tasker.Task.Failed` 表示用户从 UI 停止任务，此时关闭监控；队列引导正常完成产生的 `Succeeded` 必须忽略，否则后续游戏任务无法使用监听。`RewardConfirmEntry` 或 `NormalEndlessEntry` 收到 `Tasker.Task.Succeeded` 时，从 `progress_state` 读取当前模式，生成包含正式任务名和模式的“任务已完成”消息，再把它作为 `telegram_bot.stop(final_message=...)` 的最终消息；`Tasker.Task.Failed`（包括 UI 停止）只调用无最终消息的停止，不得误报完成。只有停止调用确实从运行态切到停止态时才打印“监听已停止”，因此未选择监控时结束游戏任务不会产生消息或误导日志。当前运行实例的停止事件立即唤醒可中断等待并清空未发送队列；最终完成消息使用配置快照和独立的一次性守护线程发送，不依赖已停止的主发送队列，也不阻塞 Maa 生命周期回调。已经进入系统网络调用的请求允许在自身超时内返回，但停止后不再处理其结果。每次重新开始时创建新的停止事件和线程，避免快速停止后重启复用旧线程。

## 坐标与识别约束

- 所有模板、ROI 和点击坐标以 `1280×720` 控制器截图为基准。
- 桌面版目前只按窗口类名和标题连接，没有强制尺寸校验。
- 模板必须由无损截图裁剪，只保留稳定特征。
- 不应把奖励内容、轮次数、动态倒计时等易变区域放进模板。
- 固定坐标只能在先识别当前页面后使用。
- 页面识别优先级高于空闲自循环节点。

## 长期监控

多个长期节点使用：

```json
{
    "post_delay": 50,
    "max_hit": 10000000
}
```

这能覆盖很长的日常运行，但不是真正无限。按纯 50ms 下限计算约 5.8 天后会耗尽，实际还包含识别耗时。需要真正无限监听时，应先确认 MaaFramework 的停止语义并统一替换，不能只在个别节点删除 `max_hit`。

当前非高台和 HUD 等待仍有部分使用 `timeout → on_error` 表达正常分支，MaaFramework 会为其生成 `debug/on_error` 截图。这是已知设计债。

## Agent 动态目标

`tools/validate_project.py` 中的 `DYNAMIC_PIPELINE_TARGETS` 是 Agent 动态节点的显式清单，覆盖：

- `focus_restore.py` 通过 `Context.run_action` 调用的点击和按键代理。
- `round_logger.py` 通过 `Context.override_pipeline` 选择的普通重开入口。

`progress_monitor.py` 注册 `progress_monitor_start` 自定义动作，但不通过 `Context.run_action` 跳转其他节点；它只覆盖 `ProgressMonitorLog` 的本次日志内容并始终成功返回。

修改 Agent 中的节点名映射时必须同步更新该清单。可达性分析必须从用户任务入口和动态目标共同出发；只遍历静态 `next` 会误删真实运行节点。

## 校验规则

`python tools/validate_project.py` 当前检查：

- Project Interface 版本、控制器、任务分组和导入文件。
- 用户任务的直接中文标题与说明。
- 选项递归引用和预设任务引用。
- Pipeline 节点重名。
- 用户任务入口存在。
- Agent 动态目标存在。
- `next` / `on_error` 目标存在。
- `pipeline_override` 只覆盖现有节点。
- 从任务入口与动态目标出发不存在不可达节点。
- TemplateMatch 引用的模板文件存在。

校验器采用所有可选覆盖边的并集做保守可达性分析：节点只要在任一合法模式、子选项或 Agent 动态路径中可能使用，就应保留。

校验器仍未完整覆盖：

- 每一种最终覆盖组合是否存在禁用节点造成的立即死路。
- 点击坐标和 ROI 是否在 `1280×720` 内。
- 自定义动作参数和 Python 实现之间的通用类型契约。
- 所有运行时动态覆盖值是否都能由静态分析推导。

高风险状态机改动除基础校验外，还应针对模式 × 技能开关 × 高台开关 × E/Q 开关做组合路径测试。

## 构建与运行目录

`build_ui.py` 组装：

```text
dist/DNAHelper/
  DNAHelper.exe
  interface.json
  maafw/
  resource/
  agent/
```

桌面壳基于固定的 MXU v2.1.3 提交，通过 `tools/mxu-v2.1.3-log-retention.patch` 维护项目定制。`tools/build_custom_mxu.ps1` 负责验证基线、应用补丁并生成 release 可执行文件；`build_ui.py` 不允许静默回退到没有这些定制命令的官方 MXU。

构建会保留 `config/` 和 `debug/`，但会先删除旧 `agent/`、`maafw/`、`resource/` 再复制新文件，因此不是事务式构建。DLL 被正在运行的 UI 占用时可能中途失败并留下半成品。构建前必须退出 UI；构建失败后应重新完整构建。

日志清理边界固定为解析后的 `<exe-dir>/debug`：程序目录、日志根目录和每个递归子项都通过 `symlink_metadata`、规范化路径和 Windows reparse-point 属性校验。任一项异常即拒绝整次删除。自动清理在启动时删除超过 14 天的文件；手动“完全清空日志”写入同目录标记并重启，在日志初始化前递归清空，避免 Windows 当前日志占用造成漏删。

源码资源发生变更但暂时不能完整构建时，只有在明确确认运行库完整的前提下才允许机械同步 `resource/` 和 `agent/`。交付前必须验证 `assets` 与 `dist/DNAHelper` 中对应文件一致。

## 维护铁律

- 先识别状态，再执行动作。
- 动作链结束后回到明确监控节点。
- 轮次只表示已完成副本数，只在“再次进行”出现时增加。
- 每个副本的技能链最多进入一次。
- 血条只作为局内正证据；血条消失不得单独重置技能锁或确认局外。
- 技能触发延迟从连续三帧 HUD 确认后开始。
- 高台结果在延迟前锁定；文档必须明确当前不会在延迟后复核页面。
- 普通无尽模式不得接入轮次、重开或技能节点。
- 驱离局内不得误接扼守的确认按钮。
- 边界未知等待必须保留当前模式合法的局内按钮，不能因血条暂时消失漏掉稍后出现的结算按钮。
- 动态 Agent 目标不能按静态死节点删除。
- 新功能必须更新任务中文名称、说明、README、本文和校验覆盖。
- 修改后运行项目校验、Python 编译检查，并同步验证运行目录。
