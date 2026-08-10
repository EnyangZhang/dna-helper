# DNA Helper 架构说明

本文描述当前实现，而不是未来设计。用户安装和操作说明见项目根目录的 [README](../README.md)，已知问题与修复状态见 [2026-08-11 审计报告](audit-2026-08-11.md)。

## 系统边界

DNA Helper 由四层组成：

1. **MXU v2.1.3**：读取 Project Interface v2 配置，提供控制器、配置、任务列表、启动/停止、日志和截图界面。
2. **MaaFramework v5.10.4**：负责截图、模板识别、Pipeline 调度和 Win32 输入。
3. **Pipeline JSON**：描述页面状态、识别优先级、点击链、技能链和长期监控。
4. **Python Agent**：只处理 Pipeline 不适合表达的窗口焦点恢复、动态轮次日志和运行时重开决策。

普通识别与点击应优先留在 Pipeline；只有需要系统 API、动态文本或运行时图修改时才使用 Agent。

## 桌面接口

`assets/interface.json` 声明：

- 一个 `Win32-Foreground` 控制器。
- 窗口类名正则 `^UnrealWindow$`。
- 窗口标题正则 `^\s*二重螺旋\s*$`。
- 截图方式 `PrintWindow`。
- 鼠标、键盘输入方式 `Seize`。
- 一个“日常挂机”任务分组。
- Python Agent 启动命令 `python agent/main.py`。

`permission_required: true` 表示桌面版需要管理员权限。项目没有 `run.py` 旁路入口；所有依赖自定义动作的任务都必须让 MXU 启动 AgentServer。

当前桌面包仍依赖系统 PATH 中的 `python` 和已安装的 `maa` Python 包。复制 `dist/DNAHelper` 到一台没有相同 Python 环境的电脑，UI 可以启动，但 Agent 自定义动作不可用。

## 用户任务和预设

当前只有两个用户任务，均位于“日常挂机”分组：

| 任务 | 模式 | 轮次 | 技能 | 高台判断 |
|---|---|---:|---:|---:|
| 密函无尽加速 | 无尽 | 无 | 无 | 无 |
| 密函无尽加速 | 驱离 | 无，持续运行 | 可选 | 可选 |
| 普通无尽加速 | 扼守 | 1–999，默认 1 | 可选 | 无 |
| 普通无尽加速 | 无尽 | 无 | 无 | 无 |
| 普通无尽加速 | 驱离 | 1–999，默认 1 | 可选 | 可选 |

新建配置提供两个互斥用途的独立预设：

- `CipherAFK` / “密函挂机”：只加入 `CipherEndlessBoost`。
- `NormalAFK` / “普通挂机”：只加入 `NormalEndlessBoost`。

预设不得同时启用两个长期任务，否则排在第一位的任务不会自然结束，后续任务无法启动。预设定义在 `resource/tasks/preset/AFK.json`，不得通过修改用户生成的 `config/` 实现。

用户可见的新能力必须：

- 加入用户指定的任务分组；本项目当前使用 `DailyAFK` / “日常挂机”。
- 使用正式中文名称和清晰的中文说明。
- 不显示未解析的本地化键。
- 不通过 `default_check: true` 绕过新建配置的预设选择。

## Pipeline 资源组织

```text
assets/resource/base/pipeline/
  RewardConfirm.json          # 密函无尽、密函驱离结算
  NormalEndlessBoost.json     # 普通扼守、无尽、驱离和轮次重开
  CharacterControl.json       # HUD、高台判断、E/Q 与输入代理

assets/resource/tasks/
  CipherEndlessBoost.json     # 密函模式和技能开关覆盖
  NormalEndlessBoost.json     # 普通模式、轮次和技能覆盖
  LiseExpelSkillCast.json     # 共享技能选项
  preset/AFK.json             # 两个独立挂机预设
```

基础 Pipeline 提供可复用节点；任务选项通过 `pipeline_override` 替换 `next`、`on_error`、`enabled`、延迟、重复次数和日志。维护时必须按“基础节点 + 当前模式覆盖 + 当前子选项覆盖”的最终结果分析，不能只阅读基础文件。

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

`CipherMode=Expel` 将入口改为 `CipherExpelMonitor`：

```text
CipherExpelMonitor
├─ 识别到第一奖励页 → 结算链
└─ 技能开启且连续确认 HUD → 技能链

技能链结束
→ CipherExpelSettlementMonitor
→ 第一奖励页“确认选择”
→ “再次进行”三连击 (920,640)
→ 第三奖励页
→ CipherExpelMonitor
```

