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
    polymarket_timeout_seconds: float = 10.0
    polymarket_scan_seconds: int = 60
    polymarket_max_markets: int = 50
    polymarket_max_negrisk_events: int = 8
    polymarket_max_shares_per_opportunity: float = 100.0
    polymarket_min_edge_bps: float = 10.0
    polymarket_max_book_age_seconds: int = 10
    helius_api_key: str = ''
    helius_commitment: str = 'confirmed'
    helius_pump_program_ids: str = '6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P,pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA'
    jupiter_api_key: str = ''
    jupiter_timeout_seconds: float = 10.0
    dexscreener_timeout_seconds: float = 10.0
    goplus_access_token: str = ''
    goplus_timeout_seconds: float = 10.0
    solana_forensic_poll_seconds: int = 300
    solana_max_candidate_age_hours: int = 24
    solana_enrichment_sample_modulo: int = 50
    solana_max_enrichments_per_cycle: int = 20
    solana_min_enrichment_interval_minutes: int = 15
    solana_shadow_exit_notional_usd: float = 25.0
    solana_quote_mint: str = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
    portfolio_min_unallocated_pct: float = 0.40
    portfolio_global_planned_risk_pct: float = 0.02
    portfolio_bucket_planned_risk_pct: float = 0.01
    portfolio_max_strategy_notional_pct: float = 0.20
    portfolio_max_venue_notional_pct: float = 0.35
    portfolio_venue_float_buffer_pct: float = 0.10
    treasury_min_rebalance_usd: float = 25.0
    treasury_max_transfer_cost_pct: float = 0.005

@lru_cache
def get_settings() -> Settings:
    return Settings()
