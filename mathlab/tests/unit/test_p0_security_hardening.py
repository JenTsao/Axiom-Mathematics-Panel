"""P0 安全加固的回归测试。

这里每一条用例都对应一个**此前实测可通**的绕过路径（在加固前的环境里能真的执行代码），
不是臆想的攻击面。目的有两个：

1. 证明防线确实生效；
2. 防止将来有人为了"沙箱太严"而把规则改回去时无声无息地重新打开漏洞。

覆盖的四处加固：
- ``mathlab/core/sandbox_security.py``  —— 强扫描器补 dunder 属性 / 危险名字 / 字符串拼接规则
- ``mathlab/core/sandbox.py``           —— 子进程执行前接入强扫描器（此前完全不扫）
- ``mathlab/core/sandbox_script.py``    —— 子进程内的弱化副本与强扫描器对齐
- ``mathlab/core/expression_guard.py``  —— sympify / parse_expr 的表达式 RCE
- ``mathlab/core/octave_bridge.py``     —— 主进程 eval/exec 前加扫描
- ``mathlab/core/jupyter_manager.py``   —— 硬编码 token、通配 CORS、关闭 XSRF
"""

import json
import sys
import urllib.error
import urllib.request

import pytest

from mathlab.core.sandbox_security import is_code_safe

# ── 加固前实测可通的绕过写法 ──────────────────────────────────────────────────
# 每条都是"先取引用、再调用"或"字符串拼接"这类只检查调用点拦不住的形式
ESCAPE_SNIPPETS = [
    pytest.param("sc = (1).__class__.__mro__[1].__subclasses__\nsubs = sc()", id="两步式-subclasses"),
    pytest.param("g = print.__globals__\nsysmod = g['sys']", id="两步式-globals"),
    pytest.param("os = getattr(print, '__globals__')['os']", id="getattr-取-globals"),
    pytest.param("os = __builtins__['__imp'+'ort__']('os')", id="字符串拼接-import"),
    pytest.param("f = open\nprint(f('/etc/passwd'))", id="裸引用-open"),
    pytest.param("import os\nprint(os.getcwd())", id="直接导入-os"),
    pytest.param("(1).__class__.__bases__[0].__subclasses__()", id="经典-mro-链"),
    pytest.param("os = vars()['__builtins__']", id="vars-取-builtins"),
    pytest.param("breakpoint()", id="breakpoint-进-pdb"),
    pytest.param("os = __loader__", id="dunder-名字引用"),
    pytest.param("t = type\nC = t('C', (object,), {})", id="裸引用-type"),
    pytest.param("import importlib\nm = importlib.import_module('os')", id="importlib-间接"),
]

# 必须继续放行的合法代码（收紧规则不能把正常数学计算打死）
LEGIT_SNIPPETS = [
    pytest.param("import numpy as np\nA = np.eye(3)\nprint(A @ A)", id="numpy-矩阵乘"),
    pytest.param("x = 1 + 2\nprint(x)", id="四则运算"),
    pytest.param("def f(a, b):\n    return a**2 + b\nprint(f(2, 3))", id="函数定义"),
    pytest.param("import sympy\nprint(sympy.integrate(x**2, (x, 0, 1)))", id="sympy-积分"),
    pytest.param("import math\nprint(math.factorial(10))", id="math-阶乘"),
    pytest.param("class Foo:\n    def __init__(self):\n        self.v = 1\nprint(Foo().v)", id="类与-init"),
    pytest.param("s = '__main__'\nprint(s)", id="main-字符串放行"),
    pytest.param("d = {'a': 1}\nprint(d['a'])", id="字典下标"),
]


@pytest.mark.unit
class TestScannerBypassesBlocked:
    """强扫描器必须拦住每一条已知绕过路径。"""

    @pytest.mark.parametrize("code", ESCAPE_SNIPPETS)
    def test_escape_snippet_rejected(self, code):
        safe, msg = is_code_safe(code)
        assert not safe, "绕过路径未被拦截: %r" % code
        assert msg and msg != "安全"


@pytest.mark.unit
class TestScannerKeepsLegitCode:
    """收紧规则后合法数学代码仍须通过（避免"安全但不可用"）。"""

    @pytest.mark.parametrize("code", LEGIT_SNIPPETS)
    def test_legit_code_accepted(self, code):
        safe, msg = is_code_safe(code)
        assert safe, "合法代码被误拦: %s" % msg


