"""Pytest hooks shared across the suite."""

from pathlib import Path

from dotenv import load_dotenv

# The app loads `.env` via pydantic-settings; pytest does not unless we do it here.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
