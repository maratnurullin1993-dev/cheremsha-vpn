from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Personal VPN Mini App"
    app_env: str = "dev"
    dev_mode: bool = True

    host: str = "0.0.0.0"
    port: int = 8000
    public_base_url: str = "http://localhost:8000"
    webapp_url: str = "http://localhost:8000"

    bot_token: str = ""
    telegram_proxy_url: str = ""
    admin_id: int = 0
    admin_api_token: str = Field(default="change_me")

    database_path: str = "data/app.sqlite3"

    vpn_node_name: str = "Personal Node"
    vpn_country: str = "NL"
    vpn_host: str = ""
    vpn_port: int = 443
    vpn_server_name: str = ""
    vpn_public_key: str = ""
    vpn_short_id: str = ""
    vpn_flow: str = "xtls-rprx-vision"
    default_days: int = 30

    xray_config_path: str = ""
    xray_restart_command: str = ""

    max_active_keys: int = 20
    default_7d_traffic_gb: int = 10
    default_30d_traffic_gb: int = 50

    support_url: str = "https://t.me/"

    @field_validator("vpn_port", mode="before")
    @classmethod
    def default_vpn_port(cls, value: object) -> object:
        if value == "":
            return 443
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
