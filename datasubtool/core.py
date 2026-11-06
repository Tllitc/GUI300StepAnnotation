"""长步骤采集数据集交付重命名核心逻辑。"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping

import openpyxl
from openpyxl import Workbook

REQUIRED_COLUMNS = ("平台", "采集人员", "文件夹编号")
STATUS_PENDING = "未处理"
STATUS_SUCCESS = "成功"
STATUS_FAILED = "失败"

MAPPING_COLUMNS = (
    "序号",
    "平台",
    "采集人员",
    "原文件夹编号",
    "新编号",
    "源目录",
    "输出目录",
    "状态",
    "备注",
)

# 常见平台写法到母目录真实目录名的别名映射（值统一小写比较）
_PLATFORM_ALIASES = {
    "安卓": "android",
    "安卓端": "android",
    "android": "android",
    "android端": "android",
    "ios": "ios",
    "iphone": "ios",
    "ipados": "ios",
    "苹果": "ios",
    "mac": "macos",
    "macos": "macos",
    "mac os": "macos",
    "macosx": "macos",
    "mac os x": "macos",
    "windows": "windows",
    "win": "windows",
    "win10": "windows",
    "win11": "windows",
    "windows10": "windows",
    "windows11": "windows",
}


class ConversionError(Exception):
    """预检或转换过程中的可读错误。"""


@dataclass
class RawRow:
    excel_row: int
    date: str
    platform_raw: str
    person: str
    folder_id: str


@dataclass
class Entry:
    excel_row: int
    date: str
    platform_raw: str
    platform: str  # 母目录下真实平台目录名
    person: str
    folder_id: str
    source_dir: Path


@dataclass
class PlanItem:
    seq: int  # 1-based 全局序号
    entry: Entry
    new_id: str
    target_dir: Path
    status: str = STATUS_PENDING
    message: str = ""


@dataclass
class Plan:
    items: list[PlanItem]
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors and bool(self.items)


@dataclass
class Result:
    success: int
    failed: int
    pending: int
    mapping_path: Path | None
    errors: list[str]


def _cell_text(value) -> str:
    """把单元格值转成去掉首尾空白的字符串，整数型浮点不带 .0。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _value_at(values, index: int | None) -> str:
    if index is None or values is None or index >= len(values):
        return ""
    return _cell_text(values[index])


def load_excel(excel_path: str | Path) -> list[RawRow]:
    """读取交付清单第一个工作表，仅解析表头与必需列。"""
    path = Path(excel_path)
    if not path.is_file():
        raise ConversionError(f"Excel 文件不存在：{path}")
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # 文件损坏、格式不支持等
        raise ConversionError(f"无法打开 Excel：{exc}") from exc

    try:
        ws = wb[wb.sheetnames[0]]
        rows_iter = ws.iter_rows(values_only=True)
        try:
            header = next(rows_iter)
        except StopIteration:
            raise ConversionError("Excel 为空，缺少表头") from None

        columns: dict[str, int] = {}
        for index, cell in enumerate(header):
            name = _cell_text(cell)
            if name and name not in columns:
                columns[name] = index

        missing = [name for name in REQUIRED_COLUMNS if name not in columns]
        if missing:
            raise ConversionError("缺少必需列：" + "、".join(missing))

        rows: list[RawRow] = []
        for excel_row, values in enumerate(rows_iter, start=2):
            platform_raw = _value_at(values, columns["平台"])
            person = _value_at(values, columns["采集人员"])
            folder_id = _value_at(values, columns["文件夹编号"])
            if not platform_raw and not person and not folder_id:
                continue
            rows.append(
                RawRow(
                    excel_row=excel_row,
                    date=_value_at(values, columns.get("日期")),
                    platform_raw=platform_raw,
                    person=person,
                    folder_id=folder_id,
                )
            )
    finally:
        wb.close()

    if not rows:
        raise ConversionError("Excel 中没有有效数据行")
    return rows


def normalize_platform(raw_value: str, available_platforms: list[str]) -> str | None:
    """把平台写法映射为母目录中真实存在的平台目录名，无法识别返回 None。"""
    raw = (raw_value or "").strip()
    if not raw:
        return None

    available = {name.casefold(): name for name in available_platforms if name}
    # 1) 与真实目录名大小写不敏感直接匹配
    direct = available.get(raw.casefold())
    if direct is not None:
        return direct

    # 2) 走别名表，再确认目录真实存在
    target = _PLATFORM_ALIASES.get(raw.casefold())
    if target is None:
        return None
    return available.get(target)