@pytest.mark.unit
class TestChildScannerParity:
    """子进程内的扫描副本必须与强扫描器同判。

    ``sandbox_script.py`` 是独立脚本（打包环境不保证能 import mathlab），自带一份规则；
    历史上这份副本缺 dunder 属性与名字检查，是"两套机制没串联"的实际漏洞来源。
    """

    @pytest.mark.parametrize("code", ESCAPE_SNIPPETS)
    def test_child_rejects_what_parent_rejects(self, code):
        from mathlab.core.sandbox_script import _scan_code_safety

        safe, _msg = _scan_code_safety(code)
        assert not safe, "子进程副本比父进程宽: %r" % code

    @pytest.mark.parametrize("code", LEGIT_SNIPPETS)
    def test_child_accepts_legit(self, code):
        from mathlab.core.sandbox_script import _scan_code_safety

        safe, msg = _scan_code_safety(code)
        assert safe, "子进程副本误拦合法代码: %s" % msg

    def test_child_runtime_builtins_dropped_type(self):
        """type/dir 已从运行时内置名单移除：静态漏网时也拿不到类对象。"""
        from mathlab.core.sandbox_script import ALLOWED_BUILTINS

        assert "type" not in ALLOWED_BUILTINS
        assert "dir" not in ALLOWED_BUILTINS
        assert "len" in ALLOWED_BUILTINS and "print" in ALLOWED_BUILTINS


@pytest.mark.unit
class TestSandboxProcessGate:
    """SandboxProcess.run_code 必须在派生子进程之前就拒绝危险代码。"""

    def test_dangerous_code_never_spawns_process(self, monkeypatch):
        from mathlab.core.sandbox import SandboxProcess

        sandbox = SandboxProcess()

        def _boom(*args, **kwargs):
            raise AssertionError("危险代码不应该走到派生子进程")

        monkeypatch.setattr(sandbox, "_start_process", _boom)

        result = sandbox.run_code("import os\nprint(os.listdir('/'))")
        assert result["success"] is False
        assert "安全拦截" in result["error"]

    def test_legit_code_still_runs_in_subprocess(self):
        """真实子进程执行合法 numpy 代码仍然工作（防止把功能打死）。"""
        from mathlab.core.sandbox import SandboxProcess

        sandbox = SandboxProcess(max_time_seconds=60)
        try:
            result = sandbox.run_code("import numpy as np\nprint((np.eye(2) * 3).tolist())")
            assert result["success"] is True, result["error"]
            assert "[[3.0, 0.0], [0.0, 3.0]]" in result["output"]
        finally:
            sandbox.terminate()


