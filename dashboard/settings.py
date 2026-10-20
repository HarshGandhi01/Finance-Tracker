from database_loader import load_database
from views import render_settings

render_settings(load_database())
