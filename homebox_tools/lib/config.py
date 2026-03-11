"""Configuration loading from YAML file with env var overrides."""

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class Config:
    homebox_url: str
    homebox_username: str
    homebox_password: str
    amazon_session_dir: str

    @property
    def config_dir(self) -> Path:
        return Path.home() / ".config" / "homebox-tools"

    @property
    def session_path(self) -> Path:
        return Path(self.amazon_session_dir).expanduser()


DEFAULT_CONFIG_PATH = Path.home() / ".config" / "homebox-tools" / "config.yaml"


def load_config(path: str | Path | None = None) -> Config:
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path) as f:
        data = yaml.safe_load(f)

    homebox = data.get("homebox", {})
    amazon = data.get("amazon", {})

    return Config(
        homebox_url=os.environ.get("HOMEBOX_URL", homebox.get("url", "")),
        homebox_username=os.environ.get("HOMEBOX_USERNAME", homebox.get("username", "")),
        homebox_password=os.environ.get("HOMEBOX_PASSWORD", homebox.get("password", "")),
        amazon_session_dir=amazon.get(
            "session_dir",
            str(Path.home() / ".config" / "homebox-tools" / "amazon-session"),
        ),
    )
