import ast
import builtins
import io
import json
import sys

ALLOWED_MODULES = {
    "math",
    "random",
    "numpy",
    "sympy",
    "matplotlib",
    "scipy",
    "sklearn",
}
DENIED_MODULES = {"importlib", "os", "sys", "subprocess", "ctypes"}
# [P0 安全加固] 运行时可用内置函数名单。已移除 type/dir：
# type(obj) 能直接拿到类对象并沿 __mro__ 走到任意子类（逃逸起点），dir/id 用于探测对象结构。
# 静态扫描已拦下这些名字，运行时同步收口，避免整条防线只依赖单侧检查。
ALLOWED_BUILTINS = {
    "abs",
    "all",
    "any",
    "bool",
    "callable",
    "chr",
    "complex",
    "dict",
    "divmod",
    "enumerate",
    "float",
    "hash",
    "hex",
    "id",
    "int",
    "isinstance",
    "issubclass",
    "iter",
    "len",
    "list",
    "map",
    "max",
    "min",
    "next",
    "oct",
    "ord",
    "pow",
    "range",
    "repr",
    "reversed",
    "round",
    "set",
    "slice",
    "sorted",
    "str",
    "sum",
    "tuple",
    "zip",
    "print",
}
# [P0 安全加固] 运行时显式拒绝名单：即便静态扫描漏网，调用时也会抛错而非放行
DANGEROUS_BUILTINS = {
    "open",
    "eval",
    "exec",
    "compile",
    "getattr",
    "setattr",
    "delattr",
    "vars",
    "globals",
    "locals",
    "breakpoint",
    "input",
}

