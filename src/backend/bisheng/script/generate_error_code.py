import importlib
import inspect
import json
import os

from bisheng.common.errcode import BaseErrorCode


def main():
    json_file = "all_error_code.json"
    all_code = {}
    print("This is a function for generate all error code json for frontend.")
    error_code_path = os.path.join(os.path.dirname(__file__), '../common/errcode')
    for root, dirs, files in os.walk(error_code_path):
        for file in files:
            if file.endswith(".py") and file != '__init__.py' and file != 'base.py':
                module = importlib.import_module('bisheng.common.errcode.' + file.replace('.py', ''))
                for name, obj in inspect.getmembers(module):
                    if inspect.isclass(obj) and issubclass(obj, BaseErrorCode) and obj is not BaseErrorCode:
                        code = getattr(obj, 'Code')
                        message = getattr(obj, 'Msg')
                        if code in all_code:
                            print(f"Warning: Duplicate error code {code} found in {obj}!")
                        all_code[code] = message.replace("{", "{{").replace("}", "}}")
    all_code_key = sorted(all_code.keys())
    result = {}
    for code in all_code_key:
        result[str(code)] = all_code[code]

    with open(json_file, 'w') as f:
        json.dump(result, f, ensure_ascii=False, indent=4)


if __name__ == '__main__':
    main()
