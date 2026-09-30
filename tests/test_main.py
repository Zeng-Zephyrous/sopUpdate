import importlib
import json

import pytest

from dsl_export.console_client import ConsoleSession, PERSISTED_LOGIN_SECONDS
from dsl_export.exporter import ExportError, export_complete_dsl


class FakeAPI:
    endpoint = "https://dify.example.com"

    def __init__(self):
        self.tool_detail_requests = []
        self.tool_index_requests = 0

    def list_tags(self):
        return [{"id": "tag-1", "name": "release-1"}]

    def list_apps(self, tag_id=None):
        apps = [
            {"id": "app-parent", "name": "Parent", "mode": "workflow"},
            {"id": "app-child", "name": "Renamed Child", "mode": "workflow"},
            {"id": "app-grandchild", "name": "Grandchild", "mode": "workflow"},
        ]
        return apps[:1] if tag_id else apps

    def list_workflow_tools(self):
        self.tool_index_requests += 1
        return [
            {
                "id": "tool-child",
                "name": "old-child-name",
            },
            {
                "id": "tool-grandchild",
                "name": "Grandchild",
                "workflow_app_id": "app-grandchild",
            },
        ]

    def get_workflow_tool(self, tool_id):
        self.tool_detail_requests.append(tool_id)
        return {"workflow_app_id": "app-child"}

    def export_dsl(self, app_id):
        if app_id == "app-parent":
            return """app:
  name: Parent
workflow:
  graph:
    nodes:
      - data:
          type: tool
          provider_type: workflow
          provider_id: tool-child
          provider_name: old-child-name
"""
        if app_id == "app-child":
            return """app:
  name: Renamed Child
workflow:
  graph:
    nodes:
      - data:
          type: tool
          provider_type: workflow
          provider_id: tool-grandchild
          provider_name: Grandchild
"""
        return "app:\n  name: Grandchild\nworkflow:\n  graph:\n    nodes: []\n"


def test_persisted_login_expires_after_30_minutes(monkeypatch, tmp_path) -> None:
    session = ConsoleSession("https://dify.example.com", tmp_path)
    monkeypatch.setattr("dsl_export.console_client.time.time", lambda: 10_000.0)

    session._mark_login_persisted()
    assert session._persisted_login_is_fresh()

    monkeypatch.setattr(
        "dsl_export.console_client.time.time",
        lambda: 10_000.0 + PERSISTED_LOGIN_SECONDS,
    )
    assert not session._persisted_login_is_fresh()

    stale_file = tmp_path / "stale-cookie-data"
    stale_file.write_text("expired", encoding="utf-8")
    session._prepare_profile()

    assert tmp_path.exists()
    assert not stale_file.exists()


def test_visible_browser_closes_and_export_continues_headless(
    monkeypatch, tmp_path
) -> None:
    session = ConsoleSession("https://dify.example.com", tmp_path)
    launches = []

    class VisibleContext:
        closed = False

        def close(self):
            self.closed = True

    visible_context = VisibleContext()
    headless_context = object()
    page = object()
    session.context = visible_context

    monkeypatch.setattr(
        session,
        "_launch_context",
        lambda *, headless: launches.append(headless) or headless_context,
    )
    monkeypatch.setattr(session, "_live_page", lambda: page)
    monkeypatch.setattr(session, "_open_console", lambda: None)
    monkeypatch.setattr(session, "_probe_logged_in", lambda: (True, ""))

    session._continue_headless_after_login()

    assert visible_context.closed
    assert launches == [True]
    assert session.context is headless_context
    assert session.page is page


def test_successful_context_request_skips_page_fallback(monkeypatch, tmp_path) -> None:
    session = ConsoleSession("https://dify.example.com", tmp_path)
    page_requests = []
    monkeypatch.setattr(session, "_csrf_headers", lambda: {})
    monkeypatch.setattr(
        session,
        "_via_context",
        lambda *args: {
            "ok": True,
            "status": 200,
            "text": "{}",
            "json": {"data": []},
            "strategy": "context.request",
        },
    )
    monkeypatch.setattr(
        session,
        "_via_page",
        lambda *args: page_requests.append(args),
    )

    assert session._request_json("/apps") == {"data": []}
    assert page_requests == []


def test_exports_named_tagged_app_and_recursive_dependency(tmp_path) -> None:
    progress = []
    api = FakeAPI()
    manifest = export_complete_dsl(
        api, "Parent", "release-1", tmp_path, log=progress.append
    )

    assert manifest["workflow_count"] == 3
    assert manifest["dependency_count"] == 2
    assert manifest["unresolved_workflow_references"] == []
    assert (tmp_path / "Parent.yml").exists()
    assert (tmp_path / "Renamed Child.yml").exists()
    assert (tmp_path / "Grandchild.yml").exists()
    assert json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8")) == manifest
    assert any("[1] Pulling DSL: Parent" in line for line in progress)
    assert any("Renamed Child.yml" in line for line in progress)
    assert any("manifest.json" in line for line in progress)
    assert api.tool_index_requests == 1
    assert api.tool_detail_requests == ["tool-child"]


def test_skips_tool_registry_when_app_names_resolve_dependencies(tmp_path) -> None:
    api = FakeAPI()
    api.export_dsl = lambda app_id: (
        "app:\n  name: Parent\nworkflow:\n  graph:\n    nodes:\n"
        "      - data:\n          type: tool\n          provider_type: workflow\n"
        "          provider_name: Grandchild\n"
        if app_id == "app-parent"
        else "app:\n  name: Grandchild\nworkflow:\n  graph:\n    nodes: []\n"
    )

    manifest = export_complete_dsl(api, "Parent", "release-1", tmp_path)

    assert manifest["workflow_count"] == 2
    assert api.tool_index_requests == 0


def test_requires_name_to_match_within_tag(tmp_path) -> None:
    with pytest.raises(ExportError, match="Missing"):
        export_complete_dsl(FakeAPI(), "Missing", "release-1", tmp_path)


def test_main_switches_workspace_and_exports(monkeypatch, tmp_path) -> None:
    main_module = importlib.import_module("dsl_export.main")
    events = []

    class FakeSession:
        endpoint = "https://dify.example.com"

        def __init__(self, endpoint, profile_dir, **kwargs):
            events.append(("profile", endpoint, profile_dir))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def switch_workspace(self, name):
            events.append(("workspace", name))

    monkeypatch.setattr(main_module, "ConsoleSession", FakeSession)
    monkeypatch.setattr(
        main_module,
        "export_complete_dsl",
        lambda api, name, tag, output: {
            "workflow_count": 1,
            "dependency_count": 0,
            "unresolved_workflow_references": [],
        },
    )

    exit_code = main_module.main(
        [
            "--endpoint",
            "https://dify.example.com",
            "--name",
            "Parent",
            "--tag",
            "release-1",
            "--workspace",
            "China",
            "--output",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert ("workspace", "China") in events