# AST 安全扫描器：在代码执行前进行静态分析，拦截绕过运行时限制的恶意代码
BANNED_MODULES_AST = {
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
BANNED_FUNCTIONS_AST = {
    "eval",
    "exec",
    "open",
    "compile",
    "globals",
    "locals",
    "__import__",
    # [P0 安全加固] 反射类工具：可用 getattr(f, "__globals__") 拿到模块命名空间后逃逸
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

# [P0 安全加固] 与 sandbox_security.CodeSecurityScanner 保持同一套规则。
# 本子进程是独立脚本（打包环境下不保证能 import mathlab），因此规则必须自带一份；
# 父进程 SandboxProcess.run_code() 已先用强扫描器拦一道，这里是最后一道防线。
BANNED_ATTRIBUTES_AST = {
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

# [P0 安全加固] 连"被引用"都禁止的名字（`f = open` 后再调用可绕过调用点检查）
DANGEROUS_REFERENCES_AST = {
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

# [P0 安全加固] 含 "__" 的字符串常量的放行名单（取不到任何对象，但用户代码会写）
SAFE_DUNDER_STRINGS = {
    "__main__",
    "__name__",
    "__init__",
    "__all__",
    "__doc__",
    "__future__",
}


def _scan_code_safety(code_string):
    """AST 安全扫描：在执行前检测危险模块导入和函数调用"""
    try:
        tree = ast.parse(code_string)
    except SyntaxError as e:
        return False, f"语法错误: {e}"

    errors = []

    class SecurityVisitor(ast.NodeVisitor):
        def visit_Import(self, node):
            for alias in node.names:
                base_module = alias.name.split(".")[0]
                if base_module in BANNED_MODULES_AST:
                    errors.append(f"安全拦截: 禁止导入模块 '{alias.name}'")
            self.generic_visit(node)

        def visit_ImportFrom(self, node):
            if node.module:
                base_module = node.module.split(".")[0]
                if base_module in BANNED_MODULES_AST:
                    errors.append(f"安全拦截: 禁止从 '{node.module}' 导入")
            self.generic_visit(node)

        def visit_Call(self, node):
            if isinstance(node.func, ast.Name):
                if node.func.id in BANNED_FUNCTIONS_AST:
                    errors.append(f"安全拦截: 禁止调用高危函数 '{node.func.id}()'")
            elif isinstance(node.func, ast.Attribute):
                attr_name = node.func.attr
                if attr_name in BANNED_FUNCTIONS_AST or attr_name.startswith("__"):
                    errors.append(f"安全拦截: 禁止通过属性访问 '{attr_name}'")
            self.generic_visit(node)

        def visit_Attribute(self, node):
            # [P0 安全加固] 封掉全部 dunder 属性访问：固定名单会被 __loader__/__reduce__
            # 等未列出的属性绕过，而数学代码不会写 obj.__xxx__，误伤面为零
            attr = node.attr
            if attr in BANNED_ATTRIBUTES_AST or (attr.startswith("__") and attr.endswith("__")):
                errors.append(f"安全拦截: 禁止访问危险属性 '{attr}'")
            self.generic_visit(node)

        def visit_Name(self, node):
            # [P0 安全加固] 拦截 __builtins__[...] 之类的 dunder 名字引用，
            # 以及"先取引用后调用"的危险内置函数（只拦读取，允许当变量名赋值）
            if node.id.startswith("__") and node.id.endswith("__"):
                errors.append(f"安全拦截: 禁止引用危险名字 '{node.id}'")
            elif isinstance(node.ctx, ast.Load) and node.id in DANGEROUS_REFERENCES_AST:
                errors.append(f"安全拦截: 禁止引用危险函数 '{node.id}'")
            self.generic_visit(node)

        def visit_Constant(self, node):
            # [P0 安全加固] "__imp"+"ort__" 这类拼接可以绕过名字检查，按内容拦
            if isinstance(node.value, str) and "__" in node.value and node.value not in SAFE_DUNDER_STRINGS:
                errors.append(f"安全拦截: 禁止使用含 '__' 的字符串常量 {node.value!r}")
            self.generic_visit(node)

    SecurityVisitor().visit(tree)

    if errors:
        return False, "\n".join(errors)
    return True, "安全"


def restricted_import(name, *args, **kwargs):
    base = name.split(".")[0]
    if base in DENIED_MODULES:
        raise ImportError(f"Module '{name}' is strictly forbidden")
    if base not in ALLOWED_MODULES:
        raise ImportError(f"Module '{name}' is not allowed")
    return __import__(name, *args, **kwargs)


def forbidden_func(name):
    def wrapper(*args, **kwargs):
        raise RuntimeError(f"Function '{name}' is not allowed in sandbox")

    return wrapper


# Initialize safe environment
safe_builtins_dict = {name: getattr(builtins, name) for name in ALLOWED_BUILTINS}
safe_builtins_dict["__import__"] = restricted_import
for func_name in DANGEROUS_BUILTINS:
    safe_builtins_dict[func_name] = forbidden_func(func_name)

safe_globals = {
    "__builtins__": safe_builtins_dict,
    "__name__": "__main__",
}


def execute_code(code):
    # [安全修复] 在执行前先进行 AST 安全扫描，拦截恶意代码
    is_safe, safety_error = _scan_code_safety(code)
    if not is_safe:
        return {"success": False, "output": "", "error": safety_error}

    output_buffer = io.StringIO()

    def safe_print(*args, **kwargs):
        kwargs.setdefault("file", output_buffer)
        builtins.print(*args, **kwargs)

    safe_globals["__builtins__"]["print"] = safe_print

    try:
        # Parse AST to handle expressions automatically like a REPL
        tree = ast.parse(code, mode="exec")
        if not tree.body:
            return {"success": True, "output": "", "error": ""}

        last_node = tree.body[-1]

        if isinstance(last_node, ast.Expr):
            # If the last statement is an expression, evaluate it and print its repr
            # First, execute everything except the last node
            tree.body = tree.body[:-1]
            if tree.body:
                exec(compile(tree, "<string>", "exec"), safe_globals)

            # Then evaluate the last expression
            val = eval(
                compile(ast.Expression(last_node.value), "<string>", "eval"),
                safe_globals,
            )
            if val is not None:
                builtins.print(repr(val), file=output_buffer)
        else:
            # Execute the whole thing
            exec(compile(tree, "<string>", "exec"), safe_globals)

        output = output_buffer.getvalue()
        return {"success": True, "output": output, "error": ""}
    except BaseException as e:
        output = output_buffer.getvalue()
        return {"success": False, "output": output, "error": str(e)}


def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            req = json.loads(line)
            code = req.get("code", "")
            res = execute_code(code)
            out_str = json.dumps(res) + "\n"
            sys.stdout.write(out_str)
            sys.stdout.flush()
        except BaseException as e:
            sys.stdout.write(json.dumps({"success": False, "output": "", "error": str(e)}) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
