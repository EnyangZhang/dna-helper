# DNA Helper 架构说明

本文描述当前实现，而不是未来设计。用户安装和操作说明见项目根目录的 [README](../README.md)，已知问题与修复状态见 [2026-08-11 审计报告](audit-2026-08-11.md)。

## 系统边界

皎皎币挂机正式固定按键序列以 **S 5000ms → D 100ms** 结束；校验器与运行 Pipeline 必须保持这两个长按值及顺序同步。

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

当前有四个用户任务：三个游戏任务位于“日常挂机”分组，一个可独立保活或自动让行的监听启动任务位于“监控”分组：

| 任务 | 模式 | 轮次 | 技能 | 高台判断 |
|---|---|---:|---:|---:|
| 密函无尽加速 | 无尽 | 无 | 无 | 无 |
| 密函无尽加速 | 驱离 | 1–9999，默认 1 | 可选 | 可选 |
| 普通无尽加速 | 扼守 | 1–999，默认 1 | 可选 | 无 |
| 普通无尽加速 | 无尽 | 无 | 无 | 无 |
| 普通无尽加速 | 驱离 | 1–9999，默认 1 | 可选 | 可选 |
| 皎皎币挂机 | 自动循环 | 1–999，默认 1 | 固定按键序列 | 目标小地图必选 |
| 进度监控 | 无 | 无 | 无 | 无 |

新建配置提供两个互斥用途的独立预设：

- `CipherAFK` / “密函挂机”：先加入 `ProgressMonitor`，再加入 `CipherEndlessBoost`。
- `NormalAFK` / “普通挂机”：先加入 `ProgressMonitor`，再加入 `NormalEndlessBoost`。

`ProgressMonitor` 在预设中必须排在对应游戏任务之前。MXU 会先把每项 `Calling post_task: entry=...` 与返回的 `task_id` 写入当前 `debug/mxu-tauri.log`；Agent 用自身 `task_id` 定位本轮监控提交记录，并在最多 500ms 的只读重试窗口内检查其后的已提交入口。若存在 `RewardConfirmEntry`、`NormalEndlessEntry` 或 `CoinAFKEntry`，它把 `ProgressMonitorLog.next` 动态覆盖为空；否则保留基础 Pipeline 的保活路径。该判断不调用 `MaaTaskerGetTaskDetail`、不访问不存在的 Maa 任务 ID、不依赖任务选项，因此已保存的旧预设无需迁移。预设仍不得同时启用两个游戏任务，否则排在第一位的长期任务不会自然结束。预设定义在 `resource/tasks/preset/AFK.json`，不得通过修改用户生成的 `config/` 实现。

用户可见的新能力必须：

- 加入用户指定的任务分组；游戏任务使用 `DailyAFK` / “日常挂机”，监听启动任务使用 `Monitor` / “监控”。
- 使用正式中文名称和清晰的中文说明。
- 不显示未解析的本地化键。
- 不通过 `default_check: true` 绕过新建配置的预设选择。

所有新功能的连续鼠标点击统一采用普通扼守式快速链：首节点识别并执行 Maa 原生 `Click`，后续点击均使用 `DirectHit + Click`；三连击的前两段各使用 50ms `post_delay`，第三击后以 `0ms` 进入 `DirectHit + focus_guard_finalize`。收尾动作只恢复窗口和鼠标并记录逻辑事件，绝不发送游戏输入。逻辑进度、轮次和成功日志只允许在收尾节点触发一次。禁止 Agent 发送鼠标点击，也禁止用单个 Agent 自定义动作内部的 `repeat` 代替该结构。普通扼守的主局内分支与技能后局内分支、密函和皎皎币现有点击链均遵守此结构；校验器枚举检查这些链，并全局拒绝基础 Pipeline 与任务覆盖中的任何 `kind: click`。任何不同次数或延迟的例外都必须记录原因并由校验器或测试固定。

所有 Pipeline 节点还必须显式声明 `rate_limit`、`pre_delay`、`post_delay`，禁止继承 MaaFramework 默认时序。即时路由、状态门控、输入代理和完成决策使用 `0 / 0 / 0`；长期或边界未知空闲轮询使用 `0 / 0 / 50`；连续 HUD 确认的前两帧使用 `0 / 0 / 50`、最后一帧使用 `0 / 0 / 0`。用户配置等待和限时识别窗口可以使用其他非负值，但必须写全三个字段并由文档及校验或测试说明。这个约束同时控制“页面出现到第一次点击”的延迟和点击链内部间隔，不能只验证后者。`tools/validate_project.py` 对全部节点强制检查字段存在且为非负数。

