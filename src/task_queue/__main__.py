"""Allow running as: python -m src.task_queue"""
from .server import app
import uvicorn

uvicorn.run(app, host="127.0.0.1", port=8632, log_level="info")
