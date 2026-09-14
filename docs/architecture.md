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

当前游戏能力统一位于“日常挂机”分组；监听启动任务位于“监控”分组：

| 任务 | 模式 | 轮次 | 技能 | 高台判断 |
|---|---|---:|---:|---:|
| 密函无尽加速 | 无尽 | 无 | 无 | 无 |
| 密函无尽加速 | 驱离 | 1–9999，默认 1 | 可选 | 可选 |
| 普通无尽加速 | 扼守 | 1–999，默认 1 | 可选 | 无 |
| 普通无尽加速 | 无尽 | 无 | 无 | 无 |
| 普通无尽加速 | 驱离 | 1–9999，默认 1 | 可选 | 可选 |
| 皎皎币挂机 | 自动循环 | 1–999，默认 1 | 固定按键序列 | 目标小地图必选 |
| 调停挂机 | 自动循环 | 1–9999，默认 1 | 固定 W/左键/四 F/鼠标/右键/Z 输入 | 无 |
| 狩月人之阶挂机 | 自动循环 | 1–9999，默认 1 | 三次左键蓄力/Q 起手后持续 E | 无 |
| 钓鱼挂机 | 大世界钓鱼 | 1–9999，默认 120 | 提示驱动输入 | 无 |
| 沉浸式戏剧挂机 | 首次手动入场，前往后循环 | 无（不计数） | W/D/F/Q 起手，伊薇或伊薇（不持续 E）角色方案 | 无 |
| 进度监控 | 无 | 无 | 无 | 无 |

新建配置提供两个互斥用途的独立预设：

- `CipherAFK` / “密函挂机”：先加入 `ProgressMonitor`，再加入 `CipherEndlessBoost`。
- `NormalAFK` / “普通挂机”：先加入 `ProgressMonitor`，再加入启用的 `NormalEndlessBoost`，并加入默认关闭的 `MediationAFK`、`MoonHunterAFK` 与 `TheatreAFK` 供用户选择。

`ProgressMonitor` 在预设中必须排在对应游戏任务之前。MXU 会先把每项 `Calling post_task: entry=...` 与返回的 `task_id` 写入当前 `debug/mxu-tauri.log`；Agent 用自身 `task_id` 定位本轮监控提交记录，并在最多 500ms 的只读重试窗口内检查其后的已提交入口。若存在 `RewardConfirmEntry`、`NormalEndlessEntry`、`CoinAFKEntry`、`MediationAFKEntry`、`MoonHunterAFKEntry`、`FishingEntry` 或 `TheatreAFKEntry`，它把 `ProgressMonitorLog.next` 动态覆盖为空；否则保留基础 Pipeline 的保活路径。该判断不调用 `MaaTaskerGetTaskDetail`、不访问不存在的 Maa 任务 ID、不依赖任务选项，因此已保存的旧预设无需迁移。预设仍不得同时启用两个游戏任务，否则排在第一位的长期任务不会自然结束。预设定义在 `resource/tasks/preset/AFK.json`，不得通过修改用户生成的 `config/` 实现。

用户可见的新能力必须：

- 加入用户指定的任务分组；游戏任务使用 `DailyAFK` / “日常挂机”，监听启动任务使用 `Monitor` / “监控”。
- 使用正式中文名称和清晰的中文说明。
- 不显示未解析的本地化键。
- 不通过 `default_check: true` 绕过新建配置的预设选择。

所有新功能的连续鼠标点击统一采用普通扼守式快速链：首节点识别并执行 Maa 原生 `Click`，后续点击均使用 `DirectHit + Click`；三连击的前两段各使用 50ms `post_delay`，第三击后以 `0ms` 进入 `DirectHit + focus_guard_finalize`。收尾动作只恢复窗口和鼠标并记录逻辑事件，绝不发送游戏输入。逻辑进度、轮次和成功日志只允许在收尾节点触发一次。禁止 Agent 发送鼠标点击，也禁止用单个 Agent 自定义动作内部的 `repeat` 代替该结构。普通扼守的主局内分支与技能后局内分支、密函、皎皎币和调停现有点击链均遵守此结构；校验器枚举检查这些链，并全局拒绝基础 Pipeline 与任务覆盖中的任何 `kind: click`。任何不同次数或延迟的例外都必须记录原因并由校验器或测试固定。

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
  MediationAFK.json           # 调停 Space 启动、HUD 门控、固定角色输入和结算重开
  MoonHunterAFK.json          # 狩月人之阶 HUD 门控、持续角色输入和重新开始循环
  Fishing.json               # 大世界钓鱼提示识别与输入
  TheatreAFK.json            # 沉浸式戏剧 HUD 门控、独立角色方案与“前往”三连击循环

assets/resource/tasks/
  CipherEndlessBoost.json     # 密函模式和技能开关覆盖
  NormalEndlessBoost.json     # 普通模式、轮次和技能覆盖
  CoinAFK.json                # 皎皎币挂机任务与轮次覆盖
  MediationAFK.json           # 调停挂机任务与轮次覆盖
  MoonHunterAFK.json          # 狩月人之阶挂机任务与轮次覆盖
  Fishing.json               # 钓鱼挂机任务与数量覆盖
  TheatreAFK.json            # 沉浸式戏剧挂机任务与角色方案覆盖
  ProgressMonitor.json        # “监控”分组的正式任务定义
  LiseExpelSkillCast.json     # 共享技能选项
  preset/AFK.json             # 监控在前、游戏任务在后的两个挂机预设
