from collections import deque

import numpy as np
from sympy import latex

# C# 引擎导入期已自行降级（get_cs_geometry 返回 None）；此处保留兜底，
# 防止 utils 等上游依赖异常时击穿本模块。
try:
    from mathlab.core.cs_geometry_engine import get_cs_geometry
except Exception:  # pragma: no cover - 取决于本机依赖环境
    get_cs_geometry = None

from mathlab.core.models.base import GeometricObject


class Locus(GeometricObject):
    """动点轨迹：追踪依赖点的运动轨迹

    性能优化：使用 deque(maxlen=N) 作为环形缓冲区，
    - append 为 O(1)（旧 list.pop(0) 为 O(n)）
    - maxlen 自动淘汰旧数据，无需手动检查长度
    - 仅在序列化/通知时转换为 list，避免每次 add 的 O(n) 复制
    """

    def __init__(self, obj_id, name, tracer_point_id, driver_point_id, max_points=1000):
        super().__init__(obj_id, name, "Locus")
        self.tracer_point_id = tracer_point_id  # 被追踪的点
        self.driver_point_id = driver_point_id  # 驱动运动的点
        self.max_points = max_points
        self.trail_points = deque(maxlen=max_points)  # O(1) 环形缓冲区
        self.points_data = []
        self._dirty = False  # 延迟同步标记
        self.depends_on = [tracer_point_id, driver_point_id]

    def add_trail_point(self, x, y):
        """添加一个轨迹点（O(1) 操作，不触发列表复制）"""
        self.trail_points.append((x, y))
        self._dirty = True

    def _sync_points_data(self):
        """仅在需要时将 deque 转换为 list（序列化/通知前调用）"""
        if self._dirty:
            self.points_data = list(self.trail_points)
            self.coordinates = {"points": self.points_data}
            self._dirty = False

    def clear_trail(self):
        """清除轨迹"""
        self.trail_points.clear()
        self.points_data.clear()
        self.coordinates = {"points": []}
        self._dirty = False

    def update_coordinates(self, engine):
        pass

    def to_latex(self):
        return rf"Locus of {self.name}"

    def serialize(self):
        self._sync_points_data()  # 确保序列化前数据已同步
        data = super().serialize()
        data["tracer_point_id"] = self.tracer_point_id
        data["driver_point_id"] = self.driver_point_id
        data["max_points"] = self.max_points
        data["trail_points"] = list(self.trail_points)
        data["points_data"] = self.points_data
        return data

    @classmethod
    def deserialize(cls, data):
        obj = cls(
            data["id"],
            data["name"],
            data.get("tracer_point_id", ""),
            data.get("driver_point_id", ""),
            data.get("max_points", 1000),
        )
        obj.coordinates = data.get("coordinates", {})
        obj.constraints = data.get("constraints", [])
        obj.depends_on = data.get("depends_on", [])
        # 反序列化时将 list 转回 deque 以保持数据结构一致
        trail = data.get("trail_points", [])
        obj.trail_points = deque(trail, maxlen=obj.max_points)
        obj.points_data = data.get("points_data", [])
        obj._dirty = False
        return obj


