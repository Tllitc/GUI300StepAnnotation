# -*- coding: utf-8 -*-
"""一键构建并发布 GUI长步骤采标工具-iOS。

流程：
1. 检测 PyInstaller 是否已安装；
2. 确定本次发布版本号（--set-version 优先，否则取 app_version.__version__）；
3. 调用 PyInstaller 在项目根目录打包 main.py（--onefile --noconsole）；
4. 将 exe 复制到发布目录（默认 NAS 共享目录），并写入 version.json 清单；
5. 全部成功后，把 app_version.py 的 __version__ 补丁位 +1，供下次发布使用。

任何一步失败都会以非零退出码退出，且不会自增版本号。
"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime

import app_version

# 项目根目录 = 本脚本所在目录；PyInstaller 需在此目录下执行
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# 仅替换 app_version.py 中 __version__ = "x.y.z" 这一行
_VERSION_LINE_RE = re.compile(r'^(__version__\s*=\s*")[^"]*(")', re.MULTILINE)

# 校验手动指定的版本号格式：X.Y.Z（三段纯数字）
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def update_version_file(version):
    """把 app_version.py 中的 __version__ 行替换为指定版本，其余内容不动。"""
    version_path = app_version.__file__
    # newline="" 读取与写回，保留原有的换行符风格（CRLF/LF）
    with open(version_path, "r", encoding="utf-8", newline="") as f:
        content = f.read()
    new_content, count = _VERSION_LINE_RE.subn(
        lambda match: match.group(1) + version + match.group(2),
        content,
        count=1,
    )
    if count != 1:
        raise RuntimeError("未能在 app_version.py 中定位 __version__ 行，版本号未写回")
    with open(version_path, "w", encoding="utf-8", newline="") as f:
        f.write(new_content)


def check_pyinstaller():
    """检测 PyInstaller 是否安装；未安装时打印提示并退出。"""
    try:
        import PyInstaller
    except ImportError:
        print("请先安装 PyInstaller：pip install pyinstaller")
        sys.exit(1)
    print(f"检测到 PyInstaller 版本：{PyInstaller.__version__}")
    return PyInstaller


def build_executable(PyInstaller):
    """调用 PyInstaller 打包，返回生成的 exe 绝对路径。

    若 app_version.SPEC_FILE 指定了 .spec 文件（用于需要捆绑外部资源的
    产品，如安卓端 scrcpy、iOS 端 ios.exe），则按 spec 打包；否则使用
    内置命令行参数打包入口脚本 main.py。
    """
    exe_stem = os.path.splitext(app_version.EXE_NAME)[0]
    spec_file = getattr(app_version, "SPEC_FILE", None)
    import PyInstaller.__main__

    # 显式指定输出目录，避免 PyInstaller 在 import 时按启动 cwd 固化默认路径，
    # 导致从其他目录启动本脚本时产物落到上级目录
    dist_dir = os.path.join(PROJECT_ROOT, "dist")
    work_dir = os.path.join(PROJECT_ROOT, "build")

    if spec_file:
        spec_path = os.path.join(PROJECT_ROOT, spec_file)
        if not os.path.isfile(spec_path):
            raise RuntimeError(f"未找到 PyInstaller spec 文件：{spec_path}")
        pyi_args = [
            spec_path,
            "--clean",
            "--noconfirm",
            "--distpath",
            dist_dir,
            "--workpath",
            work_dir,
        ]
        print(f"开始 PyInstaller 打包（spec：{spec_file}）...")
    else:
        pyi_args = [
            "--onefile",
            "--noconsole",
            "--clean",
            "--noconfirm",
            "--distpath",
            dist_dir,
            "--workpath",
            work_dir,
            "--name",
            exe_stem,
            "--icon",
            "logo17.ico",
            "main.py",
        ]
        print("开始 PyInstaller 打包 ...")

    try:
        PyInstaller.__main__.run(pyi_args)
    except SystemExit as exc:
        if exc.code not in (0, None):
            raise RuntimeError(f"PyInstaller 打包失败（退出码 {exc.code}）")
    exe_path = os.path.join(PROJECT_ROOT, "dist", app_version.EXE_NAME)
    if not os.path.isfile(exe_path):
        raise RuntimeError(f"打包结束但未找到产物：{exe_path}")
    print(f"打包成功：{exe_path}")
    return exe_path


def publish(exe_path, publish_dir, version):
    """复制 exe 到发布目录并写入 version.json，两步必须都成功。"""
    print(f"发布目录：{publish_dir}")
    os.makedirs(publish_dir, exist_ok=True)

    dest_exe = os.path.join(publish_dir, app_version.EXE_NAME)
    print(f"复制 exe：{exe_path} -> {dest_exe}")
    shutil.copy2(exe_path, dest_exe)

    manifest = {
        "version": version,
        "exe": app_version.EXE_NAME,
        "published_at": datetime.now().isoformat(),
    }
    manifest_path = os.path.join(publish_dir, app_version.MANIFEST_NAME)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"已写入版本清单：{manifest_path}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="使用 PyInstaller 一键构建 GUI长步骤采标工具-iOS 并发布到共享目录"
    )
    parser.add_argument(
        "--publish-dir",
        default=app_version.PUBLISH_DIR,
        help=f"发布目录，默认 {app_version.PUBLISH_DIR}",
    )
    parser.add_argument(
        "--set-version",
        metavar="X.Y.Z",
        default=None,
        help="手动指定本次发布版本（如 1.2.0），会先写回 app_version.py 再构建",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # 构建前必须确认 PyInstaller 可用
    PyInstaller = check_pyinstaller()

    # 确定本次发布版本号
    if args.set_version is not None:
        if not _SEMVER_RE.match(args.set_version):
            raise RuntimeError(f"版本号格式非法（应为 X.Y.Z）：{args.set_version}")
        version = args.set_version
        update_version_file(version)
        print(f"已按 --set-version 将版本写回 app_version.py：{version}")
    else:
        version = app_version.__version__
    print(f"本次发布版本：{version}")

    # 切到项目根目录执行打包（4 个本地依赖模块由 import 分析自动收集）
    os.chdir(PROJECT_ROOT)
    exe_path = build_executable(PyInstaller)

    # 发布失败不得自增版本号
    publish(exe_path, args.publish_dir, version)

    # 全部成功，补丁位 +1 写回，供下次发布使用
    next_version = app_version.bump_patch(version)
    update_version_file(next_version)

    print("发布完成！")
    print(f"  本次发布版本：{version}")
    print(f"  发布目录：{args.publish_dir}")
    print(f"  下一版本号：{next_version}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        # 参数错误、PyInstaller 缺失等已自行 sys.exit 的场景直接向上抛
        raise
    except Exception as exc:
        print(f"构建发布失败：{exc}")
        sys.exit(1)
