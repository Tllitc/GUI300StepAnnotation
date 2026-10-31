#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
iOS 截图模块
通过 go-ios (ios.exe) 命令行工具从 iPhone 截图
"""

import os
import subprocess
import tempfile
from datetime import datetime


class IOSScreenCapture:
    """iOS 截图器（基于 go-ios）"""

    def __init__(self, udid=None):
        self.udid = udid
        self.ios_exe = self._find_ios_exe()

    def _find_ios_exe(self):
        """查找 ios.exe 路径"""
        local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ios.exe")
        if os.path.isfile(local):
            return local
        return "ios.exe"

    def _get_env(self):
        """获取包含 tunnel 环境变量的 env dict"""
        env = os.environ.copy()
        env.setdefault("ENABLE_GO_IOS_AGENT", "user")
        return env

    def capture(self, output_path=None):
        """截取 iOS 设备屏幕

        参数:
            output_path: 输出文件路径，None 则保存到临时目录

        返回:
            (success: bool, filepath: str|None): 是否成功，文件路径
        """
        if output_path is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = os.path.join(tempfile.gettempdir(), f"ios_screenshot_{ts}.png")

        cmd = [self.ios_exe, "screenshot", f"--output={output_path}"]
        if self.udid:
            cmd.insert(1, f"--udid={self.udid}")

        env = self._get_env()

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=30,
                cwd=os.path.dirname(os.path.abspath(__file__)),
                env=env,
            )
        except subprocess.TimeoutExpired:
            print(f"[ERROR] 截图超时 (30s)")
            return False, None
        except FileNotFoundError:
            print(f"[ERROR] ios.exe 未找到: {self.ios_exe}")
            return False, None

        if proc.returncode != 0:
            print(f"[ERROR] 截图失败: {proc.stderr or proc.stdout}")
            return False, None

        if os.path.isfile(output_path) and os.path.getsize(output_path) > 0:
            return True, output_path

        print(f"[ERROR] 截图文件未生成: {output_path}")
        return False, None
