"""统一配置管理模块。

从 settings.json 加载配置，支持默认值、嵌套键访问和运行时覆写。
所有模块应通过 get_config() 获取配置，而非各自硬编码。
"""

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
    # D-3：撤销栈启用开关（关闭时 Ctrl+Z 灰置，UndoStack 零开销）
    "enable_undo": True,
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
_config_lock = threading.Lock()
_config_path: Optional[str] = None


def _find_settings_path() -> str:
    """定位 settings.json 文件路径。"""
    here = os.path.dirname(os.path.abspath(__file__))
    # mathlab/utils/ → mathlab/settings.json
    return os.path.join(here, "..", "settings.json")


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并字典，override 中的值覆盖 base 中的同名键。"""
    result = base.copy()
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def load_config(force_reload: bool = False) -> Dict[str, Any]:
    """加载并缓存配置。

    首次调用时从 settings.json 读取并与默认值合并。
    后续调用返回缓存，除非 force_reload=True。
    """
    global _config_cache
    with _config_lock:
        if _config_cache is not None and not force_reload:
            return _config_cache

        global _config_path
        if _config_path is None:
            _config_path = _find_settings_path()

        config = _DEFAULT_CONFIG.copy()
        if os.path.exists(_config_path):
            try:
                with open(_config_path, "r", encoding="utf-8") as f:
                    user_config = json.load(f)
                config = _deep_merge(config, user_config)
                logger.debug("配置加载完毕: %s", _config_path)
            except Exception as e:
                logger.warning("加载配置文件失败，使用默认配置: %s", e)
        else:
            logger.debug("配置文件不存在，使用默认配置: %s", _config_path)

        _config_cache = config
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
    if key is None:
        return config

    parts = key.split(".")
    val = config
    for part in parts:
        if isinstance(val, dict) and part in val:
            val = val[part]
        else:
            return default
    return val


def set_config(key: str, value: Any) -> None:
    """运行时更新配置缓存中的某个键（不会持久化到文件）。"""
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


def save_config(config: Dict[str, Any]) -> bool:
    """将配置持久化到 settings.json。"""
    global _config_path
    if _config_path is None:
        _config_path = _find_settings_path()
    try:
        with open(_config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        with _config_lock:
            global _config_cache
            _config_cache = config.copy()
        logger.info("配置已保存: %s", _config_path)
        return True
    except Exception as e:
        logger.error("保存配置失败: %s", e)
        return False
