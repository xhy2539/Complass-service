"""文档导出服务，将纯文本或解析后的文档结构导出为 docx 文件。"""

import re
from io import BytesIO
from typing import Optional

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt
from docx.text.paragraph import Paragraph


def _replace_para_text(para: Paragraph, new_texts: list[str], index: int) -> int:
    """用 new_texts[index] 替换段落的文本，保留格式。返回下一个索引。"""
    runs = para.runs
    if index < len(new_texts):
        new_text = new_texts[index]
        if runs:
            for run in runs[1:]:
                run.text = ""
            runs[0].text = new_text
        else:
            para.text = new_text
        return index + 1
    else:
        for run in runs:
            run.text = ""
        if not runs:
            para.text = ""
        return index


class DocumentExporter:
    """文档导出器，将纯文本导出为格式化的 docx 文件。"""

    @staticmethod
    def export_text_to_docx(
        text: str, file_name: str = "contract.docx", title: Optional[str] = None
    ) -> BytesIO:
        """将纯文本导出为 docx（无原文件时使用）。"""
        doc = Document()
        style = doc.styles["Normal"]
        style.font.name = "Times New Roman"
        style.font.size = Pt(12)

        lines = text.split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                doc.add_paragraph()
                continue
            heading_level = DocumentExporter._detect_heading(line)
            if heading_level > 0:
                heading = doc.add_heading(level=heading_level)
                heading_run = heading.add_run(line)
                heading_run.font.size = DocumentExporter._get_heading_size(
                    heading_level
                )
            else:
                p = doc.add_paragraph(line)
                p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

        if title:
            for section in doc.sections:
                header = section.header
                header_para = header.paragraphs[0]
                header_para.text = title
                header_para.style = "Header"

        buffer = BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        return buffer

    @staticmethod
    def export_text_to_docx_preserve_format(
        original_file_path: str,
        new_text: str,
        file_name: str = "contract.docx",
    ) -> BytesIO:
        """基于原始 DOCX 模板替换文本，保留原有格式。

        按文档元素顺序（正文段落、表格、页眉页脚）逐段落替换文本。
        段落级格式（字体、加粗、斜体、字号、缩进、对齐）全部保留。
        表格结构、边框、合并单元格等格式保留。
        """
        doc = Document(original_file_path)
        # 用 \n\n 分隔段落，与前端 docTextFromReview 保持一致
        new_paragraphs = (
            new_text.split("\n\n") if "\n\n" in new_text else new_text.split("\n")
        )
        para_index = 0
        # --- 1. 只替换正文段落，表格保持原样 ---
        # 前端 docTextFromReview 只包含正文段落，不含表格文本
        for para in doc.paragraphs:
            para_index = _replace_para_text(para, new_paragraphs, para_index)

        # --- 2. 处理页眉页脚 ---
        for section in doc.sections:
            for header_para in section.header.paragraphs:
                para_index = _replace_para_text(header_para, new_paragraphs, para_index)
            for footer_para in section.footer.paragraphs:
                para_index = _replace_para_text(footer_para, new_paragraphs, para_index)

        # --- 3. 如果新文本比原段落多，追加到文档末尾 ---
        if para_index < len(new_paragraphs):
            extra = new_paragraphs[para_index:]
            for text in extra:
                if text.strip():
                    doc.add_paragraph(text)

        buffer = BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        return buffer

    @staticmethod
    def _detect_heading(line: str) -> int:
        if re.match(r"^第[一二三四五六七八九十]+[章节条]", line):
            return 1
        if re.match(r"^[零一二三四五六七八九十]+、", line):
            return 2
        if re.match(r"^\d+[.．]", line) and len(line) < 30:
            return 2
        if line.endswith("：") or line.endswith(":"):
            return 2
        if re.match(r"^【[^】]+】$", line):
            return 2
        if len(line) < 20 and len(line) > 2:
            digit_count = sum(1 for c in line if c.isdigit())
            if digit_count > 0 and digit_count < len(line) * 0.3:
                return 3
        return 0

    @staticmethod
    def _get_heading_size(level: int) -> Pt:
        return {1: Pt(18), 2: Pt(16), 3: Pt(14)}.get(level, Pt(12))
