import os
from pathlib import Path


os.environ.setdefault('config', str(Path(__file__).with_name('test_config.yaml').resolve()))
