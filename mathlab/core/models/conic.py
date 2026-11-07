import numpy as np

# C# 引擎导入期已自行降级（get_cs_geometry 返回 None）；此处保留兜底，
# 防止 utils 等上游依赖异常时击穿本模块。
try:
    from mathlab.core.cs_geometry_engine import get_cs_geometry
except Exception:  # pragma: no cover - 取决于本机依赖环境
    get_cs_geometry = None

from mathlab.core.models.base import GeometricObject


def _build_general_quadratic_latex(A, B, C, D, E, F, threshold=1e-10):
    """将一般二次方程系数 Ax²+Bxy+Cy²+Dx+Ey+F=0 渲染为 LaTeX 字符串。

    用于圆锥曲线（椭圆、双曲线）在发生旋转后展开坐标旋转公式得到的
    通用二次形式。绝对值小于 threshold 的系数视为 0 略去。
    """

    def fmt_num(v):
        """将 |v| 格式化为可读字符串，整数省略小数部分。"""
        av = abs(v)
        if abs(av - round(av)) < threshold:
            return str(int(round(av)))
        return f"{av:.4g}"

    coeffs = [(A, "x^2"), (B, "xy"), (C, "y^2"), (D, "x"), (E, "y"), (F, "")]
    items = []
    for c, var in coeffs:
        if abs(c) < threshold:
            continue
        coef_str = fmt_num(c)
        sign = "+" if c >= 0 else "-"
        items.append((sign, coef_str, var))

    if not items:
        return "0 = 0"

    parts = []
    for i, (sign, coef_str, var) in enumerate(items):
        # 系数为 1 时省略数字
        if var and coef_str == "1":
            content = var
        elif var:
            content = f"{coef_str}{var}"
        else:
            content = coef_str

        if i == 0:
            parts.append(content if sign == "+" else f"-{content}")
        else:
            # 不在前面加空格，由 join(' ') 统一处理分隔
            parts.append(f"{sign} {content}")

    return " ".join(parts) + " = 0"


class Ellipse(GeometricObject):
    """椭圆：支持中心点、长轴、短轴定义"""

    def __init__(self, obj_id, name, center_id, a=2.0, b=1.0, rotation=0):
        super().__init__(obj_id, name, "Ellipse")
        self.center_id = center_id
        self.a = a  # 半长轴
        self.b = b  # 半短轴
        self.rotation = rotation  # 旋转角度（弧度）
        self.depends_on = [center_id]

    def _generate_ellipse_points(self, cx, cy, a, b, rotation, num_points=200):
        t = np.linspace(0, 2 * np.pi, num_points)
        x = cx + a * np.cos(t) * np.cos(rotation) - b * np.sin(t) * np.sin(rotation)
        y = cy + a * np.cos(t) * np.sin(rotation) + b * np.sin(t) * np.cos(rotation)
        return list(zip(x.tolist(), y.tolist()))

    def update_coordinates(self, engine):
        center = engine.objects.get(self.center_id)
        if center:
            cx = center.coordinates["x"]
            cy = center.coordinates["y"]
            self.coordinates = {
                "cx": cx,
                "cy": cy,
                "a": self.a,
                "b": self.b,
                "rotation": self.rotation,
                "points": self._generate_ellipse_points(cx, cy, self.a, self.b, self.rotation),
            }

    def to_latex(self):
        cx = self.coordinates.get("cx", 0)
        cy = self.coordinates.get("cy", 0)
        if self.rotation == 0:
            return rf"\frac{{(x-{cx})^2}}{{{self.a}^2}} + \frac{{(y-{cy})^2}}{{{self.b}^2}} = 1"
        # 旋转 θ 后，将标准方程展开为一般二次方程 Ax²+Bxy+Cy²+Dx+Ey+F=0
        # 推导：令 u=x-cx, v=y-cy，则 x'=u·cosθ+v·sinθ, y'=-u·sinθ+v·cosθ
        cos_t = np.cos(self.rotation)
        sin_t = np.sin(self.rotation)
        a2 = self.a**2
        b2 = self.b**2
        A = cos_t**2 / a2 + sin_t**2 / b2
        B = 2 * sin_t * cos_t * (1 / a2 - 1 / b2)
        C = sin_t**2 / a2 + cos_t**2 / b2
        D = -2 * A * cx - B * cy
        E = -B * cx - 2 * C * cy
        F = A * cx**2 + B * cx * cy + C * cy**2 - 1
        return _build_general_quadratic_latex(A, B, C, D, E, F)

    def serialize(self):
        data = super().serialize()
        data["center_id"] = self.center_id
        data["a"] = self.a
        data["b"] = self.b
        data["rotation"] = self.rotation
        if "coordinates" in data and "points" in data["coordinates"]:
            data["coordinates"] = {k: v for k, v in data["coordinates"].items() if k != "points"}
        return data


