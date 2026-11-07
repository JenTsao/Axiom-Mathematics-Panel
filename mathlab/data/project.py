from datetime import datetime

from mathlab.data.project_schema import (
    PROJECT_SCHEMA_VERSION,
    build_project,
    read_project_file,
    write_project_file,
)


class ProjectManager:
    def __init__(self):
        self.current_project = None
        self.objects = {}
        self.console_history = []
        self.settings = {
            "created": datetime.now().isoformat(),
            "modified": datetime.now().isoformat(),
            "version": PROJECT_SCHEMA_VERSION,
        }

    def new_project(self):
        self.current_project = None
        self.objects = {}
        self.console_history = []
        self.settings = {
            "created": datetime.now().isoformat(),
            "modified": datetime.now().isoformat(),
            "version": PROJECT_SCHEMA_VERSION,
        }

    def open_project(self, file_path):
        try:
            # 统一 schema：兼容 UI / ProjectManager / FileManager 三种历史格式
            project = read_project_file(file_path)

            self.current_project = file_path
            self.objects = project["objects"]
            self.console_history = project["console_history"]
            self.settings = project["settings"]

            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def save_project(self, file_path=None, file_manager=None):
        """保存项目到磁盘。

        Parameters
        ----------
        file_path : str, optional
            目标路径，默认使用 current_project。
        file_manager : FileManager, optional
            若传入，保存成功后会同步刷新 FileIndex（更新 modified/checksum/
            最近列表），解决 ProjectManager 和 FileManager 两套保存逻辑
            互不通气、索引过期的问题。
        """
        if file_path is None:
            file_path = self.current_project

        if file_path is None:
            return {"success": False, "error": "No file path specified"}

        try:
            write_project_file(file_path, self.serialize_current_state())
            self.current_project = file_path

            # 同步刷新 FileIndex，避免索引里的 modified/checksum 过期
            if file_manager is not None:
                try:
                    object_types = list(
                        set(obj.get("type") for obj in self.objects.values() if obj.get("type") is not None)
                    )
                    file_manager.index.add_entry(
                        file_path,
                        {
                            "category": self.settings.get("category", "untitled"),
                            "object_types": object_types,
                            "tags": self.settings.get("tags", []),
                        },
                    )
                except Exception:
                    pass  # 索引刷新失败不影响保存结果

            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def add_object(self, obj_id, obj_data):
        self.objects[obj_id] = obj_data
        self._update_modified()

    def _deep_update(self, target, source):
        for key, value in source.items():
            if isinstance(value, dict) and key in target and isinstance(target[key], dict):
                self._deep_update(target[key], value)
            else:
                target[key] = value

    def update_object(self, obj_id, obj_data):
        if obj_id in self.objects:
            self._deep_update(self.objects[obj_id], obj_data)
            self._update_modified()

    def remove_object(self, obj_id):
        if obj_id in self.objects:
            del self.objects[obj_id]
            self._update_modified()

    def add_console_entry(self, entry):
        self.console_history.append({"timestamp": datetime.now().isoformat(), "entry": entry})
        if len(self.console_history) > 1000:
            self.console_history = self.console_history[-1000:]

    def get_object(self, obj_id):
        return self.objects.get(obj_id)

    def get_all_objects(self):
        return list(self.objects.values())

    def _update_modified(self):
        self.settings["modified"] = datetime.now().isoformat()

    def serialize_current_state(self):
        """导出 canonical v2.0 工程字典（保存与自动存档共用同一形状）。"""
        return build_project(
            objects=self.objects,
            console_history=self.console_history,
            settings=self.settings,
            name=self.settings.get("name", ""),
            category=self.settings.get("category", "untitled"),
            created=self.settings.get("created"),
            modified=datetime.now().isoformat(),
        )

    def export_to_png(self, canvas_widget, file_path):
        try:
            pixmap = canvas_widget.grab()
            pixmap.save(file_path)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def export_to_svg(self, canvas_widget, file_path):
        return {"success": False, "error": "SVG export not implemented yet"}

    def export_algebra_to_latex(self):
        """将画布上所有几何对象导出为 LaTeX 字符串。

        覆盖 GeometryEngine 支持的全部对象类型，与各类的 to_latex() 逻辑对齐。
        """
        latex_lines = []

        for obj_data in self.objects.values():
            obj_type = obj_data.get("type")
            name = obj_data.get("name", "")
            coords = obj_data.get("coordinates", {})

            line = None

            if obj_type == "Point":
                x = coords.get("x", 0)
                y = coords.get("y", 0)
                line = rf"\({name} = ({x},\ {y})\)"

            elif obj_type == "Circle":
                cx = coords.get("cx", 0)
                cy = coords.get("cy", 0)
                r = coords.get("r", 1)
                line = rf"\((x - {cx})^2 + (y - {cy})^2 = {r}^2\)"

            elif obj_type in ("Line", "Segment"):
                a = obj_data.get("a")
                b = obj_data.get("b")
                c = obj_data.get("c")
                if a is not None and b is not None and c is not None:
                    line = rf"\({a}x + {b}y + {c} = 0\)"
                else:
                    x1 = coords.get("x1", 0)
                    y1 = coords.get("y1", 0)
                    x2 = coords.get("x2", 0)
                    y2 = coords.get("y2", 0)
                    prefix = r"\overline{" + name + "}" if obj_type == "Segment" else name
                    line = rf"\({prefix}: ({x1},\ {y1}) \to ({x2},\ {y2})\)"

            elif obj_type == "Polygon":
                pts = coords.get("points", [])
                pts_str = r",\ ".join(rf"({p[0]},\ {p[1]})" for p in pts)
                line = rf"\(\text{{Polygon}}({name}): {pts_str}\)"

            elif obj_type == "Ellipse":
                cx = coords.get("cx", 0)
                cy = coords.get("cy", 0)
                a = coords.get("a", 2)
                b = coords.get("b", 1)
                rotation = coords.get("rotation", 0)
                if rotation == 0:
                    line = rf"\(\dfrac{{(x-{cx})^2}}{{{a}^2}} + \dfrac{{(y-{cy})^2}}{{{b}^2}} = 1\)"
                else:
                    line = rf"\(\text{{Ellipse}}({name},\ \theta={rotation:.4f}\text{{ rad}})\)"

            elif obj_type == "Hyperbola":
                cx = coords.get("cx", 0)
                cy = coords.get("cy", 0)
                a = coords.get("a", 1)
                b = coords.get("b", 1)
                rotation = coords.get("rotation", 0)
                if rotation == 0:
                    line = rf"\(\dfrac{{(x-{cx})^2}}{{{a}^2}} - \dfrac{{(y-{cy})^2}}{{{b}^2}} = 1\)"
                else:
                    line = rf"\(\text{{Hyperbola}}({name},\ \theta={rotation:.4f}\text{{ rad}})\)"

            elif obj_type == "Parabola":
                vx = coords.get("vx", 0)
                vy = coords.get("vy", 0)
                p = coords.get("p", 1)
                direction = coords.get("direction", "up")
                if direction in ("up", "down"):
                    sign = 1 if direction == "up" else -1
                    line = rf"\((x-{vx})^2 = {4 * p * sign}(y-{vy})\)"
                else:
                    sign = 1 if direction == "right" else -1
                    line = rf"\((y-{vy})^2 = {4 * p * sign}(x-{vx})\)"

            elif obj_type == "Intersection":
                x = coords.get("x", 0)
                y = coords.get("y", 0)
                line = rf"\({name} = ({x},\ {y})\)"

            elif obj_type == "FunctionPlot":
                expr = obj_data.get("expression", "")
                line = rf"\(y = {expr}\)"

            elif obj_type == "ImplicitPlot":
                expr = obj_data.get("expression", "")
                line = rf"\({expr} = 0\)"

            elif obj_type == "PolarPlot":
                expr = obj_data.get("expression", "")
                line = rf"\(r = {expr}\)"

            elif obj_type == "Locus":
                line = rf"\(\text{{Locus of }}\,{name}\)"

            if line is not None:
                latex_lines.append(line)

        return "\n".join(latex_lines)
