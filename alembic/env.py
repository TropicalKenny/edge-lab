from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool
from app.config import get_settings
from app.models import Base
import app.venues.hyperliquid_models  # register extension tables in Base.metadata
import app.venues.polymarket_models  # register extension tables in Base.metadata
import app.venues.solana_models  # register extension tables in Base.metadata
import app.portfolio_models  # register portfolio audit tables in Base.metadata
import app.evaluation_models  # register strategy evidence audit table in Base.metadata
import app.forward_models  # register frozen forward research journal tables in Base.metadata
config=context.config; config.set_main_option('sqlalchemy.url',get_settings().database_url)
if config.config_file_name: fileConfig(config.config_file_name)
target_metadata=Base.metadata
def offline():
    context.configure(url=config.get_main_option('sqlalchemy.url'),target_metadata=target_metadata,literal_binds=True)
    with context.begin_transaction(): context.run_migrations()
def online():
    c=engine_from_config(config.get_section(config.config_ini_section),prefix='sqlalchemy.',poolclass=pool.NullPool)
    with c.connect() as conn:
        context.configure(connection=conn,target_metadata=target_metadata)
        with context.begin_transaction(): context.run_migrations()
offline() if context.is_offline_mode() else online()
