"""准备 libclang 许可和随程序分发的 Windows C++ 运行库。"""

import argparse
import hashlib
import json
import os
import shutil
import sys
from importlib import import_module, metadata
from pathlib import Path

if __package__:
    from .check_cpp_semantics import (
        LIBCLANG_VERSION,
        ROOT,
        installed_native_directory,
        pe_import_names,
    )
else:
    from check_cpp_semantics import (
        LIBCLANG_VERSION,
        ROOT,
        installed_native_directory,
        pe_import_names,
    )

RUNTIME_PREFIXES = ("msvcp", "vcruntime", "concrt", "vccorlib", "vcamp", "vcomp")


def binary_info(binary: Path) -> tuple[int, tuple[int, ...] | None]:
    """读取 PE 架构和版本，不加载待分发的 DLL。"""
    importing = import_module("nuitka.utils.Importing")
    pefile = importing.importFromInlineCopy("pefile", must_exist=True)
    with pefile.PE(str(binary), fast_load=True) as executable:
        executable.parse_data_directories(directories=[
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"],
        ])
        records = getattr(executable, "VS_FIXEDFILEINFO", ())
        version = None
        if records:
            record = records[0]
            version = (
                record.FileVersionMS >> 16, record.FileVersionMS & 0xFFFF,
                record.FileVersionLS >> 16, record.FileVersionLS & 0xFFFF,
            )
        return executable.FILE_HEADER.Machine, version


def discover_runtime_directory() -> Path:
    """仅从 Visual Studio 可再分发目录发现最新的 x64 CRT。"""
    candidates: list[Path] = []
    configured = os.environ.get("VCToolsRedistDir")
    if configured:
        candidates.extend(Path(configured).glob("x64/Microsoft.VC*.CRT"))
    for name in ("ProgramFiles", "ProgramFiles(x86)"):
        directory = os.environ.get(name)
        if directory:
            candidates.extend((Path(directory) / "Microsoft Visual Studio").glob(
                "*/*/VC/Redist/MSVC/*/x64/Microsoft.VC*.CRT"
            ))
    versions = [
        (binary_info(path / "msvcp140.dll")[1], path)
        for path in set(candidates) if (path / "msvcp140.dll").is_file()
    ]
    valid = [(version, path) for version, path in versions if version is not None]
    if not valid:
        raise RuntimeError(
            "未找到 Visual Studio 的 x64 可再分发运行库；"
            "请用 --runtime-dir 指向官方 VC Redistributable 提取目录，"
            "不能从 System32 收集分发文件"
        )
    return max(valid, key=lambda item: (item[0], str(item[1])))[1]


def collect_windows_runtime(
    directory: Path, library: Path, python_directory: Path,
) -> dict[str, Path]:
    """从同一来源解析 libclang 和 Python 的 CRT 闭包，缺失即失败。"""
    directory = directory.resolve()
    windows_directory = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
    if windows_directory and directory.is_relative_to(Path(windows_directory).resolve()):
        raise RuntimeError("不能从 Windows 系统目录收集可再分发运行库")
    if not directory.is_dir():
        raise RuntimeError(f"运行库目录不存在：{directory}")
    available: dict[str, Path] = {}
    for file in sorted(directory.rglob("*.dll")):
        name = file.name.lower()
        if not name.startswith(RUNTIME_PREFIXES) or binary_info(file)[0] != 0x8664:
            continue
        previous = available.get(name)
        if previous is not None and previous.read_bytes() != file.read_bytes():
            raise RuntimeError(f"运行库目录包含多个不同的 x64 {name}，请指定唯一版本目录")
        available[name] = file
    python_library = python_directory / (
        f"python{sys.version_info.major}{sys.version_info.minor}.dll"
    )
    if not python_library.is_file():
        raise RuntimeError(f"未找到打包解释器的 Python DLL：{python_library}")
    pending = [library, python_library]
    selected: dict[str, Path] = {}
    while pending:
        binary = pending.pop()
        for name in sorted(pe_import_names(binary)):
            if not name.startswith(RUNTIME_PREFIXES) or name in selected:
                continue
            runtime = available.get(name)
            if runtime is None:
                raise RuntimeError(f"可再分发目录缺少运行库 {name}（{binary.name} 的依赖）")
            version = binary_info(runtime)[1]
            if version is None:
                raise RuntimeError(f"运行库缺少 PE 版本信息：{runtime}")
            python_runtime = python_directory / name
            if python_runtime.is_file():
                python_version = binary_info(python_runtime)[1]
                if python_version is None or python_version > version:
                    raise RuntimeError(
                        f"所选 {name} 的版本 {version} 低于或无法对比 "
                        f"Python 自带版本 {python_version}；请使用更新的可再分发目录"
                    )
            selected[name] = runtime
            pending.append(runtime)
    if not selected:
        raise RuntimeError("未发现 Windows CRT 依赖，拒绝生成未经验证的打包配置")
    return selected


