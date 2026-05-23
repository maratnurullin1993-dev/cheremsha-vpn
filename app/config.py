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
    admin_id: str = ""
    admin_ids: str = ""
    admin_api_token: str = Field(default="change_me")

    database_path: str = "data/app.sqlite3"

    vpn_node_name: str = "Personal Node"
    vpn_country: str = "NL"
    vpn_protocol: str = "vless"
    vpn_host: str = "78.17.76.184"
    vpn_port: int | None = 8443
    vpn_network: str = "ws"
    vpn_security: str = "none"
    vpn_ws_path: str = "/"
    vpn_sni: str = ""
    vpn_server_name: str = ""
    vpn_public_key: str = ""
    vpn_short_id: str = ""
    vpn_flow: str = ""
    default_days: int = 30

    xray_config_path: str = ""
    xui_db_path: str = ""
    xui_api_base_url: str = ""
    xui_api_username: str = ""
    xui_api_password: str = ""
    xui_api_inbound_id: int | None = 1
    xray_restart_command: str = ""

    @field_validator("xui_api_inbound_id", mode="before")
    @classmethod
    def default_xui_api_inbound_id(cls, value: object) -> object:
        if value == "":
            return None
        return value

    max_users: int = 20
    max_active_keys: int = 20
    default_7d_traffic_gb: int = 10
    default_30d_traffic_gb: int = 50

    support_url: str = "https://t.me/"
    v2box_ios_url: str = ""
    v2raytun_ios_url: str = ""
    v2raytun_android_url: str = ""

    @field_validator("vpn_port", mode="before")
    @classmethod
    def default_vpn_port(cls, value: object) -> object:
        if value == "":
            return None
        return value

    def reality_sni(self) -> str:
        return self.vpn_sni.strip() or self.vpn_server_name.strip()

    def vpn_network_value(self) -> str:
        return self.vpn_network.strip().lower()

    def vpn_security_value(self) -> str:
        return self.vpn_security.strip().lower()

    def subscription_base_url(self) -> str:
        public_url = self.public_base_url.strip().rstrip("/")
        webapp_url = self.webapp_url.strip().rstrip("/")
        if public_url and "localhost" not in public_url and "127.0.0.1" not in public_url:
            return public_url
        return webapp_url or public_url

    def admin_id_values(self) -> set[int]:
        values: set[int] = set()
        for raw_ids in (self.admin_id, self.admin_ids):
            for raw_id in str(raw_ids).split(","):
                raw_id = raw_id.strip()
                if raw_id and raw_id != "0":
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
