# -*- coding: utf-8 -*-
"""GUI长步骤采标工具-Android 的版本管理模块。

本模块是 GUI长步骤采标工具-Android 版本号与发布地址的唯一来源，
供 build_release.py（打包发布）和 updater.py（在线升级）共同导入。
与根目录 Windows 版共用同一套 DriveDeploy 更新机制，但发布到独立的
子目录、使用独立的 exe 名与版本号，互不影响。
"""

import re

# 语义化版本号：主版本号.次版本号.补丁号
__version__ = "1.0.6"

# UNC 网络共享发布目录（构建产物与 version.json 均发布于此）。
# 使用根发布目录下的独立子目录，避免与其他产品的 exe / 清单互相覆盖。
PUBLISH_DIR = r"\\NAS-TC\GUI采集300step\工具\GUI长步骤采标工具-Android"

# 发布的可执行文件名
EXE_NAME = "GUI长步骤采标工具-Android.exe"

# 版本清单文件名（记录最新版本号与下载地址等信息）
MANIFEST_NAME = "version.json"

# 使用捆绑了 scrcpy / adb 资源的 PyInstaller spec 文件打包
SPEC_FILE = "GUI长步骤采标工具-Android.spec"

# 版本号匹配正则：第一段 “数字.数字”，可再带一段 “.数字”
_VERSION_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")


def parse_version(text):
    """从字符串中提取版本号，返回整数元组 (主, 次, 补丁)。"""
    if not isinstance(text, str):
        return (0, 0, 0)
    match = _VERSION_RE.search(text)
    if not match:
        return (0, 0, 0)
    major = int(match.group(1))
    minor = int(match.group(2))
    patch = int(match.group(3)) if match.group(3) is not None else 0
    return (major, minor, patch)


def is_newer(remote, local):
    """比较两个版本字符串，remote 严格大于 local 时返回 True。"""
    return parse_version(remote) > parse_version(local)


def bump_patch(version):
    """补丁位 +1，返回新的版本字符串。"""
    major, minor, patch = parse_version(version)
    return "{}.{}.{}".format(major, minor, patch + 1)
