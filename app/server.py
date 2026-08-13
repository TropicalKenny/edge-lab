from app.main import app
from app.portfolio_api import router as portfolio_router

app.include_router(portfolio_router)
