"""P0 回归测试：配置单一写入口、工程文件统一 schema、自动保存间隔。

覆盖三类此前会真实丢失用户数据的缺陷：

* ``config_manager`` 冷缓存自死锁、多写入方整文件覆盖丢键；
* ``.mathlab`` 三套互不兼容的格式（尤其 UI 存的文件丢 ``name_counter``）；
* ``autosave_interval`` 偏好设置无人消费、间隔硬编码 30 秒。
"""

import json
import threading

import pytest

from mathlab.data.project_schema import (
    PROJECT_SCHEMA_VERSION,
    build_project,
    engine_payload,
    normalize_project,
    read_project_file,
    write_project_file,
)
from mathlab.utils import config_manager as cm

pytestmark = pytest.mark.unit

_OBJECTS = {"p1": {"type": "Point", "name": "A"}}


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """把配置读写重定向到临时文件，不触碰仓库的 settings.json。"""
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"theme": "sepia", "language": "en"}), encoding="utf-8")
    monkeypatch.setattr(cm, "_config_path", str(path))
    monkeypatch.setattr(cm, "_config_cache", None)
    return path


def _raw(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── 配置层 ──────────────────────────────────────────────────────────────────


class TestConfigSingleWriter:
    def test_set_config_cold_cache_does_not_deadlock(self, isolated_config):
        """冷缓存下 set_config 曾因非重入 Lock 自死锁。"""
        done = {}

        def worker():
            cm.set_config("ipc.server_port", 55555)
            done["ok"] = True

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join(timeout=3)
        assert not thread.is_alive(), "set_config 在冷缓存上死锁"
        assert done.get("ok")
        assert cm.get_config("ipc.server_port") == 55555

    def test_update_config_preserves_other_writers_keys(self, isolated_config):
        assert cm.update_config({"language": "zh"}) is True
        raw = _raw(isolated_config)
        assert raw["theme"] == "sepia"
        assert raw["language"] == "zh"
        assert cm.get_config("theme") == "sepia"

    def test_update_config_merges_nested_keys(self, isolated_config):
        cm.update_config({"ipc": {"server_port": 50000}})
        raw = _raw(isolated_config)
        assert raw["ipc"]["server_port"] == 50000
        assert cm.get_config("ipc.client_port") == 45679

    def test_save_config_legacy_snapshot_does_not_wipe_keys(self, isolated_config):
        """旧调用方把 get_config() 快照加一个键后原样传回，不能丢 theme。"""
        snapshot = cm.get_config()
        snapshot["ai_model"] = "custom-model"
        assert cm.save_config(snapshot) is True
        raw = _raw(isolated_config)
        assert raw["theme"] == "sepia"
        assert raw["language"] == "en"
        assert raw["ai_model"] == "custom-model"

    def test_cross_writer_key_survival(self, isolated_config):
        cm.update_config({"theme": "light"})
        snapshot = cm.get_config()
        snapshot["language"] = "zh"
        cm.save_config(snapshot)
        raw = _raw(isolated_config)
        assert raw["theme"] == "light"
        assert raw["language"] == "zh"

    def test_get_config_returns_copy(self, isolated_config):
        full = cm.get_config()
        full["theme"] = "light"
        full.setdefault("ipc", {})["server_port"] = 1
        assert cm.get_config("theme") == "sepia"
        assert cm.get_config("ipc.server_port") == 45678
        assert cm._DEFAULT_CONFIG["ipc"]["server_port"] == 45678

    def test_deep_merge_does_not_share_nested_dicts(self):
        base = {"a": {"b": 1}}
        override = {"a": {"c": 2}, "d": {"e": 3}}
        merged = cm._deep_merge(base, override)
        merged["a"]["b"] = 99
        merged["d"]["e"] = 99
        assert base == {"a": {"b": 1}}
        assert override["d"] == {"e": 3}

    def test_update_config_rejects_non_dict(self, isolated_config):
        assert cm.update_config(["not", "a", "dict"]) is False

    def test_theme_manager_shares_one_store(self, isolated_config):
        pytest.importorskip("PySide6")
        from mathlab.utils import theme_manager as tm

        assert tm.load_settings()["theme"] == "sepia"
        tm.save_settings({"theme": "light"})
        assert cm.get_config("theme") == "light"
        assert _raw(isolated_config)["language"] == "en"


# ── 工程文件 schema ─────────────────────────────────────────────────────────


def _legacy_ui():
    return {"objects": _OBJECTS, "name_counter": {"P": 7}}


def _legacy_project_manager():
    return {
        "objects": _OBJECTS,
        "console_history": ["entry"],
        "settings": {"created": "c0", "modified": "m0", "version": "1.0"},
    }


def _legacy_file_manager():
    return {
        "version": "1.0",
        "name": "Demo",
        "category": "geometry",
        "created": "c1",
        "modified": "m1",
        "objects": _OBJECTS,
        "console_history": [],
        "settings": {"tags": ["tag1"]},
    }


_CANONICAL_KEYS = {
    "version",
    "name",
    "category",
    "created",
    "modified",
    "objects",
    "console_history",
    "settings",
}


class TestProjectSchema:
    @pytest.mark.parametrize("factory", [_legacy_ui, _legacy_project_manager, _legacy_file_manager])
    def test_normalize_legacy_formats(self, factory):
        normalized = normalize_project(factory())
        assert normalized["version"] == PROJECT_SCHEMA_VERSION
        assert _CANONICAL_KEYS <= set(normalized)
        assert normalized["objects"] == _OBJECTS

    @pytest.mark.parametrize("factory", [_legacy_ui, _legacy_project_manager, _legacy_file_manager])
    def test_normalize_is_idempotent(self, factory):
        once = normalize_project(factory())
        assert normalize_project(once) == once

    def test_legacy_name_counter_is_recovered(self):
        payload = engine_payload(normalize_project(_legacy_ui()))
        assert payload["objects"] == _OBJECTS
        assert payload["name_counter"] == {"P": 7}

    def test_engine_payload_tolerates_missing_settings(self):
        payload = engine_payload({"objects": _OBJECTS})
        assert payload == {"objects": _OBJECTS, "name_counter": {}}

    def test_normalize_rejects_non_dict(self):
        with pytest.raises(ValueError):
            normalize_project(["not", "a", "dict"])

    def test_write_read_roundtrip_keeps_name_counter(self, tmp_path):
        path = tmp_path / "demo.mathlab"
        write_project_file(path, build_project(objects=_OBJECTS, settings={"name_counter": {"P": 7}}, name="Demo"))
        loaded = read_project_file(path)
        assert loaded["name"] == "Demo"
        assert loaded["version"] == PROJECT_SCHEMA_VERSION
        assert engine_payload(loaded)["name_counter"] == {"P": 7}
        assert not (tmp_path / "demo.mathlab.tmp").exists()

    def test_write_project_file_normalizes_legacy_input(self, tmp_path):
        path = tmp_path / "legacy.mathlab"
        write_project_file(path, _legacy_ui())
        loaded = read_project_file(path)
        assert loaded["version"] == PROJECT_SCHEMA_VERSION
        assert engine_payload(loaded)["name_counter"] == {"P": 7}

    def test_project_manager_writes_canonical_file(self, tmp_path):
        from mathlab.data.project import ProjectManager

        path = tmp_path / "pm.mathlab"
        manager = ProjectManager()
        manager.objects = dict(_OBJECTS)
        manager.console_history = ["entry"]
        assert manager.save_project(str(path))["success"]
        loaded = read_project_file(path)
        assert loaded["objects"] == _OBJECTS
        assert loaded["console_history"] == ["entry"]
        assert loaded["version"] == PROJECT_SCHEMA_VERSION

    def test_file_manager_create_is_readable_by_project_manager(self, tmp_path, monkeypatch):
        from mathlab.data.file_manager import FileCategory, FileIndex, FileManager
        from mathlab.data.project import ProjectManager

        monkeypatch.setattr(FileIndex, "_get_default_index_path", lambda self: str(tmp_path / "file_index.json"))
        manager = FileManager(base_directory=str(tmp_path))
        path = manager.create_project("Demo", FileCategory.GEOMETRY)["file_path"]

        loaded = read_project_file(path)
        assert loaded["name"] == "Demo"
        assert loaded["category"] == "geometry"

        pm = ProjectManager()
        assert pm.open_project(path)["success"]
        assert pm.objects == {}

    def test_three_writers_produce_mutually_readable_files(self, tmp_path, monkeypatch):
        """UI / ProjectManager / FileManager 写的文件，任一读取方都能打开。"""
        from mathlab.data.file_manager import FileIndex, FileManager
        from mathlab.data.project import ProjectManager

        monkeypatch.setattr(FileIndex, "_get_default_index_path", lambda self: str(tmp_path / "file_index.json"))
        manager = FileManager(base_directory=str(tmp_path))

        # 1) 旧 UI 格式（顶层 name_counter）必须仍能还原几何命名计数器
        ui_path = tmp_path / "ui.mathlab"
        ui_path.write_text(json.dumps(_legacy_ui()), encoding="utf-8")
        assert engine_payload(read_project_file(ui_path))["name_counter"] == {"P": 7}
        assert manager.open_project(str(ui_path))["data"]["objects"] == _OBJECTS
        pm = ProjectManager()
        assert pm.open_project(str(ui_path))["success"]
        assert pm.objects == _OBJECTS

        # 2) ProjectManager 写的文件，UI 通道与 FileManager 都能读
        pm_path = tmp_path / "pm.mathlab"
        assert pm.save_project(str(pm_path))["success"]
        assert engine_payload(read_project_file(pm_path))["objects"] == _OBJECTS
        assert manager.open_project(str(pm_path))["success"]

        # 3) FileManager 写的文件
        fm_path = manager.create_project("Demo")["file_path"]
        assert read_project_file(fm_path)["version"] == PROJECT_SCHEMA_VERSION
        assert engine_payload(read_project_file(fm_path))["objects"] == {}

    def test_file_manager_save_accepts_legacy_dict(self, tmp_path, monkeypatch):
        from mathlab.data.file_manager import FileIndex, FileManager

        monkeypatch.setattr(FileIndex, "_get_default_index_path", lambda self: str(tmp_path / "file_index.json"))
        manager = FileManager(base_directory=str(tmp_path))
        path = tmp_path / "saved.mathlab"
        assert manager.save_project(str(path), _legacy_ui())["success"]
        assert read_project_file(path)["version"] == PROJECT_SCHEMA_VERSION
        assert engine_payload(read_project_file(path))["name_counter"] == {"P": 7}


# ── 自动保存间隔 ────────────────────────────────────────────────────────────


class TestAutosaveInterval:
    def test_interval_follows_config(self, isolated_config):
        pytest.importorskip("PySide6")
        from mathlab.core.error_manager import AutoSaver

        assert AutoSaver.resolve_interval_ms() == 5 * 60_000
        cm.update_config({"autosave_interval": 2})
        assert AutoSaver.resolve_interval_ms() == 120_000
        cm.update_config({"autosave_interval": 0})
        assert AutoSaver.resolve_interval_ms() == AutoSaver._MIN_INTERVAL_MS

    def test_invalid_or_explicit_interval(self, isolated_config):
        pytest.importorskip("PySide6")
        from mathlab.core.error_manager import AutoSaver

        cm.update_config({"autosave_interval": "oops"})
        assert AutoSaver.resolve_interval_ms() == AutoSaver._DEFAULT_INTERVAL_MS
        assert AutoSaver.resolve_interval_ms(1234) == AutoSaver._MIN_INTERVAL_MS
        assert AutoSaver.resolve_interval_ms(45_000) == 45_000
