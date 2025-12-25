from __future__ import annotations

from fastapi import FastAPI

from app.api.webhooks import payments as payments_webhooks

app = FastAPI(title="Live Photo API")

# Вебхук от YooKassa
app.include_router(payments_webhooks.router)

@app.get("/healthz")
async def healthz():
    return {"ok": True}