class Intersection(GeometricObject):
    """动态交点：实时追踪两个几何对象的相交位置"""

    def __init__(self, obj_id, name, obj1_id, obj2_id, index=0):
        super().__init__(obj_id, name, "Intersection")
        self.obj1_id = obj1_id
        self.obj2_id = obj2_id
        self.index = index
        self.depends_on = [obj1_id, obj2_id]

    def update_coordinates(self, engine):
        obj1 = engine.objects.get(self.obj1_id)
        obj2 = engine.objects.get(self.obj2_id)

        if not obj1 or not obj2:
            return

        if hasattr(engine, "cas_provider") and engine.cas_provider:
            # 引入全局异步调度中心
            from mathlab.core.async_workers import TaskManager

            def on_success(points):
                if points and len(points) > self.index:
                    self.coordinates["x"] = float(points[self.index][0])
                    self.coordinates["y"] = float(points[self.index][1])
                    # 1. 刷新自身交点在画布上的位置
                    engine._notify("object_updated", self.serialize())

                    # 2. 核心：级联更新！因为计算是异步的，引擎的常规遍历可能已经走完了，
                    # 必须在这里手动触发依赖该交点的下游物体（如以该交点为圆心的圆）的重新计算
                    dependents = engine.dependencies.get_dependents(self.id)
                    for dep_id in dependents:
                        dep_obj = engine.objects.get(dep_id)
                        if dep_obj:
                            dep_obj.update_coordinates(engine)
                            engine._notify("object_updated", dep_obj.serialize())

            # 将昂贵的 SymPy 求交任务抛入后台
            manager = getattr(TaskManager, "_instance", None) or TaskManager()
            manager.submit(
                fn=engine.cas_provider.solve_intersection,
                on_success=on_success,
                obj1=obj1,
                obj2=obj2,
            )
        else:
            # 没有 CAS 时，使用解析几何后备算法（运算极快，保持同步即可）
            points = self._solve_intersection(obj1, obj2)
            if points and len(points) > self.index:
                self.coordinates["x"] = float(points[self.index][0])
                self.coordinates["y"] = float(points[self.index][1])

    def _solve_intersection(self, obj1, obj2):
        """回退的几何求交算法"""
        try:
            if obj1.type in ["Segment", "Line"] and obj2.type in ["Segment", "Line"]:
                return self._line_line_intersection(obj1, obj2)
            elif obj1.type in ["Segment", "Line"] and obj2.type == "Circle":
                return self._line_circle_intersection(obj1, obj2)
            elif obj2.type in ["Segment", "Line"] and obj1.type == "Circle":
                return self._line_circle_intersection(obj2, obj1)
            elif obj1.type == "Circle" and obj2.type == "Circle":
                return self._circle_circle_intersection(obj1, obj2)
        except Exception:
            pass
        return []

    def _line_line_intersection(self, line1, line2):
        """求解两条直线的交点"""
        if line1.type == "Segment":
            x1, y1 = line1.coordinates.get("x1", 0), line1.coordinates.get("y1", 0)
            x2, y2 = line1.coordinates.get("x2", 0), line1.coordinates.get("y2", 0)
            a1, b1, c1 = y2 - y1, x1 - x2, x2 * y1 - x1 * y2
        else:
            a1, b1, c1 = line1.a, line1.b, line1.c

        if line2.type == "Segment":
            x1, y1 = line2.coordinates.get("x1", 0), line2.coordinates.get("y1", 0)
            x2, y2 = line2.coordinates.get("x2", 0), line2.coordinates.get("y2", 0)
            a2, b2, c2 = y2 - y1, x1 - x2, x2 * y1 - x1 * y2
        else:
            a2, b2, c2 = line2.a, line2.b, line2.c

        det = a1 * b2 - a2 * b1
        if abs(det) < 1e-10:
            return []

        cs_engine = get_cs_geometry() if get_cs_geometry is not None else None
        if cs_engine and cs_engine.is_available:
            pts = cs_engine.solve_line_line(a1, b1, c1, a2, b2, c2)
            if pts is not None:
                return pts

        # 统一为标准形式: ax + by = -c
        # 根据 Cramer 法则求解: x = Dx / det, y = Dy / det
        rhs1, rhs2 = -c1, -c2
        x = (rhs1 * b2 - rhs2 * b1) / det
        y = (a1 * rhs2 - a2 * rhs1) / det
        return [(x, y)]

    def _line_circle_intersection(self, line, circle):
        """求解直线与圆的交点（垂足+切向量法）"""
        if line.type == "Segment":
            x1, y1 = line.coordinates.get("x1", 0), line.coordinates.get("y1", 0)
            x2, y2 = line.coordinates.get("x2", 0), line.coordinates.get("y2", 0)
            a, b, c = y2 - y1, x1 - x2, x2 * y1 - x1 * y2
        else:
            a, b, c = line.a, line.b, line.c

        cx, cy = circle.coordinates.get("cx", 0), circle.coordinates.get("cy", 0)
        r = circle.coordinates.get("r", 1)
        n2 = a**2 + b**2
        if n2 < 1e-10:
            return []

        cs_engine = get_cs_geometry() if get_cs_geometry is not None else None
        if cs_engine and cs_engine.is_available:
            pts = cs_engine.solve_line_circle(a, b, c, cx, cy, r)
            if pts is not None:
                return pts

        # 圆心到直线的有符号距离分子 k = a*cx + b*cy + c
        k = a * cx + b * cy + c
        n = np.sqrt(n2)
        d = abs(k) / n  # 圆心到直线的距离

        if d > r + 1e-10:
            return []

        # 垂足坐标
        fx = cx - a * k / n2
        fy = cy - b * k / n2

        if abs(d - r) < 1e-10:
            # 相切：唯一交点即为垂足
            return [(fx, fy)]

        # 半弦长，沿直线切向量 (-b, a)/n 偏移
        h = np.sqrt(max(r**2 - d**2, 0.0))
        x1_r, y1_r = fx - h * b / n, fy + h * a / n
        x2_r, y2_r = fx + h * b / n, fy - h * a / n
        return [(x1_r, y1_r), (x2_r, y2_r)]

    def _circle_circle_intersection(self, circle1, circle2):
        """求解两个圆的交点"""
        cx1, cy1 = circle1.coordinates.get("cx", 0), circle1.coordinates.get("cy", 0)
        r1 = circle1.coordinates.get("r", 1)
        cx2, cy2 = circle2.coordinates.get("cx", 0), circle2.coordinates.get("cy", 0)
        r2 = circle2.coordinates.get("r", 1)

        dx = cx2 - cx1
        dy = cy2 - cy1
        d = np.sqrt(dx**2 + dy**2)

        if d > r1 + r2 or d < abs(r1 - r2):
            return []

        if abs(d) < 1e-10 and abs(r1 - r2) < 1e-10:
            return []

        cs_engine = get_cs_geometry() if get_cs_geometry is not None else None
        if cs_engine and cs_engine.is_available:
            pts = cs_engine.solve_circle_circle(cx1, cy1, r1, cx2, cy2, r2)
            if pts is not None:
                return pts

        a = (r1**2 - r2**2 + d**2) / (2 * d)
        h = np.sqrt(r1**2 - a**2)

        xm = cx1 + a * dx / d
        ym = cy1 + a * dy / d

        x1 = xm - h * dy / d
        y1 = ym + h * dx / d
        x2 = xm + h * dy / d
        y2 = ym - h * dx / d

        if abs(h) < 1e-10:
            return [(x1, y1)]
        return [(x1, y1), (x2, y2)]

    def serialize(self):
        data = super().serialize()
        data["obj1_id"] = self.obj1_id
        data["obj2_id"] = self.obj2_id
        data["index"] = self.index
        return data

    def to_latex(self):
        x, y = self.coordinates.get("x", 0), self.coordinates.get("y", 0)
        return rf"{self.name} = ({latex(x)}, {latex(y)})"
