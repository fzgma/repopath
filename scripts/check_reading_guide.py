"""验证源码或搬移后的可执行程序能生成有实际证据的阅读指南。"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
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
    outputs = {}
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
    guide = payload["reading_guide"]
    assert guide["status"] == "completed", guide
    assert guide["candidate_count"] >= len(guide["steps"]) > 0, guide
    assert len({step["kind"] for step in guide["steps"]}) >= 2, guide
    assert guide["capabilities"] and guide["gaps"], guide
    summary = outputs["markdown"].split("## 阅读指南（试验）", 1)[1].split("\n## ", 1)[0]
    full = outputs["full"].split("## 阅读指南（试验）", 1)[1].split("\n## ", 1)[0]
    assert "```" not in summary and "--detail full" in summary, summary
    assert "```" in full, full
    assert len(summary) < len(full), (summary, full)
    for step in guide["steps"]:
        location = step["location"]
        path = location["path"]
        assert not Path(path).is_absolute(), path
        source = (repository / path).read_text(encoding="utf-8").splitlines()
        assert 0 < location["line"] <= len(source), location
        assert step["evidence"], step
        assert path in outputs["markdown"], (path, outputs["markdown"])
    print(f"阅读指南源码/产物验收通过；报告和日志：{workspace}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