用户可见日志采用结果型事件模型。每个基础节点或任务覆盖最多配置一个正常 `focus` 事件；不为同一动作同时配置 `Node.Action.Starting` 和 `Node.Action.Succeeded`，也不输出“准备发送”“已记录结果”“延迟结束”等状态机内部过程。一次逻辑按钮操作、一次分支判断或一组 Q 输入只输出一个成功结果。E 是有意保留的例外：Agent 在每次底层 E 成功后动态写入 `第 N / 总次数`，因此 E 节点本身不得再配置序列开始或序列完成日志。轮次、异常、完成、监控启停和输入失败日志不属于冗余过程，必须保留。校验器同时检查基础 Pipeline 与任务 `pipeline_override`，阻止过程型日志重新进入运行版。

## Pipeline 资源组织

```text
assets/resource/base/pipeline/
  RewardConfirm.json          # 密函无尽、密函驱离结算
  NormalEndlessBoost.json     # 普通扼守、无尽、驱离和轮次重开
  CharacterControl.json       # HUD、高台判断、E/Q 与输入代理
  ProgressMonitor.json        # 启动 Telegram 监听并按队列自动保活/让行
  CoinAFK.json                # 皎皎币委托启动、地图筛选、放弃和 99 局循环

assets/resource/tasks/
  CipherEndlessBoost.json     # 密函模式和技能开关覆盖
  NormalEndlessBoost.json     # 普通模式、轮次和技能覆盖
  CoinAFK.json                # 皎皎币挂机任务与轮次覆盖
  ProgressMonitor.json        # “监控”分组的正式任务定义
  LiseExpelSkillCast.json     # 共享技能选项
  preset/AFK.json             # 监控在前、游戏任务在后的两个挂机预设
```

基础 Pipeline 提供可复用节点；任务选项通过 `pipeline_override` 替换 `next`、`on_error`、`enabled`、延迟、重复次数和日志。维护时必须按“基础节点 + 当前模式覆盖 + 当前子选项覆盖”的最终结果分析，不能只阅读基础文件。

## 进度监控启动任务

Telegram 监听使用 `config/agent-processes/.telegram-owner.json` 维护跨进程单一所有者。新实例原子接管 owner 记录；每个实例只有所有权守护线程可以刷新该文件，轮询、发送与定时线程不得自行读写 owner 文件，只响应守护线程共享的停止事件。守护线程每 2 秒刷新一次，连续三次失败才认定失权；失权后只调用 `telegram_bot.stop(reset_progress=False)` 停止当前旧实例的 Telegram 线程，不得关闭 AgentServer、当前 Maa 任务或重置进度。设置或手机主动关闭通讯同样通过全局代次信号只停止 Telegram 线程。所有路径都不得让错误日志包含 Bot Token。

UI 的“监控”分组提供正式任务“进度监控”，它会自动选择两种运行方式：

- 独立运行：`ProgressMonitorLog` 转入自循环的 `ProgressMonitorKeepAlive`，任务保持运行，直到 UI 停止。
- 队列引导：Agent 从 MXU 的当前提交日志确认后续 `RewardConfirmEntry`、`NormalEndlessEntry` 或 `CoinAFKEntry`，把 `ProgressMonitorLog.next` 覆盖为空并完成当前任务。

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

Agent 启动后由 `parent_watchdog.py` 使用 `OpenProcess(SYNCHRONIZE)` 持有启动它的 UI/MXU 父进程句柄，并在守护线程中通过 `WaitForSingleObject` 等待该具体进程结束。父进程正常退出、托盘右键退出、崩溃或重启后，统一关闭回调只执行一次 `telegram_bot.stop()` 与 `AgentServer.shut_down()`，让阻塞中的 `AgentServer.join()` 返回；该异常退出路径不生成任务完成消息。回调执行前同时启动 5 秒强制退出计时器，正常完成 marker 清理后取消；若 MaaFramework 停止或 join 卡住，则只强制结束当前旧 Agent 进程。Telegram 监听权连续丢失不再调用这条完整退出回调，只停止失权实例的 Telegram 线程；完整 Agent 关闭严格限定为父进程退出。使用进程句柄而不是反复查询 PID，可以避免父进程退出后 PID 被复用造成孤立 Agent 误判为仍受 UI 管理。

