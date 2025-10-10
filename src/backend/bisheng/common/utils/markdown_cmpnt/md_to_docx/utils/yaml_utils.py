import yaml
from yaml import FullLoader


def read_style_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as file:
        return yaml.load(file, FullLoader)
