"""验证源码或搬移后的可执行程序只将文本文件计入报告。"""

import argparse
import base64
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from io import TextIOWrapper
from pathlib import Path
from typing import TypeGuard

ROOT = Path(__file__).resolve().parents[1]


class Arguments(argparse.Namespace):
    """验收脚本的命令行选项。"""

    artifact: Path | None
    work_dir: Path


def _is_object(value: object) -> TypeGuard[dict[object, object]]:
    """检查 JSON 对象，字段内容继续逐项校验。"""
    return isinstance(value, dict)


def _is_array(value: object) -> TypeGuard[list[object]]:
    """检查 JSON 数组，数组成员继续逐项校验。"""
    return isinstance(value, list)


def main() -> int:
    """隐藏第三方包和外部工具，核对真实 CLI 的文件清单及行数。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--work-dir", type=Path, default=ROOT / "build/file-scan-smoke")
    args = parser.parse_args(namespace=Arguments())
    args.work_dir.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(dir=args.work_dir.resolve(), prefix="scan-"))
    repository = workspace / "mixed files 源码"
    (repository / "assets").mkdir(parents=True)
    texts = {
        "app.py": (b"# sample\r\nvalue = 1\r\n\r\n", 3, 2),
        "README.md": (b"# Sample\n\nDetails.\n", 3, 2),
        "settings.db": (b"enabled=true\n", 1, 1),
        "assets/icon.svg": (b"<svg/>\n", 1, 1),
        "utf16.txt": ("第一行\r\n\r\n第二行\r\n".encode("utf-16"), 3, 2),
        "utf32": ("第一行\r\n\r\n第二行\r\n".encode("utf-32"), 3, 2),
        "empty.txt": (b"", 0, 0),
    }
    for name, (content, _lines, _non_empty) in texts.items():
        (repository / name).write_bytes(content)
    (repository / "assets/picture.png").write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4"
        "z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg=="
    ))
    # 数据库故意使用源码扩展名，验证过滤依据是内容。
    connection = sqlite3.connect(repository / "storage.py")
    try:
        connection.execute("CREATE TABLE notes (body TEXT)")
        connection.execute("INSERT INTO notes VALUES (?)", ("text\n" * 100,))
        connection.commit()
    finally:
        connection.close()
    command = [sys.executable, "-S", str(ROOT / "repopath.py")]
    if args.artifact is not None:
        executable = workspace / "moved program 程序" / args.artifact.name
        executable.parent.mkdir()
        shutil.copy2(args.artifact.resolve(), executable)
        command = [str(executable)]
    empty_path = workspace / "empty tools"
    empty_path.mkdir()
    environment = {
        name: value for name, value in os.environ.items()
        if name.upper() not in {"VIRTUAL_ENV", "CONDA_PREFIX"}
        and not name.upper().startswith("PYTHON")
    }
    environment.update({"PATH": str(empty_path), "PYTHONUTF8": "1"})
    output = workspace / "report.json"
    result = subprocess.run(
        [*command, str(repository), "--profile", "fast", "--format", "json", "-o", str(output)],
        cwd=workspace, env=environment, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120, check=False,
    )
    (workspace / "stdout.txt").write_text(result.stdout, encoding="utf-8")
    (workspace / "stderr.txt").write_text(result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"文件扫描验收失败，日志：{workspace}\n{result.stderr}")
    payload: object = json.loads(output.read_text(encoding="utf-8"))
    assert _is_object(payload), payload
    files = payload["files"]
    assert _is_array(files), files
    actual: dict[str, tuple[object, object]] = {}
    for record in files:
        assert _is_object(record), record
        path = record["path"]
        assert isinstance(path, str), record
        assert path not in actual, path
        actual[path] = (record["lines"], record["non_empty_lines"])
    assert actual == {name: (lines, non_empty) for name, (_, lines, non_empty) in texts.items()}, actual
    overview = payload["overview"]
    assert _is_object(overview), overview
    assert overview["file_count"] == len(texts), overview
    assert overview["non_empty_lines"] == 10, overview
    assert payload["languages"] == {
        "Python": {"files": 1, "non_empty_lines": 2},
        "Markdown": {"files": 1, "non_empty_lines": 2},
        "Other": {"files": 5, "non_empty_lines": 6},
    }, payload["languages"]
    assert payload["directory_stats"] == {
        ".": {"files": 6, "non_empty_lines": 9},
        "assets": {"files": 1, "non_empty_lines": 1},
    }, payload["directory_stats"]
    assert not payload["errors"], payload["errors"]
    print(f"文件扫描源码/产物验收通过；报告和日志：{workspace}")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
