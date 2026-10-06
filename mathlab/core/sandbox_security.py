import ast
from typing import List, Tuple


class SecurityException(Exception):
    pass


class CodeSecurityScanner(ast.NodeVisitor):
    """
    基于 AST (抽象语法树) 的代码安全扫描器
    """

    # 黑名单：严禁在沙盒中导入的系统级和网络级模块
    BANNED_MODULES = {
        "os",
        "sys",
        "subprocess",
        "shutil",
        "socket",
        "urllib",
        "requests",
        "builtins",
        "multiprocessing",
        "threading",
        "pty",
        "ctypes",
        # [安全修复] 补充缺失的危险模块
        "io",
        "pickle",
        "marshal",
        "tempfile",
        "pathlib",
        "glob",
        "inspect",
        "importlib",
        "ast",
        "code",
        "codeop",
        "ptrace",
        "resource",
        "signal",
    }

    # 黑名单：严禁调用的高危内置函数
    BANNED_FUNCTIONS = {
        "eval",
        "exec",
        "open",
        "compile",
        "globals",
        "locals",
        "__import__",
        # [P0 安全加固] 反射类工具可以拿到对象的 __globals__/__class__，
        # 由于它们以普通函数名出现，dunder 属性规则拦不住，必须显式封禁
        "getattr",
        "setattr",
        "delattr",
        "vars",
        "dir",
        "breakpoint",
        "help",
        "input",
        "exit",
        "quit",
        "memoryview",
    }

    # [安全修复] 黑名单：严禁访问的危险属性（用于逃逸沙箱）
    BANNED_ATTRIBUTES = {
        "__subclasses__",
        "__mro__",
        "__bases__",
        "__class__",
        "__globals__",
        "__builtins__",
        "__code__",
        "__func__",
        "__dict__",
        "__module__",
    }

    # [P0 安全加固] 这些名字连"被引用"都不允许：先赋值给变量再调用即可绕过
    # visit_Call（`f = open` → `f('/etc/passwd')` 的第二个调用点看不出危险）
    DANGEROUS_REFERENCES = {
        "eval",
        "exec",
        "open",
        "compile",
        "globals",
        "locals",
        "__import__",
        "getattr",
        "setattr",
        "delattr",
        "vars",
        "dir",
        "breakpoint",
        "memoryview",
        "type",
    }

    # [P0 安全加固] visit_Constant 的白名单：这些 dunder 字面量本身取不到任何对象，
    # 但用户代码里确实会写（如 `if __name__ == "__main__"`），放行以免误伤
    SAFE_DUNDER_STRINGS = {
        "__main__",
        "__name__",
        "__init__",
        "__all__",
        "__doc__",
        "__future__",
    }

    def __init__(self) -> None:
        super().__init__()
        self.errors: List[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            base_module = alias.name.split(".")[0]
            if base_module in self.BANNED_MODULES:
                self.errors.append(f"安全拦截: 禁止导入模块 '{alias.name}'")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            base_module = node.module.split(".")[0]
            if base_module in self.BANNED_MODULES:
                self.errors.append(f"安全拦截: 禁止从 '{node.module}' 导入")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # 拦截诸如 eval(), exec() 等直接调用
        if isinstance(node.func, ast.Name):
            if node.func.id in self.BANNED_FUNCTIONS:
                self.errors.append(f"安全拦截: 禁止调用高危函数 '{node.func.id}()'")
            # [安全修复] 拦截 type() 内置函数，防止通过 type() 创建新类逃逸
            if node.func.id == "type":
                self.errors.append("安全拦截: 禁止调用 'type()' 函数")
        # [安全修复] 拦截通过属性访问绕过的调用，如 obj.__import__()
        elif isinstance(node.func, ast.Attribute):
            attr_name = node.func.attr
            if attr_name in self.BANNED_FUNCTIONS or attr_name.startswith("__"):
                self.errors.append(f"安全拦截: 禁止通过属性访问 '{attr_name}'")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """拦截危险属性访问。

        [P0 安全加固] 原来只比对固定的 BANNED_ATTRIBUTES 名单，攻击者换一个 dunder
        （__loader__ / __reduce__ / __getattribute__ …）即可绕过。改为封掉全部
        dunder 属性访问：数学代码不会用到 `obj.__xxx__`，误伤面为零。
        """
        attr = node.attr
        if attr in self.BANNED_ATTRIBUTES or (attr.startswith("__") and attr.endswith("__")):
            self.errors.append(f"安全拦截: 禁止访问危险属性 '{attr}'")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        """拦截危险名字的引用。

        [P0 安全加固] 原来只检查调用点，`f = open` 这种"先取引用后调用"完全放行。
        - dunder 名字（__builtins__ 等）：任何上下文都不许出现
        - DANGEROUS_REFERENCES：只拦读取（Load），用户把它们当变量名赋值不算攻击面
        """
        if node.id.startswith("__") and node.id.endswith("__"):
            self.errors.append(f"安全拦截: 禁止引用危险名字 '{node.id}'")
        elif isinstance(node.ctx, ast.Load) and node.id in self.DANGEROUS_REFERENCES:
            self.errors.append(f"安全拦截: 禁止引用危险函数 '{node.id}'")
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        """[P0 安全加固] 拦截拼接 dunder 名的字符串常量。

        把完整 dunder 拆成 "__imp" + "ort__" 可以绕过名字检查，
        因此凡是含 "__" 的字符串常量一律拒绝（允许少量无害 dunder 字面量）。
        """
        if isinstance(node.value, str) and "__" in node.value and node.value not in self.SAFE_DUNDER_STRINGS:
            self.errors.append(f"安全拦截: 禁止使用含 '__' 的字符串常量 {node.value!r}")
        self.generic_visit(node)


def is_code_safe(code_string: str) -> Tuple[bool, str]:
    """
    验证代码是否安全
    返回: (是否安全, 错误信息)
    """
    try:
        tree = ast.parse(code_string)
    except SyntaxError as e:
        return False, f"语法错误: {e}"

    scanner = CodeSecurityScanner()
    scanner.visit(tree)

    if scanner.errors:
        return False, "\n".join(scanner.errors)
    return True, "安全"
