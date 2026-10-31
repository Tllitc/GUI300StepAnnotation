#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据管理模块 (Android 适配版)
负责数据目录创建、文件保存、JSON 格式化管理等
"""

import os
import glob
import json
import subprocess

from PyQt5.QtGui import QPixmap


class DataManager:
    """Android 数据管理器"""

    def __init__(self, base_dir=None):
        if base_dir is None:
            base_dir = os.getcwd()
        self.base_dir = base_dir
        self.current_dir = base_dir

    def create_task_directory(self, platform_name="Android", app_type="", app_name=""):
        """设置任务目录"""
        try:
            os.makedirs(self.base_dir, exist_ok=True)
            self.current_dir = self.base_dir
            return True
        except Exception as e:
            print(f"设置任务目录失败: {e}")
            return False

    def get_next_gui_number(self):
        """获取下一个 GUI 编号（六位数字）"""
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

        next_num = max(numbers) + 1 if numbers else 1
        return f"{next_num:06d}"

    def create_gui_directory(self, gui_number):
        """创建 GUI 编号文件夹"""
        gui_dir_name = f"gui_{gui_number}"
        gui_dir_path = os.path.join(self.current_dir, gui_dir_name)
        os.makedirs(gui_dir_path, exist_ok=True)
        return gui_dir_path

    def get_next_screenshot_number(self, gui_number):
        """扫描 gui_编号 目录下已有截图序号，返回最小未占用序号（从 1 开始）

        使用“最小可用序号”而非 max+1，避免重截中间步骤删除旧图后
        产生编号空号（不连续）。
        """
        gui_dir = self.create_gui_directory(gui_number)
        prefix = f"gui_{gui_number}_"
        used = set()
        try:
            for name in os.listdir(gui_dir):
                if name.startswith(prefix) and name.endswith(".png"):
                    num_part = name[len(prefix):-len(".png")]
                    if num_part.isdigit():
                        used.add(int(num_part))
        except OSError:
            pass
        num = 1
        while num in used:
            num += 1
        return num

    def save_screenshot(self, gui_number, app_name, screenshot_path):
        """将截图文件复制到 gui_编号 目录，按目录内已有序号递增命名（gui_编号_序号.png）"""
        gui_dir = self.create_gui_directory(gui_number)
        next_num = self.get_next_screenshot_number(gui_number)
        filename = f"gui_{gui_number}_{next_num:04d}.png"
        dest_path = os.path.join(gui_dir, filename)

        import shutil
        try:
            shutil.copy2(screenshot_path, dest_path)
            return filename
        except Exception as e:
            print(f"保存截图失败: {e}")
            return None

    def save_json_data(self, data, gui_number):
        """保存主 JSON 数据文件"""
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

    def save_coords_json(self, coords_data, gui_number):
        """保存拉框坐标信息到 gui_XXXXXX_coords.json"""
        gui_dir = self.create_gui_directory(gui_number)
        filename = f"gui_{gui_number}_coords.json"
        filepath = os.path.join(gui_dir, filename)

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump({"version": "3.0", "coords": coords_data}, f, ensure_ascii=False, indent=2)
            return filepath
        except Exception as e:
            print(f"保存坐标 JSON 失败: {e}")
            return None

    def load_screenshot(self, gui_number, filename):
        """从磁盘加载截图（内存解耦后预览图按需从文件重建）

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
        """保存增量草稿 JSON（防崩溃/断点续采）

        :param draft: 草稿字典（仅含可序列化字段）
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
        """读取增量草稿 JSON

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
        """删除增量草稿文件（最终数据成功落盘后调用）"""
        filepath = os.path.join(self.current_dir, f"gui_{gui_number}",
                                f"gui_{gui_number}_draft.json")
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception as e:
            print(f"删除草稿失败: {e}")

    # 草稿加载错误类型常量（与 load_draft_from_dir 返回值配对）
    DRAFT_ERR_NONE = None          # 正常：返回有效草稿
    DRAFT_ERR_NOT_FOUND = "not_found"   # 无草稿文件
    DRAFT_ERR_CORRUPT = "corrupt"       # JSON 解析失败

    @staticmethod
    def load_json_from_dir(gui_dir_path):
        """读取已完成任务的最终 JSON（gui_xxxxxx.json）

        :param gui_dir_path: gui_xxxxxx 目录完整路径
        :return: (data, error) 元组；成功时 (dict, None)
        """
        import re
        dir_name = os.path.basename(os.path.normpath(gui_dir_path))
        match = re.fullmatch(r"gui_(\d{6})", dir_name)
        if not match:
            return None, "请选择 gui_xxxxxx 形式的任务目录"
        gui_number = match.group(1)
        filepath = os.path.join(gui_dir_path, f"gui_{gui_number}.json")
        if not os.path.isfile(filepath):
            return None, "该任务尚未完成，请使用『继续未完成任务』"
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f), None
        except Exception as e:
            print(f"[已完成任务] JSON 解析失败: {e}")
            return None, f"任务数据解析失败: {e}"

    @staticmethod
    def load_coords_from_dir(gui_dir_path):
        """读取 gui 目录中的拉框坐标文件（gui_xxxxxx_coords.json）

        兼容 Android 的 {"version":"3.0","coords":[...]} 对象与纯数组两种格式。

        :param gui_dir_path: gui_xxxxxx 目录完整路径
        :return: (entries, error) 元组；文件不存在时 ([], None)
        """
        import re
        dir_name = os.path.basename(os.path.normpath(gui_dir_path))
        match = re.fullmatch(r"gui_(\d{6})", dir_name)
        if not match:
            return [], None
        gui_number = match.group(1)
        filepath = os.path.join(gui_dir_path, f"gui_{gui_number}_coords.json")
        if not os.path.isfile(filepath):
            return [], None
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                entries = data.get("coords") or []
            elif isinstance(data, list):
                entries = data
            else:
                entries = []
            if not isinstance(entries, list):
                entries = []
            return entries, None
        except Exception as e:
            print(f"[已完成任务] 坐标文件解析失败: {e}")
            return [], f"坐标文件解析失败: {e}"

    @staticmethod
    def load_draft_from_dir(gui_dir_path):
        """在指定 gui 目录中查找并读取 *_draft.json

        :param gui_dir_path: gui_xxxxxx 目录完整路径
        :return: (draft_dict, error_type) 元组
            - 成功时: (draft_dict, None)
            - 无草稿文件: (None, "not_found")
            - JSON 损坏: (None, "corrupt")
        """
        try:
            draft_files = glob.glob(os.path.join(gui_dir_path, "*_draft.json"))
            if not draft_files:
                return None, DataManager.DRAFT_ERR_NOT_FOUND
            with open(draft_files[0], 'r', encoding='utf-8') as f:
                return json.load(f), DataManager.DRAFT_ERR_NONE
        except (json.JSONDecodeError, ValueError) as e:
            print(f"[草稿] JSON 解析失败: {e}")
            return None, DataManager.DRAFT_ERR_CORRUPT
        except Exception as e:
            print(f"[草稿] 加载异常: {e}")
            return None, DataManager.DRAFT_ERR_CORRUPT

    @staticmethod
    def is_task_completed(gui_dir_path):
        """检查 gui 目录中是否存在最终 JSON（gui_xxxxxx.json，不含 _coords 和 _draft 后缀）

        :param gui_dir_path: gui_xxxxxx 目录完整路径
        :return: True 表示存在最终 JSON，说明任务已正常完成
        """
        import re
        dir_name = os.path.basename(os.path.normpath(gui_dir_path))
        match = re.fullmatch(r"gui_(\d{6})", dir_name)
        if not match:
            return False
        gui_number = match.group(1)
        final_json = os.path.join(gui_dir_path, f"gui_{gui_number}.json")
        return os.path.isfile(final_json)

    @staticmethod
    def has_screenshots(gui_dir_path):
        """检查 gui 目录中是否存在任何截图文件（.png）

        :param gui_dir_path: gui_xxxxxx 目录完整路径
        :return: True 表示目录中有 .png 截图
        """
        png_files = glob.glob(os.path.join(gui_dir_path, "*.png"))
        return len(png_files) > 0

    @staticmethod
    def find_draft_dirs(base_dir):
        """列出母目录下所有形如 gui_xxxxxx 且包含 *_draft.json 的子目录

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

    def create_initial_json_structure(self, task_instruction, screen_info, app_type=""):
        """创建初始 JSON 数据结构 (Android 格式)"""
        task_type = f"Android-{app_type}" if app_type else "Android"
        return {
            "platform": screen_info.get("platform", "Android"),
            "system": screen_info.get("system", ""),
            "screen_size": screen_info.get("screen_size", [1080, 2400]),
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
