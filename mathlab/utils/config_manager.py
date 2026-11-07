"""统一配置管理模块。

从 settings.json 加载配置，支持默认值、嵌套键访问和运行时覆写。
所有模块应通过 get_config() 获取配置，而非各自硬编码。

本模块是 settings.json 的**唯一读写出口**：任何模块要持久化配置都必须走
``update_config()``（或兼容入口 ``save_config()``）。写入前会重新读取磁盘并
深度合并，避免多个写入方各自持有缓存、用陈旧快照整文件覆盖而丢掉别人的键
（历史上 theme / language / accent 就因此互相覆盖）。
"""

import copy
import json
import os
import threading
from typing import Any, Dict, Optional

from mathlab.utils.logger import get_logger

logger = get_logger(__name__)

# ── 默认配置 ────────────────────────────────────────────────────────────────
_DEFAULT_CONFIG: Dict[str, Any] = {
    "ipc": {
        "server_port": 45678,
        "client_port": 45679,
    },
    "ai_api_key": "",
    "ai_base_url": "https://api.deepseek.com/v1",
    "ai_model": "deepseek-chat",
    # R-25：画布抗锯齿开关（默认开启，偏好「图形质量」页可降级）
    "aa_enabled": True,
    # 默认主题（theme_manager.get_current_theme 的兜底值），统一配置真源
    "theme": "dark",
    # D-3：撤销栈启用开关（关闭时 Ctrl+Z 灰置，UndoStack 零开销）
    "enable_undo": True,
    # 文件式记忆系统总开关（关闭后不读取也不写入 Markdown 记忆文件）
    "enable_file_memory": True,
    # 自动保存间隔（分钟），AutoSaver 读取此值；偏好设置的 autosave_interval 与此同源
    "autosave_interval": 5,
    "sandbox": {
        "timeout": 30,
        "memory_limit_mb": 256,
    },
    "jupyter": {
        "port_start": 8888,
        "port_end": 8999,
        "start_timeout": 30,
        "memory_limit_mb": 512,
    },
}

_config_cache: Optional[Dict[str, Any]] = None
# 可重入锁：set_config / update_config 会在持锁状态下调用 load_config / 读盘辅助函数，
# 普通 Lock 会在冷缓存时自死锁（P0）。
_config_lock = threading.RLock()
_config_path: Optional[str] = None


def _find_settings_path() -> str:
    """定位 settings.json 文件路径。"""
    here = os.path.dirname(os.path.abspath(__file__))
    # mathlab/utils/ → mathlab/settings.json
    return os.path.join(here, "..", "settings.json")


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并字典，override 中的值覆盖 base 中的同名键。

    两侧都做深拷贝，避免把调用方的嵌套 dict 挂进全局缓存后形成隐式共享。
    """
    result = copy.deepcopy(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = copy.deepcopy(val)
    return result


def _read_config_file() -> Dict[str, Any]:
    """读取 settings.json 原始内容（不合并默认值、不更新缓存）。

    调用方必须已持有 ``_config_lock``。文件缺失或损坏时返回空字典，
    与 ``load_config()`` 的降级行为保持一致。
    """
    global _config_path
    if _config_path is None:
        _config_path = _find_settings_path()
    if not os.path.exists(_config_path):
        return {}
    try:
        with open(_config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            logger.warning("配置文件内容不是对象，已忽略: %s", _config_path)
            return {}
        return data
    except Exception as e:
        logger.warning("读取配置文件失败: %s", e)
        return {}


def _write_config_file(config: Dict[str, Any]) -> bool:
    """原子写入 settings.json（tmp + os.replace），调用方必须已持有锁。"""
    global _config_path
    if _config_path is None:
        _config_path = _find_settings_path()
    tmp_path = _config_path + ".tmp"
    try:
        os.makedirs(os.path.dirname(os.path.abspath(_config_path)), exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, _config_path)
        logger.info("配置已保存: %s", _config_path)
        return True
    except Exception as e:
        logger.error("保存配置失败: %s", e, exc_info=True)
        return False


def load_config(force_reload: bool = False) -> Dict[str, Any]:
    """加载并缓存配置。

    首次调用时从 settings.json 读取并与默认值合并。
    后续调用返回缓存，除非 force_reload=True。
    """
    global _config_cache
    with _config_lock:
        if _config_cache is not None and not force_reload:
            return _config_cache
        _config_cache = _deep_merge(copy.deepcopy(_DEFAULT_CONFIG), _read_config_file())
        return _config_cache


def get_config(key: str = None, default: Any = None) -> Any:
    """获取配置项。

    Args:
        key: 使用点号分隔的嵌套键路径，如 'ipc.server_port'。
             若为 None，返回整个配置字典。
        default: 键不存在时返回的默认值。

    Returns:
        配置值，或 default。
    """
    config = load_config()
    # 一律返回副本：调用方就地修改不应该穿透缓存（i18n_manager 曾这样做）
    with _config_lock:
        if key is None:
            return copy.deepcopy(config)

        parts = key.split(".")
        val = config
        for part in parts:
            if isinstance(val, dict) and part in val:
                val = val[part]
            else:
                return default
        return copy.deepcopy(val)


def set_config(key: str, value: Any) -> None:
    """运行时更新配置缓存中的某个键（不会持久化到文件）。

    注意：这是**进程内临时覆写**。``update_config()`` 会以磁盘内容为基准
    重建缓存，因此未落盘的覆写在下一次配置保存后不再保留；需要持久化请直接
    调用 ``update_config({key: value})``。
    """
    with _config_lock:
        if _config_cache is None:
            load_config()
        parts = key.split(".")
        target = _config_cache
        for part in parts[:-1]:
            if part not in target or not isinstance(target[part], dict):
                target[part] = {}
            target = target[part]
        target[parts[-1]] = value


def update_config(patch: Dict[str, Any]) -> bool:
    """把 ``patch`` 深度合并进 settings.json 并刷新缓存（唯一权威写入口）。

    写入前重新读取磁盘，因此任一写入方只传自己关心的键也不会覆盖掉
    theme / language / accent / enable_undo 等其它模块的设置。

    Args:
        patch: 需要持久化的配置片段，支持嵌套字典。

    Returns:
        写入成功返回 True；参数非法或写盘失败返回 False。
    """
    if not isinstance(patch, dict):
        logger.warning("update_config 需要 dict，实际为 %s", type(patch).__name__)
        return False

    global _config_cache
    with _config_lock:
        merged = _deep_merge(_read_config_file(), patch)
        if not _write_config_file(merged):
            return False
        _config_cache = _deep_merge(copy.deepcopy(_DEFAULT_CONFIG), merged)
        return True


def save_config(config: Dict[str, Any]) -> bool:
    """向后兼容入口：按合并语义写入，避免整字典覆盖丢失其它键。

    存量调用方常把 ``get_config()`` 的快照加一两个键后原样传回；
    这里委托 ``update_config()`` 做「读盘 → 合并 → 原子写」，不再直接覆盖文件。
    """
    return update_config(config)
