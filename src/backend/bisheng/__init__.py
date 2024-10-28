from importlib import metadata

from bisheng.cache import cache_manager  # noqa: E402
from bisheng.interface.custom.custom_component import CustomComponent
from bisheng.processing.process import load_flow_from_json  # noqa: E402

try:
    # 通过ci去自动修改
    __version__ = '0.3.7.dev1'
except metadata.PackageNotFoundError:
    # Case where package metadata is not available.
    __version__ = ''
del metadata  # optional, avoids polluting the results of dir(__package__)

__all__ = ['load_flow_from_json', 'cache_manager', 'CustomComponent']