## Agent 进程登记与全局关闭通讯

`agent/process_registry.py` 在 `AgentServer.start_up` 之前把当前 Agent 登记到 `<exe-root>/config/agent-processes/<pid>.json`。源码运行时 `exe-root` 是项目根，桌面包运行时是 `dist/DNAHelper`，两者都由 `agent/` 的上级目录推导。marker schema 固定为：

```json
{
  "schema_version": 1,
  "pid": 1234,
  "creation_time_100ns": 133700000000000000,
  "executable_path": "C:\\Python311\\python.exe"
}
```

`creation_time_100ns` 是 `GetProcessTimes` 返回的 Windows FILETIME 创建时间。`executable_path` 是解析后的 `sys.executable` 绝对路径。marker 必须小于 4096 字节，先写入同目录临时文件、`fsync`，再用 `os.replace` 原子替换；现有祖先目录、登记目录或 marker 为符号链接、Windows 重解析点或非普通目标时拒绝写入。启动失败和正常退出都尽力删除 marker。主动关闭通讯不删除 marker，因为 Agent 与任务仍然存活。

定制 MXU 注册 Tauri 命令 `disconnect_all_dna_helper_monitors`，返回 camelCase 的 `MonitorDisconnectSummary`：`generation`。Telegram `disconnect` 与该命令都把固定 schema 的信号写入 `<exe-root>/config/agent-processes/.monitor-disconnect.json`：

```json
{
  "schema_version": 1,
  "generation": "settings-1234-...",
  "created_at_unix_ms": 1787500000000,
  "source": "settings"
}
```

- MXU 和 Python 都先校验可执行目录、`config/agent-processes`、目标文件及全部现有祖先，拒绝符号链接、重解析点、非普通文件和越界路径；信号小于 4096 字节且拒绝多余 schema 字段。
- 两端都先在同目录写入并刷盘临时文件。Python 使用 `os.replace`；Windows MXU 使用 `MoveFileExW(MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)` 原子发布新代次。
- 每个 Telegram 监听在启动前读取当前 `generation` 作为基线；所有权守护线程每 2 秒读取一次，只有观察到非空且不同的新代次才调用 `telegram_bot.stop(reset_progress=False)`。因此旧命令不会关闭之后重新启动的监听。
- 该命令不枚举或终止任何进程，不调用 `AgentServer.shut_down()`、Maa `post_stop()` 或进度重置。当前 Agent、自动化任务、游戏、UI 和进度全部保持运行；仅 Telegram 接收、发送、定时状态与所有权线程停止。
- 设置按钮使用 `ConfirmDialog`，文案必须明确“关闭通讯但任务继续”。旧版 Agent 没有代次监听能力；首次升级必须完整退出一次旧运行环境，不能为兼容旧版而恢复进程终止。

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
| 皎皎币挂机 | 血条、目标小地图、继续挑战、确认选择 | 再次进行、扼守/无尽委托卡片、委托页开始挑战、Space 开始挑战；错误地图时使用放弃挑战和确定 |

皎皎币挂机的初始入口是特例：为防止从错误页面接管，它只识别委托页右下角的“开始挑战”。点击委托页和弹窗的两个开始按钮后，连续 3 帧血条确认局内并记录当前副本第 1 局，再在 1500ms 窗口内检查 `CoinAFK/target_minimap.png`。命中后先在同一 Agent 角色操作集中等待 3000ms，让战斗输入层稳定，再执行 `E → 300ms → E → 300ms → S 600ms → Q → 3500ms → S 5000ms → D 100ms`，然后进入普通扼守式局内循环；未命中则执行 `Esc → 放弃挑战 → 确定 → 再次进行`。正常重开时，再次进行后优先识别弹窗 Space 开始挑战并进入 HUD 等待；`CoinAFKWaitSpaceStart` 本身也把三帧血条确认放在首位，因此弹窗被手动处理、自动跳过或状态误退时仍能恢复局内。Space 点击后的 `CoinAFKWaitCombatHud` 不直接接受委托页按钮：只有 `CoinAFKLobbyRecoveryCandidate` 命中后等待 1500ms，且 `CoinAFKLobbyRecoveryConfirm` 再次命中，才进入委托页点击链，防止加载开始时仍保留的旧帧以 `1.0` 匹配分数把状态机错误带回局外。同一个重开监控仍保留“扼守/无尽”委托卡片和委托页开始挑战，作为游戏确实返回委托列表或详情页时的恢复分支。错误地图主动放弃不经过 `CoinAFKRoundQuota`，因此不会污染局外完成数。结算页“再次进行”出现时无论实际局内进度是否达到 99 都进入轮次记录：不足 99 时保留真实进度、计入一次完成并继续剩余副本，同时只发送一次异常通知。