@pytest.mark.unit
class TestExpressionGuard:
    """表达式解析三层层：文本闸门 / 受限命名空间 / 结果类型。"""

    PAYLOADS = [
        pytest.param("__import__('os').getpid()", id="sympify-经典注入"),
        pytest.param("x.__class__", id="属性取类"),
        pytest.param("Integer.__subclasses__()", id="子类枚举"),
        pytest.param("Symbol('a').__class__.__bases__", id="dunder-链"),
        pytest.param("open('/etc/passwd').read()", id="方法调用读文件"),
        pytest.param("getattr(x, 'real')", id="getattr-反射"),
        pytest.param("__builtins__", id="裸-builtins"),
    ]

    @pytest.mark.parametrize("expr", PAYLOADS)
    def test_payload_refused(self, expr):
        from mathlab.core.expression_guard import is_expression_safe, safe_parse_expr

        safe, _reason = is_expression_safe(expr)
        assert not safe, "文本闸门漏过: %r" % expr
        with pytest.raises(ValueError):
            safe_parse_expr(expr, local_dict={"x": __import__("sympy").Symbol("x")})

    def test_restricted_global_dict_has_no_builtins(self):
        """受限命名空间里不能有 builtins / 子模块 / 可再次打开执行面的入口。"""
        import types

        from mathlab.core.expression_guard import restricted_global_dict

        gd = restricted_global_dict()
        assert "__builtins__" not in gd
        assert "__import__" not in gd
        assert "parse_expr" not in gd and "sympify" not in gd
        assert not any(isinstance(v, types.ModuleType) for v in gd.values())

    def test_global_dict_resists_sympy_mutation(self):
        """parse_expr 会往传入的 global_dict 里回写 __builtins__（实测）。

        因此每次解析必须拿到一份**新字典**，否则第二层限制会在第一次调用后
        被悄悄解除，后续表达式又能碰到 builtins。
        """
        import sympy

        from mathlab.core.expression_guard import (
            restricted_global_dict,
            safe_parse_expr,
        )

        x = sympy.Symbol("x")
        before = set(restricted_global_dict())

        safe_parse_expr("sin(x) + x**2", local_dict={"x": x})
        safe_parse_expr("integrate(x**2, x)", local_dict={"x": x})

        after = restricted_global_dict()
        assert "__builtins__" not in after, "受限命名空间被 sympy 回写的 builtins 污染了"
        assert set(after) == before

    def test_legit_math_still_parses(self):
        import sympy

        from mathlab.core.expression_guard import safe_parse_expr, safe_sympify

        x = sympy.Symbol("x")
        assert str(safe_parse_expr("sin(x) + x**2", local_dict={"x": x})) == "x**2 + sin(x)"
        assert isinstance(safe_parse_expr("Eq(x, 1)", local_dict={"x": x}), sympy.Eq)
        # Matrix 不是 Basic，结果校验不能粗暴到把它误杀
        assert isinstance(safe_parse_expr("Matrix([[1,2],[3,4]])", local_dict={"x": x}), sympy.Matrix)
        # solve() 返回 list，同样不能被误杀
        assert str(safe_parse_expr("solve(x**2-1, x)", local_dict={"x": x})) == "[-1, 1]"
        assert str(safe_sympify("sqrt(2)*pi")) == "sqrt(2)*pi"

    def test_caret_operator_preserved(self):
        """老工程文件写 `x^2`：sympify 一直支持，加固后不能倒退。

        sympy 1.14 的 standard_transformations 已不含 ^ -> ** 的转换，
        所以 expression_guard 默认必须补 convert_xor。
        """
        import sympy

        from mathlab.core.expression_guard import safe_parse_expr

        x, y = sympy.symbols("x y")
        expr = safe_parse_expr("x^2 + y^2 - 1", local_dict={"x": x, "y": y})
        assert "*" in str(expr) or "**" in str(expr)
        assert "^" not in str(expr)


@pytest.mark.unit
class TestProjectFileRceClosed:
    """.mathlab 工程文件里的表达式不得执行代码（用落地文件做可观测断言）。"""

    def test_function_plot_expression_not_executed(self, tmp_path):
        marker = tmp_path / "PWNED.txt"
        payload = "open(%r, 'w').write('x')" % str(marker)

        from mathlab.core.models import FunctionPlot

        obj = FunctionPlot.deserialize(
            {"id": "f1", "name": "evil", "expression": payload, "x_range": [-1, 1], "num_points": 10}
        )
        obj._generate_points()

        assert len(obj.points_data) == 0
        assert not marker.exists()

    def test_implicit_plot_expression_not_executed(self, tmp_path):
        marker = tmp_path / "PWNED2.txt"
        payload = "open(%r, 'w').write('x')" % str(marker)

        from mathlab.core.models import ImplicitPlot

        obj = ImplicitPlot.deserialize({"id": "i1", "name": "evil", "expression": payload})
        obj._generate_points()
        assert not marker.exists()

    def test_constraint_expression_not_executed(self, tmp_path):
        marker = tmp_path / "PWNED3.txt"
        payload = "open(%r, 'w').write('x')" % str(marker)

        from mathlab.core.geometry_engine import _compile_constraint_func

        assert _compile_constraint_func(payload, ("x", "y")) is None
        assert not marker.exists()

    def test_cas_provider_expression_not_executed(self, tmp_path):
        marker = tmp_path / "PWNED4.txt"
        payload = "open(%r, 'w').write('x')" % str(marker)

        from mathlab.core.cas_provider import CASProvider

        cas = CASProvider()
        assert cas.parse_expression(payload) is None
        assert not marker.exists()

    def test_legit_project_file_still_loads(self):
        """合法函数曲线在加固后仍能出点（防止安全改动把功能改坏）。"""
        from mathlab.core.models import FunctionPlot

        obj = FunctionPlot("f2", "sin", "sin(x)", (-3, 3), 30)
        assert len(obj.points_data) == 30


