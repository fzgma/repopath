"""在无额外 Python 依赖和构建工具的环境验收 C++ 源码阅读分析。"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "mixed_repo"


def check_report(payload: dict[str, Any]) -> None:
    """检查真正的符号、文件依赖和阅读顺序，避免空报告被当作成功。"""
    cpp = payload["cpp"]
    assert payload["analysis"]["analyzers"]["cpp"]["status"] == "completed", cpp
    assert cpp["status"] == "completed", cpp
    assert cpp["file_count"] == 3, cpp
    assert cpp["includes"]["greeting.hpp"] == 2, cpp
    assert cpp["includes"]["string"] == 1, cpp
    assert {entry["path"] for entry in cpp["entry_points"]} == {"src/main.cc"}, cpp
    symbols = {
        (item["path"], item["name"].rsplit("::", 1)[-1])
        for item in cpp["symbols"]
    }
    assert {
        ("src/main.cc", "main"),
        ("include/greeting.hpp", "Greeter"),
        ("src/greeting.cpp", "message"),
    } <= symbols, symbols
    assert {(edge["source"], edge["target"]) for edge in cpp["dependencies"]} == {
        ("src/main.cc", "include/greeting.hpp"),
        ("src/greeting.cpp", "include/greeting.hpp"),
    }, cpp["dependencies"]
    assert payload["insights"]["reading_order"], payload["insights"]


def main() -> int:
    """搬移样例和可选单文件产物，在清空工具路径后执行真实 CLI。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, help="待验收的 Nuitka 单文件程序")
    parser.add_argument("--work-dir", type=Path, default=ROOT / "build/cpp-smoke")
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(
        prefix="artifact-" if args.artifact else "source-",
        dir=args.work_dir.resolve(),
    ))
    repository = workspace / "mixed repository 源码"
    shutil.copytree(FIXTURE, repository)
    command = [sys.executable, "-S", str(ROOT / "repopath.py")]
    if args.artifact is not None:
        executable = workspace / "moved application 程序" / args.artifact.name
        executable.parent.mkdir()
        shutil.copy2(args.artifact.resolve(), executable)
        command = [str(executable)]
    empty_path = workspace / "no build tools"
    empty_path.mkdir()
    excluded = {
        "VIRTUAL_ENV", "CONDA_PREFIX", "INCLUDE", "LIB", "LIBPATH", "CPATH",
        "CPLUS_INCLUDE_PATH", "C_INCLUDE_PATH",
    }
    environment = {
        name: value for name, value in os.environ.items()
        if name.upper() not in excluded
        and not name.upper().startswith("PYTHON")
    }
    environment.update({"PATH": str(empty_path), "PYTHONUTF8": "1"})
    report = workspace / "report.json"
    result = subprocess.run(
        [
            *command, str(repository), "--no-git", "--format", "json",
            "-o", str(report),
        ],
        cwd=workspace, env=environment, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=120, check=False,
    )
    (workspace / "stdout.txt").write_text(result.stdout, encoding="utf-8")
    (workspace / "stderr.txt").write_text(result.stderr, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(
            f"CLI 验收失败（{result.returncode}），日志：{workspace}\n{result.stderr}"
        )
    check_report(json.loads(report.read_text(encoding="utf-8")))
    print(f"C++ 源码阅读分析验收通过；报告和日志：{workspace}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
