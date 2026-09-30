from __future__ import annotations

import json
import re
from collections import deque
from pathlib import Path
from typing import Any, Callable, Protocol


RUN_ID_KEYS = {
    "child_workflow_run_id",
    "sub_workflow_run_id",
    "workflow_run_id",
    "run_id",
}


class LogSearchError(RuntimeError):
    pass


class LogSearchAPI(Protocol):
    endpoint: str

    def list_apps(self, tag_id: str | None = None) -> list[dict[str, Any]]: ...

    def list_workflow_tools(self) -> list[dict[str, Any]]: ...

    def get_workflow_tool(self, tool_id: str) -> dict[str, Any]: ...

    def list_workflow_logs(
        self, app_id: str, keyword: str, *, page: int = 1, limit: int = 100
    ) -> dict[str, Any]: ...

    def get_workflow_run(self, app_id: str, run_id: str) -> dict[str, Any]: ...

    def list_workflow_run_nodes(
        self, app_id: str, run_id: str
    ) -> list[dict[str, Any]]: ...


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r'[^0-9A-Za-z._-]+', "_", value).strip("._")
    return cleaned or "case"


def _as_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "items"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


def _find_child_run_id(
    value: Any,
    parent_run_id: str,
    *,
    depth: int = 0,
    seen: set[int] | None = None,
) -> str | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return None
    if not isinstance(value, (dict, list)) or depth > 8:
        return None
    if seen is None:
        seen = set()
    identity = id(value)
    if identity in seen:
        return None
    seen.add(identity)
    if isinstance(value, dict):
        for key, item in value.items():
            if (
                key.lower() in RUN_ID_KEYS
                and isinstance(item, str)
                and item != parent_run_id
            ):
                return item
        children = value.values()
    else:
        children = value
    for item in children:
        found = _find_child_run_id(
            item, parent_run_id, depth=depth + 1, seen=seen
        )
        if found:
            return found
    return None


def _workflow_nodes(run: dict[str, Any]) -> dict[str, dict[str, Any]]:
    nodes = ((run.get("graph") or {}).get("nodes") or [])
    return {
        str(node.get("id")): node
        for node in nodes
        if isinstance(node, dict) and node.get("id")
    }


def _is_workflow_tool(node: dict[str, Any]) -> bool:
    data = node.get("data") or {}
    return (
        str(data.get("type", "")).lower() == "tool"
        and str(data.get("provider_type", data.get("providerType", ""))).lower()
        == "workflow"
    )


class _AppResolver:
    def __init__(self, api: LogSearchAPI, apps: list[dict[str, Any]]) -> None:
        self.api = api
        self.apps = apps
        self.apps_by_id = {str(app.get("id")): app for app in apps}
        self.tools: list[dict[str, Any]] | None = None
        self.details: dict[str, dict[str, Any]] = {}

    def resolve(self, graph_node: dict[str, Any]) -> dict[str, Any] | None:
        data = graph_node.get("data") or {}
        provider_name = data.get("provider_name") or data.get("providerName")
        if provider_name:
            matches = [app for app in self.apps if app.get("name") == provider_name]
            if len(matches) == 1:
                return matches[0]

        provider_id = str(data.get("provider_id") or data.get("providerId") or "")
        if self.tools is None:
            self.tools = self.api.list_workflow_tools()
        tool = next(
            (
                item
                for item in self.tools
                if provider_id
                in {
                    str(item.get("id") or ""),
                    str(item.get("workflow_tool_id") or ""),
                    str(item.get("provider_id") or ""),
                }
                or (provider_name and item.get("name") == provider_name)
            ),
            None,
        )
        if tool is None:
            return None
        tool_id = str(tool.get("id") or tool.get("workflow_tool_id") or "")
        if tool_id and not (tool.get("workflow_app_id") or tool.get("app_id")):
            if tool_id not in self.details:
                self.details[tool_id] = self.api.get_workflow_tool(tool_id)
            tool = {**tool, **self.details[tool_id]}
        app_id = str(tool.get("workflow_app_id") or tool.get("app_id") or "")
        return self.apps_by_id.get(app_id)


