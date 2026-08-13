from app.main import app
from app.portfolio_api import router as portfolio_router
from app.evaluation_api import router as evaluation_router
from app.forward_api import router as forward_router

app.include_router(portfolio_router)
app.include_router(evaluation_router)
app.include_router(forward_router)
