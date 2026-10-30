"""文本文件的完整发布：共享原子替换和持久化步骤，避免导出失败破坏旧结果。"""

import os
import stat
import uuid
from contextlib import suppress
from pathlib import Path


def atomic_write_text(path: Path, content: str) -> None:
    """在已有父目录中写临时文件并同步，完整写入后替换目标，保留已有文件权限。

    替换前失败保留旧文件；替换后目录同步失败仍向上传播，此时目标已是完整新文件。
    每个文件独立提交，不保证一组导出文件同时替换；清理异常不覆盖原始异常。
    """
    temporary = path.with_name(".rr-output-" + uuid.uuid4().hex + ".tmp")
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        mode = None
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            if mode is not None:
                os.fchmod(stream.fileno(), mode)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)
