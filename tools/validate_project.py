"""Offline structural checks for the MaaFramework resource project."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
TASK_GROUP_REQUIREMENTS = {
    "CipherEndlessBoost": "DailyAFK",
    "NormalEndlessBoost": "DailyAFK",
    "CoinAFK": "DailyAFK",
    "ProgressMonitor": "Monitor",
}
PIPELINE_EDGE_FIELDS = ("next", "on_error")
PIPELINE_TIMING_FIELDS = ("rate_limit", "pre_delay", "post_delay")
# Agent custom actions invoke these nodes by name through Context.run_action or
# install them as runtime next targets through Context.override_pipeline.
DYNAMIC_PIPELINE_TARGETS = {
    "CipherExpelAgainByClick",
    "FocusGuardEKeyProxy",
    "FocusGuardQKeyProxy",
    "FocusGuardEBackgroundLogProxy",
    "NormalEndlessRestartByClick",
    "CoinAFKEscapeProxy",
    "CoinAFKRestartAgain",
}
COMBAT_HUD_READY_NODES = (
    "LiseCombatHudReadyFrame1",
    "LiseCombatHudReadyFrame2",
    "LiseCombatHudReady",
)
COMBAT_HUD_TEMPLATE = "CharacterControl/combat_health_bar.png"
COMBAT_HUD_ROI = [90, 675, 180, 40]
COMBAT_HUD_THRESHOLD = 0.85
SKILL_OPTION_ROOTS = {
    "CipherEnableSkills": "LiseEnableE",
    "NormalHoldEnableSkills": "NormalHoldEnableE",
    "NormalExpelEnableSkills": "LiseEnableE",
}
BACKGROUND_SKILL_OPTION_PARENTS = {
    "CipherEnableSkills",
    "NormalExpelEnableSkills",
}
SKILL_OPTION_BRANCHES = (
    (
        "LiseEnableE",
        "LiseEInterval",
        "LiseEnableQ",
        "LiseQBeforeE",
        "LiseQAfterTriggerDelay",
    ),
    (
        "NormalHoldEnableE",
        "NormalHoldEInterval",
        "NormalHoldEnableQ",
        "NormalHoldQBeforeE",
        "NormalHoldQAfterTriggerDelay",
    ),
)


def require_source_fragments(path: Path, fragments: tuple[str, ...]) -> str:
    """Return UTF-8 source after requiring fixed integration-contract fragments."""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"Missing required source: {path.relative_to(ROOT)}: {exc}") from exc
    missing = [fragment for fragment in fragments if fragment not in source]
    if missing:
        raise SystemExit(
            f"{path.relative_to(ROOT)}: missing process integration fragments: {missing}"
        )
    return source


def validate_process_termination_contract() -> None:
    """Keep Python Agent registration and the custom MXU kill command aligned."""
    registry_source = require_source_fragments(
        ROOT / "agent" / "process_registry.py",
        (
            "SCHEMA_VERSION = 1",
            "MAX_MARKER_BYTES = 4096",
            '"config" / "agent-processes"',
            "GetProcessTimes",
            "Path(sys.executable).resolve()",
            "os.replace(temporary_path, marker_path)",
        ),
    )
    if registry_source.index(
        "_validate_registry_directory(_REGISTRY_DIR)"
    ) > registry_source.index("marker_path.parent.mkdir"):
        raise SystemExit(
            "Agent registry must validate existing ancestors before creating directories"
        )

    main_source = require_source_fragments(
        ROOT / "agent" / "main.py",
        (
            "process_registry.register_current_process()",
            "AgentServer.start_up(sys.argv[-1])",
            "process_registry.unregister_current_process()",
        ),
    )
    if main_source.index("process_registry.register_current_process()") > main_source.index(
        "AgentServer.start_up(sys.argv[-1])"
    ):
        raise SystemExit("Agent must register before AgentServer.start_up")
    if main_source.index("process_registry.unregister_current_process()") < main_source.index(
        "AgentServer.start_up(sys.argv[-1])"
    ):
        raise SystemExit("Agent marker cleanup must follow the server lifecycle")

    patch_source = require_source_fragments(
        ROOT / "tools" / "mxu-v2.1.3-log-retention.patch",
        (
            "pub fn terminate_all_dna_helper_monitors()",
            "MonitorTerminationSummary",
            'serde(rename_all = "camelCase")',
            "MAX_PROCESS_MARKERS: usize = 256",
            "MAX_MARKER_BYTES: u64 = 4096",
            "GetProcessTimes",
            "QueryFullProcessImageNameW",
            "TerminateProcess",
            "TERMINATION_WAIT_MS: u32 = 2000",
            "config\").join(\"agent-processes\")",
            "terminate_all_dna_helper_monitors",
            "关闭所有监控进程",
            "不会关闭游戏或任何 DNA Helper 窗口",
            "不会关闭游戏",
        ),
    )
    if patch_source.count("terminateAllProcesses:") != 5:
        raise SystemExit("MXU process termination labels must exist in all five locales")
    forbidden_fragments = (
        "uiProcessesTerminated",
        "terminate_sibling_ui_processes",
        "await exit(0)",
    )
    present = [fragment for fragment in forbidden_fragments if fragment in patch_source]
    if present:
        raise SystemExit(f"MXU monitor cleanup must not terminate or exit UI processes: {present}")

    build_script_source = require_source_fragments(
        ROOT / "tools" / "build_custom_mxu.ps1",
        (
            "353c674b6aea4e7da617e4cb882effa744c1e05e",
            "git apply --unidiff-zero --check $patchFile",
            "git apply --unidiff-zero $patchFile",
            "git apply --unidiff-zero --reverse --check $patchFile",
        ),
    )
    if build_script_source.count("git apply --unidiff-zero") != 3:
        raise SystemExit("MXU zero-context patch must use --unidiff-zero in all apply paths")


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Invalid JSON: {path.relative_to(ROOT)}: {exc}") from exc


def collect_nested_option_refs(option: dict) -> set[str]:
    """Collect child options exposed by select/switch cases recursively."""
    refs: set[str] = set()
    for case in option.get("cases", []):
        refs.update(case.get("option", []))
    return refs


def collect_pipeline_overrides(value: object) -> list[dict[str, dict]]:
    """Collect every conditional pipeline override in an imported task file."""
    overrides: list[dict[str, dict]] = []
    if isinstance(value, dict):
        override = value.get("pipeline_override")
        if isinstance(override, dict):
            overrides.append(override)
        for child in value.values():
            overrides.extend(collect_pipeline_overrides(child))
    elif isinstance(value, list):
        for child in value:
            overrides.extend(collect_pipeline_overrides(child))
    return overrides


def collect_pipeline_edges(node: dict) -> set[str]:
    """Collect graph edges from one pipeline node or node override."""
    edges: set[str] = set()
    for field in PIPELINE_EDGE_FIELDS:
        targets = node.get(field, [])
        if isinstance(targets, str):
            targets = [targets]
        if isinstance(targets, list):
            edges.update(target for target in targets if isinstance(target, str))
    return edges


def option_case(option: dict, name: str) -> dict:
    """Return a named option case or fail with a useful validation error."""
    for case in option.get("cases", []):
        if case.get("name") == name:
            return case
    raise SystemExit(f"Option {option.get('label', '<unnamed>')} is missing case {name}")


def require_override(
    option_name: str,
    case: dict,
    node_name: str,
    expected: dict,
) -> None:
    actual = case.get("pipeline_override", {}).get(node_name, {})
    for field, value in expected.items():
        if actual.get(field) != value:
            raise SystemExit(
                f"{option_name}/{case.get('name')}: {node_name}.{field} "
                f"must be {value!r}, got {actual.get(field)!r}"
            )


def main() -> None:
    validate_process_termination_contract()
    interface_path = ASSETS / "interface.json"
    interface = load_json(interface_path)

    if interface.get("interface_version") != 2:
        raise SystemExit("assets/interface.json: interface_version must be 2")

    controller_names = {item["name"] for item in interface.get("controller", [])}
    if not controller_names:
        raise SystemExit("assets/interface.json: at least one controller is required")
    groups_by_name = {
        item["name"]: item for item in interface.get("group", []) if "name" in item
    }
    group_names = set(groups_by_name)
    monitor_group = groups_by_name.get("Monitor")
    if monitor_group is None or monitor_group.get("label") != "$group_monitor_label":
        raise SystemExit("Monitor group must use the localized monitor label")
    locale = load_json(ASSETS / interface["languages"]["zh_cn"])
    if locale.get("group_monitor_label") != "监控":
        raise SystemExit("Monitor group must render as 监控 in zh_cn")

    task_entries: set[str] = set()
    task_names: set[str] = set()
    option_names: set[str] = set()
    all_options: dict[str, dict] = {}
    task_option_refs: list[tuple[str, str, set[str]]] = []
    presets: list[tuple[str, dict]] = []
    pipeline_overrides: list[tuple[str, dict[str, dict]]] = []
    for relative in interface.get("import", []):
        imported_path = ASSETS / relative
        if not imported_path.is_file():
            raise SystemExit(f"Missing interface import: {relative}")
        imported = load_json(imported_path)
        pipeline_overrides.extend(
            (relative, override) for override in collect_pipeline_overrides(imported)
        )
        imported_options = imported.get("option", {})
        duplicate_options = set(imported_options) & option_names
        if duplicate_options:
            raise SystemExit(
                f"{relative}: duplicate option definitions: {sorted(duplicate_options)}"
            )
        option_names.update(imported_options)
        all_options.update(imported_options)
        for task in imported.get("task", []):
            task_names.add(task["name"])
            task_entries.add(task["entry"])
            task_option_refs.append((relative, task["name"], set(task.get("option", []))))
            required_group = TASK_GROUP_REQUIREMENTS.get(task["name"])
            if required_group is None:
                raise SystemExit(
                    f"{relative}: task {task['name']} needs an explicit group requirement "
                    "in tools/validate_project.py"
                )
            if required_group not in task.get("group", []):
                raise SystemExit(
                    f"{relative}: user task {task['name']} must belong to "
                    f"the {required_group} group"
                )
            for field in ("label", "description"):
                value = task.get(field)
                if not isinstance(value, str) or not value.strip() or value.startswith("$"):
                    raise SystemExit(
                        f"{relative}: task {task['name']} requires a direct Chinese {field}"
                    )
            unknown = set(task.get("controller", [])) - controller_names
            if unknown:
                raise SystemExit(
                    f"{relative}: task {task['name']} references unknown controllers: "
                    f"{sorted(unknown)}"
                )
            unknown_groups = set(task.get("group", [])) - group_names
            if unknown_groups:
                raise SystemExit(
                    f"{relative}: task {task['name']} references unknown groups: "
                    f"{sorted(unknown_groups)}"
                )
        for preset in imported.get("preset", []):
            presets.append((relative, preset))

    for relative, task_name, referenced_options in task_option_refs:
        reachable_options = set(referenced_options)
        pending = list(referenced_options)
        while pending:
            option_name = pending.pop()
            option = all_options.get(option_name)
            if option is None:
                continue
            for child_name in collect_nested_option_refs(option):
                if child_name not in reachable_options:
                    reachable_options.add(child_name)
                    pending.append(child_name)

        unknown_options = reachable_options - option_names
        if unknown_options:
            raise SystemExit(
                f"{relative}: task {task_name} references unknown options: "
                f"{sorted(unknown_options)}"
            )

    for relative, preset in presets:
        referenced_tasks = {
            item["name"] for item in preset.get("task", []) if "name" in item
        }
        unknown = referenced_tasks - task_names
        if unknown:
            raise SystemExit(
                f"{relative}: preset {preset['name']} references unknown tasks: "
                f"{sorted(unknown)}"
            )

    required_preset_tasks = {
        "CipherAFK": ["ProgressMonitor", "CipherEndlessBoost"],
        "NormalAFK": ["ProgressMonitor", "NormalEndlessBoost"],
    }
    presets_by_name = {preset["name"]: preset for _, preset in presets}
    for preset_name, expected_tasks in required_preset_tasks.items():
        preset = presets_by_name.get(preset_name)
        if preset is None:
            raise SystemExit(f"Missing required preset: {preset_name}")
        actual_tasks = [item.get("name") for item in preset.get("task", [])]
        if actual_tasks != expected_tasks:
            raise SystemExit(
                f"{preset_name} tasks must be ordered as {expected_tasks!r}, "
                f"got {actual_tasks!r}"
            )
        if not all(item.get("enabled") is True for item in preset.get("task", [])):
            raise SystemExit(f"{preset_name} tasks must all be enabled")
        monitor_preset = preset.get("task", [])[0]
        if "option" in monitor_preset:
            raise SystemExit(
                f"{preset_name}: ProgressMonitor run mode must be auto-detected"
            )

    pipeline_nodes: dict[str, dict] = {}
    pipeline_owners: dict[str, str] = {}
    template_paths: set[str] = set()
    pipeline_dir = ASSETS / "resource" / "base" / "pipeline"
    for path in sorted(pipeline_dir.rglob("*.json")):
        pipeline = load_json(path)
        duplicates = set(pipeline) & set(pipeline_nodes)
        if duplicates:
            raise SystemExit(
                f"{path.relative_to(ROOT)}: duplicate pipeline nodes: {sorted(duplicates)}"
            )
        pipeline_nodes.update(pipeline)
        pipeline_owners.update(
            {name: str(path.relative_to(ROOT)) for name in pipeline}
        )
        for node in pipeline.values():
            recognition = node.get("recognition", {})
            if recognition.get("type") != "TemplateMatch":
                continue
            template = recognition.get("param", {}).get("template")
            if isinstance(template, str):
                template_paths.add(template)

    for node_name, node in pipeline_nodes.items():
        missing_timing = [
            field for field in PIPELINE_TIMING_FIELDS if field not in node
        ]
        if missing_timing:
            raise SystemExit(
                f"{pipeline_owners[node_name]}: {node_name} must explicitly declare "
                f"pipeline timing fields: {missing_timing}"
            )
        invalid_timing = {
            field: node[field]
            for field in PIPELINE_TIMING_FIELDS
            if isinstance(node[field], bool)
            or not isinstance(node[field], (int, float))
            or node[field] < 0
        }
        if invalid_timing:
            raise SystemExit(
                f"{pipeline_owners[node_name]}: {node_name} has invalid pipeline "
                f"timing values: {invalid_timing}"
            )

    missing_entries = task_entries - set(pipeline_nodes)
    if missing_entries:
        raise SystemExit(f"Missing task entry pipeline nodes: {sorted(missing_entries)}")

    coin_entry = pipeline_nodes.get("CoinAFKEntry", {})
    if coin_entry.get("next") != ["CoinAFKInitialLobbyMonitor"]:
        raise SystemExit("CoinAFKEntry must only enter the commission-page start monitor")
    if pipeline_nodes.get("CoinAFKMoveBackward", {}).get("next") != [
        "CoinAFKInsideMonitor"
    ]:
        raise SystemExit("CoinAFK key sequence must continue into inside monitoring")
    expected_dungeon_entry_action = {
        "type": "Custom",
        "param": {"custom_action": "progress_dungeon_entered"},
    }
    if pipeline_nodes.get("CoinAFKCombatHudReady", {}).get("action") != (
        expected_dungeon_entry_action
    ):
        raise SystemExit("CoinAFKCombatHudReady must record stage 1 after HUD confirmation")
    coin_initial_next = pipeline_nodes.get("CoinAFKInitialLobbyMonitor", {}).get(
        "next", []
    )
    if not coin_initial_next or coin_initial_next[0] != "CoinAFKLobbyStart":
        raise SystemExit("CoinAFK initial monitor must start from the lobby button")
    coin_restart_next = pipeline_nodes.get("CoinAFKRestartLobbyMonitor", {}).get(
        "next", []
    )
    if (
        "CoinAFKSpaceStart" not in coin_restart_next
        or "CoinAFKCommissionCard" not in coin_restart_next
        or "CoinAFKLobbyStart" not in coin_restart_next
    ):
        raise SystemExit(
            "CoinAFK restart monitor must handle Space start and commission-page recovery"
        )
    established_fast_click_chains = (
        (
            "RewardConfirmThirdPageByClick",
            "RewardConfirmThirdPageClick2",
            "RewardConfirmThirdPageClick3",
            [920, 480],
            ["RewardConfirmEntry"],
        ),
        (
            "RewardConfirmByClick",
            "RewardConfirmFirstPageClick2",
            "RewardConfirmFirstPageClick3",
            [620, 607],
            ["RewardConfirmContinueChallenge", "RewardConfirmWaitContinue"],
        ),
        (
            "RewardConfirmContinueChallenge",
            "RewardConfirmContinueChallengeClick2",
            "RewardConfirmContinueChallengeClick3",
            [900, 500],
            ["RewardConfirmThirdPageByClick", "RewardConfirmWaitThird"],
        ),
        (
            "CipherExpelAgainByClick",
            "CipherExpelAgainClick2",
            "CipherExpelAgainClick3",
            [920, 640],
            ["CipherExpelRestartMonitor"],
        ),
        (
            "NormalEndlessContinueChallenge",
            "NormalEndlessContinueChallengeClick2",
            "NormalEndlessContinueChallengeClick3",
            [900, 500],
            ["NormalContinueTransition"],
        ),
        (
            "NormalEndlessStartChallengeByClick",
            "NormalEndlessStartChallengeClick2",
            "NormalEndlessStartChallengeClick3",
            [770, 490],
            ["NormalEndlessWaitStartChallenge"],
        ),
        (
            "NormalEndlessConfirmChoice",
            "NormalEndlessConfirmChoiceClick2",
            "NormalEndlessConfirmChoiceClick3",
            [640, 505],
            ["NormalEndlessMonitor"],
        ),
        (
            "NormalEndlessRestartByClick",
            "NormalEndlessRestartClick2",
            "NormalEndlessRestartClick3",
            [920, 640],
            ["NormalEndlessWaitStartChallenge"],
        ),
        (
            "NormalHoldPostSkillContinueChallenge",
            "NormalHoldPostSkillContinueChallengeClick2",
            "NormalHoldPostSkillContinueChallengeClick3",
            [900, 500],
            ["NormalHoldPostSkillContinueTransition"],
        ),
        (
            "NormalHoldPostSkillConfirmChoice",
            "NormalHoldPostSkillConfirmChoiceClick2",
            "NormalHoldPostSkillConfirmChoiceClick3",
            [640, 505],
            ["NormalHoldPostSkillIdle"],
        ),
    )
    coin_fast_click_chains = (
        (
            "CoinAFKLobbyStart",
            "CoinAFKLobbyStartClick2",
            "CoinAFKLobbyStartClick3",
            [1150, 640],
            ["CoinAFKWaitSpaceStart"],
        ),
        (
            "CoinAFKSpaceStart",
            "CoinAFKSpaceStartClick2",
            "CoinAFKSpaceStartClick3",
            [770, 520],
            ["CoinAFKWaitCombatHud"],
        ),
        (
            "CoinAFKContinueChallenge",
            "CoinAFKContinueChallengeClick2",
            "CoinAFKContinueChallengeClick3",
            [900, 500],
            ["CoinAFKContinueTransition"],
        ),
        (
            "CoinAFKConfirmChoice",
            "CoinAFKConfirmChoiceClick2",
            "CoinAFKConfirmChoiceClick3",
            [640, 505],
            ["CoinAFKInsideMonitor"],
        ),
        (
            "CoinAFKCommissionCard",
            "CoinAFKCommissionCardClick2",
            "CoinAFKCommissionCardClick3",
            [570, 400],
            ["CoinAFKRestartLobbyMonitor"],
        ),
        (
            "CoinAFKAbandon",
            "CoinAFKAbandonClick2",
            "CoinAFKAbandonClick3",
            [1185, 634],
            ["CoinAFKWaitAbandonConfirm"],
        ),
        (
            "CoinAFKAbandonConfirm",
            "CoinAFKAbandonConfirmClick2",
            "CoinAFKAbandonConfirmClick3",
            [770, 432],
            ["CoinAFKAbortOutsideMonitor"],
        ),
    )
    fast_click_chains = established_fast_click_chains + coin_fast_click_chains
    for first, second, third, target, final_next in fast_click_chains:
        for node_name, next_name in ((first, second), (second, third)):
            node = pipeline_nodes.get(node_name, {})
            if (
                node.get("action", {}).get("type") != "Click"
                or node.get("action", {}).get("param", {}).get("target") != target
                or node.get("post_delay") != 50
                or node.get("next") != [next_name]
                or (
                    node_name == second
                    and node.get("recognition", {}).get("type") != "DirectHit"
                )
            ):
                raise SystemExit(f"{node_name} must remain a native 50ms fast-click node")
        third_node = pipeline_nodes.get(third, {})
        finalize_name = f"{third}Finalize"
        finalize_node = pipeline_nodes.get(finalize_name, {})
        finalize_param = finalize_node.get("action", {}).get("param", {})
        if (
            third_node.get("action", {}).get("type") != "Click"
            or third_node.get("recognition", {}).get("type") != "DirectHit"
            or third_node.get("action", {}).get("param", {}).get("target") != target
            or third_node.get("post_delay") != 0
            or third_node.get("next") != [finalize_name]
        ):
            raise SystemExit(f"{third} must remain the third native mouse click")
        if (
            finalize_node.get("recognition", {}).get("type") != "DirectHit"
            or finalize_node.get("action", {}).get("type") != "Custom"
            or finalize_param.get("custom_action") != "focus_guard_finalize"
            or finalize_param.get("custom_action_param", {}).get("restore_delay_ms")
            != 100
            or finalize_node.get("rate_limit") != 0
            or finalize_node.get("pre_delay") != 0
            or finalize_node.get("post_delay") != 0
            or finalize_node.get("next") != final_next
        ):
            raise SystemExit(f"{finalize_name} must restore focus without mouse input")
    for node_name, node in pipeline_nodes.items():
        custom_param = (
            node.get("action", {})
            .get("param", {})
            .get("custom_action_param", {})
        )
        if custom_param.get("kind") == "click":
            raise SystemExit(f"{node_name}: Agent actions must never send mouse clicks")
    for relative, override in pipeline_overrides:
        for node_name, node_override in override.items():
            custom_param = (
                node_override.get("action", {})
                .get("param", {})
                .get("custom_action_param", {})
            )
            if custom_param.get("kind") == "click":
                raise SystemExit(
                    f"{relative}: {node_name} override must not send Agent mouse clicks"
                )
    for first in (
        "CoinAFKRestartAgain",
        "CoinAFKRestartAgainRetry",
        "CoinAFKAbortAgain",
    ):
        first_node = pipeline_nodes.get(first, {})
        if (
            first_node.get("action", {}).get("type") != "Click"
            or first_node.get("action", {}).get("param", {}).get("target")
            != [920, 640]
            or first_node.get("post_delay") != 50
            or first_node.get("next") != ["CoinAFKAgainClick2"]
        ):
            raise SystemExit(f"{first} must enter the shared native again-click chain")
    again_second = pipeline_nodes.get("CoinAFKAgainClick2", {})
    again_third = pipeline_nodes.get("CoinAFKAgainClick3", {})
    again_finalize = pipeline_nodes.get("CoinAFKAgainClick3Finalize", {})
    again_finalize_param = again_finalize.get("action", {}).get("param", {})
    if (
        again_second.get("action", {}).get("type") != "Click"
        or again_second.get("action", {}).get("param", {}).get("target")
        != [920, 640]
        or again_second.get("post_delay") != 50
        or again_second.get("next") != ["CoinAFKAgainClick3"]
        or again_third.get("action", {}).get("type") != "Click"
        or again_third.get("action", {}).get("param", {}).get("target") != [920, 640]
        or again_third.get("post_delay") != 0
        or again_third.get("next") != ["CoinAFKAgainClick3Finalize"]
        or again_finalize_param.get("custom_action") != "focus_guard_finalize"
        or again_finalize.get("next") != ["CoinAFKRestartLobbyMonitor"]
    ):
        raise SystemExit("CoinAFK again buttons must share the 50ms fast-click chain")
    coin_move = (
        pipeline_nodes.get("CoinAFKMoveBackward", {})
        .get("action", {})
        .get("param", {})
    )
    expected_coin_move = {
        "kind": "key_sequence",
        "steps": [
            {"delay_ms": 2000},
            {"key": 69},
            {"delay_ms": 300},
            {"key": 69},
            {"delay_ms": 300},
            {"key": 83, "hold_ms": 600},
            {"key": 81},
            {"delay_ms": 3500},
            {"key": 83, "hold_ms": 5000},
        ],
        "restore_delay_ms": 100,
    }
    if coin_move.get("custom_action") != "focus_guard_action" or coin_move.get(
        "custom_action_param"
    ) != expected_coin_move:
        raise SystemExit("CoinAFK must preserve the formal combat key sequence")
    if pipeline_nodes.get("CoinAFKAbandonConfirmClick3Finalize", {}).get("next") != [
        "CoinAFKAbortOutsideMonitor"
    ]:
        raise SystemExit("CoinAFK wrong-map abandon path must bypass round counting")
    coin_inputs = all_options.get("CoinAFKRestartCount", {}).get("inputs", [])
    if len(coin_inputs) != 1 or coin_inputs[0].get("verify") != "^[1-9]\\d{0,2}$":
        raise SystemExit("CoinAFK round count must remain in the 1-999 range")

    monitor_action = (
        pipeline_nodes.get("ProgressMonitorEntry", {}).get("action", {}).get("param", {})
    )
    if monitor_action.get("custom_action") != "progress_monitor_start":
        raise SystemExit("ProgressMonitorEntry must call progress_monitor_start")

    if "ProgressMonitorRunMode" in all_options:
        raise SystemExit("ProgressMonitor run mode must not require a UI option")
    monitor_log = pipeline_nodes.get("ProgressMonitorLog", {})
    if monitor_log.get("next") != ["ProgressMonitorKeepAlive"]:
        raise SystemExit(
            "ProgressMonitorLog must keep standalone monitoring active by default"
        )
    keep_alive = pipeline_nodes.get("ProgressMonitorKeepAlive", {})
    if keep_alive.get("next") != ["ProgressMonitorKeepAlive"]:
        raise SystemExit("ProgressMonitorKeepAlive must remain active until UI stop")
    if int(keep_alive.get("post_delay", 0)) < 1000:
        raise SystemExit("ProgressMonitorKeepAlive must not busy-loop")

    missing_dynamic_targets = DYNAMIC_PIPELINE_TARGETS - set(pipeline_nodes)
    if missing_dynamic_targets:
        raise SystemExit(
            f"Missing Agent dynamic pipeline targets: {sorted(missing_dynamic_targets)}"
        )

    for node_name in COMBAT_HUD_READY_NODES:
        node = pipeline_nodes.get(node_name)
        if node is None:
            raise SystemExit(f"Missing combat HUD confirmation node: {node_name}")
        recognition = node.get("recognition", {})
        params = recognition.get("param", {})
        if recognition.get("type") != "TemplateMatch":
            raise SystemExit(f"{node_name}: combat HUD recognition must use TemplateMatch")
        if params.get("template") != COMBAT_HUD_TEMPLATE:
            raise SystemExit(
                f"{node_name}: combat HUD template must be {COMBAT_HUD_TEMPLATE}"
            )
        if params.get("roi") != COMBAT_HUD_ROI:
            raise SystemExit(f"{node_name}: combat HUD ROI must be {COMBAT_HUD_ROI}")
        if params.get("threshold") != COMBAT_HUD_THRESHOLD:
            raise SystemExit(
                f"{node_name}: combat HUD threshold must be {COMBAT_HUD_THRESHOLD}"
            )

    state_hud_chains = {
        "NormalOutside": {
            "nodes": (
                "NormalOutsideCombatHudFrame1",
                "NormalOutsideCombatHudFrame2",
                "NormalOutsideCombatHudReady",
            ),
            "fallback": "NormalOutsideMonitor",
            "ready_next": "NormalEndlessIdle",
        },
        "NormalRestart": {
            "nodes": (
                "NormalRestartCombatHudFrame1",
                "NormalRestartCombatHudFrame2",
                "NormalRestartCombatHudReady",
            ),
            "fallback": "NormalEndlessWaitStartChallenge",
            "ready_next": "NormalEndlessIdle",
        },
        "NormalPostSkill": {
            "nodes": (
                "NormalPostSkillCombatHudFrame1",
                "NormalPostSkillCombatHudFrame2",
                "NormalPostSkillCombatHudReady",
            ),
            "fallback": "NormalPostSkillOutsideMonitor",
            "ready_next": "NormalHoldPostSkillIdle",
        },
        "CipherOutside": {
            "nodes": (
                "CipherOutsideCombatHudFrame1",
                "CipherOutsideCombatHudFrame2",
                "CipherOutsideCombatHudReady",
            ),
            "fallback": "CipherExpelOutsideMonitor",
            "ready_next": "CipherExpelMonitor",
        },
        "CipherPostSkill": {
            "nodes": (
                "CipherPostSkillCombatHudFrame1",
                "CipherPostSkillCombatHudFrame2",
                "CipherPostSkillCombatHudReady",
            ),
            "fallback": "CipherPostSkillOutsideMonitor",
            "ready_next": "CipherPostSkillInsideIdle",
        },
        "CipherReentry": {
            "nodes": (
                "CipherReentryCombatHudFrame1",
                "CipherReentryCombatHudFrame2",
                "CipherReentryCombatHudReady",
            ),
            "fallback": "CipherExpelRestartMonitor",
            "ready_next": "CipherExpelMonitor",
        },
    }
    for chain_name, chain in state_hud_chains.items():
        frame1, frame2, ready = chain["nodes"]
        expected_next = {
            frame1: [frame2],
            frame2: [ready],
            ready: [chain["ready_next"]],
        }
        for node_name in (frame1, frame2, ready):
            node = pipeline_nodes.get(node_name)
            if node is None:
                raise SystemExit(f"Missing {chain_name} HUD state node: {node_name}")
            recognition = node.get("recognition", {})
            params = recognition.get("param", {})
            if recognition.get("type") != "TemplateMatch":
                raise SystemExit(f"{node_name}: HUD state recognition must use TemplateMatch")
            if params.get("template") != COMBAT_HUD_TEMPLATE:
                raise SystemExit(f"{node_name}: unexpected HUD state template")
            if params.get("roi") != COMBAT_HUD_ROI:
                raise SystemExit(f"{node_name}: unexpected HUD state ROI")
            if params.get("threshold") != COMBAT_HUD_THRESHOLD:
                raise SystemExit(f"{node_name}: unexpected HUD state threshold")
            if node.get("next") != expected_next[node_name]:
                raise SystemExit(f"{node_name}: invalid HUD state next node")
            if node.get("on_error") != [chain["fallback"]]:
                raise SystemExit(f"{node_name}: failed HUD state check must return to its state monitor")

    expected_outside_monitors = {
        "NormalOutsideMonitor": [
            "NormalOutsideCombatHudFrame1",
            "NormalEndlessAgainDetected",
            "NormalEndlessStartChallengeByClick",
            "NormalOutsideIdle",
        ],
        "NormalEndlessWaitStartChallenge": [
            "NormalEndlessRestartByClick",
            "NormalEndlessStartChallengeByClick",
            "NormalRestartCombatHudFrame1",
            "NormalEndlessWaitStartChallenge",
        ],
        "NormalPostSkillOutsideMonitor": [
            "NormalPostSkillCombatHudFrame1",
            "NormalEndlessAgainDetected",
            "NormalEndlessStartChallengeByClick",
            "NormalPostSkillOutsideIdle",
        ],
        "CipherExpelOutsideMonitor": [
            "CipherOutsideCombatHudFrame1",
            "CipherExpelAgainDetected",
            "RewardConfirmThirdPageByClick",
            "CipherExpelOutsideIdle",
        ],
        "CipherPostSkillOutsideMonitor": [
            "CipherPostSkillCombatHudFrame1",
            "CipherExpelAgainDetected",
            "RewardConfirmThirdPageByClick",
            "CipherPostSkillOutsideIdle",
        ],
        "CipherExpelRestartMonitor": [
            "CipherReentryCombatHudFrame1",
            "RewardConfirmThirdPageByClick",
            "CipherExpelAgainByClick",
            "CipherExpelRestartIdle",
        ],
    }
    for node_name, expected_next in expected_outside_monitors.items():
        node = pipeline_nodes.get(node_name)
        if node is None or node.get("next") != expected_next:
            raise SystemExit(
                f"{node_name}: outside state candidates must be {expected_next!r}"
            )

    expected_entry_router = [
        "CipherOutsideCombatHudFrame1",
        "RewardConfirmByClick",
        "CipherExpelAgainDetected",
        "RewardConfirmThirdPageByClick",
        "CipherExpelEntryIdle",
    ]
    if pipeline_nodes.get("CipherExpelEntryMonitor", {}).get("next") != expected_entry_router:
        raise SystemExit(
            "CipherExpelEntryMonitor: unknown-state entry must classify HUD, "
            "inside confirmation, and outside buttons"
        )

    for removed_node in (
        "CipherExpelWaitAgain",
        "CipherExpelWaitThird",
        "CipherRestartCombatHudFrame1",
        "CipherRestartCombatHudFrame2",
        "CipherRestartCombatHudReady",
        "NormalExpelMonitor",
        "NormalExpelPostSkillMonitor",
    ):
        if removed_node in pipeline_nodes:
            raise SystemExit(f"{removed_node}: legacy mixed-state node must stay removed")

    expected_state_gates = {
        "NormalHoldInsideGate": (["NormalEndlessMonitor"], ["NormalEndlessIdle"]),
        "NormalExpelInsideGate": (["NormalExpelInsideIdle"], ["NormalExpelInsideIdle"]),
        "NormalHoldPostSkillInsideGate": (
            ["NormalHoldPostSkillMonitor"],
            ["NormalHoldPostSkillIdle"],
        ),
        "NormalExpelPostSkillInsideGate": (
            ["NormalExpelPostSkillInsideIdle"],
            ["NormalExpelPostSkillInsideIdle"],
        ),
        "CipherPostSkillInsideGate": (
            ["CipherPostSkillInsideIdle"],
            ["CipherPostSkillInsideIdle"],
        ),
        "CipherExpelInsideGate": (
            ["CipherExpelInsideIdle"],
            ["CipherExpelInsideIdle"],
        ),
        "CipherExpelSettlementGate": (
            ["CipherExpelSettlementIdle"],
            ["CipherExpelSettlementIdle"],
        ),
    }
    for node_name, (expected_next, expected_error) in expected_state_gates.items():
        node = pipeline_nodes.get(node_name)
        recognition = node.get("recognition", {}) if node else {}
        params = recognition.get("param", {})
        if (
            recognition.get("type") != "TemplateMatch"
            or params.get("template") != COMBAT_HUD_TEMPLATE
            or params.get("roi") != COMBAT_HUD_ROI
            or params.get("threshold") != COMBAT_HUD_THRESHOLD
        ):
            raise SystemExit(f"{node_name}: state gate must use the combat health bar")
        if node.get("next") != expected_next or node.get("on_error") != expected_error:
            raise SystemExit(f"{node_name}: invalid inside/outside state transition")

    if "CharacterControl/q_inactive.png" in template_paths:
        raise SystemExit("Q icon must not be used as a combat HUD trigger")

    expected_skill_nodes = {
        "LiseSkillOrderEntry": ["LisePressE", "LisePressQ", "LiseSkillCastEnd"],
        "LisePressE": ["LisePressQ", "LiseSkillCastEnd"],
        "LisePressQBeforeE": [
            "LiseQBeforeEIntervalDelay",
            "LisePressEAfterQ",
            "LiseSkillCastEnd",
        ],
        "LiseQBeforeEIntervalDelay": ["LisePressEAfterQ", "LiseSkillCastEnd"],
        "LisePressEAfterQ": ["LiseSkillCastEnd"],
    }
    for node_name, expected_next in expected_skill_nodes.items():
        node = pipeline_nodes.get(node_name)
        if node is None:
            raise SystemExit(f"Missing shared skill-order node: {node_name}")
        if node.get("next") != expected_next:
            raise SystemExit(
                f"{node_name}.next must be {expected_next!r}, got {node.get('next')!r}"
            )

    for node_name, node in pipeline_nodes.items():
        for event in node.get("focus", {}).values():
            if "[黎瑟]" in event.get("content", ""):
                raise SystemExit(f"{node_name}: skill log prefix must use [角色]")

    for node_name in ("LisePressQ", "LisePressQBeforeE"):
        params = (
            pipeline_nodes[node_name]
            .get("action", {})
            .get("param", {})
            .get("custom_action_param", {})
        )
        expected_q_params = {
            "kind": "key",
            "key": 81,
            "repeat": 3,
            "interval_ms": 100,
        }
        if params != expected_q_params:
            raise SystemExit(
                f"{node_name}: Q input must be sent 3 times at 100ms intervals"
            )

    for parent_name, e_option_name in SKILL_OPTION_ROOTS.items():
        parent = all_options.get(parent_name)
        if parent is None:
            raise SystemExit(f"Missing skill option parent: {parent_name}")
        yes_options = option_case(parent, "Yes").get("option", [])
        if e_option_name not in yes_options:
            raise SystemExit(
                f"{parent_name}: must expose {e_option_name} when skills are enabled"
            )
        if parent_name in BACKGROUND_SKILL_OPTION_PARENTS:
            if "BackgroundSkillInput" not in yes_options:
                raise SystemExit(
                    f"{parent_name}: expel skills must expose BackgroundSkillInput"
                )
            if yes_options[-1] != "BackgroundSkillInput":
                raise SystemExit(
                    f"{parent_name}: BackgroundSkillInput must be applied after nested E/Q "
                    "options so its custom action remains authoritative"
                )
        elif "BackgroundSkillInput" in yes_options:
            raise SystemExit(
                f"{parent_name}: BackgroundSkillInput is restricted to expel modes"
            )
        if "LiseQBeforeE" in yes_options or "NormalHoldQBeforeE" in yes_options:
            raise SystemExit(
                f"{parent_name}: Q-before-E must be nested under both E and Q switches"
            )

    background_input = all_options.get("BackgroundSkillInput")
    if background_input is None or background_input.get("default_case") != "No":
        raise SystemExit("BackgroundSkillInput must exist and default to foreground input")
    background_yes = option_case(background_input, "Yes")
    for node_name in (
        "LisePressE",
        "LisePressEAfterQ",
        "LisePressQ",
        "LisePressQBeforeE",
    ):
        custom_action = (
            background_yes.get("pipeline_override", {})
            .get(node_name, {})
            .get("action", {})
            .get("param", {})
            .get("custom_action")
        )
        if custom_action != "hybrid_skill_action":
            raise SystemExit(
                f"BackgroundSkillInput/Yes must route {node_name} through "
                "hybrid_skill_action"
            )

    for e_name, interval_name, q_name, order_name, delay_name in SKILL_OPTION_BRANCHES:
        enable_e = all_options.get(e_name, {})
        e_yes_options = option_case(enable_e, "Yes").get("option", [])
        e_no_options = option_case(enable_e, "No").get("option", [])
        for required in ("LiseECount", interval_name, q_name):
            if required not in e_yes_options:
                raise SystemExit(f"{e_name}/Yes must expose {required}")
        if order_name in e_yes_options or order_name in e_no_options:
            raise SystemExit(f"{e_name}: {order_name} must only be nested under Q/Yes")
        if "LiseEnableQOnly" not in e_no_options:
            raise SystemExit(f"{e_name}/No must expose LiseEnableQOnly")

        enable_q = all_options.get(q_name, {})
        q_yes_options = option_case(enable_q, "Yes").get("option", [])
        q_no_options = option_case(enable_q, "No").get("option", [])
        if order_name not in q_yes_options or order_name in q_no_options:
            raise SystemExit(f"{q_name}: {order_name} must only appear under Q/Yes")

        q_order = all_options.get(order_name)
        if q_order is None or q_order.get("default_case") != "No":
            raise SystemExit(f"{order_name} must exist and default to No")
        q_before = option_case(q_order, "Yes")
        if delay_name not in q_before.get("option", []):
            raise SystemExit(f"{order_name}/Yes must expose {delay_name}")
        if delay_name in option_case(q_order, "No").get("option", []):
            raise SystemExit(f"{order_name}/No must hide {delay_name}")
        require_override(
            order_name,
            q_before,
            "LiseSkillOrderEntry",
            {"next": ["LisePressQBeforeE", "LisePressEAfterQ", "LiseSkillCastEnd"]},
        )
        q_after = option_case(q_order, "No")
        require_override(
            order_name,
            q_after,
            "LiseSkillOrderEntry",
            {"next": ["LisePressE", "LisePressQ", "LiseSkillCastEnd"]},
        )
        require_override(
            order_name,
            q_after,
            "LisePressE",
            {"next": ["LisePressQ", "LiseSkillCastEnd"]},
        )

        delay = all_options.get(delay_name, {})
        delay_inputs = delay.get("inputs", [])
        if not delay_inputs or delay_inputs[0].get("default") != "2000":
            raise SystemExit(f"{delay_name}: Q-after delay must default to 2000ms")
        delay_override = delay.get("pipeline_override", {}).get(
            "LiseQBeforeEIntervalDelay", {}
        )
        if delay_override.get("pre_delay") != "{delay_ms}":
            raise SystemExit(
                f"{delay_name}: must control LiseQBeforeEIntervalDelay.pre_delay"
            )

    for q_name in ("LiseEnableQ", "NormalHoldEnableQ", "LiseEnableQOnly"):
        enable_q = all_options.get(q_name, {})
        for case_name, enabled in (("Yes", True), ("No", False)):
            case = option_case(enable_q, case_name)
            require_override(q_name, case, "LisePressQ", {"enabled": enabled})
            require_override(
                q_name, case, "LisePressQBeforeE", {"enabled": enabled}
            )

    for e_name in ("LiseEnableE", "NormalHoldEnableE"):
        enable_e = all_options.get(e_name, {})
        for case_name, enabled in (("Yes", True), ("No", False)):
            case = option_case(enable_e, case_name)
            require_override(e_name, case, "LisePressE", {"enabled": enabled})
            require_override(
                e_name, case, "LisePressEAfterQ", {"enabled": enabled}
            )
            require_override(
                e_name,
                case,
                "LiseQBeforeEIntervalDelay",
                {"enabled": enabled},
            )

    def progress_start_action(mode: str, total: object, stage_total: int) -> dict:
        return {
            "type": "Custom",
            "param": {
                "custom_action": "focus_guard_start",
                "custom_action_param": {
                    "progress_mode": mode,
                    "progress_total": total,
                    "progress_stage_total": stage_total,
                },
            },
        }

    if pipeline_nodes.get("RewardConfirmEntry", {}).get("action") != progress_start_action(
        "密函无尽", 0, 0
    ):
        raise SystemExit("RewardConfirmEntry must initialize cipher endless progress")
    if pipeline_nodes.get("NormalEndlessEntry", {}).get("action") != progress_start_action(
        "普通扼守", 1, 99
    ):
        raise SystemExit("NormalEndlessEntry must initialize normal hold progress")

    expected_progress_events = {
        "RewardConfirmThirdPageClick3Finalize": "cipher_cycle_completed",
        "NormalEndlessContinueChallengeClick3Finalize": "continue_challenge",
        "NormalHoldPostSkillContinueChallengeClick3Finalize": "continue_challenge",
        "NormalEndlessStartChallengeClick3Finalize": "next_round_started",
        "CoinAFKContinueChallengeClick3Finalize": "continue_challenge",
        "CoinAFKSpaceStartClick3Finalize": "next_round_started",
    }
    for node_name, expected_event in expected_progress_events.items():
        params = (
            pipeline_nodes.get(node_name, {})
            .get("action", {})
            .get("param", {})
            .get("custom_action_param", {})
        )
        if params.get("progress_event") != expected_event:
            raise SystemExit(f"{node_name}: must emit progress event {expected_event}")

    expected_dungeon_entry_action = {
        "type": "Custom",
        "param": {"custom_action": "progress_dungeon_entered"},
    }
    for node_name in (
        "NormalOutsideCombatHudReady",
        "NormalRestartCombatHudReady",
        "NormalPostSkillCombatHudReady",
    ):
        if pipeline_nodes.get(node_name, {}).get("action") != (
            expected_dungeon_entry_action
        ):
            raise SystemExit(f"{node_name}: must record stage 1 after HUD confirmation")

    normal_mode = all_options.get("NormalMode", {})
    hold_mode = option_case(normal_mode, "Endless")
    require_override(
        "NormalMode",
        hold_mode,
        "NormalEndlessEntry",
        {"next": ["NormalOutsideMonitor"]},
    )
    require_override(
        "NormalMode",
        hold_mode,
        "NormalEndlessMonitor",
        {
            "next": [
                "NormalEndlessContinueChallenge",
                "NormalEndlessConfirmChoice",
                "NormalEndlessIdle",
            ]
        },
    )
    require_override(
        "NormalMode",
        hold_mode,
        "LiseSkillCastEnd",
        {"next": ["NormalHoldPostSkillIdle"]},
    )
    require_override(
        "NormalMode",
        hold_mode,
        "NormalEndlessContinueChallengeClick3Finalize",
        {"next": ["NormalContinueTransition"]},
    )
    require_override(
        "NormalMode",
        hold_mode,
        "NormalEndlessConfirmChoiceClick3Finalize",
        {"next": ["NormalEndlessIdle"]},
    )
    require_override(
        "NormalMode",
        hold_mode,
        "NormalEndlessIdle",
        {
            "next": [
                "NormalHoldInsideGate",
                "NormalEndlessContinueChallenge",
                "NormalEndlessConfirmChoice",
                "NormalEndlessAgainDetected",
                "NormalEndlessStartChallengeByClick",
                "NormalEndlessIdle",
            ]
        },
    )

    infinite_mode = option_case(normal_mode, "Infinite")
    require_override(
        "NormalMode",
        infinite_mode,
        "NormalEndlessEntry",
        {
            "action": progress_start_action("普通无尽", 0, 0),
            "next": ["NormalEndlessMonitor"],
        },
    )
    require_override(
        "NormalMode",
        infinite_mode,
        "NormalEndlessMonitor",
        {
            "next": [
                "NormalEndlessContinueChallenge",
                "NormalEndlessConfirmChoice",
                "NormalEndlessIdle",
            ]
        },
    )
    require_override(
        "NormalMode",
        infinite_mode,
        "NormalEndlessIdle",
        {"next": ["NormalEndlessMonitor"]},
    )
    infinite_override = infinite_mode.get("pipeline_override", {})
    for inherited_click_node in (
        "NormalEndlessContinueChallenge",
        "NormalEndlessConfirmChoice",
    ):
        if inherited_click_node in infinite_override:
            raise SystemExit(
                "NormalMode/Infinite must inherit the native three-click chain"
            )
    require_override(
        "NormalMode",
        infinite_mode,
        "NormalContinueTransition",
        {"next": ["NormalEndlessConfirmChoice", "NormalEndlessMonitor"]},
    )

    expel_mode = option_case(normal_mode, "Expel")
    require_override(
        "NormalMode",
        expel_mode,
        "NormalEndlessEntry",
        {"next": ["NormalOutsideMonitor"]},
    )
    require_override(
        "NormalMode",
        expel_mode,
        "LiseSkillCastEnd",
        {"next": ["NormalExpelPostSkillInsideIdle"]},
    )
    for node_name in ("NormalOutsideCombatHudReady", "NormalRestartCombatHudReady"):
        require_override(
            "NormalMode",
            expel_mode,
            node_name,
            {"next": ["NormalExpelInsideIdle"]},
        )
    require_override(
        "NormalMode",
        expel_mode,
        "NormalPostSkillCombatHudReady",
        {"next": ["NormalExpelPostSkillInsideIdle"]},
    )

    for option_name, mode_name, stage_total in (
        ("NormalEndlessRestartCount", "普通扼守", 99),
        ("NormalExpelRestartCount", "普通驱离", 0),
    ):
        option = all_options.get(option_name, {})
        action = (
            option.get("pipeline_override", {})
            .get("NormalEndlessEntry", {})
            .get("action")
        )
        if action != progress_start_action(mode_name, "{count}", stage_total):
            raise SystemExit(f"{option_name}: must initialize configured progress")

    normal_expel_round_inputs = all_options.get("NormalExpelRestartCount", {}).get(
        "inputs", []
    )
    if (
        not normal_expel_round_inputs
        or normal_expel_round_inputs[0].get("default") != "1"
    ):
        raise SystemExit("NormalExpelRestartCount must default to one completed dungeon")
    if normal_expel_round_inputs[0].get("verify") != r"^[1-9]\d{0,3}$":
        raise SystemExit("NormalExpelRestartCount must accept values from 1 through 9999")

    cipher_mode = all_options.get("CipherMode", {})
    cipher_expel_mode = option_case(cipher_mode, "Expel")
    if "CipherExpelRestartCount" not in cipher_expel_mode.get("option", []):
        raise SystemExit("CipherMode/Expel must expose CipherExpelRestartCount")
    require_override(
        "CipherMode",
        cipher_expel_mode,
        "RewardConfirmEntry",
        {
            "action": progress_start_action("密函驱离", 1, 0),
            "next": ["CipherExpelEntryMonitor"],
        },
    )
    require_override(
        "CipherMode",
        cipher_expel_mode,
        "RewardConfirmThirdPageClick3Finalize",
        {"next": ["CipherExpelRestartMonitor"]},
    )
    require_override(
        "CipherMode",
        cipher_expel_mode,
        "LiseSkillCastEnd",
        {"next": ["CipherExpelSettlementMonitor"]},
    )

    cipher_round_option = all_options.get("CipherExpelRestartCount", {})
    cipher_round_inputs = cipher_round_option.get("inputs", [])
    if not cipher_round_inputs or cipher_round_inputs[0].get("default") != "1":
        raise SystemExit("CipherExpelRestartCount must default to one completed dungeon")
    if cipher_round_inputs[0].get("verify") != r"^[1-9]\d{0,3}$":
        raise SystemExit("CipherExpelRestartCount must accept values from 1 through 9999")
    cipher_round_override = cipher_round_option.get("pipeline_override", {})
    if cipher_round_override.get("RewardConfirmEntry", {}).get(
        "action"
    ) != progress_start_action("密函驱离", "{count}", 0):
        raise SystemExit("CipherExpelRestartCount must initialize finite progress")
    cipher_quota_override = cipher_round_override.get("CipherExpelRoundQuota", {})
    if cipher_quota_override.get("max_hit") != "{count}":
        raise SystemExit("CipherExpelRestartCount must control CipherExpelRoundQuota.max_hit")
    for node_name, action_name in (
        ("CipherExpelRoundQuota", "cipher_expel_log_round"),
        ("CipherExpelRoundDecision", "cipher_expel_decide_restart"),
    ):
        action = cipher_round_override.get(node_name, {}).get("action", {})
        params = action.get("param", {})
        if (
            action.get("type") != "Custom"
            or params.get("custom_action") != action_name
            or params.get("custom_action_param") != {"total": "{count}"}
        ):
            raise SystemExit(f"CipherExpelRestartCount: invalid {node_name} override")

    expected_cipher_round_chain = {
        "CipherExpelAgainDetected": ["CipherExpelRoundQuota"],
        "CipherExpelRoundQuota": ["CipherExpelRoundLog"],
        "CipherExpelRoundLog": ["CipherExpelRoundDecision"],
        "CipherExpelRoundDecision": ["CipherExpelFinished"],
        "CipherExpelAgainClick3Finalize": ["CipherExpelRestartMonitor"],
    }
    for node_name, expected_next in expected_cipher_round_chain.items():
        if pipeline_nodes.get(node_name, {}).get("next") != expected_next:
            raise SystemExit(f"{node_name}: invalid cipher expel round chain")
    if pipeline_nodes.get("CipherExpelFinished", {}).get("action", {}).get("type") != "StopTask":
        raise SystemExit("CipherExpelFinished must stop the task at the configured quota")

    inside_monitors = {
        "NormalEndlessMonitor": [
            "NormalEndlessContinueChallenge",
            "NormalEndlessConfirmChoice",
            "NormalEndlessIdle",
        ],
        "NormalEndlessCombatEntry": [
            "NormalEndlessContinueChallenge",
            "NormalEndlessConfirmChoice",
            "LiseSkillOrderEntry",
            "LiseSkillCastEnd",
        ],
        "NormalExpelCombatEntry": [
            "LiseSkillOrderEntry",
            "LiseSkillCastEnd",
        ],
        "NormalHoldPostSkillMonitor": [
            "NormalHoldPostSkillContinueChallenge",
            "NormalHoldPostSkillConfirmChoice",
            "NormalHoldPostSkillIdle",
        ],
        "CipherExpelSettlementMonitor": [
            "RewardConfirmByClick",
            "CipherExpelSettlementGate",
            "CipherExpelAgainDetected",
            "RewardConfirmThirdPageByClick",
            "CipherExpelSettlementIdle",
        ],
        "CipherExpelMonitor": [
            "RewardConfirmByClick",
            "LiseCombatHudReadyFrame1",
            "CipherExpelInsideGate",
            "CipherExpelAgainDetected",
            "RewardConfirmThirdPageByClick",
            "CipherExpelInsideIdle",
        ],
    }
    for node_name, expected_next in inside_monitors.items():
        node = pipeline_nodes.get(node_name)
        if node is None:
            raise SystemExit(f"Missing inside monitor node: {node_name}")
        if node.get("next") != expected_next:
            raise SystemExit(
                f"{node_name}.next must be {expected_next!r}, "
                f"got {node.get('next')!r}"
            )

    expected_post_skill_returns = {
        "NormalHoldPostSkillContinueChallengeClick3Finalize": "NormalHoldPostSkillContinueTransition",
        "NormalHoldPostSkillConfirmChoiceClick3Finalize": "NormalHoldPostSkillIdle",
    }
    for node_name, target in expected_post_skill_returns.items():
        if pipeline_nodes.get(node_name, {}).get("next") != [target]:
            raise SystemExit(f"{node_name}: must stay in the post-skill inside state")

    expected_post_skill_finalizers = {
        "NormalHoldPostSkillContinueChallengeClick3Finalize": {
            "restore_delay_ms": 100,
            "progress_event": "continue_challenge",
        },
        "NormalHoldPostSkillConfirmChoiceClick3Finalize": {
            "restore_delay_ms": 100,
        },
    }
    for node_name, expected_params in expected_post_skill_finalizers.items():
        action = pipeline_nodes[node_name].get("action", {})
        params = action.get("param", {})
        if action.get("type") != "Custom":
            raise SystemExit(f"{node_name}: post-skill finalizer must restore focus")
        if params.get("custom_action") != "focus_guard_finalize":
            raise SystemExit(f"{node_name}: must use focus_guard_finalize")
        if params.get("custom_action_param") != expected_params:
            raise SystemExit(
                f"{node_name}: unexpected post-skill click parameters"
            )

    expected_continue_transitions = {
        "NormalContinueTransition": [
            "NormalEndlessConfirmChoice",
            "NormalEndlessIdle",
        ],
        "NormalHoldPostSkillContinueTransition": [
            "NormalHoldPostSkillConfirmChoice",
            "NormalHoldPostSkillIdle",
        ],
    }
    for node_name, targets in expected_continue_transitions.items():
        node = pipeline_nodes.get(node_name, {})
        if node.get("recognition", {}).get("type") != "DirectHit":
            raise SystemExit(f"{node_name}: continue transition must use DirectHit")
        if node.get("action", {}).get("type") != "DoNothing":
            raise SystemExit(f"{node_name}: continue transition must not send input")
        if int(node.get("post_delay", 0)) != 0:
            raise SystemExit(f"{node_name}: continue transition must not block the next page")
        if node.get("next") != targets:
            raise SystemExit(f"{node_name}: invalid continue transition order")

    hold_skills = all_options.get("NormalHoldEnableSkills", {})
    hold_skills_yes = option_case(hold_skills, "Yes")
    for hud_node in ("NormalOutsideCombatHudReady", "NormalRestartCombatHudReady"):
        require_override(
            "NormalHoldEnableSkills",
            hold_skills_yes,
            hud_node,
            {"next": ["LiseCombatLoadDelay"]},
        )
    for node_name in (
        "NormalEndlessConfirmChoiceClick3Finalize",
        "NormalEndlessIdle",
    ):
        require_override(
            "NormalHoldEnableSkills",
            hold_skills_yes,
            node_name,
            {"next": ["NormalEndlessCombatEntry"]},
        )
    require_override(
        "NormalHoldEnableSkills",
        hold_skills_yes,
        "NormalContinueTransition",
        {"next": ["NormalEndlessConfirmChoice", "NormalEndlessCombatEntry"]},
    )

    expel_skills = all_options.get("NormalExpelEnableSkills", {})
    expel_skills_yes = option_case(expel_skills, "Yes")
    for hud_node in ("NormalOutsideCombatHudReady", "NormalRestartCombatHudReady"):
        require_override(
            "NormalExpelEnableSkills",
            expel_skills_yes,
            hud_node,
            {"next": ["LiseCombatLoadDelay"]},
        )
    require_override(
        "NormalExpelEnableSkills",
        expel_skills_yes,
        "NormalExpelCombatEntry",
        {
            "next": [
                "LiseSkillOrderEntry",
                "LiseSkillCastEnd",
            ]
        },
    )
    expel_skills_no = option_case(expel_skills, "No")
    if expel_skills_no.get("pipeline_override"):
        raise SystemExit("NormalExpelEnableSkills/No must not add skill or button candidates")

    cipher_skills = all_options.get("CipherEnableSkills", {})
    cipher_skills_yes = option_case(cipher_skills, "Yes")
    require_override(
        "CipherEnableSkills",
        cipher_skills_yes,
        "RewardConfirmFirstPageClick3Finalize",
        {"next": ["CipherPostSkillOutsideMonitor"]},
    )
    require_override(
        "CipherEnableSkills",
        cipher_skills_yes,
        "CipherExpelAgainClick3Finalize",
        {"next": ["CipherExpelRestartMonitor"]},
    )
    cipher_skills_no = option_case(cipher_skills, "No")
    require_override(
        "CipherEnableSkills",
        cipher_skills_no,
        "CipherExpelMonitor",
        {
            "next": [
                "RewardConfirmByClick",
                "CipherExpelInsideGate",
                "CipherExpelAgainDetected",
                "RewardConfirmThirdPageByClick",
                "CipherExpelInsideIdle",
            ]
        },
    )

    forbidden_inside_targets = {
        "NormalEndlessAgainDetected",
        "NormalEndlessStartChallengeByClick",
        "CipherExpelAgainByClick",
        "CipherExpelAgainDetected",
        "RewardConfirmThirdPageByClick",
    }
    for node_name in (
        "NormalEndlessMonitor",
        "NormalEndlessCombatEntry",
        "NormalHoldPostSkillMonitor",
        "NormalExpelCombatEntry",
    ):
        leaked = forbidden_inside_targets & set(pipeline_nodes[node_name].get("next", []))
        if leaked:
            raise SystemExit(f"{node_name}: inside state leaks outside candidates {sorted(leaked)}")

    expected_boundary_waits = {
        "NormalEndlessIdle": [
            "NormalHoldInsideGate",
            "NormalEndlessContinueChallenge",
            "NormalEndlessConfirmChoice",
            "NormalEndlessAgainDetected",
            "NormalEndlessStartChallengeByClick",
            "NormalEndlessIdle",
        ],
        "NormalExpelInsideIdle": [
            "NormalExpelInsideGate",
            "NormalEndlessAgainDetected",
            "NormalEndlessStartChallengeByClick",
            "NormalExpelInsideIdle",
        ],
        "NormalHoldPostSkillIdle": [
            "NormalHoldPostSkillInsideGate",
            "NormalHoldPostSkillContinueChallenge",
            "NormalHoldPostSkillConfirmChoice",
            "NormalEndlessAgainDetected",
            "NormalEndlessStartChallengeByClick",
            "NormalHoldPostSkillIdle",
        ],
        "NormalExpelPostSkillInsideIdle": [
            "NormalExpelPostSkillInsideGate",
            "NormalPostSkillOutsideMonitor",
        ],
        "CipherPostSkillInsideIdle": [
            "CipherPostSkillInsideGate",
            "CipherPostSkillOutsideMonitor",
        ],
    }
    for node_name, expected_next in expected_boundary_waits.items():
        if pipeline_nodes.get(node_name, {}).get("next") != expected_next:
            raise SystemExit(
                f"{node_name}: boundary wait must preserve the expected "
                "health-bar, mode-local button, outside-evidence, and idle order"
            )

    hold_only_targets = {
        "NormalEndlessContinueChallenge",
        "NormalEndlessConfirmChoice",
        "NormalHoldPostSkillContinueChallenge",
        "NormalHoldPostSkillConfirmChoice",
    }
    for node_name in (
        "NormalExpelInsideIdle",
        "NormalExpelPostSkillInsideIdle",
        "NormalPostSkillOutsideMonitor",
    ):
        leaked = hold_only_targets & set(pipeline_nodes[node_name].get("next", []))
        if leaked:
            raise SystemExit(
                f"{node_name}: expel boundary must not use Hold-only buttons {sorted(leaked)}"
            )

    forbidden_outside_targets = {
        "NormalEndlessContinueChallenge",
        "NormalEndlessConfirmChoice",
        "RewardConfirmByClick",
        "LiseSkillOrderEntry",
        "LiseCombatHudReadyFrame1",
    }
    for node_name in expected_outside_monitors:
        leaked = forbidden_outside_targets & set(pipeline_nodes[node_name].get("next", []))
        if leaked:
            raise SystemExit(f"{node_name}: outside state leaks inside candidates {sorted(leaked)}")

    for interval_option_name in ("LiseEInterval", "NormalHoldEInterval"):
        interval = all_options.get(interval_option_name, {})
        override = interval.get("pipeline_override", {})
        e_override = override.get("LisePressE", {})
        e_after_q_override = override.get("LisePressEAfterQ", {})
        expected_placeholder = "{interval_ms}"
        if (
            e_override.get("repeat_delay") != expected_placeholder
            or e_override.get("post_delay") != expected_placeholder
            or e_after_q_override.get("repeat_delay") != expected_placeholder
        ):
            raise SystemExit(
                f"{interval_option_name}: both E repeat delays and E post delay "
                "must use {interval_ms}"
            )
        if "LiseQBeforeEIntervalDelay" in override:
            raise SystemExit(
                f"{interval_option_name}: Q-after delay must use its dedicated option"
            )

    e_count_override = all_options.get("LiseECount", {}).get("pipeline_override", {})
    for node_name in ("LisePressE", "LisePressEAfterQ"):
        node_override = e_count_override.get(node_name, {})
        if node_override.get("repeat") != "{count}":
            raise SystemExit(f"LiseECount: {node_name}.repeat must use {{count}}")
        params = (
            node_override.get("action", {})
            .get("param", {})
            .get("custom_action_param", {})
        )
        expected_e_params = {
            "kind": "key",
            "key": 69,
            "repeat": 1,
            "sequence_total": "{count}",
        }
        if params != expected_e_params:
            raise SystemExit(
                f"LiseECount: {node_name} must pass the configured total to E logging"
            )

    graph = {
        name: collect_pipeline_edges(node) for name, node in pipeline_nodes.items()
    }
    for relative, override in pipeline_overrides:
        unknown_override_nodes = set(override) - set(pipeline_nodes)
        if unknown_override_nodes:
            raise SystemExit(
                f"{relative}: pipeline_override targets unknown nodes: "
                f"{sorted(unknown_override_nodes)}"
            )
        for name, node_override in override.items():
            graph[name].update(collect_pipeline_edges(node_override))

    missing_edge_targets = {
        f"{source} -> {target}"
        for source, targets in graph.items()
        for target in targets - set(pipeline_nodes)
    }
    if missing_edge_targets:
        raise SystemExit(
            f"Pipeline references missing nodes: {sorted(missing_edge_targets)}"
        )

    reachable: set[str] = set()
    pending = list(task_entries | DYNAMIC_PIPELINE_TARGETS)
    while pending:
        name = pending.pop()
        if name in reachable:
            continue
        reachable.add(name)
        pending.extend(graph[name] - reachable)

    unreachable = set(pipeline_nodes) - reachable
    if unreachable:
        details = [
            f"{name} ({pipeline_owners[name]})" for name in sorted(unreachable)
        ]
        raise SystemExit(f"Unreachable pipeline nodes: {details}")

    image_dir = ASSETS / "resource" / "base" / "image"
    missing_templates = [
        template for template in sorted(template_paths) if not (image_dir / template).is_file()
    ]
    if missing_templates:
        raise SystemExit(f"Missing template images: {missing_templates}")

    print(
        f"OK: {len(controller_names)} controller(s), "
        f"{len(group_names)} group(s), {len(task_entries)} task(s), "
        f"{len(presets)} preset(s), "
        f"{len(pipeline_nodes)} reachable pipeline node(s), "
        f"{len(template_paths)} template(s)"
    )


if __name__ == "__main__":
    main()
