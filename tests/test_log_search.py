import json

from log_search.searcher import search_case_logs


PARENT_RUN_ID = "11111111-1111-4111-8111-111111111111"
CHILD_RUN_ID = "22222222-2222-4222-8222-222222222222"


class FakeLogAPI:
    endpoint = "https://dify.example.com"

    def list_apps(self, tag_id=None):
        return [
            {"id": "app-parent", "name": "Root Workflow"},
            {"id": "app-child", "name": "Renamed Child"},
        ]

    def list_workflow_tools(self):
        return [{"id": "tool-child", "name": "Old Child Name"}]

    def get_workflow_tool(self, tool_id):
        assert tool_id == "tool-child"
        return {"workflow_app_id": "app-child"}

    def list_workflow_logs(self, app_id, keyword, *, page=1, limit=100):
        assert (app_id, keyword) == ("app-parent", "CASE-123")
        return {
            "data": [{"workflow_run": {"id": PARENT_RUN_ID}}],
            "has_more": False,
        }

    def get_workflow_run(self, app_id, run_id):
        if run_id == PARENT_RUN_ID:
            return {
                "id": run_id,
                "inputs": {"case_num": "CASE-123"},
                "graph": {
                    "nodes": [
                        {
                            "id": "node-child",
                            "data": {
                                "type": "tool",
                                "provider_type": "workflow",
                                "provider_id": "tool-child",
                                "provider_name": "Old Child Name",
                            },
                        }
                    ]
                },
            }
        assert (app_id, run_id) == ("app-child", CHILD_RUN_ID)
        return {"id": run_id, "inputs": {"case_num": "CASE-123"}, "graph": {"nodes": []}}

    def list_workflow_run_nodes(self, app_id, run_id):
        if run_id == PARENT_RUN_ID:
            return [
                {
                    "node_id": "node-child",
                    "outputs": json.dumps({"child_workflow_run_id": CHILD_RUN_ID}),
                }
            ]
        return []


def test_search_case_logs_exports_complete_child_run_tree(tmp_path) -> None:
    manifest = search_case_logs(
        FakeLogAPI(), "Root Workflow", "CASE-123", tmp_path
    )

    destination = tmp_path / "CASE-123"
    assert manifest["root_run_ids"] == [PARENT_RUN_ID]
    assert manifest["run_count"] == 2
    assert manifest["unresolved_nodes"] == []
    assert manifest["runs"][0]["children"] == [f"app-child:{CHILD_RUN_ID}"]
    assert manifest["runs"][1]["parent_run_id"] == PARENT_RUN_ID
    assert len(list(destination.glob("*.json"))) == 3
    assert json.loads((destination / "manifest.json").read_text(encoding="utf-8")) == manifest