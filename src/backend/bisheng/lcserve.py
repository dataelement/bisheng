# This file is used by lc-serve to load the mounted app and serve it.

import os

from bisheng.main import setup_app

# Use the JCLOUD_WORKSPACE for db URL if it's provided by JCloud.
if 'JCLOUD_WORKSPACE' in os.environ:
    os.environ[
        'bisheng_DATABASE_URL'
    ] = f"sqlite:///{os.environ['JCLOUD_WORKSPACE']}/bisheng.db"

app = setup_app()
