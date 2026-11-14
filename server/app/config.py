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
    # The AI: any OpenAI-compatible API. Default is Gemini 2.5 Flash-Lite (cheapest good model with a free tier).
    llm_key: str = field(default_factory=lambda: _env("LLM_API_KEY") or _env("GEMINI_API_KEY"))
    llm_base_url: str = field(default_factory=lambda: _env("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "gemini-2.5-flash-lite"))
    llm_daily_calls: int = field(default_factory=lambda: int(_env("LLM_DAILY_CALLS_PER_PERSON", "150")))
    tg_token: str = field(default_factory=lambda: _env("TELEGRAM_BOT_TOKEN"))
    tg_secret: str = field(default_factory=lambda: _env("TELEGRAM_WEBHOOK_SECRET", "dev-telegram-secret"))
    tg_username: str = field(default_factory=lambda: _env("TELEGRAM_BOT_USERNAME", "whatsonyourmind_bot"))
    google_client_id: str = field(default_factory=lambda: _env("GOOGLE_CLIENT_ID"))
    care_alert_minutes: int = field(default_factory=lambda: int(_env("CARE_ALERT_MINUTES", "45")))
    database_path: str = field(default_factory=lambda: _env("DATABASE_PATH", "./mindy.db"))
    default_tz: str = field(default_factory=lambda: _env("DEFAULT_TIMEZONE", "Europe/London"))
    allowed_origins: list = field(default_factory=lambda: [o for o in _env("ALLOWED_ORIGINS", "*").split(",") if o])
    admin_key: str = field(default_factory=lambda: _env("ADMIN_KEY", "change-me"))
    reminder_template: str = field(default_factory=lambda: _env("REMINDER_TEMPLATE", "mindy_reminder"))
    template_lang: str = field(default_factory=lambda: _env("TEMPLATE_LANG", "en_GB"))
    care_template: str = field(default_factory=lambda: _env("CARE_TEMPLATE", "mindy_care"))
    care_alert_template: str = field(default_factory=lambda: _env("CARE_ALERT_TEMPLATE", "mindy_care_alert"))
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
    def telegram_live(self) -> bool:
        return bool(self.tg_token)

    @property
    def instagram_live(self) -> bool:
        return bool(self.ig_token)

    @property
    def ai_live(self) -> bool:
        return bool(self.llm_key)


settings = Settings()
