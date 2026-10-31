#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据管理模块
负责数据目录创建、文件保存、JSON 格式化管理等
跨平台支持：Windows / macOS
"""

import os
import re
import glob
import json
import platform
import subprocess
import ctypes

from PyQt5.QtGui import QPixmap


class DataManager:
    """数据管理器（跨平台）"""

    def __init__(self, base_dir=None):
        """
        初始化数据管理器
        :param base_dir: 基础目录，gui 文件夹将直接创建在此目录下
        """
        if base_dir is None:
            base_dir = os.getcwd()
        self.base_dir = base_dir
        self.current_dir = base_dir
        self._system = platform.system()

    def create_task_directory(self, platform_name, app_type, app_name):
        """
        设置任务目录为 base_dir，gui_编号 文件夹将直接创建在此目录下
        :param platform_name: 平台名称 (mac, windows, ios, android) - 保留参数兼容性
        :param app_type: 软件类型 (社交、电商等) - 保留参数兼容性
        :param app_name: 具体软件名称 - 保留参数兼容性
        :return: True if success, False otherwise
        """
        try:
            os.makedirs(self.base_dir, exist_ok=True)
            self.current_dir = self.base_dir
            return True
        except Exception as e:
            print(f"设置任务目录失败: {e}")
            return False

    def get_next_gui_number(self):
        """
        获取下一个 GUI 编号（六位数字）
        :return: 例如 "000001"
        """
        gui_dirs = [d for d in os.listdir(self.current_dir)
                   if os.path.isdir(os.path.join(self.current_dir, d)) and d.startswith("gui_")]

        if not gui_dirs:
            return "000001"

        numbers = []
        for d in gui_dirs:
            try:
                num_str = d.replace("gui_", "")
                numbers.append(int(num_str))
            except:
                continue

        if numbers:
            next_num = max(numbers) + 1
        else:
            next_num = 1

        return f"{next_num:06d}"

    def create_gui_directory(self, gui_number):
        """
        创建 GUI 编号文件夹
        :param gui_number: GUI 编号，例如 "000001"
        :return: GUI 文件夹路径
        """
        gui_dir_name = f"gui_{gui_number}"
        gui_dir_path = os.path.join(self.current_dir, gui_dir_name)
        os.makedirs(gui_dir_path, exist_ok=True)
        return gui_dir_path

    def get_next_screenshot_number(self, gui_number, gui_dir=None):
        """
        获取下一个截图编号
        :param gui_number: GUI 编号，例如 "000001"
        :param gui_dir: GUI 文件夹路径，如果为 None 则使用 current_dir
        :return: 例如 "0001"
        """
        if gui_dir is None:
            gui_dir = os.path.join(self.current_dir, f"gui_{gui_number}")

        prefix = f"gui_{gui_number}_"
        screenshot_files = [f for f in os.listdir(gui_dir)
                          if f.startswith(prefix) and f.endswith((".png", ".jpg"))]

        if not screenshot_files:
            return "0001"

        numbers = []
        for f in screenshot_files:
            try:
                num_str = f.replace(prefix, "").split(".")[0]
                numbers.append(int(num_str))
            except:
                continue

        if numbers:
            next_num = max(numbers) + 1
        else:
            next_num = 1

        return f"{next_num:04d}"

    def save_screenshot(self, image_data, gui_number, format="PNG"):
        """
        保存截图文件到对应的 gui_编号文件夹
        :param image_data: PIL Image 对象或字节数据
        :param gui_number: GUI 编号
        :param format: 图片格式 (PNG 或 JPG)
        :return: 文件路径
        """
        gui_dir = self.create_gui_directory(gui_number)

        ext = "png" if format == "PNG" else "jpg"
        # 生成递增的文件名: gui_编号_序号.ext（轮询时序号递增不重复）
        number = self.get_next_screenshot_number(gui_number, gui_dir)
        filename = f"gui_{gui_number}_{number}.{ext}"
        filepath = os.path.join(gui_dir, filename)

        try:
            if hasattr(image_data, 'save'):
                # PIL Image 对象
                if format == "JPG":
                    image_data.save(filepath, "JPEG", quality=95)
                else:
                    image_data.save(filepath, "PNG")
            else:
                # 字节数据
                with open(filepath, 'wb') as f:
                    f.write(image_data)

            return filepath
        except Exception as e:
            print(f"保存截图失败: {e}")
            return None

    def save_screenshot_overwrite(self, image_data, gui_number, filename, format="PNG"):
        """
        将截图覆盖保存到指定文件名（复用原序号，绝不分配新序号）
        :param image_data: PIL Image / QPixmap 对象或字节数据
        :param gui_number: GUI 编号
        :param filename: 原截图文件名，例如 "gui_000001_0003.png"
        :param format: 图片格式 (PNG 或 JPG)
        :return: 文件路径；文件名校验不通过或保存失败时返回 None
        """
        if not filename:
            print("覆盖保存截图失败: 文件名为空")
            return None

        # 仅允许写入当前 gui 目录下属于该 gui 编号的截图，防止路径穿越/写错文件
        safe_name = os.path.basename(filename)
        prefix = f"gui_{gui_number}_"
        if not safe_name.startswith(prefix) or not safe_name.endswith((".png", ".jpg")):
            print(f"覆盖保存截图失败: 非法文件名 {filename}")
            return None

        gui_dir = self.create_gui_directory(gui_number)
        filepath = os.path.join(gui_dir, safe_name)

        try:
            if hasattr(image_data, 'save'):
                # PIL Image / QPixmap 对象
                if format == "JPG":
                    image_data.save(filepath, "JPEG", quality=95)
                else:
                    image_data.save(filepath, "PNG")
            else:
                # 字节数据
                with open(filepath, 'wb') as f:
                    f.write(image_data)

            return filepath
        except Exception as e:
            print(f"覆盖保存截图失败: {e}")
            return None

    def load_screenshot(self, gui_number, filename):
        """
        从磁盘加载截图（内存解耦后预览图按需从文件重建）
        :param gui_number: GUI 编号
        :param filename: 截图文件名，例如 "gui_000001_0003.png"
        :return: QPixmap；文件不存在或加载失败时返回 None
        """
        if not filename:
            return None
        filepath = os.path.join(self.current_dir, f"gui_{gui_number}", filename)
        try:
            pixmap = QPixmap(filepath)
            if pixmap.isNull():
                print(f"加载截图失败: {filepath}")
                return None
            return pixmap
        except Exception as e:
            print(f"加载截图异常: {e}")
            return None

    def save_draft(self, draft, gui_number):
        """
        保存增量草稿 JSON（防崩溃/续采）
        :param draft: 草稿字典
        :param gui_number: GUI 编号
        :return: 文件路径或 None
        """
        gui_dir = self.create_gui_directory(gui_number)
        filename = f"gui_{gui_number}_draft.json"
        filepath = os.path.join(gui_dir, filename)

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(draft, f, ensure_ascii=False, indent=2)
            return filepath
        except Exception as e:
            print(f"保存草稿失败: {e}")
            return None

    def load_draft(self, gui_number):
        """
        读取增量草稿 JSON
        :param gui_number: GUI 编号
        :return: 草稿字典；不存在或损坏时返回 None
        """
        filepath = os.path.join(self.current_dir, f"gui_{gui_number}",
                                f"gui_{gui_number}_draft.json")
        try:
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"加载草稿失败: {e}")

        return None

    def delete_draft(self, gui_number):
        """
        删除增量草稿文件（最终数据成功落盘后调用）
        :param gui_number: GUI 编号
        """
        filepath = os.path.join(self.current_dir, f"gui_{gui_number}",
                                f"gui_{gui_number}_draft.json")
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception as e:
            print(f"删除草稿失败: {e}")

    @staticmethod
    def load_draft_from_dir(gui_dir_path):
        """
        在指定 gui 目录中查找并读取 *_draft.json
        :param gui_dir_path: gui_xxxxxx 目录完整路径
        :return: 草稿字典；不存在或损坏时返回 None
        """
        try:
            draft_files = glob.glob(os.path.join(gui_dir_path, "*_draft.json"))
            if not draft_files:
                return None
            with open(draft_files[0], 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"加载草稿失败: {e}")
            return None

    @staticmethod
    def load_json_from_dir(gui_dir_path):
        """
        读取 gui_xxxxxx 目录下的最终 JSON（已完成任务）
        :param gui_dir_path: gui_xxxxxx 目录完整路径
        :return: (data_or_None, error_or_None)
        """
        if not gui_dir_path:
            return None, "请选择 gui_xxxxxx 形式的任务目录"

        dir_name = os.path.basename(os.path.normpath(gui_dir_path))
        match = re.fullmatch(r"gui_(\d{6})", dir_name)
        if not match:
            return None, "请选择 gui_xxxxxx 形式的任务目录"

        gui_number = match.group(1)
        filepath = os.path.join(gui_dir_path, f"gui_{gui_number}.json")
        if not os.path.exists(filepath):
            return None, "该任务尚未完成，请使用『继续未完成任务』"

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f), None
        except Exception as e:
            return None, f"任务 JSON 解析失败: {e}"

    @staticmethod
    def load_coords_from_dir(gui_dir_path):
        """
        读取 gui_xxxxxx 目录下的 coords JSON（coords 为可选项）
        :param gui_dir_path: gui_xxxxxx 目录完整路径
        :return: (entries_list, error_or_None)
        """
        if not gui_dir_path:
            return [], "请选择 gui_xxxxxx 形式的任务目录"

        dir_name = os.path.basename(os.path.normpath(gui_dir_path))
        match = re.fullmatch(r"gui_(\d{6})", dir_name)
        if not match:
            return [], "请选择 gui_xxxxxx 形式的任务目录"

        gui_number = match.group(1)
        filepath = os.path.join(gui_dir_path, f"gui_{gui_number}_coords.json")
        if not os.path.exists(filepath):
            return [], None

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                coords = json.load(f)
        except Exception as e:
            return [], f"坐标文件解析失败: {e}"

        if isinstance(coords, list):
            return coords, None
        if isinstance(coords, dict) and isinstance(coords.get("coords"), list):
            return coords["coords"], None
        return [], "坐标文件解析失败: 不支持的坐标格式"

    @staticmethod
    def find_draft_dirs(base_dir):
        """
        列出母目录下所有形如 gui_xxxxxx 且包含 *_draft.json 的子目录
        :param base_dir: 母目录
        :return: 目录完整路径列表（按名称排序）；母目录不存在时返回 []
        """
        if not base_dir or not os.path.isdir(base_dir):
            return []
        result = []
        for name in sorted(os.listdir(base_dir)):
            sub = os.path.join(base_dir, name)
            if (len(name) == 10 and name.startswith("gui_")
                    and name[4:].isdigit()
                    and os.path.isdir(sub)
                    and glob.glob(os.path.join(sub, "*_draft.json"))):
                result.append(sub)
        return result

    def save_json_data(self, data, gui_number):
        """
        保存 JSON 数据文件到对应的 gui_编号文件夹
        :param data: 字典数据
        :param gui_number: GUI 编号
        :return: 文件路径
        """
        gui_dir = self.create_gui_directory(gui_number)

        filename = f"gui_{gui_number}.json"
        filepath = os.path.join(gui_dir, filename)

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return filepath
        except Exception as e:
            print(f"保存 JSON 失败: {e}")
            return None

    def load_json_data(self, gui_number):
        """
        加载 JSON 数据文件
        :param gui_number: GUI 编号
        :return: 字典数据或 None
        """
        filename = f"gui_{gui_number}.json"
        filepath = os.path.join(self.current_dir, f"gui_{gui_number}", filename)

        try:
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"加载 JSON 失败: {e}")

        return None

    def save_coords_json(self, coords_data, gui_number):
        """
        保存拉框坐标信息到独立的 JSON 文件
        :param coords_data: 坐标数据列表，每个元素包含 step/action/vertices/center
        :param gui_number: GUI 编号
        :return: 文件路径或 None (失败时)
        """
        gui_dir = self.create_gui_directory(gui_number)
        filename = f"gui_{gui_number}_coords.json"
        filepath = os.path.join(gui_dir, filename)

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(coords_data, f, ensure_ascii=False, indent=2)
            return filepath
        except Exception as e:
            print(f"保存坐标 JSON 失败: {e}")
            return None

    def get_screen_info(self):
        """
        获取屏幕信息（跨平台）
        :return: 包含平台、系统、屏幕尺寸的字典
        """
        screen_size = [1920, 1080]  # 默认值

        try:
            if self._system == "Windows":
                screen_size = self._get_screen_size_windows()
            elif self._system == "Darwin":
                screen_size = self._get_screen_size_macos()
            else:
                screen_size = self._get_screen_size_linux()
        except Exception as e:
            print(f"获取屏幕尺寸失败，使用默认值: {e}")

        system_info = self._get_system_info()

        return {
            "platform": platform.platform(),
            "system": system_info,
            "screen_size": screen_size
        }

    def _get_screen_size_windows(self):
        """Windows 平台获取屏幕分辨率"""
        try:
            user32 = ctypes.windll.user32
            width = user32.GetSystemMetrics(0)   # SM_CXSCREEN
            height = user32.GetSystemMetrics(1)  # SM_CYSCREEN
            if width > 0 and height > 0:
                return [width, height]
        except Exception:
            pass

        # 备选方案：使用 tkinter（如果可用）
        try:
            import tkinter as tk
            root = tk.Tk()
            width = root.winfo_screenwidth()
            height = root.winfo_screenheight()
            root.destroy()
            if width > 0 and height > 0:
                return [width, height]
        except Exception:
            pass

        return [1920, 1080]

    def _get_screen_size_macos(self):
        """macOS 平台获取屏幕分辨率"""
        try:
            result = subprocess.run(
                ['system_profiler', 'SPDisplaysDataType'],
                capture_output=True,
                text=True
            )
            for line in result.stdout.split('\n'):
                if 'Resolution' in line:
                    parts = line.split(':')
                    if len(parts) > 1:
                        res_str = parts[1].strip()
                        dims = res_str.split('x')
                        if len(dims) >= 2:
                            try:
                                width = int(dims[0].strip())
                                height = int(dims[1].split()[0].strip())
                                return [width, height]
                            except:
                                pass
                    break
        except Exception:
            pass

        return [1440, 900]

    def _get_screen_size_linux(self):
        """Linux 平台获取屏幕分辨率"""
        try:
            result = subprocess.run(
                ['xrandr'],
                capture_output=True,
                text=True
            )
            for line in result.stdout.split('\n'):
                if ' connected' in line and 'primary' in line:
                    import re
                    match = re.search(r'(\d+)x(\d+)', line)
                    if match:
                        return [int(match.group(1)), int(match.group(2))]
                    match = re.search(r'(\d+)x(\d+)', line)
                    if match:
                        return [int(match.group(1)), int(match.group(2))]
        except Exception:
            pass

        return [1920, 1080]

    def _get_system_info(self):
        """获取系统信息字符串"""
        system = self._system
        if system == "Windows":
            version = platform.release()
            return f"Windows {version}"
        elif system == "Darwin":
            try:
                version = platform.mac_ver()[0]
            except Exception:
                version = ""
            return f"macOS {version}"
        else:
            return f"{system} {platform.release()}"

    def create_initial_json_structure(self, task_instruction, screen_info, app_type=""):
        """
        创建初始 JSON 数据结构
        :param task_instruction: 任务指令
        :param screen_info: 屏幕信息
        :param app_type: 应用类型（用于构建 task_type）
        :return: JSON 数据字典
        """
        # 构建 task_type: 平台名称-应用类型
        system = self._system
        if system == "Darwin":
            platform_display = "MacOS"
        elif system == "Windows":
            platform_display = "Windows"
        else:
            platform_display = system

        if app_type:
            task_type = f"{platform_display}-{app_type}"
        else:
            task_type = platform_display

        return {
            "platform": screen_info.get("platform", platform.platform()),
            "system": screen_info.get("system", f"{platform_display}"),
            "screen_size": screen_info.get("screen_size", [1920, 1080]),
            "task_type": task_type,
            "messages": [
                {
                    "role": "user",
                    "instruction": task_instruction
                },
                {
                    "role": "assistant",
                    "trajectory": []
                }
            ]
        }
