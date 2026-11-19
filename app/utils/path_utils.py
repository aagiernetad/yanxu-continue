"""所有本地文件工具共享同一条实际目录边界，提示词不能代替检查。"""
import os
from pathlib import Path

from app.api.context import get_input_files


def resolve_path(filename: str, session_dir: str | None = None, *, for_write=False) -> str:
    if not session_dir or not filename or "\x00" in filename:
        raise ValueError("缺少任务目录或文件名")
    root = Path(session_dir).resolve()
    name = filename.replace("\\", "/")
    for prefix in ("/workspace/", "/mnt/data/", "/home/user/"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    # 兼容模型重复返回提示词中的 output/session_x/run_x 前缀。
    logical_prefix = "/".join(root.parts[-3:]) + "/"
    if name.startswith(logical_prefix):
        name = name[len(logical_prefix):]
    path = Path(name)
    # Windows 的备用数据流和无盘符根路径也必须拒绝。
    if any(":" in part for part in path.parts[1:]) or (not path.is_absolute() and ":" in name):
        raise ValueError("文件名含有无效路径字符")
    resolved = (path if path.is_absolute() else root / path).resolve()
    if not resolved.is_relative_to(root) or resolved == root:
        raise ValueError("拒绝访问：文件必须位于本次任务目录内")
    if for_write and os.path.normcase(resolved.relative_to(root).as_posix()) in {os.path.normcase(name) for name in get_input_files()}:
        raise ValueError("不能覆盖输入附件，请使用新的输出文件名")
    return str(resolved)
