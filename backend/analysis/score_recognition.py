"""Run a local Audiveris executable and read its MusicXML export."""

import os
import shutil
import subprocess
from pathlib import Path


MUSICXML_EXTENSIONS = (".musicxml", ".mxl", ".xml")
MISSING_AUDIVERIS = "找不到 Audiveris。安装后重启网站，或启动时用 --audiveris 指定可执行文件。"


def find_audiveris(configured=None):
    if configured:
        explicit = Path(configured).expanduser()
        command = str(explicit) if explicit.is_file() else shutil.which(str(explicit))
        return Path(command).resolve() if command else None
    command = shutil.which("audiveris")
    if command:
        return Path(command).resolve()
    if os.name == "nt":
        folders = [Path(os.environ[name]) for name in ("ProgramFiles", "ProgramFiles(x86)") if name in os.environ]
        if os.environ.get("LOCALAPPDATA"):
            folders.append(Path(os.environ["LOCALAPPDATA"]) / "Programs")
        for folder in folders:
            path = folder / "Audiveris" / "Audiveris.exe"
            if path.is_file():
                return path.resolve()
        local = Path(__file__).resolve().parents[2] / "temp" / "audiveris-local" / "app"
        return next(local.rglob("Audiveris.exe"), None)
    return None


def recognize_pdf(pdf, executable, directory):
    if b"%PDF-" not in pdf[:1024]:
        raise ValueError("无法读取 PDF，请检查文件格式和完整性")
    if executable is None:
        raise ValueError(MISSING_AUDIVERIS)

    source = directory / "score.pdf"
    source.write_bytes(pdf)
    output = directory / "export"
    output.mkdir()
    command = [str(executable), "-batch", "-transcribe", "-export", "-output", str(output), "--", str(source)]
    try:
        with (directory / "audiveris.log").open("wb") as log:
            result = subprocess.run(command, cwd=directory, stdout=log, stderr=subprocess.STDOUT, timeout=180,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Audiveris 识谱超过 3 分钟，请尝试只导入需要的几页") from exc
    except (FileNotFoundError, PermissionError) as exc:
        raise ValueError(MISSING_AUDIVERIS) from exc
    if result.returncode != 0:
        raise ValueError(f"Audiveris 转换失败（退出码 {result.returncode}）。请确认 PDF 可打开且包含清晰五线谱")

    exports = sorted(path for path in output.rglob("*") if path.is_file()
                     and path.suffix.lower() in MUSICXML_EXTENSIONS)
    if not exports:
        raise ValueError("Audiveris 未识别出可用的五线谱，请尝试清晰的印刷乐谱")
    if len(exports) != 1:
        raise ValueError("识别结果包含多个乐章，请把需要的一段拆成单独的 PDF 再导入")
    written = exports[0]
    if not 0 < written.stat().st_size <= 5 * 1024 * 1024:
        raise ValueError("识谱导出文件为空或超过 5 MB，请缩短 PDF")
    return written.suffix.lower(), written.read_bytes()
