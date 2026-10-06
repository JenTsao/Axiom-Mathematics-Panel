# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import copy_metadata, collect_data_files

block_cipher = None

# 1. 静态资源映射：确保 HTML 渲染器、提示词模板等被正确打包
added_files = [
    ('mathlab/resources/chat_renderer.html', 'mathlab/resources'),
    ('mathlab/config/prompts.yaml', 'mathlab/config'),
    ('mathlab/resources/monaco.html', 'mathlab/resources'),
    ('mathlab/resources/dist/*', 'mathlab/resources/dist'),
    ('MathLab.CSharpEngine/bin/Release/netstandard2.0/*.dll', 'MathLab.CSharpEngine/bin/Release/netstandard2.0'),
    ('mathlab/locale/*', 'locale'),
    ('mathlab/ui/*.qss', 'mathlab/ui'),
    ('mathlab/resources/icons/*', 'mathlab/resources/icons'),
    # 若有本地图标，请取消下方注释
    # ('mathlab/resources/icon.ico', 'mathlab/resources'),
]
# 收集 rfc3987_syntax 包的数据文件（.lark 语法文件）
# [P0 发布链修复] 原实现无条件 `import rfc3987_syntax`，但它是 jsonschema 的可选传递依赖，
# 没有出现在 requirements.txt 里 —— 干净环境执行 pyinstaller 会直接 ModuleNotFoundError。
import os

try:
    import rfc3987_syntax

    rfc3987_syntax_dir = os.path.dirname(rfc3987_syntax.__file__)
    added_files += [(os.path.join(rfc3987_syntax_dir, 'syntax_rfc3987.lark'), 'rfc3987_syntax')]
except ImportError:
    print('rfc3987_syntax 未安装，跳过其 .lark 语法文件收集')

# [P0 发布链修复] 内嵌 JupyterLab 需要它的静态前端资源（HTML/JS/CSS）。
# 缺这段时打包出的发行包里 Jupyter 标签页只有后端没有界面；
# build_spec.spec 早已收集，CI 用的这份根 spec 一直没同步。
for _pkg in ('jupyterlab', 'jupyterlab_server', 'notebook', 'ipykernel', 'jupyter_server'):
    try:
        added_files += collect_data_files(_pkg)
    except Exception as _exc:  # 可选依赖缺失不应该让构建整体失败
        print('collect_data_files(%s) 跳过: %s' % (_pkg, _exc))

for _pkg in ('jupyter_client', 'jupyterlab', 'jupyter_server'):
    try:
        added_files += copy_metadata(_pkg)
    except Exception as _exc:
        print('copy_metadata(%s) 跳过: %s' % (_pkg, _exc))

# 2. 隐式依赖声明：强制打包动态加载的引擎和代理
hidden_imports = [
    'PySide6.QtWebEngineCore',
    'PySide6.QtWebEngineWidgets',
    'mathlab.core.agent_registry',
    'mathlab.core.context_assembler',
    'jupyter_client.provisioning.local_provisioner',
    'markdown',
    'ipykernel',
    'runpy',
    'jedi',
    'mathlab.ui.code_editor',
    'unicodedata',
    'sympy.parsing.latex',
    'mpmath',
    'scipy.special',
    'PySide6.QtNetwork',
    'PySide6.QtPrintSupport',
    'markdown.extensions.fenced_code',
    'markdown.extensions.tables',
    'markdown.extensions.toc',
    'mathlab.core.sandbox_script',
    # JupyterLab 相关依赖（PyInstaller 静态分析可能遗漏）
    'jupyterlab',
    'jupyterlab.labapp',
    'jupyter_core',
    'ipykernel_launcher',
    # rfc3987_syntax 依赖（jsonschema 需要）
    'rfc3987_syntax',
]

a = Analysis(
    ['mathlab/main.py'], 
    pathex=[],
    binaries=[],
    datas=added_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PyQt6', 'PySide2'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# 3. 生成 Windows 专属的可执行程序
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MathLab',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False, # 设为 False 以隐藏黑色控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MathLab',
)

# 4. 生成 macOS 专属的 .app 应用程序包
app = BUNDLE(
    coll,
    name='MathLab.app',
    icon=None,
    bundle_identifier='com.commander.mathlab',
)
