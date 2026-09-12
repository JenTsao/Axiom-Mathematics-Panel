class GeometricObject:
    TYPES = [
        "Point",
        "Line",
        "Segment",
        "Circle",
        "Polygon",
        "Ray",
        "Angle",
        "Ellipse",
        "Hyperbola",
        "Parabola",
        "ConicSection",
        "FunctionPlot",
        "ImplicitPlot",
        "PolarPlot",
        "Locus",
        "Intersection",
        "Sphere",
        "Plane3D",
    ]

    def __init__(self, obj_id, name, obj_type):
        self.id = obj_id
        self.name = name
        self.type = obj_type
        self.coordinates = {}
        self.symbolic_expr = None
        self.constraints = []
        self.depends_on = []
        self.is_draft = False

    def update_coordinates(self, engine=None):
        pass

    def to_latex(self):
        if self.type == "Point":
            x, y = self.coordinates.get("x", 0), self.coordinates.get("y", 0)
            return rf"{self.name} = ({x}, {y})"
        return self.name

    def serialize(self):
        # 直接读取 _symbolic_expr，避免访问 Point 的懒加载 property 而触发
        # 不必要的 SymPy symbols 构造（序列化本身并不需要符号对象）
        symbolic = getattr(self, "_symbolic_expr", None)
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "coordinates": self.coordinates,
            "symbolic_expr": str(symbolic) if symbolic else None,
            "constraints": [c if isinstance(c, str) else str(c) for c in self.constraints],
            "depends_on": self.depends_on,
            "is_draft": getattr(self, "is_draft", False),
        }

    @classmethod
    def deserialize(cls, data):
        # 延迟导入所有子类，避免循环依赖
        from mathlab.core.models.circle import Circle
        from mathlab.core.models.conic import ConicSection, Ellipse, Hyperbola, Parabola
        from mathlab.core.models.function import FunctionPlot, ImplicitPlot, PolarPlot
        from mathlab.core.models.line import Line, Segment
        from mathlab.core.models.locus import Intersection, Locus
        from mathlab.core.models.point import Plane3D, Point, Sphere
        from mathlab.core.models.polygon import Polygon

        obj_type = data.get("type")
        obj = None

        if obj_type == "Polygon":
            obj = Polygon.deserialize(data)
        elif obj_type == "Ellipse":
            coords = data.get("coordinates", {})
            obj = Ellipse(
                data["id"],
                data["name"],
                data.get("center_id", ""),
                coords.get("a", 2.0),
                coords.get("b", 1.0),
                coords.get("rotation", 0),
            )
        elif obj_type == "Hyperbola":
            coords = data.get("coordinates", {})
            obj = Hyperbola(
                data["id"],
                data["name"],
                data.get("center_id", ""),
                coords.get("a", 1.0),
                coords.get("b", 1.0),
                coords.get("rotation", 0),
            )
        elif obj_type == "Parabola":
            coords = data.get("coordinates", {})
            obj = Parabola(
                data["id"],
                data["name"],
                data.get("vertex_id", ""),
                coords.get("p", 1.0),
                coords.get("direction", "up"),
            )
        elif obj_type == "ConicSection":
            obj = ConicSection.deserialize(data)
        elif obj_type == "FunctionPlot":
            obj = FunctionPlot.deserialize(data)
        elif obj_type == "ImplicitPlot":
            obj = ImplicitPlot.deserialize(data)
        elif obj_type == "PolarPlot":
            obj = PolarPlot.deserialize(data)
        elif obj_type == "Locus":
            obj = Locus.deserialize(data)
        elif obj_type == "Point":
            obj = Point.deserialize(data)
        elif obj_type == "Sphere":
            coords = data.get("coordinates", {})
            obj = Sphere(
                data["id"],
                data["name"],
                data.get("center_id", ""),
                coords.get("r", 1.0),
            )
        elif obj_type == "Segment":
            obj = Segment(
                data["id"],
                data["name"],
                data.get("point1_id", ""),
                data.get("point2_id", ""),
            )
        elif obj_type == "Line":
            obj = Line(
                data["id"],
                data["name"],
                data.get("point1_id", ""),
                data.get("point2_id", ""),
            )
        elif obj_type == "Circle":
            coords = data.get("coordinates", {})
            obj = Circle(
                data["id"],
                data["name"],
                data.get("center_id", ""),
                coords.get("r", 1.0),
            )
        elif obj_type == "Intersection":
            obj = Intersection(
                data["id"],
                data["name"],
                data.get("obj1_id", ""),
                data.get("obj2_id", ""),
                data.get("index", 0),
            )
        elif obj_type == "Plane3D":
            coords = data.get("coordinates", {})
            obj = Plane3D(
                data["id"],
                data["name"],
                coords.get("A", 0),
                coords.get("B", 0),
                coords.get("C", 1),
                coords.get("D", 0),
            )
        else:
            obj = cls(data["id"], data["name"], obj_type)
            # 兼容未显式声明的子类类型（如 Ray, Angle），恢复必须的关键属性
            for key in ["point1_id", "point2_id", "vertex_id", "center_id"]:
                if key in data:
                    setattr(obj, key, data[key])

        if obj:
            obj.coordinates = data.get("coordinates", {})
            obj.constraints = data.get("constraints", [])
            obj.depends_on = data.get("depends_on", [])

        return obj
