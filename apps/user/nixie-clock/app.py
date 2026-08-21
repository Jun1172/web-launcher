import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))
from shared import serve_page
serve_page(Path(__file__).with_name("index.html"))
