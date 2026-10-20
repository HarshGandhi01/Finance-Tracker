from database_loader import load_database
from views import render_overview

render_overview(load_database())
