from fastapi import FastAPI

from app.api.reverse_rule import router as reverse_rule_router

app = FastAPI(title="Reverse Rule Workflow API")
app.include_router(reverse_rule_router)
