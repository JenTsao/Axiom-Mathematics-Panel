import hashlib
import json
import os
import shutil
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from mathlab.data.project_schema import (
    build_project,
    read_project_file,
    write_project_file,
)

# 进程级 MD5 缓存，key = (abspath, file_size, mtime_ns)
# 避免同一文件未改动时重复读盘计算，减少主线程 I/O 阻塞。
# 最多缓存 512 条，防止长期运行内存无限增长。
_CHECKSUM_CACHE: Dict[tuple, str] = {}
_CHECKSUM_CACHE_MAX = 512


class FileCategory(Enum):
    GEOMETRY = "geometry"
    ALGEBRA = "algebra"
    ALGORITHM = "algorithm"
    AI_PROJECT = "ai_project"
    UNTITLED = "untitled"


class FileFormat(Enum):
    MATHLAB = ("mathlab", "MathLab Project")
    PNG = ("png", "PNG Image")
    SVG = ("svg", "SVG Vector")
    LATEX = ("tex", "LaTeX Document")
    JSON = ("json", "JSON Data")

    def __init__(self, extension: str, description: str):
        # 显式设置 _value_，使 .value 返回扩展名字符串而非整个元组
        # 否则 FileFormat.PNG.value 会是 ('png', 'PNG Image') 而非 'png'
        self._value_ = extension
        self.extension = extension
        self.description = description


class SearchFilter:
    def __init__(self):
        self.query = ""
        self.category = None
        self.object_types = []
        self.date_from = None
        self.date_to = None
        self.tags = []

    def matches(self, project_info: Dict) -> bool:
        if self.query:
            query_lower = self.query.lower()
            name = project_info.get("name", "").lower()
            if query_lower not in name:
                return False

        if self.category and project_info.get("category") != self.category:
            return False

        if self.object_types:
            project_types = project_info.get("object_types", [])
            if not any(t in project_types for t in self.object_types):
                return False

        if self.date_from:
            created = project_info.get("created")
            if created and created < self.date_from:
                return False

        if self.date_to:
            created = project_info.get("created")
            if created and created > self.date_to:
                return False

        if self.tags:
            project_tags = project_info.get("tags", [])
            if not any(t in project_tags for t in self.tags):
                return False

        return True


