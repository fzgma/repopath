"""验收脚本在非 UTF-8 控制台下仍能完成检查并输出中文路径。"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("script", ["check_cpp_analysis.py", "check_reading_guide.py"])
def test_smoke_script_with_legacy_console(script: str, tmp_path: Path) -> None:
    """模拟 Windows CI 的西文输出编码，覆盖源码分析及验收结果输出。"""
    environment = dict(os.environ, PYTHONUTF8="0", PYTHONIOENCODING="cp1252")
    result = subprocess.run(
        [
            sys.executable, str(ROOT / "scripts" / script),
            "--work-dir", str(tmp_path / "验收报告"),
        ],
        env=environment, capture_output=True, text=True, encoding="utf-8",
        errors="strict", timeout=120, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "验收通过" in result.stdout
    assert "验收报告" in result.stdout
