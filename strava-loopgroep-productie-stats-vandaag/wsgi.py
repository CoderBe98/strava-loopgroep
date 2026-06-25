import atexit
import logging

from app import create_app, start_scheduler
from config import get_settings

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
settings = get_settings()
app = create_app(settings)
scheduler = start_scheduler(settings)
atexit.register(lambda: scheduler.shutdown(wait=False) if scheduler.running else None)