class Hyperbola(GeometricObject):
    """双曲线：支持中心点、实轴、虚轴定义"""

    def __init__(self, obj_id, name, center_id, a=1.0, b=1.0, rotation=0):
        super().__init__(obj_id, name, "Hyperbola")
        self.center_id = center_id
        self.a = a  # 实半轴
        self.b = b  # 虚半轴
        self.rotation = rotation  # 旋转角度（弧度）
        self.depends_on = [center_id]

    def update_coordinates(self, engine):
        center = engine.objects.get(self.center_id)
        if center:
            self.coordinates = {
                "cx": center.coordinates["x"],
                "cy": center.coordinates["y"],
                "a": self.a,
                "b": self.b,
                "rotation": self.rotation,
            }

    def to_latex(self):
        cx = self.coordinates.get("cx", 0)
        cy = self.coordinates.get("cy", 0)
        if self.rotation == 0:
            return rf"\frac{{(x-{cx})^2}}{{{self.a}^2}} - \frac{{(y-{cy})^2}}{{{self.b}^2}} = 1"
        # 旋转 θ 后展开为一般二次方程。注意双曲线 a²/b² 前的符号相反。
        cos_t = np.cos(self.rotation)
        sin_t = np.sin(self.rotation)
        a2 = self.a**2
        b2 = self.b**2
        A = cos_t**2 / a2 - sin_t**2 / b2
        B = 2 * sin_t * cos_t * (1 / a2 + 1 / b2)
        C = sin_t**2 / a2 - cos_t**2 / b2
        D = -2 * A * cx - B * cy
        E = -B * cx - 2 * C * cy
        F = A * cx**2 + B * cx * cy + C * cy**2 - 1
        return _build_general_quadratic_latex(A, B, C, D, E, F)

    def serialize(self):
        data = super().serialize()
        data["center_id"] = self.center_id
        data["a"] = self.a
        data["b"] = self.b
        data["rotation"] = self.rotation
        if "coordinates" in data and "points" in data["coordinates"]:
            data["coordinates"] = {k: v for k, v in data["coordinates"].items() if k != "points"}
        return data


class Parabola(GeometricObject):
    """抛物线：支持顶点、焦点或标准方程定义"""

    def __init__(self, obj_id, name, vertex_id, p=1.0, direction="up"):
        super().__init__(obj_id, name, "Parabola")
        self.vertex_id = vertex_id
        self.p = p  # 焦距参数
        self.direction = direction  # 'up', 'down', 'left', 'right'
        self.depends_on = [vertex_id]

    def update_coordinates(self, engine):
        vertex = engine.objects.get(self.vertex_id)
        if vertex:
            self.coordinates = {
                "vx": vertex.coordinates["x"],
                "vy": vertex.coordinates["y"],
                "p": self.p,
                "direction": self.direction,
            }

    def to_latex(self):
        vx = self.coordinates.get("vx", 0)
        vy = self.coordinates.get("vy", 0)
        if self.direction in ["up", "down"]:
            sign = 1 if self.direction == "up" else -1
            return rf"(x-{vx})^2 = {4*self.p*sign}(y-{vy})"
        else:
            sign = 1 if self.direction == "right" else -1
            return rf"(y-{vy})^2 = {4*self.p*sign}(x-{vx})"

    def serialize(self):
        data = super().serialize()
        data["vertex_id"] = self.vertex_id
        data["p"] = self.p
        data["direction"] = self.direction
        if "coordinates" in data and "points" in data["coordinates"]:
            data["coordinates"] = {k: v for k, v in data["coordinates"].items() if k != "points"}
        return data


