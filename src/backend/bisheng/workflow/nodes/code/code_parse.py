import ast
import importlib
import inspect
from typing import Union, Type, Dict, Any


class CodeParser:
    """
    A parser for Python source code, extracting code details.
    """

    def __init__(self, code: Union[str, Type]) -> None:
        """
        Initializes the parser with the provided code.
        """
        if isinstance(code, type):
            if not inspect.isclass(code):
                raise ValueError("The provided code must be a class.")
            # If the code is a class, get its source code
            code = inspect.getsource(code)
        self.code = code
        self.exec_globals = {}
        self.exec_locals = {}
        self.data: Dict[str, Any] = {
            "imports": [],
        }
        self.handlers = {
            ast.Import: self.parse_imports,
            ast.ImportFrom: self.parse_imports,
            ast.FunctionDef: self.parse_functions,
            ast.ClassDef: self.parse_classes,
            ast.Assign: self.parse_global_vars,
        }

    def parse_code(self) -> Dict[str, Any]:
        """
        Runs all parsing operations and returns the resulting data.
        """
        tree = self.get_tree()

        for node in ast.walk(tree):
            self.parse_node(node)
        return self.data

    def get_tree(self):
        """
        Parses the provided code to validate its syntax.
        It tries to parse the code into an abstract syntax tree (AST).
        """
        return ast.parse(self.code)

    def parse_node(self, node: Union[ast.stmt, ast.AST]) -> None:
        """
        Parses an AST node and updates the data
        dictionary with the relevant information.
        """
        if handler := self.handlers.get(type(node)):  # type: ignore
            handler(node)  # type: ignore

    def parse_imports(self, node: Union[ast.Import, ast.ImportFrom]) -> None:
        """
        Extracts "imports" from the code, including aliases.
        """
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    self.data["imports"].append(f"{alias.name} as {alias.asname}")
                else:
                    self.data["imports"].append(alias.name)
                # 实际导入模块
                try:
                    self.exec_globals[alias.asname or alias.name] = importlib.import_module(alias.name)
                except ModuleNotFoundError as e:
                    raise ModuleNotFoundError(f"Module {alias.name} not found. Please install it and try again.") from e
        elif isinstance(node, ast.ImportFrom):
            try:
                imported_module = importlib.import_module(node.module)
                for alias in node.names:
                    if alias.asname:
                        self.data["imports"].append((node.module, f"{alias.name} as {alias.asname}"))
                    else:
                        self.data["imports"].append((node.module, alias.name))
                    self.exec_globals[alias.name] = getattr(imported_module, alias.name)
            except ModuleNotFoundError:
                raise ModuleNotFoundError(f"Module {node.module} not found. Please install it and try again")

    def parse_functions(self, node: ast.FunctionDef) -> None:
        """
        Extracts "functions" from the code.
        """
        compiled_func = compile(ast.Module(body=[node], type_ignores=[]), "<string>", "exec")
        exec(compiled_func, self.exec_globals, self.exec_locals)

    def parse_classes(self, node: ast.ClassDef) -> None:
        compiled_class = compile(ast.Module(body=[node], type_ignores=[]), "<string>", "exec")
        exec(compiled_class, self.exec_globals, self.exec_locals)
        self.exec_globals[node.name] = self.exec_locals[node.name]

    def parse_global_vars(self, node: ast.Assign) -> None:
        """
        Extracts global variables from the code.
        """
        global_var = {
            "targets": [t.id if hasattr(t, "id") else ast.dump(t) for t in node.targets],
            "value": ast.unparse(node.value),
        }
        if isinstance(node.value, ast.Constant):
            for one in global_var["targets"]:
                self.exec_globals[one] = global_var["value"]

    def exec_method(self, method_name: str, *args, **kwargs):
        """
        Executes the method with the provided arguments and keyword arguments.
        """
        method = self.exec_locals.get(method_name)
        if not method:
            raise AttributeError(f"Method {method_name} not found.")
        return method(*args, **kwargs)

    def init_class(self, class_name: str, *args, **kwargs):
        """
        Initializes the class with the provided arguments and keyword arguments.
        """
        class_ = self.exec_globals.get(class_name)
        if not class_:
            raise AttributeError(f"Class {class_name} not found.")
        return class_(*args, **kwargs)