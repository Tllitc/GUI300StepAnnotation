import json
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import (  # noqa: E402
    REQUIRED_COLUMNS,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_SUCCESS,
    ConversionError,
    RawRow,
    build_plan,
    convert,
    detect_platforms,
    is_dataset_file,
    load_excel,
    normalize_platform,
)

AVAILABLE = ["Android", "iOS", "macos", "Windows", "@Recycle", "工具"]


def _write_excel(path: Path, headers: list[str], rows: list[list]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(path)


def _make_source(root: Path, platform: str, person: str, folder_id: str) -> Path:
    dataset = root / platform / person / folder_id
    dataset.mkdir(parents=True)
    return dataset


def _make_dataset(
    root: Path,
    platform: str,
    person: str,
    folder_id: str,
    screenshots: tuple[str, ...] = ("0001", "0002"),
) -> Path:
    dataset = _make_source(root, platform, person, folder_id)
    data = {
        "platform": "Windows-10",
        "messages": [
            {"role": "user", "instruction": f"打开 {folder_id} 文件夹"},
            {
                "role": "assistant",
                "trajectory": [
                    {
                        "step": index,
                        "intent": f"双击 {folder_id}_{name}.png 图标",
                        "observation": {"screenshot": f"{folder_id}_{name}.png"},
                    }
                    for index, name in enumerate(screenshots)
                ],
            },
        ],
    }
    (dataset / f"{folder_id}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    coords = [{"step": 0, "action": "click", "vertices": [[1, 2]], "center": [1, 2]}]
    (dataset / f"{folder_id}_coords.json").write_text(
        json.dumps(coords, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for name in screenshots:
        (dataset / f"{folder_id}_{name}.png").write_bytes(b"\x89PNG\r\n\x1a\n" + name.encode())
    return dataset


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Windows", "Windows"),
        ("windows", "Windows"),
        ("安卓", "Android"),
        ("Android", "Android"),
        ("android", "Android"),
        ("ios", "iOS"),
        ("IOS", "iOS"),
        ("iOS", "iOS"),
        ("Mac", "macos"),
        ("macos", "macos"),
        ("Linux", None),
        ("", None),
        ("工具", "工具"),
    ],
)
def test_normalize_platform(raw, expected):
    assert normalize_platform(raw, AVAILABLE) == expected


def test_normalize_platform_missing_real_dir():
    assert normalize_platform("Android", ["Windows", "macos"]) is None
    assert normalize_platform("Windows", []) is None


def test_load_excel_parses_rows(tmp_path):
    path = tmp_path / "交付.xlsx"
    _write_excel(
        path,
        ["日期", "平台", "采集APP", "采集人员", " 文件夹编号 ", "指令"],
        [
            ["2026-10-26", " Windows ", "x", "张三", "gui_000001", "指令"],
            [None, None, None, None, None, None],
            ["2026-10-27", "Android", "y", " 李四 ", "gui_000002", ""],
            ["2026-10-28", "Android", "z", "王五", 12, ""],
        ],
    )

    rows = load_excel(path)

    assert len(rows) == 3
    assert rows[0].excel_row == 2
    assert rows[0].platform_raw == "Windows"
    assert rows[0].person == "张三"
    assert rows[0].folder_id == "gui_000001"
    assert rows[1].excel_row == 4
    assert rows[1].person == "李四"
    assert rows[2].folder_id == "12"
    assert all(isinstance(row, RawRow) for row in rows)


def test_load_excel_missing_column_and_file(tmp_path):
    path = tmp_path / "缺列.xlsx"
    _write_excel(path, ["平台", "采集人员"], [["Windows", "张三"]])
    with pytest.raises(ConversionError):
        load_excel(path)

    with pytest.raises(ConversionError):
        load_excel(tmp_path / "不存在.xlsx")


def test_build_plan_numbering(tmp_path):
    source_root = tmp_path / "母目录"
    target_root = tmp_path / "输出"
    for platform in ("Windows", "Android", "iOS", "macos"):
        (source_root / platform).mkdir(parents=True)
    _make_source(source_root, "Windows", "张三", "gui_000005")
    _make_source(source_root, "Windows", "张三", "gui_000001")
    _make_source(source_root, "Android", "李四", "gui_000003")
    _make_source(source_root, "Android", "李四", "gui_000007")

    rows = [
        RawRow(2, "", "Windows", "张三", "gui_000005"),
        RawRow(3, "", "Android", "李四", "gui_000003"),
        RawRow(4, "", "Windows", "张三", "gui_000001"),
        RawRow(5, "", "Android", "李四", "gui_000007"),
    ]
    plan = build_plan(rows, source_root, target_root)

    assert plan.ok, plan.errors
    assert [item.seq for item in plan.items] == [1, 2, 3, 4]
    assert [item.new_id for item in plan.items] == [
        "gui_000001",
        "gui_000001",
        "gui_000002",
        "gui_000002",
    ]
    assert plan.items[0].target_dir == target_root / "Windows" / "gui_000001"
    assert plan.items[1].target_dir == target_root / "Android" / "gui_000001"
    assert plan.items[2].target_dir == target_root / "Windows" / "gui_000002"
    assert plan.items[3].target_dir == target_root / "Android" / "gui_000002"
    # 预检阶段不写任何文件
    assert not target_root.exists()


def test_build_plan_collects_all_errors(tmp_path):
    source_root = tmp_path / "母目录"
    target_root = tmp_path / "输出"
    _make_source(source_root, "Windows", "张三", "gui_000001")
    _make_source(source_root, "Android", "李四", "gui_000002")
    (target_root / "Android" / "gui_000001").mkdir(parents=True)

    rows = [
        RawRow(2, "", "Windows", "张三", "gui_000001"),
        RawRow(3, "", "Windows", "张三", "gui_000001"),  # 重复
        RawRow(4, "", "Windows", "张三", "gui_999999"),  # 源目录缺失
        RawRow(5, "", "Android", "李四", "gui_000002"),  # 目标冲突
        RawRow(6, "", "Linux", "王五", "gui_000001"),  # 未知平台
    ]
    before = sorted(str(p.relative_to(target_root)) for p in target_root.rglob("*"))

    plan = build_plan(rows, source_root, target_root)

    assert not plan.ok
    assert len(plan.errors) == 4
    joined = "\n".join(plan.errors)
    assert "重复" in joined and "源目录不存在" in joined
    assert "编号冲突" in joined and "无法映射" in joined
    assert "第3行" in joined and "第4行" in joined and "第5行" in joined and "第6行" in joined
    after = sorted(str(p.relative_to(target_root)) for p in target_root.rglob("*"))
    assert before == after


def test_convert_success(tmp_path):
    source_root = tmp_path / "母目录"
    target_root = tmp_path / "输出"
    dataset = _make_dataset(source_root, "Windows", "张三", "gui_000003")
    original_json = json.loads((dataset / "gui_000003.json").read_text(encoding="utf-8"))
    original_json["remark"] = "参考 gui_0000031 与 gui_000003.txt"
    (dataset / "gui_000003.json").write_text(
        json.dumps(original_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (dataset / "note.txt").write_text("原样保留 gui_000003_note.txt", encoding="utf-8")
    (dataset / "gui_000003_draft.json").write_text('{"draft": true}', encoding="utf-8")
    (dataset / "gui_000003.json.bak").write_text("backup", encoding="utf-8")
    (dataset / "gui_000003_coords.json.bak_20261028_145211").write_text(
        "backup", encoding="utf-8"
    )
    source_files = sorted(p.name for p in dataset.iterdir())

    plan = build_plan(
        [RawRow(2, "", "Windows", "张三", "gui_000003")], source_root, target_root
    )
    assert plan.ok, plan.errors

    logs: list[str] = []
    progress: list[tuple[int, int]] = []
    result = convert(
        plan,
        target_root,
        on_log=logs.append,
        on_progress=lambda done, total, item: progress.append((done, total)),
    )

    target_dir = target_root / "Windows" / "gui_000001"
    assert result.success == 1 and result.failed == 0 and result.pending == 0
    assert result.mapping_path is not None and result.mapping_path.is_file()
    assert logs and progress == [(1, 1)]
    assert sorted(p.name for p in target_dir.iterdir()) == [
        "gui_000001.json",
        "gui_000001_0001.png",
        "gui_000001_0002.png",
    ]
    # 非数据集文件（含 _coords.json）不被复制
    for name in (
        "note.txt",
        "gui_000001_coords.json",
        "gui_000001_draft.json",
        "gui_000001.json.bak",
        "gui_000001_coords.json.bak_20261028_145211",
    ):
        assert not (target_dir / name).exists()
    assert any("[跳过]" in line and "5 个非数据集文件" in line for line in logs)
    # png 字节一致
    assert (target_dir / "gui_000001_0001.png").read_bytes() == (
        b"\x89PNG\r\n\x1a\n" + b"0001"
    )
    assert (target_dir / "gui_000001_0002.png").read_bytes() == (
        b"\x89PNG\r\n\x1a\n" + b"0002"
    )
    # 主 JSON 文本替换
    text = (target_dir / "gui_000001.json").read_text(encoding="utf-8")
    assert "gui_000001_0001.png" in text and "gui_000001_0002.png" in text
    assert "gui_000001.txt" in text
    # 旧编号后不是 _ 或 . 时按规则不替换
    assert "打开 gui_000003 文件夹" in text
    assert "gui_000003_" not in text and "gui_000003." not in text
    assert "gui_0000031" in text  # 前缀相似的编号不能被误替换
    final_json = json.loads(text)
    assert final_json["messages"][1]["trajectory"][0]["intent"] == "双击 gui_000001_0001.png 图标"
    # 源目录未被修改
    assert dataset.is_dir()
    assert sorted(p.name for p in dataset.iterdir()) == source_files


def test_mapping_sheet_columns_and_status(tmp_path):
    source_root = tmp_path / "母目录"
    target_root = tmp_path / "输出"
    _make_dataset(source_root, "Windows", "张三", "gui_000001")
    plan = build_plan(
        [RawRow(2, "", "Windows", "张三", "gui_000001")], source_root, target_root
    )
    result = convert(plan, target_root)

    wb = load_workbook(result.mapping_path)
    ws = wb.active
    values = list(ws.values)
    assert values[0] == (
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
    assert len(values[0]) == 9
    row = values[1]
    assert row[:5] == (1, "Windows", "张三", "gui_000001", "gui_000001")
    assert row[7] == STATUS_SUCCESS


def test_convert_cancel_marks_remaining_pending(tmp_path):
    source_root = tmp_path / "母目录"
    target_root = tmp_path / "输出"
    _make_dataset(source_root, "Windows", "张三", "gui_000001")
    _make_dataset(source_root, "Windows", "张三", "gui_000002")
    plan = build_plan(
        [
            RawRow(2, "", "Windows", "张三", "gui_000001"),
            RawRow(3, "", "Windows", "张三", "gui_000002"),
        ],
        source_root,
        target_root,
    )
    assert plan.ok, plan.errors

    calls: list[int] = []

    def should_cancel() -> bool:
        calls.append(1)
        return True  # 第一次检查即取消

    result = convert(plan, target_root, should_cancel=should_cancel)

    assert len(calls) == 1
    assert plan.items[0].status == STATUS_SUCCESS
    assert plan.items[1].status == STATUS_PENDING
    assert result.success == 1 and result.failed == 0 and result.pending == 1
    assert result.mapping_path is not None and result.mapping_path.is_file()
    assert (target_root / "Windows" / "gui_000001").is_dir()
    assert not (target_root / "Windows" / "gui_000002").exists()

    values = list(load_workbook(result.mapping_path).active.values)
    assert values[1][7] == STATUS_SUCCESS
    assert values[2][7] == STATUS_PENDING
    assert STATUS_FAILED not in {values[1][7], values[2][7]}


@pytest.mark.parametrize(
    "name, expected",
    [
        ("gui_000003.json", True),
        ("gui_000003_coords.json", False),
        ("gui_000003_0001.png", True),
        ("gui_000003_12345.png", True),
        ("gui_000003_0001.PNG", True),
        ("gui_000003_draft.json", False),
        ("gui_000003.json.bak", False),
        ("gui_000003_coords.json.bak_20261028_145211", False),
        ("gui_000003_0001.png.bak", False),
        ("gui_0000031_0001.png", False),
        ("note.txt", False),
    ],
)
def test_is_dataset_file(name, expected):
    assert is_dataset_file(name, "gui_000003") is expected


def test_detect_platforms(tmp_path):
    source_root = tmp_path / "母目录"
    for platform in ("Windows", "Android", "iOS", "macos"):
        (source_root / platform).mkdir(parents=True)
    rows = [
        RawRow(2, "", "Windows", "张三", "gui_000001"),
        RawRow(3, "", "安卓", "李四", "gui_000001"),
        RawRow(4, "", "windows", "张三", "gui_000002"),
        RawRow(5, "", "Linux", "王五", "gui_000001"),
        RawRow(6, "", "Mac", "张三", "gui_000001"),
    ]

    assert detect_platforms(rows, source_root) == ["Windows", "Android", "macos"]
    assert detect_platforms(rows, tmp_path / "不存在") == []


def test_build_plan_start_numbers(tmp_path):
    source_root = tmp_path / "母目录"
    target_root = tmp_path / "输出"
    for platform in ("Windows", "Android"):
        (source_root / platform).mkdir(parents=True)
    _make_source(source_root, "Windows", "张三", "gui_000005")
    _make_source(source_root, "Windows", "张三", "gui_000001")
    _make_source(source_root, "Android", "李四", "gui_000003")

    rows = [
        RawRow(2, "", "Windows", "张三", "gui_000005"),
        RawRow(3, "", "Android", "李四", "gui_000003"),
        RawRow(4, "", "Windows", "张三", "gui_000001"),
    ]
    plan = build_plan(rows, source_root, target_root, {"Windows": 5})

    assert plan.ok, plan.errors
    assert [item.new_id for item in plan.items] == [
        "gui_000005",
        "gui_000001",
        "gui_000006",
    ]
    assert plan.items[0].target_dir == target_root / "Windows" / "gui_000005"
    assert plan.items[2].target_dir == target_root / "Windows" / "gui_000006"
    assert not target_root.exists()


def test_build_plan_invalid_start_number(tmp_path):
    source_root = tmp_path / "母目录"
    target_root = tmp_path / "输出"
    _make_source(source_root, "Windows", "张三", "gui_000001")
    rows = [RawRow(2, "", "Windows", "张三", "gui_000001")]

    for invalid in (0, -3, "abc"):
        plan = build_plan(rows, source_root, target_root, {"Windows": invalid})
        assert not plan.ok
        assert any("起始序号无效" in message for message in plan.errors)
        assert not target_root.exists()


def test_convert_dataset_without_dataset_files_fails(tmp_path):
    source_root = tmp_path / "母目录"
    target_root = tmp_path / "输出"
    dataset = _make_source(source_root, "Windows", "张三", "gui_000003")
    (dataset / "gui_000003_draft.json").write_text('{"draft": true}', encoding="utf-8")
    (dataset / "gui_000003.json.bak").write_text("backup", encoding="utf-8")

    plan = build_plan(
        [RawRow(2, "", "Windows", "张三", "gui_000003")], source_root, target_root
    )
    assert plan.ok, plan.errors
    result = convert(plan, target_root)

    assert result.success == 0 and result.failed == 1
    assert plan.items[0].status == STATUS_FAILED
    assert "未找到可复制的数据集文件" in plan.items[0].message
    assert not (target_root / "Windows" / "gui_000001").exists()
    assert result.mapping_path is not None and result.mapping_path.is_file()
    values = list(load_workbook(result.mapping_path).active.values)
    assert values[1][7] == STATUS_FAILED