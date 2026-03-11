import os
import tempfile
from pathlib import Path

import pytest
import yaml

from homebox_tools.lib.config import load_config, Config


def test_load_config_from_yaml():
    data = {
        "homebox": {
            "url": "http://localhost:3100",
            "username": "test@example.com",
            "password": "secret",
        },
        "amazon": {"session_dir": "/tmp/session"},
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(data, f)
        path = f.name
    try:
        cfg = load_config(path)
        assert cfg.homebox_url == "http://localhost:3100"
        assert cfg.homebox_username == "test@example.com"
        assert cfg.homebox_password == "secret"
        assert cfg.amazon_session_dir == "/tmp/session"
    finally:
        os.unlink(path)


def test_env_vars_override_config():
    data = {
        "homebox": {
            "url": "http://localhost:3100",
            "username": "test@example.com",
            "password": "secret",
        },
        "amazon": {"session_dir": "/tmp/session"},
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(data, f)
        path = f.name
    try:
        env = {
            "HOMEBOX_URL": "http://override:3100",
            "HOMEBOX_USERNAME": "override@example.com",
            "HOMEBOX_PASSWORD": "override-secret",
        }
        orig = {}
        for k, v in env.items():
            orig[k] = os.environ.get(k)
            os.environ[k] = v
        try:
            cfg = load_config(path)
            assert cfg.homebox_url == "http://override:3100"
            assert cfg.homebox_username == "override@example.com"
            assert cfg.homebox_password == "override-secret"
        finally:
            for k, v in orig.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    finally:
        os.unlink(path)


def test_load_config_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_config("/nonexistent/config.yaml")
