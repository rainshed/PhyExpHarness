import os
import sys
from pathlib import Path

def data_dir(value=None):
    if value: return Path(value).expanduser().resolve()
    if os.environ.get('PHYEXP_DATA_DIR'): return Path(os.environ['PHYEXP_DATA_DIR']).expanduser().resolve()
    if sys.platform == 'darwin': return Path.home()/'Library/Application Support/PhyExpHarness'
    return Path(os.environ.get('XDG_DATA_HOME') or str(Path.home()/'.local/share')).expanduser().resolve()/'PhyExpHarness'
