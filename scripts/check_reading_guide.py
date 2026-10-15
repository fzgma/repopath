"""验证源码或搬移后的可执行程序能过滤二进制并生成带来源的阅读指南。"""

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from io import TextIOWrapper
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "reading_repo"


def main() -> int:
    """隐藏 Python 第三方包和构建工具，检查指南及来源位置。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--work-dir", type=Path, default=ROOT / "build/reading-smoke")
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(dir=args.work_dir.resolve(), prefix="guide-"))
    repository = workspace / "mixed library 源码"
    shutil.copytree(FIXTURE, repository)
    text_files = [path for path in repository.rglob("*") if path.is_file()]
    expected_paths = {path.relative_to(repository).as_posix() for path in text_files}
    expected_lines = sum(
        bool(line.strip())
        for path in text_files
        for line in path.read_text(encoding="utf-8").splitlines()
    )
    for encoding in ("utf-16", "utf-32"):
        name = f"{encoding}.txt"
        (repository / name).write_bytes("第一行\r\n第二行\r\n".encode(encoding))
        expected_paths.add(name)
        expected_lines += 2
    # 将二进制混入真实分析流程，源码和 Windows/Linux 打包程序都必须跳过。
    (repository / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00image\n")
    (repository / "image.cpp").write_bytes(b"GIF89a\x01\x00\x01\x00")
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
    excluded = {
        "VIRTUAL_ENV", "CONDA_PREFIX", "INCLUDE", "LIB", "LIBPATH", "CPATH",
        "CPLUS_INCLUDE_PATH", "C_INCLUDE_PATH",
    }
    environment = {
        name: value for name, value in os.environ.items()
        if name.upper() not in excluded and not name.upper().startswith("PYTHON")
    }
    environment.update({"PATH": str(empty_path), "PYTHONUTF8": "1"})
    outputs: dict[str, str] = {}
    for report_format, extension, detail in (
        ("json", "json", "summary"),
        ("markdown", "md", "summary"),
        ("markdown", "full.md", "full"),
    ):
        output = workspace / f"report.{extension}"
        result = subprocess.run(
            [
                *command, str(repository), "--reading-guide", "--no-git",
                "--reading-limit", "20", "--format", report_format, "-o", str(output),
                "--detail", detail,
            ],
            cwd=workspace, env=environment, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120, check=False,
        )
        (workspace / f"{extension}-stdout.txt").write_text(result.stdout, encoding="utf-8")
        (workspace / f"{extension}-stderr.txt").write_text(result.stderr, encoding="utf-8")
        if result.returncode:
            raise RuntimeError(f"阅读指南验收失败，日志：{workspace}\n{result.stderr}")
        outputs["full" if detail == "full" else report_format] = output.read_text(encoding="utf-8")
    payload = json.loads(outputs["json"])
    assert {item["path"] for item in payload["files"]} == expected_paths, payload["files"]
    assert payload["overview"]["file_count"] == len(expected_paths), payload["overview"]
    assert payload["overview"]["non_empty_lines"] == expected_lines, payload["overview"]
    assert not payload["errors"], payload["errors"]
    guide = payload["reading_guide"]
    assert guide["status"] == "completed", guide
    assert guide["candidate_count"] >= len(guide["steps"]) > 0, guide
    assert len({step["kind"] for step in guide["steps"]}) >= 2, guide
    assert guide["capabilities"] and isinstance(guide["gaps"], list), guide
    assert guide["purpose"] and guide["components"], guide
    summary = outputs["markdown"].split("## 阅读指南（实验）", 1)[1].split("\n## ", 1)[0]
    full = outputs["full"].split("## 阅读指南（实验）", 1)[1].split("\n## ", 1)[0]
    assert "```" not in summary and "--detail full" in summary, summary
    assert "```" in full, full
    assert len(summary) < len(full), (summary, full)
    for heading in ("1. 项目说明摘录", "2. 组成线索", "3. 阅读线索"):
        assert heading in summary and heading in full, heading
    for step in guide["steps"]:
        location = step["location"]
        path = location["path"]
        assert not Path(path).is_absolute(), path
        source = (repository / path).read_text(encoding="utf-8").splitlines()
        assert 0 < location["line"] <= len(source), location
        assert step["evidence"], step
        assert step["reason"] and step["learn"], step
        assert path in outputs["markdown"], (path, outputs["markdown"])
    print(f"阅读指南源码/产物验收通过；报告和日志：{workspace}")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
