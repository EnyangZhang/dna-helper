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
