from fastapi import FastAPI

from poker_bot_platform import __version__

app = FastAPI(title="ACM Poker Bot Platform", version=__version__)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