class ConicSection(GeometricObject):
    """一般圆锥曲线：通过一般方程 Ax²+Bxy+Cy²+Dx+Ey+F=0 定义"""

    def __init__(
        self,
        obj_id,
        name,
        A=1,
        B=0,
        C=1,
        D=0,
        E=0,
        F=-1,
        x_range=(-10, 10),
        y_range=(-10, 10),
    ):
        super().__init__(obj_id, name, "ConicSection")
        self.A = A
        self.B = B
        self.C = C
        self.D = D
        self.E = E
        self.F = F
        self.x_range = x_range
        self.y_range = y_range
        self.equation_str = f"{A}*x**2 + {B}*x*y + {C}*y**2 + {D}*x + {E}*y + {F}"
        self.points_data = []  # 存储离散点用于绘制

    def generate_points(self, num_points=500):
        """通过 C# 极速生成离散点，回退到矢量化隐函数求解"""
        try:
            cs_engine = get_cs_geometry() if get_cs_geometry is not None else None
            if cs_engine and cs_engine.is_available:
                pts = cs_engine.generate_conic_points(
                    self.A,
                    self.B,
                    self.C,
                    self.D,
                    self.E,
                    self.F,
                    self.x_range,
                    self.y_range,
                    num_points,
                )
                if pts is not None:
                    self.points_data = pts
                    self.coordinates = {"points": pts}
                    return pts

            x_vals = np.linspace(self.x_range[0], self.x_range[1], num_points)
            a_coeff = float(self.C)
            b_coeff = float(self.B) * x_vals + float(self.E)
            c_coeff = float(self.A) * x_vals**2 + float(self.D) * x_vals + float(self.F)

            discriminant = b_coeff**2 - 4 * a_coeff * c_coeff
            valid = discriminant >= 0

            points = []
            if a_coeff == 0:
                # 退化线性：y = -c / b（非零 b 处有效）
                linear_mask = valid & (np.abs(b_coeff) > 1e-10)
                if np.any(linear_mask):
                    y_vals = -c_coeff[linear_mask] / b_coeff[linear_mask]
                    in_range = (y_vals >= self.y_range[0]) & (y_vals <= self.y_range[1])
                    x_valid = x_vals[linear_mask][in_range]
                    y_valid = y_vals[in_range]
                    points = list(zip(x_valid.tolist(), y_valid.tolist()))
            else:
                sqrt_disc = np.sqrt(discriminant[valid])
                x_valid = x_vals[valid]
                bv = b_coeff[valid]
                y1 = (-bv + sqrt_disc) / (2 * a_coeff)
                y2 = (-bv - sqrt_disc) / (2 * a_coeff)

                in_range1 = (y1 >= self.y_range[0]) & (y1 <= self.y_range[1])
                in_range2 = (y2 >= self.y_range[0]) & (y2 <= self.y_range[1])

                points = list(zip(x_valid[in_range1].tolist(), y1[in_range1].tolist()))
                # 避免重复点（当 y1 ≈ y2 时）
                distinct = in_range2 & (np.abs(y2 - y1) > 1e-6)
                if np.any(distinct):
                    points += list(zip(x_valid[distinct].tolist(), y2[distinct].tolist()))

            self.points_data = points
            self.coordinates = {"points": points}
            return points
        except Exception as e:
            print(f"Error generating conic section points: {e}")
            return []

    def to_latex(self):
        terms = []
        if self.A != 0:
            terms.append(f"{self.A}x^2")
        if self.B != 0:
            terms.append(f"{self.B}xy")
        if self.C != 0:
            terms.append(f"{self.C}y^2")
        if self.D != 0:
            terms.append(f"{self.D}x")
        if self.E != 0:
            terms.append(f"{self.E}y")
        if self.F != 0:
            terms.append(f"{self.F}")
        return " + ".join(terms) + " = 0" if terms else "0 = 0"

    def serialize(self):
        data = super().serialize()
        data["A"] = self.A
        data["B"] = self.B
        data["C"] = self.C
        data["D"] = self.D
        data["E"] = self.E
        data["F"] = self.F
        data["x_range"] = self.x_range
        data["y_range"] = self.y_range
        data["equation_str"] = self.equation_str
        data["points_data"] = self.points_data
        return data

    @classmethod
    def deserialize(cls, data):
        obj = cls(
            data["id"],
            data["name"],
            data.get("A", 1),
            data.get("B", 0),
            data.get("C", 1),
            data.get("D", 0),
            data.get("E", 0),
            data.get("F", -1),
            data.get("x_range", (-10, 10)),
            data.get("y_range", (-10, 10)),
        )
        obj.coordinates = data.get("coordinates", {})
        obj.constraints = data.get("constraints", [])
        obj.depends_on = data.get("depends_on", [])
        obj.points_data = data.get("points_data", [])
        obj.equation_str = data.get("equation_str", "")
        return obj
