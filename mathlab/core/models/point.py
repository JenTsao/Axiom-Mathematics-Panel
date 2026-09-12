from sympy import latex, symbols

from mathlab.core.models.base import GeometricObject


class Point(GeometricObject):
    # 将默认参数扩展为 x, y, z
    def __init__(self, obj_id, name, x=0, y=0, z=0):
        super().__init__(obj_id, name, "Point")
        self.coordinates = {"x": x, "y": y, "z": z}  # 新增 z
        # 符号表达式（z 维度，用于 3D 约束求解）延迟到首次访问时构造：
        # 每次创建点都调用 3 次 SymPy symbols() 会显著拖慢批量绘图/反序列化。
        self._symbolic_expr = None

    @property
    def symbolic_expr(self):
        """首次访问时才创建符号元组（仅供约束求解等场景使用）。"""
        if self._symbolic_expr is None:
            safe_name = self.name.replace("-", "_")
            self._symbolic_expr = (
                symbols(f"x_{safe_name}"),
                symbols(f"y_{safe_name}"),
                symbols(f"z_{safe_name}"),
            )
        return self._symbolic_expr

    @symbolic_expr.setter
    def symbolic_expr(self, value):
        self._symbolic_expr = value

    def update_coordinates(self, x=None, y=None, z=None):
        # 防御：引擎遍历依赖链时会以 update_coordinates(engine) 调用，
        # 此时首个位置参数是引擎实例而非坐标值，需直接忽略。
        if x is not None and hasattr(x, "objects") and hasattr(x, "dependencies"):
            return
        if x is not None:
            self.coordinates["x"] = x
        if y is not None:
            self.coordinates["y"] = y
        if z is not None:
            self.coordinates["z"] = z

    def to_latex(self):
        x = self.coordinates.get("x", 0)
        y = self.coordinates.get("y", 0)
        z = self.coordinates.get("z", 0)
        # 动态判断：如果 z 为 0，依然显示 2D 格式，保持界面清爽
        if abs(z) < 1e-10:
            return rf"{self.name} = ({latex(x)}, {latex(y)})"
        return rf"{self.name} = ({latex(x)}, {latex(y)}, {latex(z)})"

    @classmethod
    def deserialize(cls, data):
        # 兼容旧版本保存的仅有 x, y 的项目文件
        coords = data.get("coordinates", {})
        obj = cls(
            data["id"],
            data["name"],
            coords.get("x", 0),
            coords.get("y", 0),
            coords.get("z", 0),
        )
        return obj


class Sphere(GeometricObject):
    """3D 球体：由球心和半径定义"""

    def __init__(self, obj_id, name, center_id, radius=1.0):
        super().__init__(obj_id, name, "Sphere")
        self.center_id = center_id
        self.radius = radius
        self.depends_on = [center_id]

    def update_coordinates(self, engine):
        center = engine.objects.get(self.center_id)
        if center:
            self.coordinates = {
                "cx": center.coordinates.get("x", 0),
                "cy": center.coordinates.get("y", 0),
                "cz": center.coordinates.get("z", 0),  # 获取 z
                "r": self.radius,
            }

    def to_latex(self):
        cx = self.coordinates.get("cx", 0)
        cy = self.coordinates.get("cy", 0)
        cz = self.coordinates.get("cz", 0)
        return rf"(x-{cx})^2 + (y-{cy})^2 + (z-{cz})^2 = {self.radius}^2"

    def serialize(self):
        data = super().serialize()
        data["center_id"] = self.center_id
        data["radius"] = self.radius
        if "coordinates" not in data:
            data["coordinates"] = {}
        data["coordinates"]["r"] = self.radius
        return data


class Plane3D(GeometricObject):
    """3D 平面：通过一般方程 Ax + By + Cz + D = 0 定义"""

    def __init__(self, obj_id, name, A=0, B=0, C=1, D=0):
        super().__init__(obj_id, name, "Plane3D")
        self.A, self.B, self.C, self.D = A, B, C, D
        self.coordinates = {"A": A, "B": B, "C": C, "D": D}

    def to_latex(self):
        # 简单输出，可以参考 2D Line 改进
        return rf"{self.A}x + {self.B}y + {self.C}z + {self.D} = 0"