皎皎币挂机的全部三连鼠标操作都不使用 Agent 鼠标输入，包括委托页开始、Space 开始、委托卡片恢复、再次进行、局内继续/确认和错误地图放弃/确定。它们统一与普通扼守保持相同的快速结构：三次均直接执行 Maa `Click`，前两个节点各等待 50ms，第三击后立即进入无输入的 `focus_guard_finalize` 恢复焦点；需要进度事件的链也只在收尾节点记录一次。这样既保留相同的原生快速连点，也不会把三次物理点击重复计算为三轮或误触发角色攻击。

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
├─ 检测“再次进行”并完成轮次计数
├─ CipherExpelRestartMonitor（重开等待，不再计数）
│  ├─ “再次进行”仍残留 → 重试三连击 (920,640)
│  ├─ Space 确认 → 三连击后继续等待 HUD
│  └─ 连续 3 帧血条 → 进入下一轮 CipherExpelMonitor
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
                → 进入不含计数节点的 CipherExpelRestartMonitor
                → 点击副本外 Space 确认
                → 连续 3 帧血条确认后进入下一轮
```

任务入口、血条确认、技能释放、第一页确认和 Space 确认都不计数。只有局外监控首次识别到“再次进行”才表示完成一轮；点击后的残留按钮由 `CipherExpelRestartMonitor` 重试，不能再次经过 `CipherExpelAgainDetected`，避免同一页面重复增加轮次。

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

任务入口、技能释放和“开始挑战”均不增加局外完成数。HUD 三帧确认只负责把有限副本的局内进度初始化为第 1 局；之后每次成功“继续挑战”进入下一局。技能开关不得改变轮次定义。

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
- “继续挑战”成功后立即经过 `NormalContinueTransition`；技能已释放的路径使用 `NormalHoldPostSkillContinueTransition`。两者都显式使用 `0 / 0 / 0` 即时路由，优先识别下一页合法的“确认选择”，未命中才恢复对应局内监控。按钮残影的快速重试由 Agent 的 5 秒逻辑进度去重兜底。

未达到轮次上限时依次点击“再次进行”和“开始挑战”。技能开启后，新一轮必须重新连续确认 HUD 才能进入技能延迟；技能结束后进入 `NormalHoldPostSkillInsideGate` / `NormalHoldPostSkillMonitor`。这组节点及其边界未知空闲节点都处理局内按钮；局外专属按钮命中后才进入重开链。血条恢复只回到 post-skill 节点，因此同一副本不会再次释放。完成重开后才重新允许释放。

任务入口先进入局外分类监控，因此从“再次进行”页面启动时仍优先进入完成轮次与重开流程；若实际已在副本中，连续三帧血条会切入局内。

### 无尽

`NormalMode=Infinite` 是纯局内按钮模式：

- 只识别“继续挑战”和“确认选择”。
- 每次使用“原生点击 → 原生点击 → 原生点击 → `focus_guard_finalize` 无输入收尾”的快速链完成三连击。
- 三连击后立即经过 `NormalContinueTransition`，优先检查“确认选择”后恢复按钮监控。
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
| 技能触发延迟 | 3000ms | 3000ms | 3000ms |
| E 开关 | 开 | 开 | 开 |
| E 次数 | 2 | 2 | 2 |
| E 间隔 | 1000ms | 1250ms | 1000ms |
| Q 开关 | 开 | 开 | 开 |
| Q 在 E 前释放 | 默认关 | 默认关 | 默认关 |
| Q 后触发间隔 | 3000ms | 3000ms | 3000ms |
| 仅高台 E | 默认关 | 不提供 | 默认关 |

顶层“是否开启技能”默认关闭；表中的 E/Q 默认值只在用户开启技能后生效。

三帧血条识别只负责确认战斗 HUD 已就绪；Q 图标不再参与触发或复核。一旦进入技能链，E/Q 是否执行只由选项开关决定。

普通驱离的高台开关还必须同步覆盖 `NormalOutsideCombatHudReady` 与 `NormalRestartCombatHudReady`：开启时两者直接跳到 `NormalExpelCombatEntry`，再进入 `LiseHighPlatformWindowStart`；关闭时两者跳到启用的 `LiseCombatLoadDelay`。禁止把 HUD Ready 节点指向已被当前选项禁用的延迟节点，否则 MaaFramework 会沿 `on_error` 返回 `NormalEndlessWaitStartChallenge` 并形成血条确认循环。密函驱离的 `LiseCombatHudReady.next` 同时保留 `LiseCombatLoadDelay` 与 `CipherExpelCombatEntry`，因此禁用前者后仍有合法入口。

每个 Q 节点都会通过焦点保护动作连续发送 3 次 Q，发送间隔固定为 100ms；前置和后置 Q 使用同一机制。

E 连续点击的每次底层按键成功后都会记录 `第 N / 总次数`；E 节点不再额外记录整组开始和结束，避免一次按键序列出现三套重复描述。Q 只在三次发送全部成功后记录一条 `3 / 3` 结果。

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

所有实际输入最终仍由 MaaFramework 的原生 `Click` 或 `ClickKey` 完成。页面三连击采用：

1. 首次识别后由普通 Pipeline 节点执行第一次原生点击。
2. 后两次由 `DirectHit + Click` 节点直接执行；Agent 不参与任何鼠标输入。
3. 第三击后立即进入 `focus_guard_finalize`，只处理进度事件与焦点恢复。
4. 前台监控线程持续记录最近的非游戏窗口和鼠标虚拟屏幕坐标；收尾时调用 `ClipCursor(None)`，再尝试恢复该窗口。
5. 仅当窗口恢复成功时调用 `SetCursorPos` 恢复鼠标位置；坐标允许为负数，以支持主屏左侧或上方的显示器。

`focus_guard_start` 会对每个新 Maa 游戏任务重新判定初始前台窗口：若初始前台就是控制器绑定的游戏窗口，则清空跨任务保留的非游戏窗口和鼠标快照，避免快捷键从游戏前台启动时错误切回旧窗口。Agent 键盘动作在发送输入前再次检查当前前台；当前仍是游戏时返回空恢复目标，动作结束只释放 `ClipCursor`，不调用窗口切换。原生鼠标点击链的 `focus_guard_finalize` 仍允许使用点击前由 watcher 保存的非游戏快照，因为它执行时游戏前台通常是自动点击造成的，不能按同一规则清除。

E/Q 也由 `focus_guard_action` 分别调用 `FocusGuardEKeyProxy` 和 `FocusGuardQKeyProxy`。皎皎币挂机的正式角色操作使用同一动作的 `key_sequence` 分支：长按 S/D 通过 Maa 控制器的 `post_key_down` / `post_key_up` 实现，E/Q 复用既有按键代理，序列中的等待由 Agent 精确执行。整套序列只记录一次原窗口和鼠标位置，任何长按步骤即使异常也会尽力释放当前按键，所有步骤结束后只恢复一次焦点。

只有密函驱离和普通驱离在技能开启后会显示默认关闭的“首次副本前台，后续副本后台”；普通扼守固定使用默认前台技能输入。启用此项时，任务选项把四个 E/Q 节点的自定义动作切换为 `hybrid_skill_action`，并把整套技能公共出口 `LiseSkillCastEnd` 切换为 `hybrid_skill_dungeon_complete`。`focus_guard_start` 为每个新 Maa 游戏任务清除混合输入就绪标记；就绪标记为空期间，首个副本的每一次 E/Q 都使用 `_ForegroundPrimingSkillAction`，先以 `_restore_window(game_hwnd)` 把游戏置于前台并等待 100ms，再通过 `FocusGuardEKeyProxy` / `FocusGuardQKeyProxy` 发送真实按键，最后完整调用 `_restore_window_and_cursor()` 恢复用户窗口与鼠标。首个 E/Q 成功不能设置就绪标记；只有整套技能到达公共出口后才标记当前游戏窗口允许后台输入。

下一副本及同一任务后续副本的 E/Q 使用 `_BackgroundSkillAction`，通过 `PostMessageW` 投递 `WM_KEYDOWN` / `WM_KEYUP`，不切换焦点；Q 的三次发送间隔仍为 100ms。若任一后台投递明确失败，`HybridSkillAction` 清除就绪标记，并让本次动作回退到上述前台真实输入与焦点恢复流程，成功后重新标记。页面鼠标点击全部由 Maa 原生节点完成并由 `focus_guard_finalize` 无输入收尾；未启用后台选项的技能仍使用 `focus_guard_action`。后台投递成功只证明消息进入窗口队列，不能证明 Unreal 一定消费。

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

- 普通扼守与皎皎币的有限副本在三帧战斗 HUD 确认后由 `progress_dungeon_entered` 幂等记录第 1 局，之后每次成功完成逻辑“继续挑战”才加 1；第 99 局不依赖不存在的下一次“继续挑战”。普通无尽在任务入口即以当前第 1 局初始化。密函无尽仍按完整结算循环推进。每组三连击只记录一次；普通模式的 `continue_challenge` 事件使用 5 秒去重窗口，按钮动画残影导致的快速重试不会再次增加进度。
- 局外副本轮次是“已完成副本数”，由普通扼守、普通驱离、密函驱离和皎皎币的 `RoundLogger` 在识别到“再次进行”后写入。`complete_round()` 不得改写 `stage_count`；若已观察到局内且结算时不足 `stage_total`，返回提前结算结果。Logger 仍计入本次完成并在尚有配额时继续重开，通过独立一次性发送器向手机通知一次真实进度；相同 hit count 的重复识别不得重复通知。从结算页直接接管且没有局内观测时不误报提前结算。
- `Start Challenge` 成功后只把状态切回运行、清零局内进度并等待 HUD 重新记录第 1 局，不增加局外副本轮次。
- 密函驱离的 Space 确认只表示已重新进入下一轮，不重复增加已完成数。

`focus_guard_start` 从任务和轮次选项接收 `progress_mode`、`progress_total`、`progress_stage_total`。密函无尽循环会重复进入任务入口，因此使用 Maa `task_id` 去重初始化和启动通知。密函无尽和普通无尽没有自然成功事件：`advance_cipher_cycle()` / `increment_stage()` 仅在对应局内计数由 98 增至 99 时返回 `True`，`focus_guard_action` 据此调用 `notify_infinite_99_completed()`；计数继续到 100 及以后时不再触发，且不停止游戏任务或 Telegram。

`telegram_bot.py` 仅在 `ProgressMonitorStart` 被执行且存在有效 `config/telegram.json` 或对应环境变量时启动。打开或重启 UI 本身不会启动监听。接收轮询、消息发送和定时调度使用三个独立守护线程；定时线程第一次等待 1800 秒后把 `progress_state.format_status()` 的结果放入现有发送队列，之后每 1800 秒重复。另一个所有权守护线程是 owner 文件的唯一刷新者，每 2 秒刷新 owner 并检查全局通讯停止代次；连续三次 owner 刷新失败才设置共享停止事件。三个工作线程不再各自读写 owner 或停止信号，因此一次瞬时替换或读取竞争不会造成线程静默永久退出。定时线程不直接调用网络接口也不修改进度。网络失败采用退避重试，不得阻塞 Pipeline 输入。只响应 `allowed_chat_id`，Token 与状态文件都位于已被 Git 忽略的 `config/`。

授权账号发送 `disconnect`、`/disconnect` 或带 Bot 用户名后缀的 `/disconnect@name` 时，轮询线程先同步发送一条关闭确认，再以当前 `update_id + 1` 发出零超时 `getUpdates`，明确消费终止命令，避免 Agent 重启后 Telegram 重放同一条命令；随后发布新的全局停止代次并调用 `telegram_bot.stop(reset_progress=False)`。本实例成功从运行态切换到停止态后必须打印 `[进度监控] disconnect 已执行，本机全部监控通讯已关闭；当前任务继续运行`；其他实例收到新代次时打印全局通讯已停止日志。本实例立即关闭接收、发送、定时状态和所有权线程并释放 owner 文件，其他当前版本实例最多约 2 秒后处理同一代次；全部实例都不重置 `progress_state`，因此正在运行的副本轮次、钓鱼目标和技能状态机不受影响。这里严禁从 Telegram 线程直接调用 `AgentServer.shut_down()`，也严禁保存自定义动作中的临时 `Context.tasker` 后跨线程调用 `post_stop()`：前者会让 `AgentServer.join()` 抛出 `0xe06d7363` 并使后续节点出现 `server is not alive`，后者在反向调用会话结束后抛出 `OSError`。确认、消费或广播失败使用 `finally` 保证至少关闭当前实例；未授权 Chat ID 在命令分支之前即被拒绝。

`ProgressMonitorLifecycle` 通过 MaaFramework 的 `TaskerEventSink` 接收 UI 任务生命周期。独立运行时，`ProgressMonitorEntry` 收到 `Tasker.Task.Failed` 表示用户从 UI 停止任务，此时关闭监控；队列引导正常完成产生的 `Succeeded` 必须忽略，否则后续游戏任务无法使用监听。`RewardConfirmEntry`、`NormalEndlessEntry`、`CoinAFKEntry` 和 `FishingEntry` 都属于受监控游戏任务；收到 `Tasker.Task.Succeeded` 时，从 `progress_state` 读取当前模式，生成包含正式任务名和模式的“任务已完成”消息，再把它作为 `telegram_bot.stop(final_message=...)` 的最终消息；`Tasker.Task.Failed`（包括 UI 停止）只调用无最终消息的停止，不得误报完成。只有停止调用确实从运行态切到停止态时才打印“监听已停止”，因此未选择监控时结束游戏任务不会产生消息或误导日志。当前运行实例的停止事件立即唤醒可中断等待并清空未发送队列；最终完成消息使用配置快照和独立的一次性守护线程发送，不依赖已停止的主发送队列，也不阻塞 Maa 生命周期回调。已经进入系统网络调用的请求允许在自身超时内返回，但停止后不再处理其结果。每次重新开始时创建新的停止事件和线程，避免快速停止后重启复用旧线程。UI/MXU 父进程退出是独立兜底信号，不依赖 Maa 是否仍能投递任务事件，因此桌面进程突然消失时也会停止 Telegram 定时状态线程和 AgentServer。

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
    "rate_limit": 0,
    "pre_delay": 0,
    "post_delay": 50,
    "max_hit": 10000000
}
```

