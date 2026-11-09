#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据管理模块 (iOS 适配版)
负责数据目录创建、文件保存、JSON 格式化管理等
"""

import os
import json
import glob
import subprocess

from PyQt5.QtGui import QPixmap


class DataManager:
    """iOS 数据管理器"""

    def __init__(self, base_dir=None):
        if base_dir is None:
            base_dir = os.getcwd()
        self.base_dir = base_dir
        self.current_dir = base_dir
        self.ios_exe = self._find_ios_exe()

    def _find_ios_exe(self):
        """查找 ios.exe 路径"""
        local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ios.exe")
        if os.path.isfile(local):
            return local
        return "ios.exe"

    def create_task_directory(self, platform_name="iOS", app_type="", app_name=""):
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
        """获取 gui 目录下下一个截图序号（全局递增，跨多轮不覆盖）"""
        gui_dir = self.create_gui_directory(gui_number)
        prefix = f"gui_{gui_number}_"
        max_num = 0
        if os.path.isdir(gui_dir):
            for f in os.listdir(gui_dir):
                if f.startswith(prefix) and f.endswith(".png"):
                    num_part = f[len(prefix):-4]
                    if num_part.isdigit():
                        max_num = max(max_num, int(num_part))
        return max_num + 1

    def save_screenshot(self, gui_number, screenshot_path, filename=None):
        """将截图文件复制到 gui_编号 目录。

        filename 为 None 时按递增序号命名（新步骤截图）；
        filename 指定时原地覆盖该文件（同步骤重新截图，序号保持不变）。
        覆盖采用“复制到同目录临时文件 + os.replace”方式，
        复制失败时旧文件保留，避免截图损坏/丢失。
        """
        gui_dir = self.create_gui_directory(gui_number)
        if filename is None:
            filename = f"gui_{gui_number}_{self.get_next_screenshot_number(gui_number):04d}.png"
        else:
            # B50 修复：filename 来自草稿/已交付 JSON，可能被篡改为穿越路径。
            # 仅允许写入当前 gui 目录下属于该 gui 编号的截图，非法名直接拒绝，
            # 绝不落盘（返回 None），避免把文件写到 gui 目录之外。
            safe_name = os.path.basename(filename)
            prefix = f"gui_{gui_number}_"
            if not safe_name.startswith(prefix) or not safe_name.endswith((".png", ".jpg")):
                print(f"保存截图失败: 非法文件名 {filename}")
                return None
            filename = safe_name
        dest_path = os.path.join(gui_dir, filename)

        import shutil
        try:
            tmp_dest = os.path.join(gui_dir, f".{filename}.tmp")
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
        tmp + replace 的失败语义是「原文件保持不动」，与上层「写入失败则原数据不变」一致
        （复用 save_screenshot 已验证的 tmp + os.replace 模式）。

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
        """保存拉框坐标信息到 gui_XXXXXX_coords.json（tmp + os.replace 原子写）"""
        gui_dir = self.create_gui_directory(gui_number)
        filename = f"gui_{gui_number}_coords.json"
        filepath = os.path.join(gui_dir, filename)

        try:
            # 为每个条目添加版本号
            for coord in coords_data:
                coord["_version"] = "3.1"
        except Exception as e:
            print(f"保存坐标 JSON 失败: {e}")
            return None
        # 保持纯数组格式，仅写入方式改为原子写
        return self._atomic_write_json(filepath, coords_data, "保存坐标 JSON 失败")

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

        兼容纯数组（iOS）与 {"coords":[...]} 对象两种格式。

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

    def get_ios_device_list(self):
        """通过 go-ios 获取已连接的 iOS 设备列表"""
        cmd = [self.ios_exe, "list"]
        env = os.environ.copy()
        env.setdefault("ENABLE_GO_IOS_AGENT", "user")
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding='utf-8', errors='replace',
                timeout=15, cwd=os.path.dirname(os.path.abspath(__file__)),
                env=env,
            )
            output = proc.stdout.strip()
            if not output:
                output = proc.stderr.strip()
            if not output:
                return []

            # 尝试解析 JSON
            try:
                data = json.loads(output)
            except json.JSONDecodeError:
                return []

            devices = data.get("deviceList", data)
            if isinstance(devices, dict):
                devices = [devices]
            if not isinstance(devices, list):
                return []

            result = []
            for d in devices:
                if isinstance(d, str):
                    result.append({"udid": d})
                elif isinstance(d, dict):
                    result.append(d)
            return result
        except Exception as e:
            print(f"获取设备列表失败: {e}")
            return []

    def get_ios_info(self, udid=None):
        """获取 iOS 设备信息（系统版本、屏幕尺寸等）"""
        cmd = [self.ios_exe, "--pretty"]
        if udid:
            cmd.append(f"--udid={udid}")
        cmd += ["info", "lockdown"]

        env = os.environ.copy()
        env.setdefault("ENABLE_GO_IOS_AGENT", "user")
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding='utf-8', errors='replace',
                timeout=15, cwd=os.path.dirname(os.path.abspath(__file__)),
                env=env,
            )
            output = proc.stdout.strip()
            if not output:
                output = proc.stderr.strip()
            if not output:
                return {}

            try:
                data = json.loads(output)
            except json.JSONDecodeError:
                for line in output.split("\n"):
                    try:
                        d = json.loads(line)
                        if isinstance(d, dict) and "level" not in d:
                            data = d
                            break
                    except:
                        continue
                else:
                    return {}

            if isinstance(data, dict):
                return data
            return {}
        except Exception as e:
            print(f"获取 iOS 信息失败: {e}")
            return {}

    def get_screen_info(self, udid=None):
        """获取 iOS 设备屏幕信息"""
        info = self.get_ios_info(udid)

        # 尝试从设备信息中提取屏幕尺寸（go-ios 返回 PascalCase 字段）
        screen_size = [1179, 2556]  # 默认值
        product_type = info.get("ProductType") or info.get("productType") or ""
        product_version = info.get("ProductVersion") or info.get("productVersion") or ""

        # 根据设备型号估算分辨率（逻辑分辨率）
        resolution_map = {
            # iPhone (逻辑分辨率)
            "iPhone15,2": [1179, 2556],  # iPhone 14 Pro
            "iPhone15,3": [1290, 2796],  # iPhone 14 Pro Max
            "iPhone15,4": [1170, 2532],  # iPhone 14
            "iPhone15,5": [1284, 2778],  # iPhone 14 Plus
            "iPhone16,1": [1179, 2556],  # iPhone 15 Pro
            "iPhone16,2": [1290, 2796],  # iPhone 15 Pro Max
            "iPhone14,7": [1170, 2532],  # iPhone 14
            "iPhone14,3": [1170, 2532],  # iPhone 13 Pro
            "iPhone14,2": [1284, 2778],  # iPhone 13 Pro Max
        }

        for model, res in resolution_map.items():
            if product_type and model in product_type:
                screen_size = res
                break

        platform_str = "iOS"
        system_str = f"iOS {product_version}" if product_version else "iOS"
        return {
            "platform": platform_str,
            "system": system_str,
            "screen_size": screen_size
        }

    def create_initial_json_structure(self, task_instruction, screen_info, app_type=""):
        """创建初始 JSON 数据结构 (iOS 格式)"""
        task_type = f"iOS-{app_type}" if app_type else "iOS"
        return {
            "platform": screen_info.get("platform", "iOS"),
            "system": screen_info.get("system", "iOS"),
            "screen_size": screen_info.get("screen_size", [1179, 2556]),
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
