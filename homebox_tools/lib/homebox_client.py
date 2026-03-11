"""Homebox REST API client with token management."""

import time
from pathlib import Path

import requests


# HTTP status codes that are considered transient and worth retrying.
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_BACKOFF_BASE = 1  # seconds — retry delays: 1s, 2s, 4s


class HomeboxError(Exception):
    pass


class HomeboxClient:
    def __init__(self, url: str, username: str, password: str):
        self.base_url = url.rstrip("/")
        self._username = username
        self._password = password
        self._token: str | None = None

    @property
    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self._token:
            h["Authorization"] = self._token
        return h

    def _api(self, path: str) -> str:
        return f"{self.base_url}/api/v1{path}"

    def login(self) -> None:
        try:
            resp = requests.post(
                self._api("/users/login"),
                json={
                    "username": self._username,
                    "password": self._password,
                    "stayLoggedIn": True,
                },
            )
        except requests.ConnectionError as exc:
            raise HomeboxError(f"Connection failed: {exc}") from exc
        except requests.Timeout as exc:
            raise HomeboxError(f"Request timed out: {exc}") from exc
        if not resp.ok:
            raise HomeboxError(f"Login failed: {resp.status_code} {resp.text}")
        data = resp.json()
        self._token = data.get("token", "")
        if not self._token:
            raise HomeboxError("Login response missing token")

    def _refresh_token(self) -> bool:
        try:
            resp = requests.get(self._api("/users/refresh"), headers=self._headers)
            if resp.ok:
                raw = resp.json().get("raw", "")
                if raw:
                    self._token = f"Bearer {raw}"
                    return True
        except Exception:
            pass
        return False

    def _do_request(self, method: str, url: str, headers: dict, **kwargs) -> requests.Response:
        """Execute an HTTP request with retry logic for transient errors.

        Retries up to _MAX_RETRIES times on retryable status codes (429, 5xx)
        and on connection/timeout errors, using exponential backoff.
        """
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                resp = getattr(requests, method)(url, headers=headers, **kwargs)
            except requests.ConnectionError as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_BACKOFF_BASE * (2 ** attempt))
                    continue
                raise HomeboxError(f"Connection failed after {_MAX_RETRIES} attempts: {exc}") from exc
            except requests.Timeout as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_BACKOFF_BASE * (2 ** attempt))
                    continue
                raise HomeboxError(f"Request timed out after {_MAX_RETRIES} attempts: {exc}") from exc

            if resp.status_code not in _RETRYABLE_STATUS_CODES:
                return resp

            # Retryable HTTP status — back off and try again.
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_BACKOFF_BASE * (2 ** attempt))

        # All retries exhausted with a retryable status code.
        return resp  # type: ignore[possibly-undefined]

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = self._api(path)
        resp = self._do_request(method, url, self._headers, **kwargs)
        if resp.status_code == 401:
            if self._refresh_token():
                resp = self._do_request(method, url, self._headers, **kwargs)
            else:
                # Refresh failed — try a full re-login. If login itself gets a
                # 401 it will raise HomeboxError, preventing an infinite loop.
                self.login()
                resp = self._do_request(method, url, self._headers, **kwargs)
        return resp

    def search_items(self, query: str) -> list[dict]:
        resp = self._request("get", "/items", params={"q": query})
        data = resp.json()
        return data.get("items", [])

    def get_locations(self) -> list[dict]:
        resp = self._request("get", "/locations/tree")
        return resp.json()

    def get_tags(self) -> list[dict]:
        resp = self._request("get", "/tags")
        return resp.json()

    def create_tag(self, name: str) -> str:
        resp = self._request("post", "/tags", json={"name": name})
        return resp.json()["id"]

    def create_item(
        self,
        name: str,
        description: str,
        location_id: str,
        tag_ids: list[str] | None = None,
    ) -> str:
        payload = {
            "name": name,
            "description": description,
            "locationId": location_id,
            "quantity": 1,
        }
        if tag_ids:
            payload["tagIds"] = tag_ids
        resp = self._request("post", "/items", json=payload)
        if not resp.ok:
            raise HomeboxError(f"Create item failed: {resp.status_code} {resp.text}")
        return resp.json()["id"]

    def update_item(self, item_id: str, data: dict) -> dict:
        resp = self._request("put", f"/items/{item_id}", json=data)
        if not resp.ok:
            raise HomeboxError(f"Update item failed: {resp.status_code} {resp.text}")
        return resp.json()

    def get_item(self, item_id: str) -> dict:
        resp = self._request("get", f"/items/{item_id}")
        return resp.json()

    def upload_attachment(
        self,
        item_id: str,
        file_path: Path,
        attachment_type: str = "photo",
        primary: bool = False,
    ) -> dict:
        with open(file_path, "rb") as f:
            files = {"file": (file_path.name, f)}
            data = {
                "type": attachment_type,
                "name": file_path.stem,
            }
            if primary:
                data["primary"] = "true"
            headers = {}
            if self._token:
                headers["Authorization"] = self._token
            resp = requests.post(
                self._api(f"/items/{item_id}/attachments"),
                headers=headers,
                files=files,
                data=data,
            )
        if not resp.ok:
            raise HomeboxError(f"Upload failed: {resp.status_code} {resp.text}")
        return resp.json()

    def find_location_by_name(self, name: str, locations: list[dict] | None = None) -> str | None:
        if locations is None:
            locations = self.get_locations()
        name_lower = name.lower()
        for loc in locations:
            if loc["name"].lower() == name_lower:
                return loc["id"]
            children = loc.get("children", [])
            if children:
                found = self.find_location_by_name(name, children)
                if found:
                    return found
        return None