def _root_run_ids(
    api: LogSearchAPI,
    app_id: str,
    case_number: str,
    max_results: int,
) -> list[str]:
    run_ids: list[str] = []
    page = 1
    while len(run_ids) < max_results:
        payload = api.list_workflow_logs(
            app_id, case_number, page=page, limit=min(100, max_results)
        )
        for item in _as_list(payload):
            run = item.get("workflow_run") if isinstance(item, dict) else None
            run_id = (run or item).get("id") if isinstance(run or item, dict) else None
            if run_id and run_id not in run_ids:
                run_ids.append(str(run_id))
                if len(run_ids) >= max_results:
                    break
        if not payload.get("has_more"):
            break
        page += 1
    return run_ids


def search_case_logs(
    api: LogSearchAPI,
    app_name: str,
    case_number: str,
    output_dir: str | Path,
    *,
    max_results: int = 20,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    apps = api.list_apps()
    roots = [app for app in apps if app.get("name") == app_name]
    if len(roots) != 1:
        raise LogSearchError(
            f"Expected one app named {app_name!r}, found {len(roots)}"
        )
    root_app = roots[0]
    root_ids = _root_run_ids(api, str(root_app["id"]), case_number, max_results)
    if not root_ids:
        raise LogSearchError(f"No logs found for case number {case_number!r}")

    destination = Path(output_dir) / _safe_filename(case_number)
    destination.mkdir(parents=True, exist_ok=True)
    resolver = _AppResolver(api, apps)
    queue = deque((root_app, run_id, None, None) for run_id in root_ids)
    seen: set[tuple[str, str]] = set()
    entries: list[dict[str, Any]] = []
    unresolved: list[dict[str, str]] = []

    while queue:
        app, run_id, parent_run_id, parent_node_id = queue.popleft()
        app_id = str(app["id"])
        key = (app_id, run_id)
        if key in seen:
            continue
        seen.add(key)
        log(f"[{len(entries) + 1}] Loading {app.get('name', app_id)} run {run_id}...")
        run = api.get_workflow_run(app_id, run_id)
        executions = api.list_workflow_run_nodes(app_id, run_id)
        graph_nodes = _workflow_nodes(run)
        child_keys: list[str] = []

        for execution in executions:
            node_id = str(execution.get("node_id") or "")
            graph_node = graph_nodes.get(node_id)
            if not graph_node or not _is_workflow_tool(graph_node):
                continue
            child_run_id = _find_child_run_id(
                {
                    "process_data": execution.get("process_data"),
                    "outputs": execution.get("outputs"),
                    "execution_metadata": execution.get("execution_metadata"),
                    "extras": execution.get("extras"),
                },
                run_id,
            )
            child_app = resolver.resolve(graph_node)
            if not child_run_id or child_app is None:
                unresolved.append(
                    {
                        "app_id": app_id,
                        "run_id": run_id,
                        "node_id": node_id,
                        "reason": "child run ID missing"
                        if not child_run_id
                        else "child app ID unresolved",
                    }
                )
                continue
            child_key = f"{child_app['id']}:{child_run_id}"
            child_keys.append(child_key)
            queue.append((child_app, child_run_id, run_id, node_id))

        filename = f"{len(entries) + 1:03d}-{_safe_filename(str(app.get('name', app_id)))}-{run_id}.json"
        (destination / filename).write_text(
            json.dumps(
                {"workflow_run": run, "node_executions": executions},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        entries.append(
            {
                "key": f"{app_id}:{run_id}",
                "app_id": app_id,
                "app_name": app.get("name", app_id),
                "run_id": run_id,
                "parent_run_id": parent_run_id,
                "parent_node_id": parent_node_id,
                "children": child_keys,
                "file": filename,
            }
        )

    manifest = {
        "endpoint": api.endpoint,
        "case_number": case_number,
        "root_app": {"id": root_app["id"], "name": root_app.get("name")},
        "root_run_ids": root_ids,
        "run_count": len(entries),
        "unresolved_nodes": unresolved,
        "runs": entries,
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log(f"Saved {len(entries)} complete run log(s) to {destination}")
    return manifest