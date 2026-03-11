from unittest.mock import patch, MagicMock, call
import pytest

import requests as _requests_module

from homebox_tools.lib.homebox_client import HomeboxClient, HomeboxError


@pytest.fixture
def client():
    return HomeboxClient(
        url="http://localhost:3100",
        username="test@example.com",
        password="secret",
    )


def _mock_response(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.ok = 200 <= status_code < 300
    resp.text = ""
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return resp


class TestInit:
    def test_trailing_slash_stripped(self):
        c = HomeboxClient(
            url="http://localhost:3100/",
            username="u",
            password="p",
        )
        assert c.base_url == "http://localhost:3100"

    def test_multiple_trailing_slashes_stripped(self):
        c = HomeboxClient(
            url="http://localhost:3100///",
            username="u",
            password="p",
        )
        assert c.base_url == "http://localhost:3100"

    def test_no_trailing_slash_unchanged(self):
        c = HomeboxClient(
            url="http://localhost:3100",
            username="u",
            password="p",
        )
        assert c.base_url == "http://localhost:3100"


class TestLogin:
    @patch("requests.post")
    def test_login_stores_token(self, mock_post, client):
        mock_post.return_value = _mock_response(200, {"token": "Bearer abc123"})
        client.login()
        assert client._token == "Bearer abc123"
        mock_post.assert_called_once()
        body = mock_post.call_args[1]["json"]
        assert body["stayLoggedIn"] is True

    @patch("requests.post")
    def test_login_failure_raises(self, mock_post, client):
        mock_post.return_value = _mock_response(401, {"message": "bad credentials"})
        with pytest.raises(HomeboxError):
            client.login()

    @patch("requests.post")
    def test_login_connection_error_raises_homebox_error(self, mock_post, client):
        mock_post.side_effect = _requests_module.ConnectionError("refused")
        with pytest.raises(HomeboxError, match="Connection failed"):
            client.login()

    @patch("requests.post")
    def test_login_timeout_raises_homebox_error(self, mock_post, client):
        mock_post.side_effect = _requests_module.Timeout("timed out")
        with pytest.raises(HomeboxError, match="timed out"):
            client.login()


class TestTokenRefresh:
    @patch("requests.get")
    def test_refresh_updates_token(self, mock_get, client):
        client._token = "Bearer old-token"
        mock_get.return_value = _mock_response(200, {"raw": "new-token-value"})
        result = client._refresh_token()
        assert result is True
        assert client._token == "Bearer new-token-value"

    @patch("requests.get")
    def test_refresh_failure_returns_false(self, mock_get, client):
        client._token = "Bearer old-token"
        mock_get.return_value = _mock_response(401)
        result = client._refresh_token()
        assert result is False


class TestCreateItem:
    @patch("requests.post")
    def test_create_item_returns_id(self, mock_post, client):
        client._token = "Bearer abc123"
        mock_post.return_value = _mock_response(201, {"id": "item-uuid-1", "name": "Test Item"})
        item_id = client.create_item(name="Test Item", description="A test", location_id="loc-uuid")
        assert item_id == "item-uuid-1"

    @patch("requests.post")
    def test_create_item_with_tags(self, mock_post, client):
        client._token = "Bearer abc123"
        mock_post.return_value = _mock_response(201, {"id": "item-uuid-2"})
        item_id = client.create_item(name="Test", description="", location_id="loc-1", tag_ids=["t1", "t2"])
        assert item_id == "item-uuid-2"
        body = mock_post.call_args[1]["json"]
        assert body["tagIds"] == ["t1", "t2"]


class TestSearch:
    @patch("requests.get")
    def test_search_items(self, mock_get, client):
        client._token = "Bearer abc123"
        mock_get.return_value = _mock_response(200, {"items": [{"id": "1", "name": "Existing"}]})
        results = client.search_items("Existing")
        assert len(results) == 1
        assert results[0]["name"] == "Existing"


class TestLocations:
    @patch("requests.get")
    def test_get_locations(self, mock_get, client):
        client._token = "Bearer abc123"
        mock_get.return_value = _mock_response(200, [
            {"id": "loc-1", "name": "Garage", "children": []},
            {"id": "loc-2", "name": "Loft", "children": []},
        ])
        locations = client.get_locations()
        assert len(locations) == 2

    def test_find_location_by_name(self, client):
        locations = [
            {"id": "loc-1", "name": "Garage", "children": [
                {"id": "loc-3", "name": "Workbench", "children": []},
            ]},
            {"id": "loc-2", "name": "Loft", "children": []},
        ]
        assert client.find_location_by_name("Loft", locations) == "loc-2"
        assert client.find_location_by_name("Workbench", locations) == "loc-3"
        assert client.find_location_by_name("Basement", locations) is None

    def test_find_location_case_insensitive(self, client):
        locations = [{"id": "loc-1", "name": "Garage", "children": []}]
        assert client.find_location_by_name("garage", locations) == "loc-1"


class TestTags:
    @patch("requests.get")
    def test_get_tags(self, mock_get, client):
        client._token = "Bearer abc123"
        mock_get.return_value = _mock_response(200, [{"id": "tag-1", "name": "Electronics"}])
        tags = client.get_tags()
        assert len(tags) == 1
        assert tags[0]["name"] == "Electronics"


class TestRetryLogic:
    """Tests for transient-error retry with exponential backoff."""

    @patch("time.sleep")
    @patch("requests.get")
    def test_retries_on_503_then_succeeds(self, mock_get, mock_sleep, client):
        client._token = "Bearer abc123"
        mock_get.side_effect = [
            _mock_response(503),
            _mock_response(200, {"items": []}),
        ]
        results = client.search_items("test")
        assert results == []
        assert mock_get.call_count == 2
        # One backoff sleep between attempts.
        mock_sleep.assert_called_once_with(1)

    @patch("time.sleep")
    @patch("requests.get")
    def test_retries_on_429_then_succeeds(self, mock_get, mock_sleep, client):
        client._token = "Bearer abc123"
        mock_get.side_effect = [
            _mock_response(429),
            _mock_response(200, {"items": [{"id": "1"}]}),
        ]
        results = client.search_items("q")
        assert len(results) == 1
        mock_sleep.assert_called_once_with(1)

    @patch("time.sleep")
    @patch("requests.get")
    def test_retries_exhaust_all_attempts(self, mock_get, mock_sleep, client):
        """After 3 consecutive 500s the last response is returned (not raised)."""
        client._token = "Bearer abc123"
        mock_get.side_effect = [
            _mock_response(500),
            _mock_response(500),
            _mock_response(500),
        ]
        resp = client._do_request("get", "http://example.com/api/v1/items", client._headers)
        assert resp.status_code == 500
        assert mock_get.call_count == 3
        # Two sleeps: 1s and 2s (exponential backoff).
        assert mock_sleep.call_args_list == [call(1), call(2)]

    @patch("time.sleep")
    @patch("requests.get")
    def test_no_retry_on_400(self, mock_get, mock_sleep, client):
        """Non-retryable status codes should not trigger retries."""
        client._token = "Bearer abc123"
        mock_get.return_value = _mock_response(400)
        resp = client._do_request("get", "http://example.com/api/v1/items", client._headers)
        assert resp.status_code == 400
        assert mock_get.call_count == 1
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    @patch("requests.get")
    def test_retry_exponential_backoff_timing(self, mock_get, mock_sleep, client):
        """Verify the backoff doubles each attempt: 1s, 2s."""
        client._token = "Bearer abc123"
        mock_get.side_effect = [
            _mock_response(502),
            _mock_response(502),
            _mock_response(200, {"items": []}),
        ]
        client.search_items("test")
        assert mock_sleep.call_args_list == [call(1), call(2)]


class TestConnectionErrorHandling:
    """Tests for ConnectionError and Timeout wrapping."""

    @patch("time.sleep")
    @patch("requests.get")
    def test_connection_error_retries_then_raises(self, mock_get, mock_sleep, client):
        client._token = "Bearer abc123"
        mock_get.side_effect = _requests_module.ConnectionError("refused")
        with pytest.raises(HomeboxError, match="Connection failed after 3 attempts"):
            client.search_items("test")
        assert mock_get.call_count == 3

    @patch("time.sleep")
    @patch("requests.get")
    def test_timeout_retries_then_raises(self, mock_get, mock_sleep, client):
        client._token = "Bearer abc123"
        mock_get.side_effect = _requests_module.Timeout("timed out")
        with pytest.raises(HomeboxError, match="timed out after 3 attempts"):
            client.search_items("test")
        assert mock_get.call_count == 3

    @patch("time.sleep")
    @patch("requests.get")
    def test_connection_error_recovers_on_retry(self, mock_get, mock_sleep, client):
        client._token = "Bearer abc123"
        mock_get.side_effect = [
            _requests_module.ConnectionError("refused"),
            _mock_response(200, {"items": [{"id": "1"}]}),
        ]
        results = client.search_items("test")
        assert len(results) == 1
        assert mock_get.call_count == 2
        mock_sleep.assert_called_once_with(1)

    @patch("time.sleep")
    @patch("requests.get")
    def test_timeout_recovers_on_retry(self, mock_get, mock_sleep, client):
        client._token = "Bearer abc123"
        mock_get.side_effect = [
            _requests_module.Timeout("slow"),
            _mock_response(200, {"items": []}),
        ]
        results = client.search_items("test")
        assert results == []
        assert mock_get.call_count == 2


class TestTokenExpiry401Loop:
    """Ensure 401 handling doesn't infinite-loop when refresh also returns 401."""

    @patch("requests.post")
    @patch("requests.get")
    def test_401_with_failed_refresh_relogins(self, mock_get, mock_post, client):
        """When refresh fails, login is called. If login succeeds, the request
        is retried with the new token."""
        client._token = "Bearer expired"
        # First GET: 401.  Refresh GET: also 401.
        # Then login POST: success.  Retry GET: 200.
        mock_get.side_effect = [
            _mock_response(401),               # original request
            _mock_response(401),               # refresh attempt
            _mock_response(200, {"items": []}),  # retried request after login
        ]
        mock_post.return_value = _mock_response(200, {"token": "Bearer new"})
        results = client.search_items("test")
        assert results == []
        # login was called
        mock_post.assert_called_once()
        assert client._token == "Bearer new"

    @patch("requests.post")
    @patch("requests.get")
    def test_401_with_failed_refresh_and_failed_login_raises(self, mock_get, mock_post, client):
        """If both refresh and login fail, a HomeboxError is raised — no loop."""
        client._token = "Bearer expired"
        mock_get.side_effect = [
            _mock_response(401),  # original request
            _mock_response(401),  # refresh attempt
        ]
        mock_post.return_value = _mock_response(401, {"message": "bad creds"})
        with pytest.raises(HomeboxError, match="Login failed"):
            client.search_items("test")
