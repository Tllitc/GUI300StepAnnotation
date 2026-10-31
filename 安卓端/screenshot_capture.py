#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Android 截图模块
通过 ADB 命令截取手机屏幕
"""

import os
import subprocess
import tempfile


def find_adb_path():
    """查找 adb.exe 路径（优先使用项目内 scrcpy 自带的 adb）"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # 优先使用 scrcpy_4.0 目录下的 adb
    adb_candidates = [
        os.path.join(script_dir, 'scrcpy_4.0', 'adb.exe'),
        os.path.join(script_dir, 'scrcpy', 'adb.exe'),
    ]
    for p in adb_candidates:
        if os.path.isfile(p):
            return p
    return 'adb'


class AndroidScreenCapture:
    """Android ADB 截图器"""

    def __init__(self, serial=None):
        self._serial = serial
        self._adb_path = find_adb_path()

    def set_serial(self, serial):
        """设置目标设备 serial，使后续 ADB 命令带上 -s 参数"""
        self._serial = serial

    def _adb_cmd(self, *args):
        """构造 ADB 命令"""
        cmd = [self._adb_path]
        if self._serial:
            cmd += ['-s', self._serial]
        cmd += list(args)
        return cmd

    def capture(self, output_path=None):
        """通过 ADB 截取手机屏幕，保存为 PNG 文件

        返回 (success, filepath)
        """
        if output_path is None:
            output_path = os.path.join(tempfile.gettempdir(),
                                       f"android_capture_tmp_{os.getpid()}.png")

        try:
            # adb exec-out screencap -p 获取 PNG 截图
            cmd = self._adb_cmd('exec-out', 'screencap', '-p')
            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=15
            )
            if proc.returncode != 0:
                print(f"[ADB] 截图失败: {proc.stderr.decode('utf-8', errors='replace')}")
                return False, None

            # sceencap 可能把警告文本(如 Multiple displays found)写到 stdout，
            # 混在 PNG 数据之前，破坏 PNG 文件头。PNG 签名固定为 8 字节，
            # 这里从签名处截取，丢弃签名之前可能存在的警告内容。
            png_signature = b'\x89PNG\r\n\x1a\n'
            sig_idx = proc.stdout.find(png_signature)
            if sig_idx < 0:
                print(f"[ADB] 截图输出不包含有效的 PNG 签名")
                return False, None
            png_data = proc.stdout[sig_idx:]

            with open(output_path, 'wb') as f:
                f.write(png_data)

            if os.path.getsize(output_path) > 0:
                return True, output_path
            else:
                return False, None

        except subprocess.TimeoutExpired:
            print("[ADB] 截图超时")
            return False, None
        except Exception as e:
            print(f"[ADB] 截图异常: {e}")
            return False, None

    def get_screen_size(self):
        """通过 ADB 获取手机物理分辨率，返回 [width, height]"""
        try:
            cmd = self._adb_cmd('shell', 'wm', 'size')
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            output = proc.stdout.strip()

            if 'Physical size:' in output:
                size_str = output.split('Physical size:')[-1].strip()
            elif 'Override size:' in output:
                size_str = output.split('Override size:')[-1].strip()
            else:
                print(f"[ADB] 未识别 wm size 输出: {output}")
                return [1080, 2400]

            w_str, h_str = size_str.split('x')
            return [int(w_str), int(h_str)]
        except Exception as e:
            print(f"[ADB] 获取分辨率异常: {e}")
            return [1080, 2400]

    def _getprop(self, key):
        """读取单个系统属性"""
        try:
            cmd = self._adb_cmd('shell', 'getprop', key)
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return proc.stdout.strip()
        except Exception:
            return ""

    def get_device_info(self):
        """通过 ADB 获取设备基本信息，识别实际平台与系统版本"""
        info = {"platform": "Android", "system": ""}

        try:
            android_release = self._getprop("ro.build.version.release")
            device_model = self._getprop("ro.product.model")

            # 各厂商定制系统版本
            harmony_version = self._getprop("ro.build.version.harmonyos")
            if not harmony_version:
                harmony_version = self._getprop("ro.build.harmony.os.version")
            hyperos_version = self._getprop("ro.mi.os.version.name")
            miui_version = self._getprop("ro.miui.ui.version.name")
            oplus_version = self._getprop("ro.build.version.oplusrom")
            if not oplus_version:
                oplus_version = self._getprop("ro.build.version.opporom")
            originos_version = self._getprop("ro.vivo.os.build.display.id")
            if not originos_version:
                originos_version = self._getprop("ro.vivo.os.version")

            if harmony_version:
                platform = "HarmonyOS"
                system_name = "HarmonyOS"
                system_version = harmony_version
            elif hyperos_version:
                platform = "HyperOS"
                system_name = "HyperOS"
                system_version = hyperos_version
            elif oplus_version:
                platform = "ColorOS"
                system_name = "ColorOS"
                system_version = oplus_version
            elif originos_version:
                platform = "OriginOS"
                system_name = "OriginOS"
                system_version = originos_version
            elif miui_version:
                platform = "Android"
                system_name = "MIUI"
                system_version = miui_version
            else:
                platform = "Android"
                system_name = "Android"
                system_version = android_release

            info["platform"] = platform
            info["system"] = f"{system_name} {system_version}".strip()
            info["android_version"] = android_release

            if device_model:
                info["device_model"] = device_model

            info["screen_size"] = self.get_screen_size()

        except Exception as e:
            print(f"[ADB] 获取设备信息异常: {e}")
            info["screen_size"] = [1080, 2400]

        return info

    def check_device(self):
        """检查是否有已连接的 Android 设备，返回 (has_device, serial)"""
        try:
            cmd = [self._adb_path, 'devices']
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            lines = proc.stdout.strip().split('\n')[1:]  # 跳过第一行 "List of devices attached"
            for line in lines:
                line = line.strip()
                if line and '\tdevice' in line:
                    serial = line.split('\t')[0]
                    return True, serial
            return False, None
        except Exception as e:
            print(f"[ADB] 检测设备异常: {e}")
            return False, None