```

基础 Pipeline 提供可复用节点；任务选项通过 `pipeline_override` 替换 `next`、`on_error`、`enabled`、延迟、重复次数和日志。维护时必须按“基础节点 + 当前模式覆盖 + 当前子选项覆盖”的最终结果分析，不能只阅读基础文件。

## 进度监控启动任务

Telegram 监听使用 `config/agent-processes/.telegram-owner.json` 维护跨进程单一所有者。新实例原子接管 owner 记录；每个实例只有所有权守护线程可以刷新该文件，轮询、发送与定时线程不得自行读写 owner 文件，只响应守护线程共享的停止事件。守护线程每 2 秒刷新一次，连续三次失败才认定失权；失权后只调用 `telegram_bot.stop(reset_progress=False)` 停止当前旧实例的 Telegram 线程，不得关闭 AgentServer、当前 Maa 任务或重置进度。设置或手机主动关闭通讯仍通过全局代次信号停止 Telegram 线程；仅本地设置额外扫描并终止身份通过核验的孤立 Agent，详见下一节。所有路径都不得让错误日志包含 Bot Token。

UI 的“监控”分组提供正式任务“进度监控”，它会自动选择两种运行方式：

- 独立运行：`ProgressMonitorLog` 转入自循环的 `ProgressMonitorKeepAlive`，任务保持运行，直到 UI 停止。
- 队列引导：Agent 从 MXU 的当前提交日志确认后续 `RewardConfirmEntry`、`NormalEndlessEntry`、`CoinAFKEntry`、`MediationAFKEntry`、`MoonHunterAFKEntry`、`FishingEntry` 或 `TheatreAFKEntry`，把 `ProgressMonitorLog.next` 覆盖为空并完成当前任务。

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

定制 MXU 注册异步 Tauri 命令 `disconnect_all_dna_helper_monitors`，在 `spawn_blocking` 中执行本地清理，不阻塞 UI。返回 camelCase 的 `MonitorDisconnectSummary`：`generation`、`signalError`、`scanError`、`scannedProcesses`、`orphanAgentsTerminated`、`liveAgentsPreserved`、`staleRecords`、`unverifiedEntries`、`failedPids`。Telegram `disconnect` 不变，仅发布信号并关闭自身通讯；本地命令额外扫描和终止已核验的孤立 Agent。两端都把固定 schema 的信号写入 `<exe-root>/config/agent-processes/.monitor-disconnect.json`：

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
- 手机端不枚举或终止进程，不调用 `AgentServer.shut_down()`、Maa `post_stop()` 或进度重置。若接收线程失效，手机命令不能保证执行；本次不修改 Telegram 的接收、发送或信号处理逻辑。
- 本地端使用 `CreateToolhelp32Snapshot` 扫描整个系统，再以当前可执行目录的 Agent marker 作为授权白名单。marker 必须为正常小于 4096 字节的文件，固定 schema、文件名 PID、非零 FILETIME、绝对 Python 程序路径均须有效；拒绝符号链接、重解析点和越界。未登记的进程绝不终止，其他安装目录不自动纳入。
- 打开候选进程的查询/同步句柄后，用 `GetProcessTimes` 和 `QueryFullProcessImageNameW` 核验创建时间与规范化路径；身份匹配后保持句柄并重新取进程快照，避免初次快照到 marker 读取之间 PID 复用导致父进程误判。仅父进程确实不存在、已退出，或其创建时间晚于 Agent（父 PID 复用）时允许清理；父进程无法核验或仍存活则保留。
- 只有已确认的孤立候选才申请 `PROCESS_TERMINATE`，再次核验身份和父进程，再通过同一目标句柄 `TerminateProcess` 并等待最多 2000ms 确认退出。未确认退出不计入成功；失败 PID 和未核验项返回给 UI。扫描、信号发布失败独立报告，不伪称全部关闭。登记文件不删除；失效记录只统计，不影响后续进程复用判定。
- 设置按钮为“关闭监听并清理残留进程”，使用 `ConfirmDialog` 明确进程终止边界，结果在页面和日志显示扫描/终止/保留/失效登记数量，部分失败给出警告。仍受正常 UI 管理的 Agent 只请求停止通讯，自动化任务、游戏和 UI 不受强杀。旧版孤立 Agent 即使信号或接收线程失效，也可在登记身份通过后本地终止。

## 局内 / 局外状态边界

左下角角色血条 `combat_health_bar.png` 是单向局内证据。局外或边界未知监控先检查血条；连续 3 帧命中后确认局内。血条消失不能单独确认局外，因为 Q 动画等战斗状态可能临时隐藏 HUD。局内业务监控在血条缺失后进入无超时的边界未知等待：候选顺序为“血条、该模式合法的局内按钮、局外专属按钮、空闲兜底”。合法局内按钮可以继续当前局内流程，只有局外专属按钮命中后才进入局外动作链。候选是在同一 Pipeline 轮询中的优先级列表，不是真正的多线程。

| 功能 | 局内候选 | 局外候选 |
|---|---|---|
| 密函无尽 | 第一页确认、继续挑战、Space 确认 | 再次进行（命中后自然结束） |
| 密函驱离＋技能开启 | 血条、高台小地图、第一页确认 | 再次进行、Space 确认 |
| 密函驱离＋技能关闭 | 第一页确认 | 再次进行、Space 确认 |
| 普通无尽 | 继续挑战、确认选择 | 再次进行（命中后自然结束，不点击、不重开） |
| 普通扼守＋技能开启 | 血条、继续挑战、确认选择 | 再次进行、开始挑战 |
| 普通扼守＋技能关闭 | 继续挑战、确认选择 | 再次进行、开始挑战 |
| 普通驱离＋技能开启 | 血条、高台小地图 | 再次进行、开始挑战 |
| 普通驱离＋技能关闭 | 无 | 再次进行、开始挑战 |
| 皎皎币挂机 | 血条、目标小地图、继续挑战、确认选择 | 再次进行、扼守/无尽委托卡片、委托页开始挑战、Space 开始挑战；错误地图时使用放弃挑战和确定 |
| 调停挂机 | 血条、固定 W/左键/四 F/鼠标/右键/Z 角色操作 | 再次进行、Space 开始挑战 |
| 狩月人之阶挂机 | 血条、等待 3000ms 后执行三次左键蓄力/Q 起手、每 300ms 按一次 E | 左下“重新开始”；命中后停止输入，点击后直接等待血条 |
| 沉浸式戏剧挂机 | 血条连续 3 帧确认、每副本一次 W/D/F/Q 起手；按 profile 持续 E 或无输入等待 | 仅“前往”；循环中优先检测，重开残留重试，未知页面安全等待 |

沉浸式戏剧挂机已撤回入口的全局“前往”调试，首次入口严格为 `TheatreAFKEntry → TheatreAFKWaitCombatHud → TheatreAFKCombatHudFrame1 → TheatreAFKCombatHudFrame2 → TheatreAFKCombatHudReady → TheatreAFKProfileEntry → TheatreAFKCombatSequence → TheatreAFKInsideMonitor`。首次入口和血条确认不检测 Go；重开路径仅在观察并点击“前往”后可达。角色选项默认 case `CoinDefault` 显示为“伊薇”，保留标识兼容用户配置；新增 `YiweiNoE` 显示为“伊薇（不持续 E）”。两者均路由到戏剧独立的 `TheatreAFKCombatSequence`，复用同一 W/D/F/Q 起手参数，只选择不同的起手后等待分支与日志，不复制链或覆盖输入后端。没有旧皎皎币链的可达出口，皎皎币本身不改；所有周期经过公共 `ProfileEntry`。

起手使用 `input_sequence + skill_input_group: true`，显式步骤为：`delay 3000 → W↓ → delay 1000 → W↑ → D↓ → delay 1000 → D↑ → F → delay 200 → F → delay 200 → F → Q → delay 1000`，单位均为 ms，默认前台的 Q/F 均通过控制器完整 ClickKey 发送。起手节点三项框架时序为 0，3000ms 开局等待仍在整组操作内部。循环为 `InsideMonitor.next = [TheatreAFKGo, TheatreAFKPressE]`，每次先检测 Go，未命中才由 PressE 的单步 `input_sequence [{key_press:69}]` 发送一次 E；PressE 显式 `post_delay=500` 后返回 `InsideMonitor`，监控路由自身三项时序均为 0。E 不调用带逐次日志的公共 E 代理，不产生持续刷屏，Agent 不包含无限输入循环。起手和 E 复用同一个 task_id 的输入组，每次 E 不重新记忆恢复目标；开启实验选项后，从第一局起手到全部持续 E 都建立并复用后台组，不存在首次前台预热或第 3 次 E 切换。

不持续 E 分支由 `YiweiNoE` 覆盖 `InsideMonitor.next = [TheatreAFKGo, TheatreAFKWaitGo]`；`WaitGo` 严格为 `DirectHit + DoNothing`、`0/0/50ms`，返回 InsideMonitor，不包含按键、日志、血条重入或完成事件，`PressE` 从该 profile 的可达图中完全移除。两个 case 均显式覆盖相应路由和启动/起手结果/Go 收尾日志，因此切回默认方案会恢复原路由及原日志；新方案不会谎报“E 循环已停止”。其余起手和 Go 节点参数及输入组生命周期不变。

每副本一次的起手锁由**状态可达性**表达：InsideMonitor/PressE/WaitGo 只识别 Go、发送 E 或无输入等待，不读取血条来重入起手。Q 动画、HUD 消失恢复不会切换分支或解锁 W/D/F/Q。Go 命中即停止 E 或结束无输入等待，第一节点仍直接执行 Maa 原生 Click；随后 GoClick2/GoClick3 为 DirectHit + Click，间隔 50/50ms。GoClick3Finalize 保留无输入 `focus_guard_finalize`，仅本任务设置 `finish_skill_input_group:true`：有本任务前台输入组时移除它并恢复一次该组记录的窗口/鼠标（100ms 收尾等待），不重新采集恢复目标；后台组没有恢复目标，关闭后台组后与没有组的残留按钮重试一样走普通原生点击焦点收尾，仍然恢复窗口。默认未设置该参数的其他任务完全不改变。没有进度事件，不计轮次。`TheatreInputLifecycle` 只处理 TheatreAFKEntry 的成功/失败结束通知，关闭对应 task_id 输入组，不影响其他任务；常规输入失败已有按键抬起兜底，随后清理组，禁止失败后自动重放起手。

`TheatreAFKBackgroundInput` 是本任务独立、默认 No 的实验开关，中文名称为“全程后台输入（实验）”；保留原选项及 Yes/No 标识兼容用户配置，不复用驱离的选项标识。Yes 仅把 `TheatreAFKCombatSequence` 与 `TheatreAFKPressE` 的 `custom_action` 改为 `theatre_background_keyboard_sequence`，不覆盖 `custom_action_param`，因此选定 profile 的步骤、时间和共享输入组参数完整保留。Go 收尾不负责开启后台状态；profile 只覆盖其日志，不覆盖收尾动作。两种 profile 与后台开关只修改不同字段，任意合并顺序结果一致；`YiweiNoE` 中的 PressE 即使有后台后端覆盖也始终不可达。两个方案开启后台后均从第一次 W/D/F/Q 起手全程后台，不恢复首次前台规则。

回归验证覆盖两种 profile × 前后台选项及两种覆盖顺序、切回默认方案、精确相同的起手参数、无 E 方案在 HUD 消失恢复时仅无输入等待、Go 残留重试不重放起手、多个副本仅各执行一次，以及原始三连击与其他任务图不变；校验器同时约束无输入等待节点、profile 可覆盖字段与默认路由恢复。

`TheatreBackgroundKeyboardSequenceAction` 只接受戏剧的起手与持续 E 两个节点，验证其为共享组的纯键盘序列后，直接调用 `_BackgroundKeyboardSequenceAction`。不读取或写入 `_hybrid_skill_ready_hwnd`，不维护首次次数；旧的 `hybrid_keyboard_sequence` 与 `theatre_foreground_e_count` 已移除。第一局、后续副本和新任务均直接后台发送，窗口的必要激活由用户手动完成；助手不根据当前焦点自动暂停 E 或回退前台。Go 仍清理组，下一局重新建立后台组；残留按钮、HUD 消失恢复不解锁起手。手动停止或失败只关闭对应组，不进行前台预热；失败不重放起手。

`_BackgroundKeyboardSequenceAction` 的纯键盘后端不变：静态拒绝鼠标步骤，通过 `_send_background_key_transition` 向绑定 HWND 投递 WM_KEYDOWN/WM_KEYUP，长按沿用步骤延迟，完整 F/Q/E 按键保持 30ms 后抬起。不调用前台控制器或焦点/鼠标函数；后台抬起失败从 held_inputs 补发，其他失败直接结束，不回退重放。默认 `FocusGuardAction`、驱离及钓鱼规则不变。没有切换成功日志或逐次 E 日志，输入失败使用 `_safe_user_log`，日志流失败不影响动作结果。单元测试覆盖首局与后续局的相同完整后台链、失焦不暂停、关闭选项仍前台、停止重启、失败抬起、不污染驱离就绪状态以及 Go 原生点击收尾；模拟投递通过不代表游戏实机消费保证。

重开等待保持 `[TheatreAFKGo, TheatreAFKRestartHudFrame1, TheatreAFKRestartMonitor]`；后续 Frame1/Frame2 优先处理 Go 残留，Ready 直接路由 ProfileEntry。按钮重试不回任务入口、不计数、不发送 E、不执行起手。两组 HUD 均保持前两帧 `0/0/50`、末帧 `0/0/0`、`timeout=120`；确认失败返回各自等待。点击后未知页面既无 Go 也无 HUD 时保持 `0/0/50` 安全等待，不发送 E。没有 StopTask、完成通知、局内加速、小地图或未授权按钮。

“前往”模板提取可由 `tools/extract_theatre_go_template.py` 对指定用户原图复现：截图 `1327×756` 中的完整游戏客户区为 `(29,16,1280,720)`，包含 Unreal 自绘标题栏。本机窗口测量 `GetWindowRect` 与客户区原点偏移为 `(0,0)`；Maa 的 [PrintWindow 实现](https://github.com/MaaXYZ/MaaFramework/blob/main/source/MaaWin32ControlUnit/Screencap/PrintWindowScreencap.cpp) 使用客户区截屏，不应再扣除自绘标题栏。无损文字裁剪 `(1150,662,46,25)`，ROI `(1080,640,190,65)`，阈值 `0.85`，点击 `(1172,673)`。`tests/fixtures/theatre_go_panel.png` 保存原图底部窗口坐标 `(800,600,480,120)` 的正/负样本；测试覆盖原图定位、返回按钮负样本、标题改变、三连击时序及状态机循环。未知中间页需要用户补充点击后的完整 `1280×720` 页面截图，不能推测其他按钮模板。

皎皎币挂机的初始入口是特例：为防止从错误页面接管，它只识别委托页右下角的“开始挑战”。点击委托页和弹窗的两个开始按钮后，连续 3 帧血条确认局内并记录当前副本第 1 局，再在 1500ms 窗口内检查 `CoinAFK/target_minimap.png`。命中后先在同一 Agent 角色操作集中等待 3000ms，让战斗输入层稳定，再执行 `E → 300ms → E → 300ms → S 600ms → Q → 3500ms → S 5000ms → D 100ms`，然后进入普通扼守式局内循环；未命中则执行 `Esc → 放弃挑战 → 确定 → 再次进行`。正常重开时，再次进行后优先识别弹窗 Space 开始挑战并进入 HUD 等待；`CoinAFKWaitSpaceStart` 本身也把三帧血条确认放在首位，因此弹窗被手动处理、自动跳过或状态误退时仍能恢复局内。Space 点击后的 `CoinAFKWaitCombatHud` 不直接接受委托页按钮：只有 `CoinAFKLobbyRecoveryCandidate` 命中后等待 1500ms，且 `CoinAFKLobbyRecoveryConfirm` 再次命中，才进入委托页点击链，防止加载开始时仍保留的旧帧以 `1.0` 匹配分数把状态机错误带回局外。同一个重开监控仍保留“扼守/无尽”委托卡片和委托页开始挑战，作为游戏确实返回委托列表或详情页时的恢复分支。错误地图主动放弃不经过 `CoinAFKRoundQuota`，因此不会污染局外完成数。结算页“再次进行”出现时无论实际局内进度是否达到 99 都进入轮次记录：不足 99 时保留真实进度、计入一次完成并继续剩余副本，同时只发送一次异常通知。

皎皎币挂机的全部三连鼠标操作都不使用 Agent 鼠标输入，包括委托页开始、Space 开始、委托卡片恢复、再次进行、局内继续/确认和错误地图放弃/确定。它们统一与普通扼守保持相同的快速结构：三次均直接执行 Maa `Click`，前两个节点各等待 50ms，第三击后立即进入无输入的 `focus_guard_finalize` 恢复焦点；需要进度事件的链也只在收尾节点记录一次。这样既保留相同的原生快速连点，也不会把三次物理点击重复计算为三轮或误触发角色攻击。

今后新增或调整任何有限副本次数选项时，统一使用 `1–9999`，不得再引入新的 `1–999` 上限。

调停挂机的入口是 `MediationAFKInitialMonitor` 未知状态分类器：按优先级识别结算页“再次进行”、弹窗 `Space 开始挑战` 和战斗血条，不识别委托页按钮，也不接受小地图。首次命中“再次进行”直接进入 `MediationAFKRoundQuota`，按已完成副本语义计数；若配额为 1，决策节点直接结束而不再点击重开。Space 开始链完成后进入 `MediationAFKWaitCombatHud`；从已在局内启动时则直接进入同一组三帧血条确认。连续 3 帧确认后由 `MediationAFKCombatSequence` 明确等待 3000ms，再执行固定前台序列 `W↓ → 1500ms → W↑ → 左键↓ → 250ms → 左键↑ → 300ms → F → 300ms → F → 300ms → F → 300ms → F → 800ms → 鼠标瞬时↑130px → 500ms → 右键↓ → 800ms → 右键↑ → 800ms → Z`；序列不发送 Shift。左键按住 250ms，抬起后等待 300ms 才发送第一次 F；四次 F 之间各等待 300ms，第四次 F 后等待 800ms。当前调停实验使用单次 Windows 物理相对移动事件 `(0, -130)`，随后明确等待 500ms；它通过独立的 `mouse_move_instant` 操作表达，不改变通用 `mouse_move` 分段移动的语义。`focus_guard_action` 的 `input_sequence` 分支在执行前静态拒绝重复按下、未按先抬和未闭合的键盘或鼠标按钮序列，并把单轴相对移动限制为 20000px；键盘继续使用 Maa 控制器，玩法鼠标则在再次确认游戏前台后使用 Windows 物理相对移动与左/右键转换，绕开实测只返回成功但游戏不消费的 Maa `post_relative_move / post_touch_*`。它跟踪仍按下的输入，W、左键或右键抬起失败时会在恢复焦点前再次补发抬起；右键按住 800ms，抬起后等待 800ms 再发送 Z，Z 后继续等待 500ms 才允许失焦恢复。校验器只允许 `MediationAFKCombatSequence` 使用该录制序列，页面按钮继续只允许 Maa 原生点击。其他功能默认仍必须使用带节奏的分段相对移动，除非另有明确的实机实验、文档和测试约束。随后 `MediationAFKInsideMonitor` 只维持血条边界并识别局外专属“再次进行”，不存在“继续挑战”“确认选择”或局内 99 轮计数。结算命中后 `MediationAFKRoundQuota` 记录已完成副本；未达到 1–9999 配额时走三次原生“再次进行”点击并回到 Space 开始页。重开监控同时保留残留再次进行、Space 开始和三帧血条恢复候选，允许中间页面被手动处理后恢复。

狩月人之阶挂机复用调停挂机的局内/局外边界，但页面更短：`MoonHunterAFKInitialMonitor` 只识别左下“重新开始”和战斗血条。连续 3 帧血条确认后，`MoonHunterAFKCombatSequence` 等待 3000ms，并在同一个前台输入组中连续执行三次 `左键↓ → 300ms → 左键↑ → 等待 300ms`；第三次的常规等待后再额外等待 300ms，因此最后一次抬起到 Q 共 600ms，随后执行 `Q → 3500ms`。玩法左键复用调停挂机的 Windows 前台物理鼠标路径，按下失败或序列中断时由输入代理兜底抬起。随后 `MoonHunterAFKInsideMonitor` 每轮先识别“重新开始”；未命中才进入 `MoonHunterAFKPressE` 发送一次 E，明确等待 300ms 后再次识别。血条消失不是循环终止条件，因此 Q 动画和战斗表现不会误停 E；只有“重新开始”命中后才关闭共享输入组、恢复用户原窗口和鼠标，并按已完成副本语义记录一轮。未达到 `1–9999` 配额时，以三次 Maa 原生快速点击命中 `(540,630)`，点击后直接进入血条等待，不存在额外的 Space 开始页。重开等待同时保留“重新开始”重试与三帧血条恢复，因此按钮被手动处理或页面切换较快时仍可回到局内。默认副本次数为 1。

玩法相对鼠标移动已经形成项目级输入约束：所有新增的视角、瞄准和朝向操作都必须调用前台物理鼠标分段移动路径，执行前重新确认游戏焦点，并以明确的单步像素和步间间隔形成可观察速度。禁止改回 Maa `post_relative_move`，也禁止把总位移作为一次瞬时 `mouse_event`；前者实测会出现“框架成功、游戏无响应”，后者容易被游戏合并或丢弃。页面坐标点击不属于玩法移动，仍由 Pipeline 的 Maa 原生点击节点负责，不能复用这条 Agent 输入路径。

密函驱离和普通扼守/驱离支持从局内或局外任意页面启动。任务入口在状态未知时允许一次性同时探测血条和结算按钮；完成首次分类后严格使用分区监控。边界未知节点只能加入当前模式合法的局内按钮：普通扼守保留“继续挑战 / 确认选择”，普通驱离不加入任何扼守按钮，密函驱离保留第一页确认。技能结束后使用独立的 post-skill 边界节点并保留本副本技能锁：血条重新出现只恢复监控，不会再次进入技能链。普通无尽保留局内加速链，额外通过独立的 `NormalInfiniteAgainDetected` 识别局外终止信号，不进入局外重开状态机。密函无尽在入口、第一页确认后的继续挑战等待、继续挑战后的 Space 确认等待中，均把 `CipherEndlessAgainDetected` 放在候选首位；两个终止节点均复用驱离“再次进行”模板，但只执行 `StopTask`，不点击、不增加局内或局外轮次。任务成功事件由 `ProgressMonitorLifecycle` 复用现有自然完成通知，向 Telegram 发送对应正式任务名和模式“无尽”，随后停止监听。密函驱离通过模式覆盖进入独立局外状态机，不经过此终止候选。

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

`NormalMode=Infinite` 是局内加速、结算后自然结束的无尽模式：

- 局内识别“继续挑战”和“确认选择”，额外优先识别“再次进行”作为终止信号。
- 每次使用“原生点击 → 原生点击 → 原生点击 → `focus_guard_finalize` 无输入收尾”的快速链完成三连击。
- 三连击后立即经过 `NormalContinueTransition`，优先检查“确认选择”后恢复按钮监控。
- “再次进行”命中后执行独立 `NormalInfiniteAgainDetected` 的 `StopTask`，不点击、不重开、不额外增加轮次。
- 不统计局外副本轮次，但持续累计局内逻辑轮次。
- 不进入 HUD 或技能链。
- `progress_state.increment_stage()` 仍只在本次任务的局内计数首次到达 99 时返回里程碑信号，由 Agent 发送一次通知；仅达到 99 不结束，直至识别到“再次进行”才自然结束。开启监控时通过 `ProgressMonitorLifecycle` 发送“普通无尽加速 / 无尽”完成通知并停止监听，未开启时不启动任何通讯。

`NormalInfiniteAgainDetected` 在基础 Pipeline 中默认禁用，只由 `NormalMode/Infinite` 启用。该模式独占的 `pipeline_override` 在 `NormalEndlessEntry`、`NormalEndlessMonitor`、`NormalEndlessIdle`、`NormalContinueTransition` 和两个 `Click3Finalize` 的候选首位加入此节点。它使用 `RewardConfirm/expel_again.png`、ROI `[800, 560, 300, 130]`、阈值 `0.8`、时序 `0 / 0 / 0`，没有后继、错误跳转、游戏输入或进度事件。三连击内部不插入重复识别；第三击后先完成现有焦点恢复和该按钮本身的逻辑事件，再在收尾出口检查终止信号。基础共享节点的跳转和动作不变，因此普通扼守、普通驱离以及其他任务不会启用或到达该停止节点。

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

E/Q 仍由 `focus_guard_action` 调用 `FocusGuardEKeyProxy` 和 `FocusGuardQKeyProxy`，但四个共享技能节点都带 `skill_input_group: true`。第一项实际 E/Q 会按 Maa `task_id` 创建输入组、记录一次恢复目标并只切入游戏一次；后续 E/Q 复用该组，直到 `LiseSkillCastEnd` 的 `skill_input_group_complete` 才恢复用户窗口和鼠标。E 次数与间隔继续由 Pipeline 外层 `repeat / repeat_delay` 控制，每次重复动作只发送一次 E 并通过任务级索引逐次记录日志；因为输入组保持打开，焦点恢复耗时不会插入两次 E 之间。E 后的 Q 业务间隔仍由节点 `post_delay` 控制，Q 三连也在同一组内以 100ms 间隔执行。任务选项是按顺序提交的独立 Pipeline 覆盖，嵌套 `custom_action_param` 不会深合并，因此 E 间隔选项只能覆写 `repeat_delay / post_delay`，严禁再次写入 `action`，否则会清除次数选项提供的 `kind/key/repeat/skill_input_group` 并让动作立即失败。皎皎币挂机的正式角色操作使用同一动作的 `key_sequence` 分支，但不设置技能输入组：长按 S/D 通过 Maa 控制器的 `post_key_down` / `post_key_up` 实现，E/Q 复用既有按键代理，序列中的等待由 Agent 精确执行；整套序列同样只恢复一次焦点。调停使用更严格的 `input_sequence` 分支：Maa 控制器负责 W、F 和 Z 键盘输入，Windows 前台物理鼠标事件负责左键按住、分步相对移动和右键按住；整组序列共享一次前台生命周期、失败释放和最终焦点恢复。

只有密函驱离和普通驱离在技能开启后会显示默认关闭的“首次副本前台，后续副本后台”；普通扼守固定使用默认前台技能输入。启用此项时，任务选项把四个 E/Q 节点的自定义动作切换为 `hybrid_skill_action`，并把整套技能公共出口 `LiseSkillCastEnd` 切换为 `hybrid_skill_dungeon_complete`。`focus_guard_start` 为每个新 Maa 游戏任务先关闭遗留输入组，再清除混合输入就绪标记。就绪标记为空期间，首个副本的首项实际 E/Q 通过 `_ForegroundPrimingSkillAction` 创建前台组，以 `_restore_window(game_hwnd)` 把游戏置于前台并等待 100ms；该副本后续全部 E/Q 复用同一组，公共出口才调用 `_restore_window_and_cursor()` 一次并标记当前游戏窗口允许后台输入。首个 E/Q 成功不能提前设置就绪标记。

下一副本及同一任务后续副本的首项实际 E/Q 使用 `_BackgroundSkillAction` 创建后台组，整组通过 `PostMessageW` 投递 `WM_KEYDOWN` / `WM_KEYUP`，既不切换焦点，也不会在 E/Q 之间改变输入方式；Q 的三次发送间隔仍为 100ms。若任一后台投递明确失败，`HybridSkillAction` 关闭后台组、清除就绪标记，并从失败的当前动作开始回退到一个前台组；本副本剩余 E/Q 继续复用该前台组，公共出口才恢复一次并重新标记下一副本允许后台输入。页面鼠标点击全部由 Maa 原生节点完成并由 `focus_guard_finalize` 无输入收尾；未启用后台选项的技能仍使用 `focus_guard_action`，但同样受完整技能输入组约束。后台投递成功只证明消息进入窗口队列，不能证明 Unreal 一定消费。

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
- 局外副本轮次是“已完成副本数”，由普通扼守、普通驱离、密函驱离、皎皎币和调停的 `RoundLogger` 在识别到“再次进行”后写入。`complete_round()` 不得改写 `stage_count`；若已观察到局内且结算时不足 `stage_total`，返回提前结算结果。Logger 仍计入本次完成并在尚有配额时继续重开，通过独立一次性发送器向手机通知一次真实进度；相同 hit count 的重复识别不得重复通知。从结算页直接接管且没有局内观测时不误报提前结算。调停的 `stage_total` 固定为 0，不建立局内计数；HUD 恢复只把等待下一轮状态切回运行。
- `Start Challenge` 成功后只把状态切回运行、清零局内进度并等待 HUD 重新记录第 1 局，不增加局外副本轮次。
- 密函驱离的 Space 确认只表示已重新进入下一轮，不重复增加已完成数。

`focus_guard_start` 从任务和轮次选项接收 `progress_mode`、`progress_total`、`progress_stage_total`。密函无尽循环会重复进入任务入口，因此使用 Maa `task_id` 去重初始化和启动通知。普通无尽和密函无尽在未识别到“再次进行”前持续运行。`advance_cipher_cycle()` / `increment_stage()` 仅在对应局内计数由 98 增至 99 时返回 `True`，`focus_guard_action` 据此调用 `notify_infinite_99_completed()`；计数继续到 100 及以后时不再触发。普通无尽命中 `NormalInfiniteAgainDetected`、密函无尽命中 `CipherEndlessAgainDetected` 后，以 Maa 任务成功事件结束并发送对应模式的统一完成通知，再停止监听；终止检测本身不改变任何轮次。

`telegram_bot.py` 仅在 `ProgressMonitorStart` 被执行且存在有效 `config/telegram.json` 或对应环境变量时启动。打开或重启 UI 本身不会启动监听。接收轮询、消息发送和定时调度使用三个独立守护线程。每次新接收线程先执行一次 `timeout: 0` 的 `getUpdates`，只读取当前积压消息中的最大 `update_id` 并以其加一作为正式轮询起点，不调用 `_handle_update`；因此监听关闭期间积压的 `disconnect`、状态查询和帮助命令都不会跨会话执行。基线请求失败时按原退避策略重试，绝不能在尚未建立基线时处理积压消息。定时线程第一次等待 1800 秒后把 `progress_state.format_status()` 的结果放入现有发送队列，之后每 1800 秒重复。另一个所有权守护线程是 owner 文件的唯一刷新者，每 2 秒刷新 owner 并检查全局通讯停止代次；连续三次 owner 刷新失败才设置共享停止事件。三个工作线程不再各自读写 owner 或停止信号，因此一次瞬时替换或读取竞争不会造成线程静默永久退出。定时线程不直接调用网络接口也不修改进度。网络失败采用退避重试，不得阻塞 Pipeline 输入。只响应 `allowed_chat_id`，Token 与状态文件都位于已被 Git 忽略的 `config/`。

授权账号发送 `disconnect`、`/disconnect` 或带 Bot 用户名后缀的 `/disconnect@name` 时，轮询线程先同步发送一条关闭确认，再以当前 `update_id + 1` 发出零超时 `getUpdates`，明确消费终止命令，避免 Agent 重启后 Telegram 重放同一条命令；随后发布新的全局停止代次并调用 `telegram_bot.stop(reset_progress=False)`。本实例成功从运行态切换到停止态后必须打印 `[进度监控] disconnect 已执行，本机全部监控通讯已关闭；当前任务继续运行`；其他实例收到新代次时打印全局通讯已停止日志。本实例立即关闭接收、发送、定时状态和所有权线程并释放 owner 文件，其他当前版本实例最多约 2 秒后处理同一代次；全部实例都不重置 `progress_state`，因此正在运行的副本轮次、钓鱼目标和技能状态机不受影响。这里严禁从 Telegram 线程直接调用 `AgentServer.shut_down()`，也严禁保存自定义动作中的临时 `Context.tasker` 后跨线程调用 `post_stop()`：前者会让 `AgentServer.join()` 抛出 `0xe06d7363` 并使后续节点出现 `server is not alive`，后者在反向调用会话结束后抛出 `OSError`。确认、消费或广播失败使用 `finally` 保证至少关闭当前实例；未授权 Chat ID 在命令分支之前即被拒绝。

`ProgressMonitorLifecycle` 通过 MaaFramework 的 `TaskerEventSink` 接收 UI 任务生命周期。独立运行时，`ProgressMonitorEntry` 收到 `Tasker.Task.Failed` 表示用户从 UI 停止任务，此时关闭监控；队列引导正常完成产生的 `Succeeded` 必须忽略，否则后续游戏任务无法使用监听。`RewardConfirmEntry`、`NormalEndlessEntry`、`CoinAFKEntry`、`MediationAFKEntry`、`MoonHunterAFKEntry` 和 `FishingEntry` 都属于受监控游戏任务；收到 `Tasker.Task.Succeeded` 时，从 `progress_state` 读取当前模式和完成原因。通常生成包含正式任务名和模式的“任务已完成”消息；若完成原因为 `fishing_pool_empty`，则只生成“鱼池已空。”。最终消息作为 `telegram_bot.stop(final_message=...)` 的终止通知；`Tasker.Task.Failed`（包括 UI 停止）只调用无最终消息的停止，不得误报完成。只有停止调用确实从运行态切到停止态时才打印“监听已停止”，因此未选择监控时结束游戏任务不会产生消息或误导日志。当前运行实例的停止事件立即唤醒可中断等待并清空未发送队列；最终完成消息使用配置快照和独立的一次性守护线程发送，不依赖已停止的主发送队列，也不阻塞 Maa 生命周期回调。已经进入系统网络调用的请求允许在自身超时内返回，但停止后不再处理其结果。每次重新开始时创建新的停止事件和线程，避免快速停止后重启复用旧线程。UI/MXU 父进程退出是独立兜底信号，不依赖 Maa 是否仍能投递任务事件，因此桌面进程突然消失时也会停止 Telegram 定时状态线程和 AgentServer。

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

“钓鱼挂机”也是 `DailyAFK` 下的正式任务，但不进入副本状态机。`FishingEntry → FishingMonitor` 长期以 50ms 显式节流，按优先级轮询“水中暂时无鱼”、关闭文字、鱼形 E 图标和鱼竿 Space 图标。四者都由 `agent/fishing.py` 注册的 `fishing_prompt` 自定义识别器接收完整画面：鱼竿与鱼形模板和截图先在 HSV 空间提取低饱和高亮白色像素，再以 `TM_CCOEFF_NORMED` 全屏匹配白色轮廓；关闭文字保持原有 Canny 灰度边缘匹配。

鱼池耗尽走独立的 `_match_pool_empty()`：在自定义识别器内部裁出固定 `1280×720` 基准 ROI `(320, 180, 640, 140)`，用 `5×5 MORPH_TOPHAT` 消除局部背景/提示条亮度并保留抗锯齿文字笔画。模板只含“水中暂时无鱼”，导入时预缓存 `1.0 / 0.95 / 0.975 / 1.025 / 1.05` 五种尺寸，运行时只预处理一次 ROI。每种尺寸在相关峰值处再按横向三等分核验完整字形：总分至少 `0.85`，三段最小分至少 `0.80`。优先返回通过分段校验的最佳候选，识别框加回 ROI 偏移且使用实际候选尺寸；日志 detail 保留总分、最小分段分数和 ROI，方便区分未命中与锁定。不得为补偿背景差异直接降低旧的全屏边缘阈值，也不得把耗尽检测的预处理套到 Space/E/Esc。`tests/fixtures/fishing_pool_empty_ice.png` 保留用户原始漏识别截图，测试同时覆盖原图、客户区、颜色/纹理/淡化/微缩放及缺字/无提示/其他提示/ROI 外文字负样本。

“水中暂时无鱼”候选优先级最高；命中后 `fishing_pool_empty` 动作把共享状态设为 `completed`、记录 `completion_reason: fishing_pool_empty`，不增加数量、不发送按键，节点无后继并使 Maa 任务自然成功结束。生命周期随后只发送“鱼池已空。”并停止 Telegram。每个 Maa `task_id` 按 `space`、`e`、`escape` 分别持有独立的单调时钟到期时间；一次可操作提示被接受后只锁定自身 3000ms，其他两种可操作提示仍可立即触发。锁到期后即使画面从未消失，同一提示也能再次上报，不再使用连续未命中帧重新武装。

钓鱼默认通过 `focus_guard_action` 分别调用三个专用代理，发送一次 Space、E 或 Esc。`FishingClosePromptDetected` 是明确的业务时序例外：识别成功后以 `pre_delay: 500` 等待界面稳定，再发送 Esc；另外两个按键仍为 0ms。实验开关同时覆写三个动作到 `hybrid_fishing_action`：同一任务第一个实际按键使用 `_ForegroundPrimingSkillAction` 并恢复焦点，成功后记录独立于驱离技能的钓鱼后台就绪窗口；后续三个按键共享 `_BackgroundSkillAction` 状态。只有 Esc 动作保留 `progress_event: fishing_caught`，动作成功后才调用 `progress_state.record_fishing_catch()` 加 1；Space 与 E 不携带该事件。输入成功并完成进度更新后，`_log_fishing_action()` 对 Space/E 只输出按键与前台/后台方式；Esc 汇总日志额外包含最新 `当前数量 / 目标数量`。识别准备行、静态动作成功行和独立后台代理日志均被移除，完成目标时由同一进度快照输出最终数量和完成行，日志本身失败不得影响游戏输入结果。`FishingCount` 接受 `1–9999`，默认值为 `120`，并把用户输入的目标写入 `progress_total`；计数达到目标时共享状态先切为 `completed`，随后 Esc 节点的候选链优先命中终止节点 `FishingTargetReached`，不再返回长期监控。这样最后一次 Esc 成功、状态持久化和 Maa 任务成功事件保持严格顺序，进度监控能够沿用统一生命周期发送完成通知。独立时间锁会把每一种提示的动作限制为最多每 3000ms 一次，同时允许三个提示互不阻塞；如果后台 Esc 未被游戏消费，持续存在的关闭提示会在锁到期后再次触发。Telegram 沿用统一监听、即时 `/status` 与每 30 分钟自动状态周期，并把该计数显示为“钓鱼数量 / 目标”。`focus_guard_start` 在新 Maa 任务开始时同时清除技能与钓鱼两套混合输入状态，二者不能相互污染。

这会把空闲轮询节流明确限定为 50ms，不再叠加框架默认前置等待，并能覆盖很长的日常运行，但不是真正无限。按纯 50ms 下限计算约 5.8 天后会耗尽，实际还包含识别耗时。需要真正无限监听时，应先确认 MaaFramework 的停止语义并统一替换，不能只在个别节点删除 `max_hit`。

当前非高台和 HUD 等待仍有部分使用 `timeout → on_error` 表达正常分支，MaaFramework 会为其生成 `debug/on_error` 截图。这是已知设计债。

## Agent 动态目标

`tools/validate_project.py` 中的 `DYNAMIC_PIPELINE_TARGETS` 是 Agent 动态节点的显式清单，覆盖：

- `focus_restore.py` 通过 `Context.run_action` 调用的点击和按键代理。
- `round_logger.py` 通过 `Context.override_pipeline` 选择的普通、皎皎币、调停和狩月人之阶重开入口。
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

桌面壳最先注册 `tauri-plugin-single-instance`。第二次启动同一应用标识的可执行文件时，新进程只把启动事件转发给已有实例；已有实例对 `main` 窗口依次执行 `show`、`unminimize` 和 `set_focus`，因此托盘隐藏窗口会直接恢复，当前 UI 状态、任务和 Agent 均不重建。该插件必须排在其他 Tauri 插件之前注册，避免第二实例执行后续应用初始化。

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
- 普通无尽模式不得接入局外轮次、重开或技能节点；只允许独立“再次进行 → StopTask”终止检测，并保持其他模式不可达。
- 驱离局内不得误接扼守的确认按钮。
- 边界未知等待必须保留当前模式合法的局内按钮，不能因血条暂时消失漏掉稍后出现的结算按钮。
- 动态 Agent 目标不能按静态死节点删除。
- 新功能必须更新任务中文名称、说明、README、本文和校验覆盖。
- 新功能的每个 Pipeline 节点必须显式配置三项时序，并分别验证首次识别响应与连续动作速度。
- 修改后运行项目校验、Python 编译检查，并同步验证运行目录。
