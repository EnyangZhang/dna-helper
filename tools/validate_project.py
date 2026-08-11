"""Offline structural checks for the MaaFramework resource project."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
TASK_GROUP_REQUIREMENTS = {
    "CipherEndlessBoost": "DailyAFK",
    "NormalEndlessBoost": "DailyAFK",
}
PIPELINE_EDGE_FIELDS = ("next", "on_error")
# Agent custom actions invoke these nodes by name through Context.run_action or
# install them as runtime next targets through Context.override_pipeline.
DYNAMIC_PIPELINE_TARGETS = {
    "RewardConfirmThirdPageClick2",
    "RewardConfirmFirstPageClick2",
    "RewardConfirmContinueChallengeClick2",
    "CipherExpelAgainClick2",
    "NormalEndlessStartChallengeClick2",
    "NormalEndlessConfirmChoiceClick2",
    "FocusGuardEKeyProxy",
    "FocusGuardQKeyProxy",
    "NormalEndlessRestartByClick",
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
    interface_path = ASSETS / "interface.json"
    interface = load_json(interface_path)

    if interface.get("interface_version") != 2:
        raise SystemExit("assets/interface.json: interface_version must be 2")

    controller_names = {item["name"] for item in interface.get("controller", [])}
    if not controller_names:
        raise SystemExit("assets/interface.json: at least one controller is required")
    group_names = {item["name"] for item in interface.get("group", [])}

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

    missing_entries = task_entries - set(pipeline_nodes)
    if missing_entries:
        raise SystemExit(f"Missing task entry pipeline nodes: {sorted(missing_entries)}")

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
        if "LiseQBeforeE" in yes_options or "NormalHoldQBeforeE" in yes_options:
            raise SystemExit(
                f"{parent_name}: Q-before-E must be nested under both E and Q switches"
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

    normal_mode = all_options.get("NormalMode", {})
    hold_mode = option_case(normal_mode, "Endless")
    require_override(
        "NormalMode",
        hold_mode,
        "NormalEndlessMonitor",
        {
            "next": [
                "NormalEndlessContinueChallenge",
                "NormalEndlessConfirmChoice",
                "NormalEndlessAgainDetected",
                "NormalEndlessIdle",
            ]
        },
    )
    require_override(
        "NormalMode",
        hold_mode,
        "LiseSkillCastEnd",
        {"next": ["NormalHoldPostSkillMonitor"]},
    )
    expel_mode = option_case(normal_mode, "Expel")
    require_override(
        "NormalMode",
        expel_mode,
        "NormalEndlessEntry",
        {"next": ["NormalExpelMonitor"]},
    )
    require_override(
        "NormalMode",
        expel_mode,
        "LiseSkillCastEnd",
        {"next": ["NormalExpelPostSkillMonitor"]},
    )

    post_skill_monitors = {
        "NormalHoldPostSkillMonitor": [
            "NormalHoldPostSkillContinueChallenge",
            "NormalHoldPostSkillConfirmChoice",
            "NormalEndlessAgainDetected",
            "NormalHoldPostSkillIdle",
        ],
        "NormalHoldPostSkillContinueChallenge": ["NormalHoldPostSkillMonitor"],
        "NormalHoldPostSkillConfirmChoice": ["NormalHoldPostSkillMonitor"],
        "NormalHoldPostSkillIdle": ["NormalHoldPostSkillMonitor"],
        "NormalExpelPostSkillMonitor": [
            "NormalEndlessAgainDetected",
            "NormalExpelPostSkillMonitor",
        ],
    }
    for node_name, expected_next in post_skill_monitors.items():
        node = pipeline_nodes.get(node_name)
        if node is None:
            raise SystemExit(f"Missing post-skill monitor node: {node_name}")
        if node.get("next") != expected_next:
            raise SystemExit(
                f"{node_name}.next must be {expected_next!r}, "
                f"got {node.get('next')!r}"
            )
        if any(next_node in COMBAT_HUD_READY_NODES for next_node in expected_next):
            raise SystemExit(f"{node_name}: post-skill path must not re-enter HUD")

    expected_post_skill_clicks = {
        "NormalHoldPostSkillContinueChallenge": {
            "kind": "click",
            "target": [900, 500],
            "repeat": 3,
            "interval_ms": 50,
            "restore_delay_ms": 100,
        },
        "NormalHoldPostSkillConfirmChoice": {
            "kind": "click",
            "target": [640, 505],
            "repeat": 3,
            "interval_ms": 50,
            "restore_delay_ms": 100,
        },
    }
    for node_name, expected_params in expected_post_skill_clicks.items():
        action = pipeline_nodes[node_name].get("action", {})
        params = action.get("param", {})
        if action.get("type") != "Custom":
            raise SystemExit(f"{node_name}: post-skill click must restore focus")
        if params.get("custom_action") != "focus_guard_action":
            raise SystemExit(f"{node_name}: must use focus_guard_action")
        if params.get("custom_action_param") != expected_params:
            raise SystemExit(
                f"{node_name}: unexpected post-skill click parameters"
            )

    hold_skills = all_options.get("NormalHoldEnableSkills", {})
    hold_skills_yes = option_case(hold_skills, "Yes")
    require_override(
        "NormalHoldEnableSkills",
        hold_skills_yes,
        "NormalEndlessEntry",
        {"next": ["NormalEndlessMonitor"]},
    )
    require_override(
        "NormalHoldEnableSkills",
        hold_skills_yes,
        "NormalEndlessStartChallengeClick3",
        {"next": ["NormalEndlessMonitor"]},
    )
    require_override(
        "NormalHoldEnableSkills",
        hold_skills_yes,
        "NormalEndlessMonitor",
        {
            "next": [
                "NormalEndlessContinueChallenge",
                "NormalEndlessConfirmChoice",
                "NormalEndlessAgainDetected",
                "LiseCombatHudReadyFrame1",
                "NormalEndlessIdle",
            ]
        },
    )
    for hud_node in ("LiseCombatHudReadyFrame1", "LiseCombatHudReadyFrame2"):
        require_override(
            "NormalHoldEnableSkills",
            hold_skills_yes,
            hud_node,
            {"on_error": ["NormalEndlessMonitor"]},
        )

    expel_skills = all_options.get("NormalExpelEnableSkills", {})
    expel_skills_yes = option_case(expel_skills, "Yes")
    for entry_node in ("NormalEndlessEntry", "NormalEndlessStartChallengeClick3"):
        require_override(
            "NormalExpelEnableSkills",
            expel_skills_yes,
            entry_node,
            {"next": ["NormalExpelMonitor"]},
        )
    require_override(
        "NormalExpelEnableSkills",
        expel_skills_yes,
        "NormalExpelMonitor",
        {
            "next": [
                "NormalEndlessAgainDetected",
                "LiseCombatHudReadyFrame1",
                "NormalExpelMonitor",
            ]
        },
    )
    for hud_node in ("LiseCombatHudReadyFrame1", "LiseCombatHudReadyFrame2"):
        require_override(
            "NormalExpelEnableSkills",
            expel_skills_yes,
            hud_node,
            {"on_error": ["NormalExpelMonitor"]},
        )
    expel_skills_no = option_case(expel_skills, "No")
    require_override(
        "NormalExpelEnableSkills",
        expel_skills_no,
        "NormalExpelMonitor",
        {"next": ["NormalEndlessAgainDetected", "NormalExpelMonitor"]},
    )

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
