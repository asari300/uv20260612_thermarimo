"""設定・機密情報の読み込み。"""

from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)


class DeviceConfig(BaseModel):
    serial: str  # 例: "EXAMPLE1"
    label: str  # 表示名


class Settings(BaseSettings):
    """認証情報と保存設定。優先順位: 引数 > 環境変数(ONDOTORI_*) > secrets.toml。"""

    model_config = SettingsConfigDict(
        env_prefix="ONDOTORI_",
        toml_file=Path(".config/secrets.toml"),
        extra="ignore",
    )

    api_key: str
    login_id: str
    login_pass: str
    devices: list[DeviceConfig]
    data_root: Path = Path("data")
    request_timeout: float = 30.0
    resample_intervals: list[int] = [1, 5, 10, 60, 300]

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


def load_settings(config_dir: Path = Path(".config")) -> Settings:
    """config_dir/secrets.toml と環境変数から設定を構築する。"""
    toml_file = Path(config_dir) / "secrets.toml"

    class _Settings(Settings):
        model_config = SettingsConfigDict(toml_file=toml_file)

    return _Settings()
