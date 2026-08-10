# DNA Helper

DNA Helper 是基于 [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 和 MXU 的《二重螺旋》Windows 自动化助手。当前提供 2 个用户任务、共 5 种运行模式：

- 密函无尽加速：无尽、驱离。
- 普通无尽加速：扼守、无尽、驱离。

任务通过图像识别确认当前页面，再执行鼠标或键盘输入。所有模板、ROI 和固定坐标均按 `1280×720` 基准画面制作。

## 从 GitHub 首次安装到运行

下面是新 Windows 电脑从克隆仓库到双击 DNA Helper 图标的完整流程。仓库不会提交 `dist/`、`.cache/` 或编译后的 EXE，因此首次克隆后必须在本机完成一次构建。

### 第 1 步：安装一次性构建环境

需要安装：

- [Git for Windows](https://git-scm.com/download/win)。
- 64 位 Python 3.9–3.12；建议 Python 3.11。安装时必须让 `python` 可从 PATH 调用，参见 [Python Windows 官方说明](https://docs.python.org/3/using/windows.html)。
- [Node.js 22 LTS](https://nodejs.org/en/download) 或更新的 LTS 版本。
- pnpm 10.28.0。
- [Rust stable MSVC](https://v2.tauri.app/start/prerequisites/#rust)。
- [Microsoft C++ Build Tools](https://v2.tauri.app/start/prerequisites/#microsoft-c-build-tools)，安装器中勾选“使用 C++ 的桌面开发”。
- Microsoft Edge WebView2。Windows 10 1803 及更高版本通常已经安装；如果程序窗口空白，再安装 [WebView2 Evergreen Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)。

可以先在 PowerShell 中用 `winget` 安装 Git、Python、Node.js 和 Rust：

```powershell
winget install --id Git.Git -e
winget install --id Python.Python.3.11 -e
winget install --id OpenJS.NodeJS.LTS -e
winget install --id Rustlang.Rustup -e
```

Microsoft C++ Build Tools 建议按上面的 Tauri 官方链接手动安装并确认勾选“使用 C++ 的桌面开发”。安装完所有工具后，关闭并重新打开 PowerShell，然后执行：

```powershell
rustup default stable-msvc
npm install --global pnpm@10.28.0
```

确认环境：

```powershell
git --version
python --version
node --version
pnpm --version
rustc --version
cargo --version
```

要求：

- `python` 应显示 3.9–3.12。
- `node` 应显示 22 或更新的 LTS 版本。
- `pnpm` 应显示 10.28.0。
- `rustc` 和 `cargo` 必须可运行。

如果刚安装后命令仍找不到，重启 PowerShell；仍无效时重启 Windows。

### 第 2 步：克隆仓库

以下示例将项目放在 `D:\Projects\dna-helper`；也可以换成自己的目录：

```powershell
New-Item -ItemType Directory -Force D:\Projects | Out-Null
Set-Location D:\Projects
git clone https://github.com/EnyangZhang/dna-helper.git
Set-Location .\dna-helper
```

如果已经配置 GitHub SSH 密钥，也可以使用：

```powershell
git clone git@github.com:EnyangZhang/dna-helper.git
```

后续所有命令都必须在刚克隆的 `dna-helper` 项目目录中执行。

### 第 3 步：安装 DNA Helper 的 Python 运行依赖

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -c "import maa; print('MaaFramework Python Agent：正常')"
```

首次使用不建议只把依赖安装进 `.venv`。桌面版从资源配置中执行的是系统 PATH 里的 `python agent/main.py`；如果 `maa` 只存在于虚拟环境，双击 EXE 后 Agent 会启动失败，角色技能、焦点恢复和轮次日志将不可用。

### 第 4 步：先校验项目

```powershell
python tools\validate_project.py
python -m compileall -q agent tools
```

正常结果应包含类似：

```text
OK: 1 controller(s), 1 group(s), 2 task(s), 2 preset(s), 64 reachable pipeline node(s), 9 template(s)
```

### 第 5 步：首次编译定制 MXU

DNA Helper 使用带安全日志清理功能的定制 MXU。执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\build_custom_mxu.ps1
```

该脚本会：

1. 把固定的 MXU v2.1.3 源码克隆到 `.cache/mxu-v2.1.3/`。
2. 校验固定基线提交并应用 `tools/mxu-v2.1.3-log-retention.patch`。
3. 安装前端和 Rust 依赖。
4. 生成定制 `mxu.exe`。

第一次会下载和编译大量依赖，耗时较长属于正常现象。完成时应显示：

```text
Custom MXU built: ...\mxu.exe
```

常见失败：

- `pnpm` 或 Vite 报 Node 版本过旧：安装 Node.js 22 LTS，重开 PowerShell。
- 找不到 `link.exe`、Windows SDK 或 MSVC：重新打开 Visual Studio Installer，安装“使用 C++ 的桌面开发”；必要时在“Developer PowerShell for VS 2022”中重新执行构建命令。
- 找不到 `cargo` / `rustc`：执行 `rustup default stable-msvc` 后重开终端。

### 第 6 步：组装 DNA Helper 桌面目录

确保 DNA Helper 没有在运行，然后执行：

```powershell
python build_ui.py
```

成功时会显示：

```text
构建完成：...\dist\DNAHelper\DNAHelper.exe
```

确认图标已生成：

```powershell
Test-Path .\dist\DNAHelper\DNAHelper.exe
```

结果应为 `True`。

`build_ui.py` 只接受已经构建的定制 MXU，不会退回缺少日志清理功能的官方二进制。它会复制 MaaFramework、项目资源和 Python Agent，并在以后重建时保留 `dist/DNAHelper/config/` 和 `dist/DNAHelper/debug/`。

构建并非事务式操作。程序未退出或 DLL 被占用时可能留下不完整输出；发生失败后先退出 DNA Helper，再重新执行 `python build_ui.py`，不要继续运行半成品。

### 第 7 步：创建桌面图标

打开项目中的：

```text
dist\DNAHelper\DNAHelper.exe
```

推荐创建桌面快捷方式：

1. 右键 `DNAHelper.exe`。
2. Windows 11 选择“显示更多选项”。
3. 选择“发送到 → 桌面快捷方式”。
4. 右键桌面上的 DNA Helper 快捷方式，打开“属性 → 快捷方式 → 高级”。
5. 勾选“用管理员身份运行”。

以后双击这个桌面图标即可启动，不需要再次打开 PowerShell。

### 第 8 步：第一次连接游戏并开始任务

1. 先启动《二重螺旋》。
2. 将游戏设为项目使用的 `1280×720` 窗口基准。桌面版目前不会自动拒绝错误尺寸。
3. 双击桌面 DNA Helper 图标，并同意管理员权限提示。
4. 首次启动会自动创建两个独立标签页：
   - “密函挂机”：只包含“密函无尽加速”。
   - “普通挂机”：只包含“普通无尽加速”。
5. 点击本次要运行的标签页。不要同时启动两个长期任务。
6. 打开右侧“连接设置”，选择“二重螺旋（前台控制）”和“基础资源”。
7. 选择标题为“二重螺旋”的游戏窗口并点击“连接”。MXU 能自动匹配时，也可能直接显示“已连接”。
8. 在任务卡片中选择模式、轮次和技能选项。
9. 让游戏停在对应副本或可识别页面，然后点击“开始任务”，也可以按 `F10`。
10. 需要停止时点击“停止任务”或按 `F11`。

两个标签页彼此独立，避免把两个长期任务排进同一队列后由第一个任务永久阻塞第二个。也可以新建空白标签页，再从“添加任务 → 日常挂机”手动添加任务。

控制器使用真实前台鼠标键盘输入。每组点击或按键结束后 Agent 会尝试切回原窗口，但 Windows 可能拒绝恢复；运行时不要依赖焦点一定能够成功切回。

### 以后每天如何启动

首次构建完成后，日常使用只需：

1. 启动《二重螺旋》，保持 `1280×720` 窗口基准。
2. 双击桌面的 DNA Helper 快捷方式，以管理员身份启动。
3. 选择之前保存的配置。
4. 确认游戏窗口已连接。
5. 点击“开始任务”或按 `F10`。

不需要每天重新克隆、安装依赖或编译。

### 从 GitHub 更新到最新版本

完全退出 DNA Helper，在项目目录执行：

```powershell
git pull
python -m pip install -r requirements.txt
python tools\validate_project.py
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\build_custom_mxu.ps1
python build_ui.py
```

正常更新会保留现有配置和调试日志。若 Git 提示本地文件冲突，不要使用 `git reset --hard`；先确认本地修改是否需要保留。

### 首次安装故障排查

| 现象 | 处理方法 |
|---|---|
| `python` 不是命令 | 重新安装 Python 并加入 PATH，然后重开 PowerShell。 |
| `ModuleNotFoundError: maa` | 使用桌面版实际调用的同一个 `python` 执行 `python -m pip install -r requirements.txt`。 |
| `pnpm` 不是命令 | 执行 `npm install --global pnpm@10.28.0`，然后重开 PowerShell。 |
| Node/Vite 版本错误 | 安装 Node.js 22 LTS 或更新的 LTS 版本。 |
| 找不到 MSVC、Windows SDK 或 `link.exe` | 安装 C++ Build Tools 的“使用 C++ 的桌面开发”，或在 VS 2022 Developer PowerShell 中构建。 |
| PowerShell 禁止运行脚本 | 使用 README 中带 `-ExecutionPolicy Bypass -File` 的命令。 |
| `build_ui.py` 提示缺少定制 MXU | 先成功执行第 5 步的 `build_custom_mxu.ps1`。 |
| 构建时 DLL 被占用 | 完全退出 DNA Helper 后重新构建。 |
| UI 空白 | 安装或修复 Microsoft Edge WebView2 Runtime。 |
| 找不到游戏窗口 | 确认以管理员身份运行、游戏标题为“二重螺旋”、窗口类名为 `UnrealWindow`。 |
| 一直识别不到或点击错位 | 确认游戏使用项目的 `1280×720` 基准。 |
| UI 能开但技能、焦点恢复或轮次日志失效 | 检查日志中 Agent 是否连接，并运行 `python -c "import maa"`。 |

列出当前窗口标题、类名、进程和尺寸：

```powershell
python tools\inspect_windows.py
```

项目不提供旧的 `run.py` 命令行入口；当前 Pipeline 依赖 AgentServer，应从 `DNAHelper.exe` 启动。

## 日志清理

程序启动时会自动删除 `dist/DNAHelper/debug` 内修改时间超过 14 天的普通文件，并删除清理后留下的空目录。

“设置 → 常规 → 自动清理运行日志”下方提供红色“完全清空日志”操作项。确认后程序会安排重启，并在新日志创建前清空该目录；重启后的当前日志会保留。

所有清理都会解析并核验目标，只允许操作可执行文件同级的真实 `debug` 目录。遇到符号链接、Windows 重解析点、非普通文件或越界路径时会拒绝整次操作。

## 任务说明

### 密函无尽加速

#### 无尽

持续循环处理密函的三页流程：

1. 第一奖励页识别“确认选择”，点击 `(620, 607)` 3 次。
2. 轮次页识别“继续挑战”，点击 `(900, 500)` 3 次。
3. 第三页识别“Space 确认选择”，点击 `(920, 480)` 3 次。

相邻点击间隔为 50ms。模板只包含稳定按钮文字，不依赖奖励卡片、奖励数量或倒计时。

#### 驱离

持续执行：

```text
等待战斗或结算
→ 可选：每个副本执行一次 E/Q 技能组合
→ 第一奖励页“确认选择”
→ “再次进行”
→ 第三奖励页“Space 确认选择”
→ 返回下一轮监控
```

关闭“是否开启技能”时只处理结算和重新进入，不检测或释放角色技能。密函驱离没有“副本轮次”上限设置，会持续运行直到手动停止。

### 普通无尽加速

#### 扼守

扼守按“副本轮次”运行，每轮代表一个完成后的 99 局副本。轮次只在识别到结算页的“再次进行”时增加：

```text
检测到“再次进行”
→ 记录已完成第 N / 总轮数
→ 达到总轮数：结束
→ 未达到：点击“再次进行”
→ 等待并点击“开始挑战”
→ 进入下一轮
```

任务启动、HUD 确认、技能释放和点击“开始挑战”均不会增加轮次。技能关闭时只处理局内“继续挑战”“确认选择”和结算重开；技能开启时，每轮战斗开始后额外执行一次 E/Q 组合。

#### 无尽

仅监听并快速点击局内两个按钮：

- “继续挑战”：`(900, 500)`。
- “确认选择”：`(640, 505)`。

每次识别后点击 3 次，间隔 50ms。该模式不统计轮次、不处理“再次进行”或“开始挑战”，也不提供角色技能设置。

#### 驱离

局内不点击确认按钮，只等待副本结束后的“再次进行”。识别后按与扼守相同的完成轮次语义计数；未达到总轮数时，依次点击“再次进行”和“开始挑战”进入下一轮。

技能关闭时只处理结算与重开；技能开启时，每个副本只执行一次 E/Q 组合，之后只监听“再次进行”，不会在同一副本重复释放。

## 角色技能规则

角色技能适用于：

- 密函驱离。
- 普通扼守。
- 普通驱离。

共同规则：

1. 连续 3 帧识别右下角白色的 Q 未启用图标，确认战斗 HUD 已就绪。
2. 默认等待 2000ms；配置允许的最小值也是 2000ms。
3. 按开关执行 E 和 Q。E 默认 2 次；密函驱离和普通驱离的默认 E 间隔为 1000ms，普通扼守为 1250ms。
4. 延迟结束后不再二次识别 Q 图标，避免画面变化导致已配置的 Q 被跳过。
5. 技能组合结束后进入结算监控，同一副本不重复释放。

密函驱离和普通驱离还提供“仅高台释放 E”：

- 关闭：等待配置延迟后，按 E/Q 开关直接执行。
- 开启：连续确认 HUD 后立即在 300ms 窗口内锁定高台或非高台结果，再等待完整配置延迟。
- 高台：按配置执行 E 和 Q。
- 非高台：跳过 E，若 Q 已开启则执行 Q。

普通扼守没有高台判断选项。

## 焦点恢复

控制器执行真实前台输入。Python Agent 会在点击或按键前记录用户正在操作的非游戏窗口，完成一组输入后释放鼠标限制并尝试切回该窗口。

这是尽力恢复机制，不是强保证：Windows 可能拒绝前台切换，临时弹窗也可能改变候选窗口。当前自定义动作只以游戏输入是否成功作为最终成功状态，恢复失败不会使任务失败。

## 目录

```text
agent/
  main.py                       # AgentServer 入口
  focus_restore.py              # 输入代理与焦点恢复
  round_logger.py               # 普通扼守/驱离轮次日志和重开决策
assets/
  interface.json                # MXU 控制器、资源和导入入口
  resource/base/pipeline/       # MaaFramework Pipeline
  resource/base/image/          # 1280×720 模板
  resource/tasks/               # 用户任务、选项和预设
docs/
  architecture.md               # 当前架构与维护约束
  audit-2026-08-11.md           # 审计问题及修复状态
tools/
  inspect_windows.py            # 窗口信息检查
  validate_project.py           # 结构、引用和可达性校验
build_ui.py                     # 组装 MXU 桌面目录
```

## 验证

每次修改任务、选项、Pipeline 或模板后至少运行：

```powershell
python tools\validate_project.py
python -m compileall -q agent tools
```

校验器当前检查：

- 接口导入、任务分组、中文标题和说明。
- 选项引用与预设任务引用。
- Pipeline 节点重名、任务入口、`next` / `on_error` 悬空引用。
- `pipeline_override` 目标。
- Agent 动态调用的 Pipeline 目标。
- 所有当前节点是否至少在一个任务、选项或 Agent 动态路径中可达。
- 模板文件是否存在。

## 当前已知限制

- 桌面版尚未强制检查 `1280×720`。
- 长期监控使用 `max_hit: 10000000`，并非数学意义上的无限。
- 正常的非高台和部分 HUD 等待仍通过错误分支表达，可能持续生成 `debug/on_error` 截图。
- 构建过程不是事务式的。
- 焦点恢复失败不会反馈为任务失败。
- 桌面目录依赖系统 Python 和已安装的 `maa` 包，不是真正独立发行包。

详细状态见 [2026-08-11 审计报告](docs/audit-2026-08-11.md)。
