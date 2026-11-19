"""
Markdown 转 PDF 工具

供主智能体把已经生成的 Markdown 文档转换为 PDF。Tool 层只负责解析当前
会话目录中的输入/输出路径，真正的版式转换交给 app.utils.word_converter。
"""

import logging
from pathlib import Path

try:
    from typing import Annotated, Optional
except ImportError:
    from typing_extensions import Annotated, Optional

from langchain_core.tools import tool

from app.api.context import get_session_context
from app.api.monitor import monitor
from app.utils.path_utils import resolve_path
from app.utils.word_converter import convert_md_to_pdf as convert_md_to_pdf_via_word


@tool
def convert_md_to_pdf(
    md_filename: Annotated[str, "要转换的Markdown文档路径（包含.md后缀）"],
    pdf_filename: Annotated[
        Optional[str], "输出的PDF文件路径（可选，默认与源文件同名）"
    ] = None,
) -> str:
    """
    将当前会话目录中的 Markdown 文档转换为 PDF

    :param md_filename: Markdown 文件名或相对路径，缺少后缀时会自动补为 .md
    :param pdf_filename: 可选 PDF 输出文件名；不传时与 Markdown 同名
    :return: 转换结果说明
    """
    monitor.report_tool("Markdown转PDF工具")

    try:
        # 输入路径必须先落到当前会话目录，避免模型传入任意系统路径
        session_dir = get_session_context()
        md_path = Path(md_filename).with_suffix(".md")
        md_abs_path = Path(resolve_path(str(md_path), session_dir))

        if not md_abs_path.exists():
            return f"错误：文件不存在 {md_abs_path}"

        # 未指定 PDF 文件名时，默认与源 Markdown 同目录同名
        if pdf_filename:
            pdf_path = Path(pdf_filename).with_suffix(".pdf")
            pdf_abs_path = Path(resolve_path(str(pdf_path), session_dir, for_write=True))
        else:
            pdf_abs_path = Path(resolve_path(str(md_abs_path.with_suffix(".pdf")), session_dir, for_write=True))

        # PDF 版式、中文字体和 Markdown 解析细节都封装在底层转换模块中
        return convert_md_to_pdf_via_word(md_abs_path, pdf_abs_path)

    except Exception as e:
        logging.error(f"转换失败: {e}", exc_info=True)
        return f"转换失败: {str(e)}"