@pytest.mark.unit
class TestOctaveBridgeGate:
    """octave 桥是主进程 eval/exec，必须在执行前扫描翻译后的代码。"""

    @pytest.fixture
    def bridge(self):
        from mathlab.core.octave_bridge import OctaveBridge

        return OctaveBridge()

    @pytest.mark.parametrize(
        "code",
        [
            pytest.param("np.__builtins__['__import__']('os')", id="通过-np-取-builtins"),
            pytest.param("np.__config__", id="dunder-属性"),
            pytest.param("print.__globals__", id="函数-globals"),
            pytest.param("__import__('os').getpid()", id="直接-import"),
            pytest.param("getattr(np, 'zeros')", id="getattr-反射"),
        ],
    )
    def test_escape_refused(self, bridge, code):
        from mathlab.core.octave_bridge import OctaveBridgeError

        with pytest.raises(OctaveBridgeError) as exc:
            bridge.evaluate(code)
        assert "安全拦截" in str(exc.value)

    @pytest.mark.parametrize(
        "code,kind",
        [
            pytest.param("A = [1 2; 3 4]", None, id="矩阵字面量"),
            pytest.param("sqrt(2)", float, id="标量函数"),
            pytest.param("x = linspace(0, 1, 5)", None, id="linspace"),
            pytest.param("zeros(2, 3)", None, id="zeros"),
        ],
    )
    def test_legit_octave_still_runs(self, bridge, code, kind):
        import numpy as np

        result = bridge.evaluate(code)
        if kind is float:
            assert isinstance(result, kind)
        else:
            assert result is not None or isinstance(result, (np.ndarray, type(None)))

    def test_matrix_multiply_still_works(self, bridge):
        import numpy as np

        bridge.evaluate("A = [1 2; 3 4]")
        result = bridge.evaluate("A * A")
        assert np.array_equal(np.asarray(result), np.array([[7, 10], [15, 22]]))


@pytest.mark.unit
class TestJupyterManagerHardening:
    """内嵌 Jupyter 服务的三个配置缺陷。"""

    def test_token_is_random_per_instance(self):
        from mathlab.core.jupyter_manager import JupyterManager

        a, b = JupyterManager(), JupyterManager()
        assert a._token != b._token, "令牌必须每次启动随机"
        assert a._token != "mathlab-embedded", "旧的硬编码令牌必须彻底失效"
        assert len(a._token) >= 32

    def test_server_args_drop_wildcard_cors_and_xsrf(self, monkeypatch):
        captured = {}

        class FakeProc:
            pid = 4242
            # start() 会派一个排空线程读 process.stdout；给 None 让它直接返回，
            # 否则线程里抛 AttributeError 会变成 pytest 的未处理线程异常告警
            stdout = None

            def poll(self):
                return None

            def wait(self, timeout=None):
                return 0

            def terminate(self):
                pass

            def kill(self):
                pass

        def fake_popen(cmd, *args, **kwargs):
            captured["cmd"] = cmd
            return FakeProc()

        import mathlab.core.jupyter_manager as jm

        monkeypatch.setattr(jm.subprocess, "Popen", fake_popen)
        # 就绪探测会真的连端口，这里直接放行，只检查参数
        monkeypatch.setattr(jm.JupyterManager, "_wait_for_ready", lambda self, timeout: True)

        mgr = jm.JupyterManager()
        assert mgr.start(timeout=5) is True
        cmd = captured["cmd"]

        joined = " ".join(cmd)
        assert "--ServerApp.allow_origin" not in cmd, "不允许通配 CORS"
        assert "disable_check_xsrf" not in joined, "不允许关闭 XSRF 校验"
        idx = cmd.index("--ServerApp.token")
        assert cmd[idx + 1] == mgr._token and cmd[idx + 1] != "mathlab-embedded"

    def test_readiness_probe_sends_token(self, monkeypatch):
        """jupyter_server 2.x 的 /api/status 需要认证：匿名探测拿不到 200 会卡启动。"""
        import mathlab.core.jupyter_manager as jm

        seen = {}

        class FakeResp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(req, timeout=None):
            seen["headers"] = dict(req.headers)
            return FakeResp()

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        mgr = jm.JupyterManager()
        assert mgr._wait_for_ready(timeout=5) is True
        assert "token" in str(seen["headers"].get("Authorization", ""))


