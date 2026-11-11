"""Production WSGI entry point."""
from app import app, init_app

init_app()