“挂机钓鱼”也是 `DailyAFK` 下的正式任务，但不进入副本状态机。`FishingEntry → FishingMonitor` 长期以 50ms 显式节流，按优先级轮询关闭文字、鱼形 E 图标和鱼竿 Space 图标。三者都由 `agent/fishing.py` 注册的 `fishing_prompt` 自定义识别器处理完整画面：鱼竿与鱼形模板和截图先在 HSV 空间提取低饱和高亮白色像素，再以 `TM_CCOEFF_NORMED` 匹配白色轮廓；关闭文字使用 Canny 灰度边缘匹配稳定字形，不匹配浅色半透明底板。每个 Maa `task_id` 按 `space`、`e`、`escape` 分别持有独立的单调时钟到期时间；一次提示被接受后只锁定自身 3000ms，其他两种提示仍可立即触发。锁到期后即使画面从未消失，同一提示也能再次上报，不再使用连续未命中帧重新武装。

钓鱼默认通过 `focus_guard_action` 分别调用三个专用代理，发送一次 Space、E 或 Esc。`FishingClosePromptDetected` 是明确的业务时序例外：识别成功后以 `pre_delay: 500` 等待界面稳定，再发送 Esc；另外两个按键仍为 0ms。实验开关同时覆写三个动作到 `hybrid_fishing_action`：同一任务第一个实际按键使用 `_ForegroundPrimingSkillAction` 并恢复焦点，成功后记录独立于驱离技能的钓鱼后台就绪窗口；后续三个按键共享 `_BackgroundSkillAction` 状态。只有 Esc 动作保留 `progress_event: fishing_caught`，动作成功后才调用 `progress_state.record_fishing_catch()` 加 1；Space 与 E 不携带该事件。输入成功并完成进度更新后，`_log_fishing_action()` 对 Space/E 只输出按键与前台/后台方式；Esc 汇总日志额外包含最新 `当前数量 / 目标数量`。识别准备行、静态动作成功行和独立后台代理日志均被移除，完成目标时由同一进度快照输出最终数量和完成行，日志本身失败不得影响游戏输入结果。`FishingCount` 把用户输入的 `1–9999` 目标写入 `progress_total`；计数达到目标时共享状态先切为 `completed`，随后 Esc 节点的候选链优先命中终止节点 `FishingTargetReached`，不再返回长期监控。这样最后一次 Esc 成功、状态持久化和 Maa 任务成功事件保持严格顺序，进度监控能够沿用统一生命周期发送完成通知。独立时间锁会把每一种提示的动作限制为最多每 3000ms 一次，同时允许三个提示互不阻塞；如果后台 Esc 未被游戏消费，持续存在的关闭提示会在锁到期后再次触发。Telegram 沿用统一监听、即时 `/status` 与每 30 分钟自动状态周期，并把该计数显示为“钓鱼数量 / 目标”。`focus_guard_start` 在新 Maa 任务开始时同时清除技能与钓鱼两套混合输入状态，二者不能相互污染。

