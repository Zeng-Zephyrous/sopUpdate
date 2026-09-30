from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, sync_playwright

CONSOLE_API_PREFIX = "/console/api"
PAGE_SIZE = 100
LOGIN_POLL_SECONDS = 2
LOGIN_TIMEOUT_SECONDS = 600
SESSION_RENEWAL_SECONDS = 25
API_RETRY_DELAYS = (0.5, 1.0, 2.0)
RETRYABLE_STATUS_CODES = {429, 502, 503, 504}
PERSISTED_LOGIN_SECONDS = 30 * 60
SESSION_METADATA_FILE = ".dsl-export-session.json"
RENEWABLE_COOKIES = {"__Host-refresh_token", "ESTSAUTHPERSISTENT"}
CSRF_NAMES = {"csrf_token", "csrftoken", "x-csrf-token", "xsrf-token", "_csrf", "csrf"}


class ConsoleApiError(RuntimeError):
    pass


def _find_csrf_token(values: dict[str, str | None]) -> str | None:
    for key, value in values.items():
        aliases = {key.lower()}
        for prefix in ("__host-", "__secure-"):
            if key.lower().startswith(prefix):
                aliases.add(key.lower()[len(prefix) :])
        if value and aliases & CSRF_NAMES:
            return value
    return None


class ConsoleSession:
    def __init__(
        self,
        endpoint: str,
        profile_dir: Path,
        *,
        login_timeout: int = LOGIN_TIMEOUT_SECONDS,
        log: Callable[[str], None] = print,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.profile_dir = profile_dir
        self.login_timeout = login_timeout
        self.log = log
        self._playwright = None
        self.context = None
        self.page: Page | None = None

    def __enter__(self) -> ConsoleSession:
        self._prepare_profile()
        self._playwright = sync_playwright().start()
        self.context = self._launch_context(headless=True)
        self.page = self._live_page()
        self._ensure_logged_in()
        return self

    def _prepare_profile(self) -> None:
        if not self._persisted_login_is_fresh():
            if self.profile_dir.exists():
                self.log("Saved login is older than 30 minutes; clearing browser profile.")
                shutil.rmtree(self.profile_dir)
        self.profile_dir.mkdir(parents=True, exist_ok=True)

    def __exit__(self, *exc_info: object) -> None:
        if self.context is not None:
            try:
                self.context.close()
            except PlaywrightError:
                pass
        if self._playwright is not None:
            self._playwright.stop()

    @property
    def _session_metadata_path(self) -> Path:
        return self.profile_dir / SESSION_METADATA_FILE

    def _persisted_login_is_fresh(self) -> bool:
        try:
            metadata = json.loads(
                self._session_metadata_path.read_text(encoding="utf-8")
            )
            logged_in_at = float(metadata["logged_in_at"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return False
        age = time.time() - logged_in_at
        return 0 <= age < PERSISTED_LOGIN_SECONDS

    def _mark_login_persisted(self) -> None:
        self._session_metadata_path.write_text(
            json.dumps({"logged_in_at": time.time()}),
            encoding="utf-8",
        )

    def _launch_context(self, *, headless: bool):
        options = {
            "user_data_dir": str(self.profile_dir),
            "headless": headless,
            "viewport": {"width": 1600, "height": 900},
        }
        try:
            return self._playwright.chromium.launch_persistent_context(
                channel="msedge", **options
            )
        except PlaywrightError:
            return self._playwright.chromium.launch_persistent_context(**options)

    def _live_page(self) -> Page:
        pages = [page for page in self.context.pages if not page.is_closed()]
        for page in reversed(pages):
            if (page.url or "").startswith(self.endpoint):
                return page
        return pages[-1] if pages else self.context.new_page()

    def _open_console(self) -> None:
        self.page = self._live_page()
        try:
            self.page.goto(
                f"{self.endpoint}/apps?category=all",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
        except PlaywrightError:
            self.page = self._live_page()

    def _continue_headless_after_login(self) -> None:
        self.context.close()
        self.context = self._launch_context(headless=True)
        self.page = self._live_page()
        self._open_console()
        ok, detail = self._probe_logged_in()
        if not ok:
            raise ConsoleApiError(
                f"Login was lost while closing the visible browser: {detail}"
            )
        self.log("Login confirmed; closed the visible Edge window.")

    def _probe_logged_in(self) -> tuple[bool, str]:
        try:
            query = urlencode({"page": 1, "limit": 1, "name": ""})
            payload = self._request_json(f"/apps?{query}")
            if isinstance(payload, dict) and isinstance(payload.get("data"), list):
                return True, ""
            return False, f"unexpected response: {payload!r}"
        except Exception as exc:
            return False, str(exc)

    def _ensure_logged_in(self) -> None:
        self._open_console()
        ok, detail = self._probe_logged_in()
        if ok:
            self.log("Reused saved browser login.")
            return

        cached = {
            cookie.get("name")
            for cookie in self.context.cookies()
            if cookie.get("name") in RENEWABLE_COOKIES
        }
        if cached:
            self.log("Waiting for the saved browser session to renew...")
            deadline = time.monotonic() + SESSION_RENEWAL_SECONDS
            while time.monotonic() < deadline:
                time.sleep(1.5)
                ok, detail = self._probe_logged_in()
                if ok:
                    self.log("Reused renewed browser login.")
                    return

        self.log(f"Saved login unavailable ({detail}). Opening Edge for SSO/MFA...")
        self.context.close()
        self.context = self._launch_context(headless=False)
        self._open_console()
        self.log("Complete login in the browser; the program will continue automatically.")

        deadline = time.monotonic() + self.login_timeout
        while time.monotonic() < deadline:
            time.sleep(LOGIN_POLL_SECONDS)
            self.page = self._live_page()
            ok, _ = self._probe_logged_in()
            if ok:
                self._mark_login_persisted()
                self._continue_headless_after_login()
                return
        raise ConsoleApiError(
            f"Login was not detected within {self.login_timeout} seconds"
        )

    def _csrf_headers(self) -> dict[str, str]:
        cookies = {
            cookie["name"]: cookie.get("value")
            for cookie in self.context.cookies([self.endpoint])
        }
        token = _find_csrf_token(cookies)
        if token is None:
            storage = self.page.evaluate(
                """
                () => {
                    const values = {};
                    for (const store of [localStorage, sessionStorage]) {
                        for (let i = 0; i < store.length; i++) {
                            const key = store.key(i);
                            values[key] = store.getItem(key);
                        }
                    }
                    return values;
                }
                """
            )
            token = _find_csrf_token(storage)
        return {"X-CSRF-Token": token, "X-XSRF-TOKEN": token} if token else {}

    def _request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        allow_list: bool = False,
    ) -> Any:
        url = f"{self.endpoint}{CONSOLE_API_PREFIX}{path}"
        csrf_headers = self._csrf_headers()
        errors: list[str] = []
        for retry_number in range(len(API_RETRY_DELAYS) + 1):
            responses: list[dict[str, Any]] = []
            attempts = (
                lambda: self._via_context(url, method, body, csrf_headers),
                lambda: self._via_page(url, method, body, csrf_headers),
            )
            for attempt in attempts:
                response = attempt()
                responses.append(response)
                payload = response["json"]
                valid = isinstance(payload, dict) or (
                    allow_list and isinstance(payload, list)
                )
                if response["ok"] and valid:
                    return payload
                errors.append(
                    f"{response['strategy']}: HTTP {response['status']} "
                    f"{response['text'][:200]!r}"
                )
            statuses = {response["status"] for response in responses}
            if (
                retry_number == len(API_RETRY_DELAYS)
                or not statuses
                or not statuses.issubset(RETRYABLE_STATUS_CODES)
            ):
                break
            delay = API_RETRY_DELAYS[retry_number]
            self.log(
                f"Dify API is busy (HTTP {min(statuses)}); retrying in {delay:g}s..."
            )
            time.sleep(delay)
        raise ConsoleApiError(" | ".join(errors))

    def _via_context(
        self,
        url: str,
        method: str,
        body: dict[str, Any] | None,
        csrf_headers: dict[str, str],
    ) -> dict[str, Any]:
        headers = {
            "Accept": "application/json",
            "Referer": f"{self.endpoint}/apps",
            **csrf_headers,
        }
        options: dict[str, Any] = {
            "headers": headers,
            "fail_on_status_code": False,
            "timeout": 60_000,
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
            options["data"] = json.dumps(body)
        request = self.context.request.post if method == "POST" else self.context.request.get
        response = request(url, **options)
        text = response.text()
        try:
            payload = response.json()
        except Exception:
            payload = None
        return {
            "ok": response.ok,
            "status": response.status,
            "text": text,
            "json": payload,
            "strategy": "context.request",
        }

    def _via_page(
        self,
        url: str,
        method: str,
        body: dict[str, Any] | None,
        csrf_headers: dict[str, str],
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json", **csrf_headers}
        if body is not None:
            headers["Content-Type"] = "application/json"
        result = self.page.evaluate(
            """
            async ({url, method, headers, body}) => {
                try {
                    const response = await fetch(url, {
                        method,
                        credentials: "include",
                        headers,
                        body: body ? JSON.stringify(body) : undefined,
                    });
                    const text = await response.text();
                    let json = null;
                    try { json = JSON.parse(text); } catch (_) {}
                    return {ok: response.ok, status: response.status, text, json};
                } catch (error) {
                    return {ok: false, status: -1, text: String(error), json: null};
                }
            }
            """,
            {"url": url, "method": method, "headers": headers, "body": body},
        )
        result["strategy"] = "page.fetch"
        return result

    def list_tags(self) -> list[dict[str, Any]]:
        payload = self._request_json("/tags?type=app", allow_list=True)
        if isinstance(payload, list):
            return payload
        for key in ("data", "tags"):
            if isinstance(payload.get(key), list):
                return payload[key]
        raise ConsoleApiError(f"Unexpected tag list response: {payload!r}")

    def list_apps(self, tag_id: str | None = None) -> list[dict[str, Any]]:
        apps: list[dict[str, Any]] = []
        page_number = 1
        while True:
            params: dict[str, Any] = {
                "mode": "all",
                "page": page_number,
                "limit": PAGE_SIZE,
                "name": "",
            }
            if tag_id:
                params["tag_ids"] = tag_id
            payload = self._request_json(f"/apps?{urlencode(params)}")
            batch = payload.get("data", [])
            if not isinstance(batch, list):
                raise ConsoleApiError(f"Unexpected app list response: {payload!r}")
            apps.extend(batch)
            if not payload.get("has_more"):
                return apps
            page_number += 1

    def list_workflow_tools(self) -> list[dict[str, Any]]:
        payload = self._request_json(
            "/workspaces/current/tools/workflow", allow_list=True
        )
        if isinstance(payload, list):
            tools = payload
        else:
            tools = next(
                (
                    payload[key]
                    for key in ("data", "tools", "providers")
                    if isinstance(payload.get(key), list)
                ),
                [],
            )
        return tools

    def get_workflow_tool(self, tool_id: str) -> dict[str, Any]:
        try:
            payload = self._request_json(
                "/workspaces/current/tool-provider/workflow/get?"
                + urlencode({"workflow_tool_id": tool_id})
            )
        except ConsoleApiError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def list_workflow_logs(
        self,
        app_id: str,
        keyword: str,
        *,
        page: int = 1,
        limit: int = 100,
    ) -> dict[str, Any]:
        payload = self._request_json(
            f"/apps/{app_id}/workflow-app-logs?"
            + urlencode(
                {
                    "page": page,
                    "limit": limit,
                    "keyword": keyword,
                    "detail": "true",
                }
            )
        )
        if not isinstance(payload, dict):
            raise ConsoleApiError(f"Unexpected workflow log response: {payload!r}")
        return payload

    def get_workflow_run(self, app_id: str, run_id: str) -> dict[str, Any]:
        payload = self._request_json(f"/apps/{app_id}/workflow-runs/{run_id}")
        if not isinstance(payload, dict):
            raise ConsoleApiError(f"Unexpected workflow run response: {payload!r}")
        return payload

    def list_workflow_run_nodes(
        self, app_id: str, run_id: str
    ) -> list[dict[str, Any]]:
        payload = self._request_json(
            f"/apps/{app_id}/workflow-runs/{run_id}/node-executions",
            allow_list=True,
        )
        if isinstance(payload, list):
            return payload
        for key in ("data", "items"):
            if isinstance(payload.get(key), list):
                return payload[key]
        raise ConsoleApiError(f"Unexpected node execution response: {payload!r}")

    def list_workspaces(self) -> list[dict[str, Any]]:
        payload = self._request_json("/workspaces", allow_list=True)
        if isinstance(payload, list):
            return payload
        for key in ("workspaces", "data"):
            if isinstance(payload.get(key), list):
                return payload[key]
        raise ConsoleApiError(f"Unexpected workspace list response: {payload!r}")

    def switch_workspace(self, workspace_name: str) -> None:
        matches = [
            workspace
            for workspace in self.list_workspaces()
            if workspace.get("name") == workspace_name
        ]
        if len(matches) != 1:
            raise ConsoleApiError(
                f"Expected one workspace named {workspace_name!r}, found {len(matches)}"
            )
        self._request_json(
            "/workspaces/switch",
            method="POST",
            body={"tenant_id": matches[0]["id"]},
        )

    def export_dsl(self, app_id: str) -> str:
        payload = self._request_json(f"/apps/{app_id}/export?include_secret=true")
        dsl = payload.get("data")
        if not isinstance(dsl, str) or not dsl:
            raise ConsoleApiError(f"Export returned no DSL for app {app_id}")
        return dsl