def write_runtime_package(
    files: dict[str, Path], runtime_dir: Path, config: Path,
    data_dir: Path, source: str,
) -> None:
    """生成原生 DLL 收集规则和随包哈希，不将 DLL 当作数据文件。"""
    runtime_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {"source": source, "files": []}
    records: list[dict[str, object]] = []
    filenames: list[str] = []
    for name, original in sorted(files.items()):
        # 配置逐个列出文件，旧准备结果不会混入新版本。
        destination = runtime_dir / Path(name).stem / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, destination)
        records.append({
            "name": name,
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            "version": binary_info(destination)[1],
        })
        filenames.append(destination.resolve().as_posix())
    manifest["files"] = records
    rules = [
        "- module-name: 'clang'",
        "  dlls:",
        "    - by_code:",
        "        setup_code: 'pass'",
        "        filename_code: |",
        f"          {filenames!r}",
        "      dest_path: '.'",
        "      when: 'standalone and win32'",
    ]
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("\n".join(rules) + "\n", encoding="utf-8")
    (data_dir / "windows-runtime.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8",
    )
    (data_dir / "windows-runtime-NOTICE.txt").write_text(
        "This application bundles Microsoft Visual C++ runtime files for x64.\n"
        "The files are collected from Visual Studio Redistributable Code or\n"
        "an explicitly provided official Visual C++ Redistributable extraction.\n"
        "Microsoft runtime files remain subject to their original license.\n"
        "File versions and SHA-256 hashes are recorded in windows-runtime.json.\n"
        "Redistribution: https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "build/cpp-package-data",
    )
    parser.add_argument("--runtime-dir", type=Path, help="官方 x64 VC 运行库来源目录")
    parser.add_argument(
        "--runtime-output-dir", type=Path, default=ROOT / "build/cpp-package-runtime",
    )
    parser.add_argument(
        "--runtime-config", type=Path,
        default=ROOT / "build/cpp-runtime.nuitka-package.config.yml",
    )
    args = parser.parse_args()
    native = installed_native_directory()
    if sys.platform == "win32":
        source = args.runtime_dir or discover_runtime_directory()
        files = collect_windows_runtime(source, native / "libclang.dll", Path(sys.base_prefix))
        write_runtime_package(
            files, args.runtime_output_dir, args.runtime_config, args.output_dir,
            "explicit-directory" if args.runtime_dir else "visual-studio-redist",
        )
        for filename in (
            "MICROSOFT-VC-RUNTIME-LICENSE.rtf",
            "MICROSOFT-VC14-RUNTIME-LICENSE.txt",
        ):
            license_file = source / filename
            if license_file.is_file():
                shutil.copyfile(license_file, args.output_dir / license_file.name)
        print(f"Windows 运行库已准备：{', '.join(sorted(files))}")
    else:
        if args.runtime_dir is not None:
            parser.error("--runtime-dir 仅用于 Windows 打包")
        args.runtime_config.parent.mkdir(parents=True, exist_ok=True)
        args.runtime_config.write_text("- module-name: 'clang'\n  dlls: []\n", encoding="utf-8")
    distribution = metadata.distribution("libclang")
    licenses = [
        Path(str(distribution.locate_file(file)))
        for file in distribution.files or []
        if file.name == "LICENSE.TXT" and ".dist-info" in str(file)
    ]
    if len(licenses) != 1 or not licenses[0].is_file():
        raise RuntimeError("固定 libclang wheel 中未找到唯一的 LICENSE.TXT")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(licenses[0], args.output_dir / "libclang-LICENSE.TXT")
    (args.output_dir / "libclang-NOTICE.txt").write_text(
        f"This PoC bundles libclang {LIBCLANG_VERSION} and its Python bindings.\n"
        f"Distribution: https://pypi.org/project/libclang/{LIBCLANG_VERSION}/\n"
        "Packaging project: https://github.com/sighingnow/libclang\n"
        "Upstream: https://github.com/llvm/llvm-project\n"
        "The complete license shipped in the wheel is preserved as "
        "libclang-LICENSE.TXT.\n"
        "Keep both files when redistributing the PoC executable.\n",
        encoding="utf-8",
    )
    print(f"libclang 许可已准备：{args.output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