这会把空闲轮询节流明确限定为 50ms，不再叠加框架默认前置等待，并能覆盖很长的日常运行，但不是真正无限。按纯 50ms 下限计算约 5.8 天后会耗尽，实际还包含识别耗时。需要真正无限监听时，应先确认 MaaFramework 的停止语义并统一替换，不能只在个别节点删除 `max_hit`。

当前非高台和 HUD 等待仍有部分使用 `timeout → on_error` 表达正常分支，MaaFramework 会为其生成 `debug/on_error` 截图。这是已知设计债。

## Agent 动态目标

`tools/validate_project.py` 中的 `DYNAMIC_PIPELINE_TARGETS` 是 Agent 动态节点的显式清单，覆盖：

- `focus_restore.py` 通过 `Context.run_action` 调用的点击和按键代理。
- `round_logger.py` 通过 `Context.override_pipeline` 选择的普通重开入口。
- 皎皎币挂机的五个点击代理、Esc 代理和正常完成后的动态重开入口。

`progress_monitor.py` 注册 `progress_monitor_start` 自定义动作，但不通过 `Context.run_action` 跳转其他节点；它只覆盖 `ProgressMonitorLog` 的本次日志内容并始终成功返回。

修改 Agent 中的节点名映射时必须同步更新该清单。可达性分析必须从用户任务入口和动态目标共同出发；只遍历静态 `next` 会误删真实运行节点。