def _lab_available() -> bool:
    """花几秒确认 ``jupyter lab`` 子命令真的可用。

    ``jupyterlab`` 包能被 import，不代表 ``jupyter-lab`` 入口点已注册
    （本机就是这种状态：jupyter 直接报 "Jupyter command `jupyter-lab` not found"）。
    少了这一步，夹具会白等满整个启动超时。
    """
    import subprocess

    try:
        proc = subprocess.run(  # nosec B603 - 固定 argv，只查版本号
            [sys.executable, "-m", "jupyter", "lab", "--version"],
            capture_output=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


@pytest.fixture(scope="class")
def server():
    """真起一次内嵌服务；环境不具备条件时快速 skip，而不是空等超时。

    定义在模块级：类作用域夹具写成实例方法时，pytest 会告警
    "实例属性对测试方法不可见"（每个用例是新实例）。
    """
    import mathlab.core.jupyter_manager as jm

    try:
        import jupyterlab  # noqa: F401
    except ImportError:
        pytest.skip("未安装 jupyterlab")

    if not _lab_available():
        pytest.skip("该环境未注册 jupyter-lab 子命令，无法做真实服务验证")

    mgr = jm.JupyterManager()
    if not mgr.start(timeout=45):
        mgr.stop()
        pytest.skip("JupyterLab 服务未能启动")
    yield mgr
    mgr.stop()


@pytest.mark.integration
@pytest.mark.slow
class TestJupyterServerAuthReal:
    """真起一次 Jupyter 服务，确认收紧后既挡住外部请求、又不破坏合法流程。

    标 slow：需要拉起完整 JupyterLab 进程。
    """

    def _base(self, mgr):
        return "http://127.0.0.1:%d" % mgr.port

    def _get(self, url, headers=None):
        req = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310 - 只连本用例自启的 127.0.0.1
                return resp.status
        except urllib.error.HTTPError as exc:
            return exc.code

    def test_anonymous_status_denied(self, server):
        assert self._get(self._base(server) + "/api/status") in (401, 403)

    def test_tokenized_status_allowed(self, server):
        assert self._get(self._base(server) + "/api/status", {"Authorization": "token " + server._token}) == 200

    def test_wildcard_cors_gone(self, server):
        req = urllib.request.Request(self._base(server) + "/api/status", headers={"Origin": "http://evil.example"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310 - 同上，目标固定为 127.0.0.1
                acao = resp.headers.get("Access-Control-Allow-Origin")
        except urllib.error.HTTPError as exc:
            acao = exc.headers.get("Access-Control-Allow-Origin")
        assert acao != "*"

    def test_xsrf_enforced_but_legit_flow_works(self, server):
        """无 XSRF 头的 POST 必须被拒；带 cookie + XSRF 头的合法写盘必须成功。"""
        import http.cookiejar

        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        base = self._base(server)

        def call(path, method="GET", headers=None, data=None):
            req = urllib.request.Request(base + path, headers=headers or {}, data=data, method=method)
            try:
                with opener.open(req, timeout=20) as resp:
                    return resp.status
            except urllib.error.HTTPError as exc:
                return exc.code

        # 先按内嵌视图的方式带 token 打开页面，取得会话 cookie
        assert call("/lab?token=" + server._token) in (200, 302)
        xsrf = next((c.value for c in jar if c.name == "_xsrf"), None)

        payload = json.dumps(
            {"type": "notebook", "content": {"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}}
        ).encode()
        headers = {"Content-Type": "application/json"}

        # 只有 cookie、没有 XSRF 头 -> 必须被拒（证明校验真的开着）
        assert call("/api/contents/p0_probe.ipynb", "POST", headers, payload) in (401, 403)

        # 补齐 XSRF 头 -> 合法流程仍然可用（证明没把内嵌界面写坏）
        assert xsrf, "登录页未下发 _xsrf cookie，无法验证合法流程"
        headers_with_xsrf = dict(headers, **{"X-XSRFToken": xsrf})
        status = call("/api/contents/p0_probe.ipynb", "POST", headers_with_xsrf, payload)
        assert str(status).startswith("2"), "内嵌 JupyterLab 的保存流程被收紧动作破坏: %s" % status
