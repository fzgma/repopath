"""在源码或隔离后的 Nuitka 产物上验收真实 C++ 语义分析。"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import import_module, metadata
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "cpp_semantic"
LIBCLANG_VERSION = "18.1.1"


def prepare_fixture(destination: Path) -> Path:
    """复制无 SDK 依赖的源码并生成当前机器有效的编译命令。"""
    shutil.copytree(FIXTURE, destination)
    commands: list[dict[str, str | list[str]]] = [
        {
            "directory": str(destination),
            "file": str(destination / "src" / filename),
            "arguments": [
                "clang++",
                "-x",
                "c++",
                "-std=c++17",
                "-nostdinc",
                "-nostdinc++",
                "-I",
                str(destination / "include"),
                "-c",
                str(destination / "src" / filename),
            ],
        }
        for filename in ("api.cpp", "main.cpp")
    ]
    database = destination / "compile_commands.json"
    database.write_text(
        json.dumps(commands, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return database


def isolated_environment(workspace: Path) -> dict[str, str]:
    """阻止产物从 Python、LLVM 环境变量和 PATH 寻找开发机依赖。"""
    excluded = {
        "VIRTUAL_ENV", "CONDA_PREFIX", "LD_LIBRARY_PATH", "LD_PRELOAD",
        "DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH", "CPATH",
        "CPLUS_INCLUDE_PATH", "C_INCLUDE_PATH", "INCLUDE", "LIB", "LIBPATH",
    }
    environment = {
        name: value
        for name, value in os.environ.items()
        if name.upper() not in excluded
        and not name.upper().startswith(("PYTHON", "CLANG", "LIBCLANG", "LLVM"))
    }
    empty_path = workspace / "no tools"
    unpack_path = workspace / "unpack 临时目录"
    empty_path.mkdir()
    unpack_path.mkdir()
    environment.update({
        "PATH": str(empty_path),
        "TEMP": str(unpack_path),
        "TMP": str(unpack_path),
        "TMPDIR": str(unpack_path),
        "PYTHONUTF8": "1",
    })
    return environment


def installed_native_directory() -> Path:
    """只接受 requirements-cpp 中固定的打包发行，防止 bindings 混装。"""
    distribution = metadata.distribution("libclang")
    if distribution.version != LIBCLANG_VERSION:
        raise RuntimeError(
            f"需要 libclang=={LIBCLANG_VERSION}，实际为 {distribution.version}"
        )
    try:
        metadata.distribution("clang")
    except metadata.PackageNotFoundError:
        pass
    else:
        raise RuntimeError("请勿同时安装 PyPI clang 和 libclang")
    native = Path(str(distribution.locate_file("clang/native"))).resolve()
    if not (native / native_library_name()).is_file():
        raise RuntimeError(f"libclang wheel 的原生库缺失：{native}")
    return native


def native_library_name() -> str:
    """返回当前发布矩阵对应的原生库文件名。"""
    if sys.platform == "win32":
        return "libclang.dll"
    if sys.platform.startswith("linux"):
        return "libclang.so"
    raise RuntimeError("打包验收只支持 Windows 和 Linux")


def pe_import_names(binary: Path) -> set[str]:
    """借助固定 Nuitka 的 PE 解析器读取导入表，不加载目标 DLL。"""
    importing = import_module("nuitka.utils.Importing")
    pefile = importing.importFromInlineCopy("pefile", must_exist=True)
    with pefile.PE(str(binary), fast_load=True) as executable:
        executable.parse_data_directories(directories=[
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"],
        ])
        return {
            entry.dll.decode("ascii").lower()
            for table in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT")
            for entry in getattr(executable, table, ())
        }


def check_windows_runtime(distribution: Path, library: Path) -> dict[str, list[str]]:
    """要求 libclang 及其 CRT 的运行库依赖随包，防止系统 CRT 掩盖遗漏。"""
    pending = [library]
    imports: dict[str, list[str]] = {}
    directories = (distribution, library.parent)
    available = {
        file.name.lower(): file
        for directory in directories
        for file in directory.iterdir()
        if file.is_file()
    }
    while pending:
        binary = pending.pop()
        name = binary.relative_to(distribution).as_posix()
        if name in imports:
            continue
        dependencies = pe_import_names(binary)
        imports[name] = sorted(dependencies)
        for dependency in sorted(dependencies):
            if not dependency.startswith((
                "msvcp", "vcruntime", "concrt", "vccorlib", "vcamp", "vcomp",
            )):
                continue
            bundled = available.get(dependency)
            if bundled is None:
                raise RuntimeError(
                    f"Nuitka 产物缺少运行库 {dependency}（{name} 的依赖）；"
                    "请重新准备所需运行库后打包，"
                    "不能以开发机系统 DLL 可用作为便携性验收依据"
                )
            pending.append(bundled)
    return imports


def check_windows_onefile_bootstrap(artifact: Path) -> None:
    """单文件入口在解包之前不能依赖负载中的 VC 运行库。"""
    external = sorted(
        name for name in pe_import_names(artifact)
        if name.startswith(("msvcp", "vcruntime", "concrt", "vccorlib", "vcamp", "vcomp"))
    )
    if external:
        raise RuntimeError(
            f"单文件启动入口仍依赖外部运行库：{', '.join(external)}；"
            "请使用静态链接运行库的启动入口重新构建"
        )


def check_linux_runtime(library: Path) -> dict[str, str]:
    """记录 ELF 依赖、RPATH 和版本要求，拒绝缺库或绝对构建路径。"""
    environment = dict(os.environ)
    for key in ("LD_LIBRARY_PATH", "LD_PRELOAD"):
        environment.pop(key, None)
    results: dict[str, str] = {}
    for name, command in (
        ("dynamic", ["readelf", "--dynamic", str(library)]),
        ("versions", ["readelf", "--version-info", str(library)]),
        ("resolved", ["ldd", str(library)]),
    ):
        result = subprocess.run(
            command, env=environment, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30, check=True,
        )
        results[name] = result.stdout
    if "not found" in results["resolved"]:
        raise RuntimeError(f"Linux 产物仍有未满足的库依赖：\n{results['resolved']}")
    for line in results["dynamic"].splitlines():
        if "(RPATH)" in line or "(RUNPATH)" in line:
            paths = re.search(r"\[(.*)\]", line)
            if paths is None or any(
                not value.startswith(("$ORIGIN", "${ORIGIN}"))
                for value in paths.group(1).split(":") if value
            ):
                raise RuntimeError(f"产物 RPATH 不可随目录搬移：{line.strip()}")
    return results


def check_windows_runtime_manifest(distribution: Path) -> None:
    """核对随包运行库与构建时选定的来源一致，避免同名旧库混入。"""
    manifest = distribution / "licenses" / "windows-runtime.json"
    if not manifest.is_file():
        raise RuntimeError("Nuitka 产物未包含 Windows 运行库清单")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise RuntimeError("Windows 运行库清单为空或格式无效")
    names: set[str] = set()
    for item in cast(list[object], files):
        entry = cast(dict[str, Any], item) if isinstance(item, dict) else {}
        name = entry.get("name")
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or "/" in name or "\\" in name
            or not name.lower().endswith(".dll")
            or name.lower() in names
        ):
            raise RuntimeError("Windows 运行库清单包含无效或重复的文件名")
        names.add(name.lower())
        runtime = distribution / name
        if not runtime.is_file():
            raise RuntimeError(f"Nuitka 产物缺少清单中的运行库：{name}")
        digest = hashlib.sha256(runtime.read_bytes()).hexdigest()
        if digest != entry.get("sha256"):
            raise RuntimeError(f"随包运行库与构建时选定的文件不一致：{name}")
    if not {"msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"} <= names:
        raise RuntimeError("Windows 运行库清单未覆盖当前 libclang 所需的运行库")


def check_packaged_native(
    distribution: Path, native: Path, workspace: Path,
) -> None:
    """同时检查 standalone 和 onefile 打包前的真实原生负载。"""
    bundled = distribution / "clang" / "native" / native_library_name()
    if not bundled.is_file():
        raise RuntimeError(f"Nuitka 产物未包含原生库：{bundled}")
    if not (distribution / "licenses" / "libclang-LICENSE.TXT").is_file():
        raise RuntimeError("Nuitka 产物未包含 libclang 许可证")
    evidence: dict[str, list[str]] | dict[str, str]
    if sys.platform == "win32":
        # Linux 打包可能调整 ELF 的 RPATH，因此只对未调整的 PE 校验哈希。
        expected = hashlib.sha256(
            (native / native_library_name()).read_bytes()
        ).digest()
        actual = hashlib.sha256(bundled.read_bytes()).digest()
        if actual != expected:
            raise RuntimeError("随包 libclang 与安装的固定版本不一致")
        check_windows_runtime_manifest(distribution)
        evidence = check_windows_runtime(distribution, bundled)
    else:
        evidence = check_linux_runtime(bundled)
    (workspace / "native-dependencies.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8",
    )


@contextmanager
def hide_installed_native(native: Path, enabled: bool) -> Iterator[None]:
    """在专用打包环境临时隐藏原始库；无论验收结果如何都恢复。"""
    if not enabled:
        yield
        return
    prefix = Path(sys.prefix).resolve()
    hidden = native.with_name("native.repopath-smoke-hidden")
    if (
        not native.is_relative_to(prefix)
        or not hidden.resolve().is_relative_to(prefix)
        or native.name != "native"
        or native.parent.name != "clang"
        or hidden.exists()
    ):
        raise RuntimeError(f"拒绝移动专用解释器目录之外的库：{native}")
    native.rename(hidden)
    try:
        yield
    finally:
        hidden.rename(native)


def relocate_artifact(
    mode: str, artifact: Path, workspace: Path, native: Path,
) -> Path:
    """将产物复制到含空格和中文的新目录，验证随包库已收集。"""
    destination = workspace / "moved application 程序"
    if mode == "standalone":
        if not artifact.is_file() or not artifact.parent.name.endswith(".dist"):
            raise RuntimeError("standalone 的 --artifact 必须是 .dist 内的程序")
        shutil.copytree(artifact.parent, destination)
        check_packaged_native(destination, native, workspace)
    else:
        if not artifact.is_file():
            raise RuntimeError(f"onefile 产物不存在：{artifact}")
        # Nuitka 默认保留压入 onefile 的 .dist，不能只测开发机上能否启动。
        distribution = artifact.parent / f"{artifact.stem}.dist"
        check_packaged_native(distribution, native, workspace)
        if sys.platform == "win32":
            check_windows_onefile_bootstrap(artifact)
        destination.mkdir()
        shutil.copy2(artifact, destination / artifact.name)
    return destination / artifact.name


def run_cli(
    command: list[str], repository: Path, database: Path, report: Path,
    workspace: Path, environment: dict[str, str], *, backend: str | None,
    succeeds: bool = True,
) -> dict[str, Any]:
    """执行真实 CLI，任何非预期退出或 JSON 缺失都直接失败。"""
    arguments = [
        *command, str(repository), "--profile", "deep", "--no-python",
        "--no-git", "--format", "json", "-o", str(report),
    ]
    if backend is not None:
        arguments.extend([
            "--cpp-backend", backend, "--compile-commands", str(database),
        ])
    result = subprocess.run(
        arguments, cwd=workspace, env=environment, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=120,
        check=False,
    )
    report.with_suffix(".stdout.txt").write_text(result.stdout, encoding="utf-8")
    report.with_suffix(".stderr.txt").write_text(result.stderr, encoding="utf-8")
    if (result.returncode == 0) != succeeds:
        raise RuntimeError(
            f"CLI 非预期退出 {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    if not report.is_file():
        raise RuntimeError(f"CLI 未写出 JSON：{report}\n{result.stderr}")
    return json.loads(report.read_text(encoding="utf-8"))


def check_semantic_report(payload: dict[str, Any]) -> None:
    """验证双 TU 覆盖、重载解析、USR 归并和跨文件定义定位。"""
    cpp = payload["cpp"]
    assert cpp["backend"] == "libclang", cpp
    assert cpp["status"] == "completed", cpp
    assert cpp["semantic_status"] == "completed", cpp
    assert cpp["analysis_level"] == "semantic", cpp
    assert LIBCLANG_VERSION in cpp["library_version"], cpp["library_version"]
    assert payload["analysis"]["analyzers"]["cpp"]["status"] == "completed"
    coverage = cpp["coverage"]
    assert coverage["total_files"] == 3, coverage
    assert coverage["covered_files"] == 3, coverage
    assert coverage["total_translation_units"] == 2, coverage
    assert coverage["parsed_translation_units"] == 2, coverage
    assert coverage["failed_translation_units"] == 0, coverage
    assert coverage["uncovered_files"] == [], coverage
    symbols = cpp["semantic_symbols"]
    assert len({symbol["usr"] for symbol in symbols}) == len(symbols), symbols
    overloads = [
        symbol for symbol in symbols
        if symbol["qualified_name"] == "demo::transform"
    ]
    assert len(overloads) == 2, overloads
    integer = next(
        symbol for symbol in overloads
        if "".join(symbol["type_spelling"].split()) == "int(int)"
    )
    floating = next(symbol for symbol in overloads if symbol is not integer)
    assert integer["usr"] and floating["usr"] != integer["usr"], overloads
    assert any(
        location["path"] == "include/api.hpp"
        for location in integer["declarations"]
    ), integer
    assert len(integer["definitions"]) == 1, integer
    assert integer["definitions"][0]["path"] == "src/api.cpp", integer
    mains = [symbol for symbol in symbols if symbol["name"] == "main"]
    assert len(mains) == 1, mains
    calls = [
        call for call in cpp["direct_calls"]
        if call["caller_usr"] == mains[0]["usr"]
    ]
    assert len(calls) == 1, calls
    assert calls[0]["callee_usr"] == integer["usr"], calls
    assert calls[0]["location"]["path"] == "src/main.cpp", calls
    assert calls[0]["location"]["line"] == 4, calls


def main() -> int:
    """准备独立目录并执行所选源码或打包验收。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=("basic", "source", "standalone", "onefile"),
        required=True,
    )
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--work-dir", type=Path, default=ROOT / "build/cpp-smoke")
    parser.add_argument(
        "--hide-installed-library", action="store_true",
        help="仅在专用打包环境使用：临时隐藏安装的原生库，并在结束后恢复",
    )
    args = parser.parse_args()
    packaged = args.mode in {"standalone", "onefile"}
    if packaged != (args.artifact is not None):
        parser.error("standalone/onefile 必须指定 --artifact，源码模式不能指定")
    if args.hide_installed_library and not packaged:
        parser.error("--hide-installed-library 只能用于打包产物")
    args.work_dir.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(
        prefix=f"{args.mode}-", dir=args.work_dir.resolve(),
    ))
    repository = workspace / "C++ fixture 空格"
    database = prepare_fixture(repository)
    environment = isolated_environment(workspace)
    if args.mode == "basic":
        command = [sys.executable, "-S", str(ROOT / "repopath.py")]
        basic = run_cli(
            command, repository, database, workspace / "basic.json",
            workspace, environment, backend=None,
        )
        assert basic["cpp"]["backend"] == "basic", basic["cpp"]
        assert basic["cpp"]["status"] == "completed", basic["cpp"]
        missing = run_cli(
            command, repository, database, workspace / "missing-library.json",
            workspace, environment, backend="libclang", succeeds=False,
        )
        assert missing["cpp"]["backend"] == "libclang", missing["cpp"]
        assert missing["cpp"]["status"] == "failed", missing["cpp"]
        assert missing["cpp"]["semantic_status"] == "failed", missing["cpp"]
    else:
        native = installed_native_directory()
        if packaged:
            artifact = relocate_artifact(
                args.mode, args.artifact.resolve(), workspace, native,
            )
            command = [str(artifact)]
        else:
            command = [sys.executable, str(ROOT / "repopath.py")]
        with hide_installed_native(native, args.hide_installed_library):
            payload = run_cli(
                command, repository, database, workspace / "semantic.json",
                workspace, environment, backend="libclang",
            )
            check_semantic_report(payload)
    print(f"C++ {args.mode} 验收通过；报告和日志：{workspace}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