## 校验规则

`python tools/validate_project.py` 当前检查：

- Project Interface 版本、控制器、任务分组和导入文件。
- 用户任务的直接中文标题与说明。
- 选项递归引用和预设任务引用。
- Pipeline 节点重名。
- 每个 Pipeline 节点显式声明非负的 `rate_limit`、`pre_delay`、`post_delay`，不得继承框架默认时序。
- 用户任务入口存在。
- Agent 动态目标存在。
- `next` / `on_error` 目标存在。
- `pipeline_override` 只覆盖现有节点。
- 从任务入口与动态目标出发不存在不可达节点。
- TemplateMatch 引用的模板文件存在。
- Agent marker 与全局通讯停止信号的 schema、原子替换、AgentServer 前登记/退出清理生命周期，以及定制 MXU 补丁中的无进程终止广播命令、禁止影响任务与 UI 的约束、中文按钮与五种 locale 键。

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
  config/agent-processes/       # Agent marker、Telegram owner 与全局通讯停止代次
```

桌面壳基于固定的 MXU v2.1.3 提交，通过 `tools/mxu-v2.1.3-log-retention.patch` 维护项目定制。补丁以零上下文格式生成，构建脚本只有在 HEAD 精确匹配固定基线提交后才使用 `git apply --unidiff-zero` 正向应用或反向核验，避免补丁文件中的空白上下文损坏，同时不扩大到其他 MXU 版本。`tools/build_custom_mxu.ps1` 负责验证基线、应用补丁并生成 release 可执行文件；`build_ui.py` 不允许静默回退到没有这些定制命令的官方 MXU。

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
- 新功能的每个 Pipeline 节点必须显式配置三项时序，并分别验证首次识别响应与连续动作速度。
- 修改后运行项目校验、Python 编译检查，并同步验证运行目录。