def detect_platforms(rows: list[RawRow], source_root: str | Path) -> list[str]:
    """按 Excel 行序返回可识别的平台目录名（去重，忽略无法识别的平台）。"""
    root = Path(source_root)
    try:
        available = [child.name for child in root.iterdir() if child.is_dir()]
    except OSError:
        return []

    platforms: list[str] = []
    for row in rows:
        platform = normalize_platform(row.platform_raw, available)
        if platform is not None and platform not in platforms:
            platforms.append(platform)
    return platforms


def is_dataset_file(name: str, folder_id: str) -> bool:
    """判断文件是否属于数据集白名单：<id>.json、<id>_<数字>.png。"""
    if not folder_id:
        return False
    if name.lower() == f"{folder_id}.json".lower():
        return True
    return (
        re.fullmatch(
            re.escape(folder_id) + r"_\d+\.png", name, re.IGNORECASE
        )
        is not None
    )


def build_plan(
    rows: list[RawRow],
    source_root: str | Path,
    target_root: str | Path,
    start_numbers: Mapping[str, int] | None = None,
) -> Plan:
    """预检全部行：平台、源目录、重复源目录、目标编号冲突，汇总所有问题。"""
    source_root = Path(source_root)
    target_root = Path(target_root)
    items: list[PlanItem] = []
    errors: list[str] = []

    starts: dict[str, int] = {}
    for platform, value in (start_numbers or {}).items():
        try:
            number = int(value)
        except (TypeError, ValueError):
            errors.append(f"平台「{platform}」起始序号无效：{value}（需为正整数）")
            continue
        if number < 1:
            errors.append(f"平台「{platform}」起始序号无效：{value}（需为正整数）")
            continue
        starts[platform] = number

    if not source_root.is_dir():
        return Plan(items, [f"母目录不存在或不是文件夹：{source_root}"])

    available = [child.name for child in source_root.iterdir() if child.is_dir()]
    if not rows:
        errors.append("交付清单中没有可处理的数据行")

    seen_sources: dict[str, int] = {}
    counters: dict[str, int] = {}

    for row in rows:
        platform = normalize_platform(row.platform_raw, available)
        if platform is None:
            errors.append(
                f"第{row.excel_row}行：平台「{row.platform_raw}」无法映射到母目录下的平台目录"
            )
            continue

        person = row.person.strip()
        folder_id = row.folder_id.strip()
        if not person or not folder_id:
            errors.append(f"第{row.excel_row}行：采集人员或文件夹编号为空")
            continue

        source_dir = source_root / platform / person / folder_id
        if not source_dir.is_dir():
            errors.append(f"第{row.excel_row}行：源目录不存在：{source_dir}")
            continue

        key = os.path.normcase(str(source_dir))
        if key in seen_sources:
            errors.append(
                f"第{row.excel_row}行：源目录与第{seen_sources[key]}行重复：{source_dir}"
            )
            continue
        seen_sources[key] = row.excel_row

        count = counters.get(platform, starts.get(platform, 1))
        counters[platform] = count + 1
        new_id = f"gui_{count:06d}"
        target_dir = target_root / platform / new_id
        if target_dir.exists():
            errors.append(f"第{row.excel_row}行：目标目录已存在，编号冲突：{target_dir}")
            continue

        entry = Entry(
            excel_row=row.excel_row,
            date=row.date,
            platform_raw=row.platform_raw,
            platform=platform,
            person=person,
            folder_id=folder_id,
            source_dir=source_dir,
        )
        items.append(
            PlanItem(seq=len(items) + 1, entry=entry, new_id=new_id, target_dir=target_dir)
        )

    return Plan(items, errors)


def _rewrite_json_refs(json_path: Path, old_id: str, new_id: str) -> None:
    """按文本替换 JSON 中的旧编号引用，保留原始换行与排版。"""
    with open(json_path, "r", encoding="utf-8", newline="") as fh:
        text = fh.read()
    pattern = re.compile(r"(?<![0-9A-Za-z_])" + re.escape(old_id) + r"(?=[_.])")
    new_text = pattern.sub(new_id, text)
    if new_text == text:
        return
    with open(json_path, "w", encoding="utf-8", newline="") as fh:
        fh.write(new_text)


