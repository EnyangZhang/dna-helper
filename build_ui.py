"""Build a standalone MXU desktop UI for DNA Helper."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import maa


ROOT = Path(__file__).resolve().parent
ASSETS_DIR = ROOT / "assets"
DEFAULT_OUTPUT = ROOT / "dist" / "DNAHelper"
CUSTOM_MXU_EXE = (
    ROOT
    / ".cache"
    / "mxu-v2.1.3"
    / "src-tauri"
    / "target"
    / "x86_64-pc-windows-msvc"
    / "release"
    / "mxu.exe"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="生成使用 MaaNTE 同款 MXU 的 DNA Helper 桌面客户端"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"输出目录，默认：{DEFAULT_OUTPUT}",
    )
    parser.add_argument(
        "--mxu-exe",
        type=Path,
        help="已有定制 mxu.exe 路径；未提供时使用项目缓存中的定制构建",
    )
    return parser.parse_args()


def validate_output_path(output: Path) -> Path:
    resolved = output.resolve()
    allowed_root = (ROOT / "dist").resolve()
    if resolved == allowed_root or allowed_root not in resolved.parents:
        raise RuntimeError(f"输出目录必须位于 {allowed_root} 的子目录中：{resolved}")
    return resolved


def find_mxu_exe(explicit: Path | None) -> Path:
    if explicit is not None:
        resolved = explicit.expanduser().resolve()
        if not resolved.is_file():
            raise RuntimeError(f"指定的 MXU 不存在：{resolved}")
        return resolved

    if CUSTOM_MXU_EXE.is_file():
        return CUSTOM_MXU_EXE.resolve()

    raise RuntimeError(
        "缺少带安全日志清理功能的定制 MXU。请先运行 "
        r"tools\build_custom_mxu.ps1，或通过 --mxu-exe 指定已构建的定制版本。"
    )


def prepare_output(output: Path) -> None:
    if output.exists() and (not output.is_dir() or output.is_symlink()):
        raise RuntimeError(f"拒绝覆盖非普通目录：{output}")
    output.mkdir(parents=True, exist_ok=True)

    # 仅清理构建产物，保留 MXU 生成的 config/ 与 debug/。
    for name in ("agent", "maafw", "resource"):
        target = output / name
        if target.exists():
            if not target.is_dir() or target.is_symlink():
                raise RuntimeError(f"拒绝覆盖非普通目录：{target}")
            shutil.rmtree(target)
    for name in (
        "DNAHelper.exe",
        "interface.json",
        "THIRD_PARTY_MXU_LICENSE.txt",
        "THIRD_PARTY_MXU_README.md",
    ):
        target = output / name
        if target.exists():
            if not target.is_file() or target.is_symlink():
                raise RuntimeError(f"拒绝覆盖非普通文件：{target}")
            target.unlink()


def copy_runtime(output: Path) -> None:
    maa_bin = Path(maa.__file__).resolve().parent / "bin"
    if not (maa_bin / "MaaFramework.dll").is_file():
        raise RuntimeError(f"未找到 MaaFramework 运行库：{maa_bin}")
    shutil.copytree(maa_bin, output / "maafw")


def copy_project_files(output: Path) -> None:
    interface_path = ASSETS_DIR / "interface.json"
    interface = json.loads(interface_path.read_text(encoding="utf-8"))
    version = str(interface.get("version", "0.1.0"))
    interface["title"] = f"DNA Helper v{version} | 二重螺旋助手"
    (output / "interface.json").write_text(
        json.dumps(interface, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )
    shutil.copytree(ASSETS_DIR / "resource", output / "resource")
    shutil.copytree(ROOT / "agent", output / "agent")


def copy_licenses(mxu_exe: Path, output: Path) -> None:
    for name, destination in (
        ("LICENSE", "THIRD_PARTY_MXU_LICENSE.txt"),
        ("README.md", "THIRD_PARTY_MXU_README.md"),
    ):
        source = mxu_exe.parent / name
        if source.is_file():
            shutil.copy2(source, output / destination)


def main() -> int:
    args = parse_args()
    output = validate_output_path(args.output)
    mxu_exe = find_mxu_exe(args.mxu_exe)

    print(f"MXU：{mxu_exe}")
    print(f"输出：{output}")
    prepare_output(output)
    shutil.copy2(mxu_exe, output / "DNAHelper.exe")
    copy_runtime(output)
    copy_project_files(output)
    copy_licenses(mxu_exe, output)
    print(f"构建完成：{output / 'DNAHelper.exe'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
