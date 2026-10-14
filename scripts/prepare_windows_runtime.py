"""下载并解包固定微软运行库，不执行安装器或修改系统。"""

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_VERSION = "14.51.36247.0"
RUNTIME_SHA256 = "843068991daaa1f73ad9f6239bce4d0f6a07a51f18c37ea2a867e9beca71295c"
RUNTIME_URL = (
    "https://download.visualstudio.microsoft.com/download/pr/"
    "ebdab8e5-1d7b-4d9f-a11b-cbb1720c3b12/"
    f"{RUNTIME_SHA256.upper()}/VC_redist.x64.exe"
)
LICENSE_SHA256 = "08651651a7602fc7c0e2763de0fde1ff9f868df2780597cd1775ee9d6441c783"
LICENSE_URL = (
    "https://visualstudio.microsoft.com/wp-content/uploads/2025/10/"
    "Visual-C-V14-License-Redistributable_and_Runtime_ENU.docx"
)


def verified_download(url: str, expected: str, target: Path, local: Path | None) -> None:
    """只接受与固定 SHA256 一致的官方文件，支持复用本地下载做验证。"""
    if local is not None:
        content = local.read_bytes()
    else:
        with urllib.request.urlopen(url, timeout=60) as response:
            content = response.read()
    if hashlib.sha256(content).hexdigest() != expected:
        raise RuntimeError(f"官方文件 SHA256 不匹配，拒绝继续：{url}")
    target.write_bytes(content)


def extract_runtime(archive: Path, directory: Path) -> Path:
    """按固定 Burn 包的清单提取 x64 CAB，使用系统 expand 解压。"""
    content = archive.read_bytes()
    cabinets: list[bytes] = []
    offset = 0
    while (offset := content.find(b"MSCF\x00\x00\x00\x00", offset)) >= 0:
        if offset + 36 <= len(content):
            length = struct.unpack_from("<I", content, offset + 8)[0]
            if 36 <= length <= len(content) - offset:
                cabinets.append(content[offset:offset + length])
        offset += 8
    if len(cabinets) != 2:
        raise RuntimeError("固定 VC Redistributable 的 CAB 结构不符合预期")
    expand = Path(os.environ["SystemRoot"]) / "System32" / "expand.exe"

    def unpack(source: Path, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [str(expand), str(source), "-F:*", str(destination)],
            check=True, capture_output=True, timeout=60,
        )

    for index, name in enumerate(("bootstrap", "payload")):
        cabinet = directory / f"cab-{index}.cab"
        cabinet.write_bytes(cabinets[index])
        unpack(cabinet, directory / name)
    manifest = ET.parse(directory / "bootstrap" / "0")
    payloads = [
        item.attrib["SourcePath"]
        for item in manifest.findall(".//{*}Payload")
        if item.get("FilePath", "").replace("\\", "/")
        == "packages/vcRuntimeMinimum_amd64/cab1.cab"
    ]
    if len(payloads) != 1 or Path(payloads[0]).name != payloads[0]:
        raise RuntimeError("固定 VC Redistributable 清单缺少唯一的 x64 运行库")
    native = directory / "x64"
    unpack(directory / "payload" / payloads[0], native)
    for file in native.glob("*.dll_amd64"):
        shutil.copyfile(file, native / file.name.removesuffix("_amd64"))
    if not all((native / name).is_file() for name in (
        "msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll",
    )):
        raise RuntimeError("固定运行库包未提取出所需的 x64 DLL")
    return native


def extract_license(document: Path, native: Path) -> None:
    """保留官方许可的全部非空正文段落，按原顺序写入随包文本。"""
    with zipfile.ZipFile(document) as archive:
        document_root = ET.fromstring(archive.read("word/document.xml"))
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs = [
        "".join(node.text or "" for node in paragraph.findall(".//w:t", namespace))
        for paragraph in document_root.findall(".//w:p", namespace)
    ]
    content = "\n\n".join(text for text in paragraphs if text.strip())
    if not content:
        raise RuntimeError("官方运行库许可正文为空")
    (native / "MICROSOFT-VC14-RUNTIME-LICENSE.txt").write_text(
        content + "\n", encoding="utf-8",
    )


def main() -> int:
    """为 CI 准备独立运行库来源；任何下载或解包错误直接终止。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "build/windows-runtime-source",
    )
    parser.add_argument("--archive", type=Path, help="复用已下载的固定安装包")
    parser.add_argument("--license-document", type=Path, help="复用已下载的固定许可 DOCX")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("此脚本仅在 Windows 构建机运行")
    directory = args.output_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / "VC_redist.x64.exe"
    document = directory / "Visual-C-V14-License-Redistributable_and_Runtime_ENU.docx"
    verified_download(RUNTIME_URL, RUNTIME_SHA256, archive, args.archive)
    verified_download(LICENSE_URL, LICENSE_SHA256, document, args.license_document)
    native = extract_runtime(archive, directory)
    extract_license(document, native)
    (directory / "provenance.json").write_text(json.dumps({
        "version": RUNTIME_VERSION,
        "archive_url": RUNTIME_URL,
        "archive_sha256": RUNTIME_SHA256,
        "license_url": LICENSE_URL,
        "license_sha256": LICENSE_SHA256,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"固定 Windows 运行库 {RUNTIME_VERSION} 已准备：{native}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
