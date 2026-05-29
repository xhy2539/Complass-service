"""文档导出服务，将纯文本或解析后的文档结构导出为 docx 文件。"""

import re
from io import BytesIO
from typing import Optional

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt


class DocumentExporter:
    """文档导出器，将纯文本导出为格式化的 docx 文件。"""

    @staticmethod
    def export_text_to_docx(
        text: str, file_name: str = "contract.docx", title: Optional[str] = None
    ) -> BytesIO:
        """
        将纯文本导出为 docx 文件（清洁版）。

        Args:
            text: 合同纯文本
            file_name: 导出文件名
            title: 可选的文档标题

        Returns:
            BytesIO 对象，包含 docx 文件内容
        """
        doc = Document()

        # 设置默认字体和大小（宋体/ Times New Roman）
        style = doc.styles["Normal"]
        style.font.name = "Times New Roman"
        style.font.size = Pt(12)

        # 按换行符拆分段落
        lines = text.split("\n")

        for line in lines:
            line = line.strip()
            if not line:
                # 空行添加空段落
                doc.add_paragraph()
                continue

            # 检测标题（简单的启发式规则）
            heading_level = DocumentExporter._detect_heading(line)

            if heading_level > 0:
                # 添加标题
                heading = doc.add_heading(level=heading_level)
                heading_run = heading.add_run(line)
                heading_run.font.size = DocumentExporter._get_heading_size(
                    heading_level
                )
            else:
                # 添加正文段落
                p = doc.add_paragraph(line)
                p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY  # 两端对齐

        # 添加页眉（可选）
        if title:
            sections = doc.sections
            for section in sections:
                header = section.header
                header_para = header.paragraphs[0]
                header_para.text = title
                header_para.style = "Header"

        # 保存到 BytesIO
        buffer = BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        return buffer

    @staticmethod
    def _detect_heading(line: str) -> int:
        """
        检测段落是否为标题（启发式规则）。

        返回标题级别：0=正文, 1-3=标题
        """
        # 规则1：纯数字编号开头（1.  2.1  第一章 等）
        if re.match(r"^第[一二三四五六七八九十]+[章节条]", line):
            return 1
        if re.match(r"^[零一二三四五六七八九十]+、", line):
            return 2
        if re.match(r"^\d+[.．]", line) and len(line) < 30:
            return 2

        # 规则2：特定关键词结尾（：等）
        if line.endswith("：") or line.endswith(":"):
            return 2

        # 规则3：全角括号标题
        if re.match(r"^【[^】]+】$", line):
            return 2

        # 规则4：短行且全是中文/符号（可能是标题）
        if len(line) < 20 and len(line) > 2:
            # 检查是否包含较多数字（可能是条款编号）
            digit_count = sum(1 for c in line if c.isdigit())
            if digit_count > 0 and digit_count < len(line) * 0.3:
                return 3

        return 0

    @staticmethod
    def _get_heading_size(level: int) -> Pt:
        """根据标题级别返回字体大小。"""
        sizes = {
            1: Pt(18),  # 一级标题
            2: Pt(16),  # 二级标题
            3: Pt(14),  # 三级标题
        }
        return sizes.get(level, Pt(12))

    @staticmethod
    def split_into_paragraphs(text: str) -> list[str]:
        """
        将长文本按段落拆分。

        优先按空行拆分，其次按句号/分号+换行符。
        """
        # 先按换行符拆分
        lines = text.split("\n")

        paragraphs = []
        current = []

        for line in lines:
            line = line.strip()
            if not line:
                if current:
                    para = " ".join(current)
                    if para:
                        paragraphs.append(para)
                    current = []
            else:
                current.append(line)

        # 处理最后一段
        if current:
            para = " ".join(current)
            if para:
                paragraphs.append(para)

        return paragraphs
