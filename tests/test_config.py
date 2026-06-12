import textwrap

import pytest
from pydantic import ValidationError

from src.mod.config import load_settings

SECRETS = textwrap.dedent(
    """
    api_key = "K"
    login_id = "USER0001"
    login_pass = "pass"

    [[devices]]
    serial = "EXAMPLE1"
    label = "1号機"

    [[devices]]
    serial = "EXAMPLE2"
    label = "2号機"
    """
)


def test_load_settings_from_toml(tmp_path):
    (tmp_path / "secrets.toml").write_text(SECRETS, encoding="utf-8")
    settings = load_settings(tmp_path)
    assert settings.api_key == "K"
    assert settings.login_id == "USER0001"
    assert [d.serial for d in settings.devices] == ["EXAMPLE1", "EXAMPLE2"]
    assert settings.devices[0].label == "1号機"
    assert settings.resample_intervals == [1, 5, 10, 60, 300]


def test_env_overrides_toml(tmp_path, monkeypatch):
    (tmp_path / "secrets.toml").write_text(SECRETS, encoding="utf-8")
    monkeypatch.setenv("ONDOTORI_API_KEY", "FROM_ENV")
    settings = load_settings(tmp_path)
    assert settings.api_key == "FROM_ENV"
    assert settings.login_id == "USER0001"


def test_missing_secrets_raises(tmp_path, monkeypatch):
    for var in ("ONDOTORI_API_KEY", "ONDOTORI_LOGIN_ID", "ONDOTORI_LOGIN_PASS"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ValidationError):
        load_settings(tmp_path)  # secrets.toml なし