def _convert_item(item: PlanItem) -> list[str]:
    """复制单个数据集的白名单文件并改名，返回被跳过的非数据集文件名。"""
    src = item.entry.source_dir
    dst = item.target_dir
    old_id = item.entry.folder_id.strip()
    new_id = item.new_id

    if not src.is_dir():
        raise ConversionError(f"源目录不存在：{src}")
    if dst.exists():
        raise ConversionError(f"目标目录已存在：{dst}")
    dst.mkdir(parents=True)

    skipped: list[str] = []
    copied = 0
    for root, _dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        for name in files:
            if not is_dataset_file(name, old_id):
                skipped.append(name)
                continue
            out_dir = dst / rel
            out_dir.mkdir(parents=True, exist_ok=True)
            new_name = new_id + name[len(old_id):]
            shutil.copy2(Path(root) / name, out_dir / new_name)
            copied += 1

    if copied == 0:
        raise ConversionError("未找到可复制的数据集文件")

    for json_path in dst.rglob("*.json"):
        _rewrite_json_refs(json_path, old_id, new_id)
    return skipped


def _next_mapping_path(target_root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = target_root / f"数据集映射表_{stamp}.xlsx"
    index = 1
    while path.exists():
        path = target_root / f"数据集映射表_{stamp}_{index}.xlsx"
        index += 1
    return path


def _write_mapping(target_root: Path, items: list[PlanItem]) -> Path:
    path = _next_mapping_path(target_root)
    wb = Workbook()
    ws = wb.active
    ws.title = "映射表"
    ws.append(list(MAPPING_COLUMNS))
    for item in items:
        ws.append(
            [
                item.seq,
                item.entry.platform,
                item.entry.person,
                item.entry.folder_id,
                item.new_id,
                str(item.entry.source_dir),
                str(item.target_dir),
                item.status,
                item.message,
            ]
        )
    wb.save(path)
    return path


def convert(
    plan: Plan,
    target_root: str | Path,
    on_log: Callable[[str], None] | None = None,
    on_progress: Callable[[int, int, PlanItem], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> Result:
    """执行复制转换；单条失败不中断，支持协作式取消。"""
    if not plan.ok:
        raise ConversionError("预检未通过，不能开始转换")

    root = Path(target_root)
    root.mkdir(parents=True, exist_ok=True)
    total = len(plan.items)
    log = on_log or (lambda _msg: None)
    errors: list[str] = []
    log(f"开始处理 {total} 条数据集，输出目录：{root}")

    cancelled = False
    for index, item in enumerate(plan.items, start=1):
        if cancelled:
            item.status = STATUS_PENDING
            item.message = "已取消，未处理"
            continue

        try:
            skipped = _convert_item(item)
        except Exception as exc:
            shutil.rmtree(item.target_dir, ignore_errors=True)
            item.status = STATUS_FAILED
            item.message = f"{type(exc).__name__}: {exc}"
            errors.append(
                f"第{item.entry.excel_row}行 {item.entry.folder_id} → {item.new_id} 失败：{item.message}"
            )
            log(f"[失败] {item.entry.platform} {item.entry.folder_id} → {item.new_id}：{item.message}")
        else:
            item.status = STATUS_SUCCESS
            item.message = ""
            log(
                f"[成功] {index}/{total} {item.entry.platform} "
                f"{item.entry.folder_id} → {item.new_id}"
            )
            if skipped:
                preview = "、".join(skipped[:5]) + ("…" if len(skipped) > 5 else "")
                log(
                    f"[跳过] {item.entry.platform} {item.entry.folder_id} → {item.new_id}："
                    f"{len(skipped)} 个非数据集文件（{preview}）"
                )

        if on_progress:
            on_progress(index, total, item)

        if should_cancel and should_cancel():
            cancelled = True
            log("收到取消请求，剩余条目将不再处理")

    mapping_path = _write_mapping(root, plan.items)
    success = sum(1 for item in plan.items if item.status == STATUS_SUCCESS)
    failed = sum(1 for item in plan.items if item.status == STATUS_FAILED)
    pending = sum(1 for item in plan.items if item.status == STATUS_PENDING)
    if pending:
        errors.append(f"已取消，{pending} 条未处理")

    log(f"处理完成：成功 {success}，失败 {failed}，未处理 {pending}")
    log(f"映射表已生成：{mapping_path}")
    return Result(
        success=success,
        failed=failed,
        pending=pending,
        mapping_path=mapping_path,
        errors=errors,
    )