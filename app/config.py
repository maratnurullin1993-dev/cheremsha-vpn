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
    bot_username: str = ""
    telegram_bot_url: str = "https://t.me/"
    telegram_proxy_url: str = ""
    admin_id: int = 0
    admin_ids: str = ""
    admin_api_token: str = Field(default="change_me")

    database_path: str = "data/app.sqlite3"

    vpn_node_name: str = "Personal Node"
    vpn_country: str = "NL"
    vpn_host: str = ""
    vpn_port: int | None = None
    vpn_sni: str = ""
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
            return None
        return value

    def reality_sni(self) -> str:
        return self.vpn_sni.strip() or self.vpn_server_name.strip()

    def subscription_base_url(self) -> str:
        public_url = self.public_base_url.strip().rstrip("/")
        webapp_url = self.webapp_url.strip().rstrip("/")
        if public_url and "localhost" not in public_url and "127.0.0.1" not in public_url:
            return public_url
        return webapp_url or public_url

    def admin_id_values(self) -> set[int]:
        values = {self.admin_id} if self.admin_id else set()
        for raw_id in self.admin_ids.split(","):
            raw_id = raw_id.strip()
            if raw_id:
                values.add(int(raw_id))
        return values

    def is_admin(self, telegram_id: int) -> bool:
        return telegram_id in self.admin_id_values()

    def default_admin_id(self) -> int:
        values = sorted(self.admin_id_values())
        return values[0] if values else 0

    def telegram_open_url(self) -> str:
        username = self.bot_username.strip().lstrip("@")
        if not username:
            return ""
        return f"https://t.me/{username}?startapp=main"


@lru_cache
def get_settings() -> Settings:
    return Settings()
