from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    app_env: str = 'development'
    database_url: str = 'sqlite:///./edge_lab.db'
    redis_url: str = 'redis://localhost:6379/0'
    signer_enabled: bool = False
    risk_max_normal_loss_pct: float = 0.0025
    risk_max_exceptional_loss_pct: float = 0.005
    risk_daily_stop_pct: float = 0.01
    risk_weekly_stop_pct: float = 0.03
    risk_monthly_stop_pct: float = 0.06
    risk_halve_at_drawdown_pct: float = 0.10
    risk_freeze_at_drawdown_pct: float = 0.15
    risk_max_market_data_age_seconds: int = 5
    hyperliquid_network: str = 'mainnet'
    hyperliquid_timeout_seconds: float = 10.0
    hyperliquid_market_poll_seconds: int = 60
    hyperliquid_funding_poll_seconds: int = 3600
    hyperliquid_funding_coins: str = 'BTC,ETH,SOL'

@lru_cache
def get_settings() -> Settings:
    return Settings()
