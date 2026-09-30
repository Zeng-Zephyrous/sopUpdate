from __future__ import annotations

import json
import re
from collections import deque
from pathlib import Path
from typing import Any, Callable, Protocol

import yaml


class ExportError(RuntimeError):
    pass


class ExportAPI(Protocol):
    endpoint: str

    def list_tags(self) -> list[dict[str, Any]]: ...

    def list_apps(self, tag_id: str | None = None) -> list[dict[str, Any]]: ...

    def list_workflow_tools(self) -> list[dict[str, Any]]: ...

    def export_dsl(self, app_id: str) -> str: ...


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return cleaned or "unnamed"


def _dependency_refs(dsl_text: str) -> set[tuple[str | None, str | None]]:
    document = yaml.safe_load(dsl_text) or {}
    nodes = ((document.get("workflow") or {}).get("graph") or {}).get("nodes") or []
    references: set[tuple[str | None, str | None]] = set()
    for node in nodes:
        data = node.get("data") or {}
        if data.get("provider_type") == "workflow":
            name = data.get("provider_name")
            provider_id = data.get("provider_id")
            if name or provider_id:
                references.add((name, provider_id))
        elif data.get("type") == "agent":
            tools = ((data.get("agent_parameters") or {}).get("tools") or {}).get("value") or []
            for tool in tools:
                if tool.get("type") == "workflow" and tool.get("provider_name"):
                    references.add((tool["provider_name"], None))
    return references


def _label(entry: dict[str, Any]) -> str | None:
    value = entry.get("label")
    if isinstance(value, dict):
        value = value.get("en_US") or next(
            (item for item in value.values() if isinstance(item, str)), None
        )
    return value if isinstance(value, str) and value else None


def _resolve_dependency(
    apps: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    name: str | None,
    provider_id: str | None,
) -> dict[str, Any] | None:
    if name:
        matches = [app for app in apps if app.get("name") == name]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ExportError(f"Multiple apps are named {name!r}")

    tool = next(
        (
            entry
            for entry in tools
            if (name and entry.get("name") == name)
            or (
                provider_id
                and provider_id
                in {
                    entry.get("id"),
                    entry.get("workflow_tool_id"),
                    entry.get("provider_id"),
                }
            )
        ),
        None,
    )
    if tool is None:
        return None

    app_id = tool.get("workflow_app_id") or tool.get("app_id")
    if app_id:
        app = next((candidate for candidate in apps if candidate.get("id") == app_id), None)
        if app:
            return app

    label = _label(tool)
    if label:
        matches = [app for app in apps if app.get("name") == label]
        if len(matches) == 1:
            return matches[0]
    return None


def _select_root(
    api: ExportAPI,
    app_name: str,
    tag_name: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tags = [tag for tag in api.list_tags() if tag.get("name") == tag_name]
    if len(tags) != 1:
        available = ", ".join(sorted(tag.get("name", "") for tag in api.list_tags()))
        raise ExportError(
            f"Expected one tag named {tag_name!r}, found {len(tags)}. "
            f"Available: {available or '(none)'}"
        )

    tagged_apps = api.list_apps(tags[0]["id"])
    matches = [app for app in tagged_apps if app.get("name") == app_name]
    if len(matches) != 1:
        tagged_names = ", ".join(sorted(app.get("name", "") for app in tagged_apps))
        raise ExportError(
            f"Expected one app named {app_name!r} with tag {tag_name!r}, "
            f"found {len(matches)}. Tagged apps: {tagged_names or '(none)'}"
        )
    return matches[0], tagged_apps


def export_complete_dsl(
    api: ExportAPI,
    app_name: str,
    tag_name: str,
    output_dir: str | Path,
    *,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    log(f"Finding app {app_name!r} with tag {tag_name!r}...")
    root, _ = _select_root(api, app_name, tag_name)
    log("Loading workspace apps and workflow-tool registry...")
    all_apps = api.list_apps()
    tools = api.list_workflow_tools()
    apps_by_id = {app["id"]: app for app in all_apps}
    apps_by_id.setdefault(root["id"], root)

    queue = deque([(root, True)])
    seen: set[str] = set()
    unresolved: set[str] = set()
    entries: list[dict[str, Any]] = []
    exported_names: set[str] = set()
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    while queue:
        app, is_root = queue.popleft()
        app_id = app["id"]
        if app_id in seen:
            continue
        seen.add(app_id)

        app_display_name = app.get("name", app_id)
        progress_number = len(entries) + 1
        log(f"[{progress_number}] Pulling DSL: {app_display_name}")
        dsl_text = api.export_dsl(app_id)
        dependencies: list[str] = []
        queued_dependencies = 0
        for provider_name, provider_id in sorted(
            _dependency_refs(dsl_text), key=lambda item: (item[0] or "", item[1] or "")
        ):
            dependency = _resolve_dependency(
                list(apps_by_id.values()), tools, provider_name, provider_id
            )
            if dependency is None:
                unresolved.add(provider_name or provider_id or "unknown")
                continue
            dependencies.append(dependency.get("name", dependency["id"]))
            if dependency["id"] not in seen:
                queue.append((dependency, False))
                queued_dependencies += 1

        base_name = _safe_filename(app.get("name", app_id))
        filename = f"{base_name}.yml"
        if filename.lower() in exported_names:
            filename = f"{base_name}-{app_id}.yml"
        exported_names.add(filename.lower())
        output_path = destination / filename
        output_path.write_text(dsl_text, encoding="utf-8")
        log(
            f"[{progress_number}] Saved: {output_path} "
            f"({queued_dependencies} new dependencies queued)"
        )
        entries.append(
            {
                "id": app_id,
                "name": app.get("name", app_id),
                "mode": app.get("mode", ""),
                "file": filename,
                "is_root": is_root,
                "dependencies": dependencies,
            }
        )

    manifest = {
        "endpoint": api.endpoint,
        "app_name": app_name,
        "tag": tag_name,
        "workflow_count": len(entries),
        "dependency_count": sum(not entry["is_root"] for entry in entries),
        "unresolved_workflow_references": sorted(unresolved),
        "workflows": entries,
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log(f"Completed: {len(entries)} DSL file(s); manifest: {manifest_path}")
    return manifest
