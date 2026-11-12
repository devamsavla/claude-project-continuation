import os
from dataclasses import dataclass, field


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass
class Settings:
    wa_token: str = field(default_factory=lambda: _env("WA_TOKEN"))
    wa_phone_number_id: str = field(default_factory=lambda: _env("WA_PHONE_NUMBER_ID"))
    wa_app_secret: str = field(default_factory=lambda: _env("WA_APP_SECRET"))
    wa_verify_token: str = field(default_factory=lambda: _env("WA_VERIFY_TOKEN", "dev-verify-token"))
    graph_version: str = field(default_factory=lambda: _env("GRAPH_VERSION", "v27.0"))
    ig_token: str = field(default_factory=lambda: _env("IG_TOKEN"))
    ig_user_id: str = field(default_factory=lambda: _env("IG_USER_ID"))
    ig_app_secret: str = field(default_factory=lambda: _env("IG_APP_SECRET"))
    ig_verify_token: str = field(default_factory=lambda: _env("IG_VERIFY_TOKEN", "dev-verify-token"))
    anthropic_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    model_fast: str = field(default_factory=lambda: _env("MINDY_MODEL_FAST", "claude-haiku-5-5"))
    model_smart: str = field(default_factory=lambda: _env("MINDY_MODEL_SMART", "claude-sonnet-5-5"))
    database_path: str = field(default_factory=lambda: _env("DATABASE_PATH", "./mindy.db"))
    default_tz: str = field(default_factory=lambda: _env("DEFAULT_TIMEZONE", "Europe/London"))
    allowed_origins: list = field(default_factory=lambda: [o for o in _env("ALLOWED_ORIGINS", "*").split(",") if o])
    admin_key: str = field(default_factory=lambda: _env("ADMIN_KEY", "change-me"))
    reminder_template: str = field(default_factory=lambda: _env("REMINDER_TEMPLATE", "mindy_reminder"))
    template_lang: str = field(default_factory=lambda: _env("TEMPLATE_LANG", "en_GB"))
    login_template: str = field(default_factory=lambda: _env("LOGIN_TEMPLATE", "mindy_login_code"))
    app_url: str = field(default_factory=lambda: _env("APP_URL", "https://app.whatsonyourmind.online"))
    public_wa_number: str = field(default_factory=lambda: _env("PUBLIC_WA_NUMBER", "447700900000"))
    public_ig_handle: str = field(default_factory=lambda: _env("PUBLIC_IG_HANDLE", "whatsonyourmind"))
    webapp_dir: str = field(default_factory=lambda: _env("WEBAPP_DIR", ""))

    @property
    def dev_codes(self) -> bool:
        """Show sign-in codes on screen only while WhatsApp isn't connected (local testing)."""
        return not self.whatsapp_live and _env("DEV_CODES", "1") == "1"

    @property
    def whatsapp_live(self) -> bool:
        return bool(self.wa_token and self.wa_phone_number_id)

    @property
    def instagram_live(self) -> bool:
        return bool(self.ig_token)

    @property
    def ai_live(self) -> bool:
        return bool(self.anthropic_key)


settings = Settings()
