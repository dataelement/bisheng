"""Load pure catalog modules without bootstrapping database-backed service packages."""

import importlib
import sys
from pathlib import Path
from types import ModuleType

package_name = "_discovery_contract_tests"
if package_name not in sys.modules:
    package = ModuleType(package_name)
    package.__path__ = [str(Path(__file__).parents[2] / "bisheng/llm/domain/services")]
    sys.modules[package_name] = package
catalog = importlib.import_module(f"{package_name}.model_discovery")
providers = importlib.import_module(f"{package_name}.model_discovery_providers")
presets = importlib.import_module(f"{package_name}.model_discovery_presets")