技能关闭时，`CipherExpelMonitor` 只监听第一奖励页，不进入 HUD 或技能节点。技能开启时每个副本只执行一次；`LiseSkillCastEnd` 转入仅结算监控，因此 Q 图标保持未启用或按键失败也不会在同一副本重新触发。

密函驱离没有轮次配额，第三页结束后持续返回下一轮监控。

## 普通状态机

### 完成轮次语义

普通扼守和普通驱离的“副本轮次”表示**已完成副本数**，唯一计数触发点是识别到“再次进行”：

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

`round_logger.py` 使用：

- `context.get_hit_count(...)` 读取完成轮数。
- `context.override_pipeline(...)` 动态写入当前日志。
- `context.override_pipeline(...)` 将决策节点的 `next` 改为重开链或结束节点。

### 扼守

`NormalMode=Endless` 在代码中代表界面上的“扼守”：

- 监控局内“继续挑战”。
- 监控局内“确认选择”。
- 监控结算页“再次进行”。
- 技能开启时还监控 Q 未启用 HUD。

未达到轮次上限时依次点击“再次进行”和“开始挑战”。技能开启后，新一轮必须重新连续确认 HUD 才能进入技能延迟；技能结束后返回扼守监控。

### 无尽

`NormalMode=Infinite` 是纯局内按钮模式：

- 只识别“继续挑战”和“确认选择”。
- 每次由 `focus_guard_action` 一次完成三连击。
- 不识别“再次进行”。
- 不统计轮次。
- 不进入 HUD 或技能链。

### 驱离

`NormalMode=Expel` 的局内没有确认按钮：

- 技能关闭：`NormalExpelMonitor` 只监听“再次进行”。
- 技能开启：入口先确认 HUD并执行一次技能，之后只监听“再次进行”。
- 识别“再次进行”后按完成轮次语义计数。
- 未达到配额时复用普通重开链，等待并点击“开始挑战”。

## 技能状态机

技能入口适用于密函驱离、普通扼守和普通驱离。共同流程：

```text
Frame1: q_inactive.png
→ 50ms
Frame2: q_inactive.png
→ 50ms
Frame3: q_inactive.png
→ 战斗 HUD 就绪
→ 普通延迟或高台分支
→ E（可禁用）
→ Q（可禁用）
→ LiseSkillCastEnd
```

Q 模板参数：

- 模板：`CharacterControl/q_inactive.png`，尺寸 `57×57`。
- ROI：`(1100,598,100,100)`。
- 阈值：`0.90`。

默认技能参数：

| 参数 | 密函驱离 | 普通扼守 | 普通驱离 |
|---|---:|---:|---:|
| 技能触发延迟 | 2000ms | 2000ms | 2000ms |
| E 开关 | 开 | 开 | 开 |
| E 次数 | 2 | 2 | 2 |
| E 间隔 | 1000ms | 1250ms | 1000ms |
| Q 开关 | 开 | 开 | 开 |
| 仅高台 E | 默认关 | 不提供 | 默认关 |

顶层“是否开启技能”默认关闭；表中的 E/Q 默认值只在用户开启技能后生效。

延迟结束后不再二次识别 Q。三帧识别只负责确认战斗 HUD 已就绪；一旦进入技能链，E/Q 是否执行只由选项开关决定。

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
4. 输入后调用 `ClipCursor(None)`，再尝试恢复先前的非游戏前台窗口。

E/Q 也由 `focus_guard_action` 分别调用 `FocusGuardEKeyProxy` 和 `FocusGuardQKeyProxy`。

这些代理节点虽然不一定从任务入口的静态 `next` 图可达，却是 Agent 的真实动态入口，不能作为死节点删除。普通重开链的 `NormalEndlessRestartByClick` 同样由 `round_logger.py` 动态选择。

焦点恢复属于尽力执行：

- Windows 可能拒绝 `SetForegroundWindow`。
- 只维护一个最近候选窗口。
- 短暂弹窗可能覆盖原恢复目标。
- 当前返回值只反映游戏输入是否成功，恢复失败不会使自定义动作失败。

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
- 技能触发延迟从连续三帧 HUD 确认后开始。
- 高台结果在延迟前锁定；文档必须明确当前不会在延迟后复核页面。
- 普通无尽模式不得接入轮次、重开或技能节点。
- 驱离局内不得误接扼守的确认按钮。
- 动态 Agent 目标不能按静态死节点删除。
- 新功能必须更新任务中文名称、说明、README、本文和校验覆盖。
- 修改后运行项目校验、Python 编译检查，并同步验证运行目录。
