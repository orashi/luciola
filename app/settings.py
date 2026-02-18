from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    tz: str = "Asia/Tokyo"
    app_env: str = "dev"
    database_url: str = "sqlite:///./data/app.db"

    qbit_host: str = "localhost"
    qbit_port: int = 8080
    qbit_username: str = ""
    qbit_password: str = ""
    qbit_category: str = "anime"
    qbit_save_root: str = "/downloads"

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    jellyfin_host: str = "127.0.0.1"
    jellyfin_port: int = 8096
    jellyfin_api_key: str = ""

    incoming_root: str = "/media/incoming"
    library_root: str = "/media/library/Anime"
    preferred_subgroups: str = ""
    rss_urls: str = ""
    backfill_limit_per_show: int = 200

    # Poll safety + source expansion limits
    max_episode_queries_per_show: int = 6
    max_search_terms_per_show: int = 12  # Increased from 6 to include both English and non-English terms
    max_feed_urls_per_show: int = 24  # Increased from 12 to accommodate more search terms
    max_candidates_per_show: int = 180
    rss_timeout_sec: int = 8  # Increased from 4 to prevent timeouts
    rss_max_entries_per_feed: int = 60
    fallback_bangumi_api_pages: int = 1
    fallback_api_results_per_show: int = 50

    # Stability controls
    per_show_time_budget_sec: int = 25
    max_add_per_show_per_cycle: int = 5


settings = Settings()
