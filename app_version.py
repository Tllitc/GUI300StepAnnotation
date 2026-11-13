# -*- coding: utf-8 -*-
"""版本管理模块。

本模块是 GUI长步骤采标工具-Windows 版本号与发布地址的唯一来源，
供 build_release.py（打包发布）和 updater.py（在线升级）共同导入，
避免版本号在多处维护导致不一致。
"""

import re

# 语义化版本号：主版本号.次版本号.补丁号
__version__ = "1.0.8"

# UNC 网络共享发布目录（构建产物与 version.json 均发布于此）
PUBLISH_DIR = r"\\NAS-TC\GUI采集300step\工具\GUI长步骤采标工具-Windows"

# 发布的可执行文件名
EXE_NAME = "GUI长步骤采标工具-Windows.exe"

# 版本清单文件名（记录最新版本号与下载地址等信息）
MANIFEST_NAME = "version.json"

# 可选：指定 PyInstaller .spec 文件进行打包（用于需要捆绑外部资源的产品，
# 如安卓端的 scrcpy、iOS 端的 ios.exe）。为 None 时 build_release.py 使用
# 内置命令行参数打包入口脚本。多产品各自的 app_version.py 可覆盖此项。
SPEC_FILE = None

# 版本号匹配正则：第一段 “数字.数字”，可再带一段 “.数字”
# 例如 "1.0.3"、"v2.5" 均可识别；单独的数字不予匹配
_VERSION_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")


def parse_version(text):
    """从字符串中提取版本号，返回整数元组 (主, 次, 补丁)。

    容错规则：
    - 用正则提取第一段 “数字.数字.数字”，如 "v1.2.3-beta" -> (1, 2, 3)；
    - 只有两段时（如 "1.2"）补丁位补 0，返回 (1, 2, 0)；
    - 输入为空、非字符串或无法提取时，返回 (0, 0, 0)。
    """
    if not isinstance(text, str):
        return (0, 0, 0)
    match = _VERSION_RE.search(text)
    if not match:
        return (0, 0, 0)
    major = int(match.group(1))
    minor = int(match.group(2))
    # 第三段缺省时补 0（如 "1.2" -> (1, 2, 0)）
    patch = int(match.group(3)) if match.group(3) is not None else 0
    return (major, minor, patch)


def is_newer(remote, local):
    """比较两个版本字符串，remote 严格大于 local 时返回 True。"""
    return parse_version(remote) > parse_version(local)


def bump_patch(version):
    """补丁位 +1，返回新的版本字符串。

    例如 "1.0.3" -> "1.0.4"、"2.5.9" -> "2.5.10"；
    非法输入按 (0, 0, 0) 处理，返回 "0.0.1"。
    """
    major, minor, patch = parse_version(version)
    return "{}.{}.{}".format(major, minor, patch + 1)
