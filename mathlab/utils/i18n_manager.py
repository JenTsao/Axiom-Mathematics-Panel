from __future__ import annotations

import json
import os
import sys

DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = {"en": "English", "zh": "中文"}


class I18nManager:
    """Singleton i18n manager with language-change notification support."""

    _instance = None
    _CACHE_MAX_SIZE = 256  # LRU 缓存上限

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(I18nManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self.current_language = DEFAULT_LANGUAGE
        self.translations: dict = {}
        self._listeners: list = []  # list[callable]
        self._lookup_cache: dict = {}  # {(lang, key): raw_value} — 翻译键查找缓存

        self._load_translations()
        self._restore_language_from_config()

    # ------------------------------------------------------------------
    # Translation loading
    # ------------------------------------------------------------------
    def _restore_language_from_config(self):
        """从配置文件恢复用户上次保存的语言设置。

        避免重启后语言回到默认值的问题。
        """
        try:
            from mathlab.utils.config_manager import get_config

            saved_lang = get_config("language")
            if saved_lang and saved_lang in SUPPORTED_LANGUAGES:
                self.current_language = saved_lang
                print(f"[I18n] Restored language from config: {saved_lang}")
        except Exception as e:
            print(f"[I18n] Failed to restore language from config: {e}")

    def _load_translations(self):
        # 🚨 动态判断运行环境
        if getattr(sys, "frozen", False):
            # PyInstaller 打包后的临时运行目录
            base_dir = sys._MEIPASS
        else:
            # 本地源码开发环境
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        locale_dir = os.path.join(base_dir, "locale")

        if not os.path.exists(locale_dir):
            print(f"[I18n Error] Locale directory not found: {locale_dir}")

        for lang_code in SUPPORTED_LANGUAGES:
            file_path = os.path.join(locale_dir, f"{lang_code}.json")
            if os.path.exists(file_path):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        self.translations[lang_code] = json.load(f)
                    print(f"[I18n Success] Loaded language package: {lang_code}")
                except json.JSONDecodeError as e:
                    print(f"[I18n Fatal] JSON corrupted {lang_code}.json: {e}")
                except Exception as e:
                    print(f"[I18n Error] loading {file_path}: {e}")
            else:
                print(f"[I18n Error] Language file not found: {file_path}")

    # ------------------------------------------------------------------
    # Language management
    # ------------------------------------------------------------------
    def set_language(self, lang_code: str) -> bool:
        """Change the active language and notify all registered listeners."""
        if lang_code not in SUPPORTED_LANGUAGES:
            return False
        if lang_code == self.current_language:
            return True
        self.current_language = lang_code
        self._lookup_cache.clear()  # 语言切换时清空缓存
        self._save_language_to_config(lang_code)
        self._notify_listeners(lang_code)
        return True

    def _save_language_to_config(self, lang_code: str):
        """将语言设置保存到配置文件，确保重启后生效。"""
        try:
            from mathlab.utils.config_manager import update_config

            # 只提交自己关心的键；旧写法 get_config() + save_config() 会把
            # 整份缓存覆盖回磁盘，抹掉 theme / accent 等其它模块的设置。
            update_config({"language": lang_code})
            print(f"[I18n] Language saved to config: {lang_code}")
        except Exception as e:
            print(f"[I18n] Failed to save language to config: {e}")

    def get_language(self) -> str:
        return self.current_language

    def get_supported_languages(self) -> dict:
        return SUPPORTED_LANGUAGES

    # ------------------------------------------------------------------
    # Listener registration
    # ------------------------------------------------------------------
    def add_language_change_listener(self, callback) -> None:
        """Register *callback(lang_code: str)* to be called on language change."""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def remove_language_change_listener(self, callback) -> None:
        """Unregister a previously registered callback."""
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _notify_listeners(self, lang_code: str) -> None:
        for cb in list(self._listeners):
            try:
                cb(lang_code)
            except Exception as e:
                print(f"[i18n] Listener error: {e}")

    # ------------------------------------------------------------------
    # Translation lookup
    # ------------------------------------------------------------------
    def t(self, key: str, *args, **kwargs) -> str:
        """
        Translate *key* (dot-separated path) with optional format arguments.

        Returns the *key* itself when a translation is not found so the UI
        always shows something useful instead of crashing.
        """
        # 缓存键 = (语言, 翻译键)，加速高频重复查找
        cache_key = (self.current_language, key)
        if cache_key in self._lookup_cache:
            raw_value = self._lookup_cache.pop(cache_key)
            self._lookup_cache[cache_key] = raw_value
        else:
            keys = key.split(".")
            value = self.translations.get(self.current_language, {})

            for k in keys:
                if not isinstance(value, dict):
                    return key
                value = value.get(k)
                if value is None:
                    return key

            if not isinstance(value, str):
                return key

            raw_value = value
            # LRU 淘汰：缓存满时删除最早条目
            if len(self._lookup_cache) >= self._CACHE_MAX_SIZE:
                self._lookup_cache.pop(next(iter(self._lookup_cache)))
            self._lookup_cache[cache_key] = raw_value

        # 格式化参数
        if not args and not kwargs:
            return raw_value

        try:
            return raw_value.format(*args, **kwargs)
        except (IndexError, KeyError):
            return raw_value


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------
_i18n: I18nManager | None = None


def get_i18n() -> I18nManager:
    global _i18n
    if _i18n is None:
        _i18n = I18nManager()
    return _i18n


def t(key: str, *args, **kwargs) -> str:
    """Shorthand for ``get_i18n().t(key, ...)``."""
    return get_i18n().t(key, *args, **kwargs)
