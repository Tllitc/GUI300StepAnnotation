# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置 - GUI长步骤采标工具-macOS

用法:
    pyinstaller main.spec --noconfirm
产物:
    dist/GUI长步骤采标工具-macOS.app

说明:
- 应用依赖 PyQt5（界面）、pynput（全局快捷键，独立子进程）、pyobjc（macOS 系统能力）。
- 使用 multiprocessing 启动快捷键子进程，main.py 已调用 freeze_support()，无需额外 hooks。
- 首次运行需在「系统设置 > 隐私与安全性」中授予「屏幕录制」和「辅助功能」权限。
"""

APP_NAME = 'GUI长步骤采标工具-macOS'
BUNDLE_IDENTIFIER = 'com.annotation.macos.guitool'
ICON_FILE = 'logo.icns'
VERSION = '1.0.0'

# pynput 在 macOS 下的后端为延迟导入，显式声明以避免被遗漏
hidden_imports = [
    'pynput.keyboard._darwin',
    'pynput.mouse._darwin',
    'pynput._util.darwin',
]

# 排除仅适用于 Linux/Windows 的后端，减小体积
excludes = [
    'pynput.keyboard._xorg',
    'pynput.keyboard._uinput',
    'pynput.mouse._xorg',
    'pynput.mouse._uinput',
    'Xlib',
    'evdev',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_FILE,
)

app = BUNDLE(
    exe,
    name=f'{APP_NAME}.app',
    icon=ICON_FILE,
    bundle_identifier=BUNDLE_IDENTIFIER,
    info_plist={
        'CFBundleName': APP_NAME,
        'CFBundleDisplayName': APP_NAME,
        'CFBundleIdentifier': BUNDLE_IDENTIFIER,
        'CFBundleShortVersionString': VERSION,
        'CFBundleVersion': VERSION,
        'CFBundleExecutable': APP_NAME,
        # Retina 高清渲染
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '10.13.0',
        # 全局快捷键 / 自动化需要控制其他应用
        'NSAppleEventsUsageDescription': '本应用需要辅助功能权限以监听全局快捷键，完成 GUI 操作采集。',
        # 保留 Dock 图标与常规窗口行为
        'LSUIElement': False,
    },
)
