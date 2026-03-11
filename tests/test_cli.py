import subprocess
import sys

import pytest


def test_help_flag():
    result = subprocess.run(
        [sys.executable, "-m", "homebox_tools", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "homebox-tools" in result.stdout.lower() or "usage" in result.stdout.lower()


def test_no_args_shows_error():
    result = subprocess.run(
        [sys.executable, "-m", "homebox_tools"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0


def test_url_and_folder_mutually_exclusive():
    result = subprocess.run(
        [sys.executable, "-m", "homebox_tools", "https://amazon.com/dp/B0TEST", "--folder", "/tmp/test"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0


def test_version_flag():
    result = subprocess.run(
        [sys.executable, "-m", "homebox_tools", "--version"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "0.1.0" in result.stdout


def test_version_flag_contains_prog_name():
    result = subprocess.run(
        [sys.executable, "-m", "homebox_tools", "--version"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "homebox-tools" in result.stdout
