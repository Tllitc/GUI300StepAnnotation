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
        """扫描 gui_编号 目录下已有截图序号，返回 max(已有序号) + 1（3.1 B38）

        三端语义统一为「全局递增」。原实现按「最小未占用序号」分配，删图/撤销
        留下的空洞会被后续任意新截图复用，文件名序号与 step 顺序彻底脱钩（B38），
        也无法从文件名区分「第 N 步的原始截图」与「后来补采的截图」。

        代价：删中间步/重截后允许序号留洞——「顺序可追溯」的责任交给 step 字段，
        INV-11 只钉「全局唯一 + 命名合规 + 引用存在 + 单调递增（插入场景放宽）」。
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
        return max(used) + 1 if used else 1

    def save_screenshot(self, gui_number, app_name, screenshot_path, filename=None):
        """将截图文件复制到 gui_编号 目录（gui_编号_序号.png）

        filename 为 None 时按目录内最小未占用序号命名（新步骤截图）；
        filename 指定时原地覆盖该文件（同步骤重新截图，序号保持不变）。
        覆盖采用“复制到同目录临时文件 + os.replace”方式，
        复制失败时旧文件保留，避免“旧图已删、新图未写”的不可逆窗口。
        """
        gui_dir = self.create_gui_directory(gui_number)
        if filename is None:
            next_num = self.get_next_screenshot_number(gui_number)
            filename = f"gui_{gui_number}_{next_num:04d}.png"
        else:
            # B50 加固：filename 来自草稿/已交付 JSON，可能被篡改为穿越路径。
            # 仅允许写入当前 gui 目录下属于该 gui 编号的截图，非法名直接拒绝。
            safe_name = os.path.basename(filename)
            prefix = f"gui_{gui_number}_"
            if not safe_name.startswith(prefix) or not safe_name.endswith((".png", ".jpg")):
                print(f"保存截图失败: 非法文件名 {filename}")
                return None
            filename = safe_name
        dest_path = os.path.join(gui_dir, filename)

        import shutil
        tmp_dest = os.path.join(gui_dir, f".{filename}.tmp")
        try:
            shutil.copy2(screenshot_path, tmp_dest)
            os.replace(tmp_dest, dest_path)
            return filename
        except Exception as e:
            print(f"保存截图失败: {e}")
            try:
                if os.path.isfile(tmp_dest):
                    os.remove(tmp_dest)
            except Exception:
                pass
            return None

    @staticmethod
    def _atomic_write_json(filepath, payload, err_label="保存 JSON 失败"):
        """原子写 JSON：先写同目录隐藏临时文件，再 os.replace 换入目标。

        直接 open(path, "w") 会立即截断原文件，序列化中途失败（磁盘写满、进程被杀、
        数据含不可序列化对象）就留下半截或空文件——已交付数据不可恢复。
        tmp + replace 的失败语义是「原文件保持不动」，与 save_screenshot 采用的
        tmp + os.replace 口径一致。

        :param filepath: 目标文件路径
        :param payload: 待序列化的对象
        :param err_label: 失败日志前缀
        :return: 成功返回目标路径，失败返回 None
        """
        directory = os.path.dirname(filepath) or "."
        tmp_path = os.path.join(directory, f".{os.path.basename(filepath)}.tmp")
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, filepath)
            return filepath
        except Exception as e:
            print(f"{err_label}: {e}")
            try:
                if os.path.isfile(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            return None

    def backup_final_json(self, gui_number):
        """编辑写回前把现存最终 JSON 复制为 gui_编号.json.bak（覆盖式安全网）

        仅当源文件存在时才生成；复制失败只告警不阻断保存——备份是兜底，
        不该因它写不进去而拒掉用户正常的修改落盘。

        :param gui_number: GUI 编号
        :return: 备份文件路径；无原文件或复制失败时返回 None
        """
        gui_dir = self.create_gui_directory(gui_number)
        src = os.path.join(gui_dir, f"gui_{gui_number}.json")
        if not os.path.isfile(src):
            return None
        dst = f"{src}.bak"
        try:
            import shutil
            shutil.copy2(src, dst)
            return dst
        except Exception as e:
            print(f"备份 JSON 失败: {e}")
            return None

    def save_json_data(self, data, gui_number):
        """保存主 JSON 数据文件（tmp + os.replace 原子写）"""
        gui_dir = self.create_gui_directory(gui_number)
        filename = f"gui_{gui_number}.json"
        filepath = os.path.join(gui_dir, filename)

        return self._atomic_write_json(filepath, data, "保存 JSON 失败")

    def save_coords_json(self, coords_data, gui_number):
        """保存拉框坐标信息到 gui_XXXXXX_coords.json（tmp + os.replace 原子写）

        Android 保持 {"version","coords"} 对象顶层结构不变，仅写入方式改为原子写。
        """
        gui_dir = self.create_gui_directory(gui_number)
        filename = f"gui_{gui_number}_coords.json"
        filepath = os.path.join(gui_dir, filename)

        return self._atomic_write_json(
            filepath, {"version": "3.0", "coords": coords_data}, "保存坐标 JSON 失败"
        )

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