class FileMetadata:
    def __init__(self, file_path: str):
        self.file_path = file_path
        self._load_metadata()

    def _load_metadata(self):
        if os.path.exists(self.file_path):
            stat = os.stat(self.file_path)
            self.size = stat.st_size
            # st_ctime 在 Windows 上是文件创建时间，在 Linux/macOS 上是
            # inode 元数据最后变更时间（并非真正的创建时间）。
            # 此处仅作近似使用，跨平台场景下可能不准确。
            self.created = datetime.fromtimestamp(stat.st_ctime).isoformat()
            self.modified = datetime.fromtimestamp(stat.st_mtime).isoformat()
            self.checksum = self._calculate_checksum()
        else:
            self.size = 0
            self.created = None
            self.modified = None
            self.checksum = None

    def _calculate_checksum(self) -> str:
        """计算文件 MD5，优先返回进程级缓存结果。

        缓存 key = (abspath, file_size, mtime_ns)，当文件内容未变动时
        直接命中缓存，无需重新读盘，避免阻塞主线程。
        """
        try:
            stat = os.stat(self.file_path)
            cache_key = (self.file_path, stat.st_size, stat.st_mtime_ns)
            cached = _CHECKSUM_CACHE.get(cache_key)
            if cached is not None:
                return cached

            md5 = hashlib.md5(usedforsecurity=False)
            with open(self.file_path, "rb") as f:
                while chunk := f.read(65536):
                    md5.update(chunk)
            result = md5.hexdigest()

            # 超出容量时淘汰最早的一批（简单策略：清掉一半）
            if len(_CHECKSUM_CACHE) >= _CHECKSUM_CACHE_MAX:
                drop = list(_CHECKSUM_CACHE.keys())[: _CHECKSUM_CACHE_MAX // 2]
                for k in drop:
                    _CHECKSUM_CACHE.pop(k, None)
            _CHECKSUM_CACHE[cache_key] = result
            return result
        except (OSError, IOError):
            return ""


class FileIndex:
    def __init__(self, index_path: Optional[str] = None):
        self.index_path = index_path or self._get_default_index_path()
        self.entries: Dict[str, Dict] = {}
        self.recent_files: List[str] = []
        self.max_recent = 10

    def _get_default_index_path(self) -> str:
        app_data = os.path.expanduser("~/.mathlab")
        os.makedirs(app_data, exist_ok=True)
        return os.path.join(app_data, "file_index.json")

    def load(self) -> bool:
        try:
            if os.path.exists(self.index_path):
                with open(self.index_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.entries = data.get("entries", {})
                    self.recent_files = data.get("recent_files", [])
                return True
        except Exception:
            pass
        return False

    def save(self) -> bool:
        try:
            os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
            with open(self.index_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "entries": self.entries,
                        "recent_files": self.recent_files[-self.max_recent :],
                    },
                    f,
                    indent=2,
                )
            return True
        except Exception:
            return False

    def add_entry(self, file_path: str, info: Dict) -> bool:
        abs_path = os.path.abspath(file_path)
        metadata = FileMetadata(abs_path)

        entry = {
            "path": abs_path,
            "name": os.path.basename(abs_path),
            "category": info.get("category", FileCategory.UNTITLED.value),
            "object_types": info.get("object_types", []),
            "tags": info.get("tags", []),
            "created": metadata.created,
            "modified": metadata.modified,
            "size": metadata.size,
            "checksum": metadata.checksum,
        }

        self.entries[abs_path] = entry
        self._add_to_recent(abs_path)
        return self.save()

    def remove_entry(self, file_path: str) -> bool:
        abs_path = os.path.abspath(file_path)
        if abs_path in self.entries:
            del self.entries[abs_path]
            if abs_path in self.recent_files:
                self.recent_files.remove(abs_path)
            return self.save()
        return False

    def get_entry(self, file_path: str) -> Optional[Dict]:
        abs_path = os.path.abspath(file_path)
        return self.entries.get(abs_path)

    def search(self, search_filter: SearchFilter) -> List[Dict]:
        results = []
        for entry in self.entries.values():
            if search_filter.matches(entry):
                results.append(entry)

        results.sort(key=lambda x: x.get("modified", ""), reverse=True)
        return results

    def get_recent_files(self, limit: int = 10) -> List[Dict]:
        recent = []
        for path in reversed(self.recent_files[-limit:]):
            if path in self.entries:
                recent.append(self.entries[path])
        return recent

    def _add_to_recent(self, file_path: str):
        abs_path = os.path.abspath(file_path)
        if abs_path in self.recent_files:
            self.recent_files.remove(abs_path)
        self.recent_files.append(abs_path)
        if len(self.recent_files) > self.max_recent:
            self.recent_files = self.recent_files[-self.max_recent :]

    def get_statistics(self) -> Dict:
        stats = {
            "total_files": len(self.entries),
            "by_category": {},
            "by_type": {},
            "total_size": 0,
        }

        for entry in self.entries.values():
            category = entry.get("category", "unknown")
            stats["by_category"][category] = stats["by_category"].get(category, 0) + 1

            for obj_type in entry.get("object_types", []):
                stats["by_type"][obj_type] = stats["by_type"].get(obj_type, 0) + 1

            stats["total_size"] += entry.get("size", 0)

        return stats


class FileManager:
    def __init__(self, base_directory: Optional[str] = None):
        self.base_directory = base_directory or self._get_default_base_directory()
        self.index = FileIndex()
        self.index.load()

    def _get_default_base_directory(self) -> str:
        documents = os.path.expanduser("~/Documents")
        mathlab_dir = os.path.join(documents, "MathLab")
        os.makedirs(mathlab_dir, exist_ok=True)
        return mathlab_dir

    def create_project(self, name: str, category: FileCategory = FileCategory.UNTITLED) -> Dict:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c if c.isalnum() else "_" for c in name)
        filename = f"{safe_name}_{timestamp}.mathlab"
        file_path = os.path.join(self.base_directory, filename)

        project_data = build_project(name=name, category=category.value)

        try:
            write_project_file(file_path, project_data)

            self.index.add_entry(file_path, {"category": category.value, "object_types": [], "tags": []})

            return {"success": True, "file_path": file_path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def open_project(self, file_path: str) -> Dict:
        try:
            # 统一 schema：返回值恒为 canonical v2.0 超集
            data = read_project_file(file_path)

            self.index.add_entry(
                file_path,
                {
                    "category": data.get("category", FileCategory.UNTITLED.value),
                    "object_types": list(
                        set(t for t in (obj.get("type") for obj in data.get("objects", {}).values()) if t is not None)
                    ),
                    "tags": data.get("settings", {}).get("tags", []),
                },
            )

            return {"success": True, "data": data}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def save_project(self, file_path: str, data: Dict) -> Dict:
        try:
            data["modified"] = datetime.now().isoformat()
            write_project_file(file_path, data)

            self.index.add_entry(
                file_path,
                {
                    "category": data.get("category", FileCategory.UNTITLED.value),
                    "object_types": list(
                        set(t for t in (obj.get("type") for obj in data.get("objects", {}).values()) if t is not None)
                    ),
                    "tags": data.get("settings", {}).get("tags", []),
                },
            )

            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_project(self, file_path: str, keep_backup: bool = False) -> Dict:
        try:
            if os.path.exists(file_path):
                backup_path = file_path + ".backup"
                backup_created = False  # 标记本次调用是否创建了备份

                if keep_backup:
                    shutil.copy2(file_path, backup_path)
                    backup_created = True

                os.remove(file_path)

                # 仅删除本次调用刚刚创建的备份（keep_backup=False 且本次未建备份时不动磁盘上已有的旧备份）
                if not keep_backup and backup_created and os.path.exists(backup_path):
                    try:
                        os.remove(backup_path)
                    except Exception:
                        pass

            self.index.remove_entry(file_path)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def duplicate_project(self, file_path: str, new_name: Optional[str] = None) -> Dict:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if new_name:
                data["name"] = new_name

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_name = os.path.basename(file_path).replace(".mathlab", "")
            new_filename = f"{base_name}_copy_{timestamp}.mathlab"
            new_path = os.path.join(self.base_directory, new_filename)

            data["created"] = datetime.now().isoformat()
            data["modified"] = datetime.now().isoformat()

            with open(new_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            self.index.add_entry(
                new_path,
                {
                    "category": data.get("category", FileCategory.UNTITLED.value),
                    "object_types": list(
                        set(t for t in (obj.get("type") for obj in data.get("objects", {}).values()) if t is not None)
                    ),
                    "tags": data.get("settings", {}).get("tags", []),
                },
            )

            return {"success": True, "new_path": new_path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def search_projects(self, search_filter: SearchFilter) -> List[Dict]:
        return self.index.search(search_filter)

    def get_recent_projects(self, limit: int = 10) -> List[Dict]:
        return self.index.get_recent_files(limit)

    def get_statistics(self) -> Dict:
        return self.index.get_statistics()

    def categorize_project(self, file_path: str, category: FileCategory, tags: Optional[List[str]] = None) -> Dict:
        abs_path = os.path.abspath(file_path)
        if abs_path not in self.index.entries:
            return {"success": False, "error": "Project not found in index"}

        self.index.entries[abs_path]["category"] = category.value
        if tags:
            self.index.entries[abs_path]["tags"] = tags

        self.index.save()
        return {"success": True}

    def get_projects_by_category(self, category: FileCategory) -> List[Dict]:
        search_filter = SearchFilter()
        search_filter.category = category.value
        return self.index.search(search_filter)

    def cleanup_index(self) -> Dict:
        removed = 0
        invalid_paths = []

        for path in list(self.index.entries.keys()):
            if not os.path.exists(path):
                invalid_paths.append(path)

        for path in invalid_paths:
            del self.index.entries[path]
            if path in self.index.recent_files:
                self.index.recent_files.remove(path)
            removed += 1

        self.index.save()
        return {"success": True, "removed": removed}

    def export_project_summary(self, file_path: str) -> str:
        entry = self.index.get_entry(file_path)
        if not entry:
            return ""

        lines = [
            f"Project: {entry['name']}",
            f"Category: {entry['category']}",
            f"Created: {entry.get('created', 'Unknown')}",
            f"Modified: {entry.get('modified', 'Unknown')}",
            f"Size: {entry.get('size', 0)} bytes",
            f"Object Types: {', '.join(entry.get('object_types', []))}",
            f"Tags: {', '.join(entry.get('tags', []))}",
        ]
        return "\n".join(lines)
