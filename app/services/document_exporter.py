"""文档导出服务，将纯文本或解析后的文档结构导出为 docx 文件。"""

import re
from io import BytesIO
from typing import Optional

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt
from docx.text.paragraph import Paragraph


def _set_para_text(para: Paragraph, text: str) -> None:
    """替换段落文本，保留格式（字体、加粗、字号等由原有 run 继承）。"""
    runs = para.runs
    if runs:
        for run in runs[1:]:
            run.text = ""
        runs[0].text = text
    else:
        para.text = text


def _text_similarity(t1: str, t2: str) -> float:
    """基于字符级 Jaccard 相似度的文本比较。"""
    if not t1 or not t2:
        return 0.0
    s1 = set(t1.strip())
    s2 = set(t2.strip())
    if not s1 or not s2:
        return 0.0
    return len(s1 & s2) / len(s1 | s2)


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

        改用内容相似度匹配替代位置匹配，在段落增删时保持对齐：
        - 相似度达阈值的段落 → 替换文本，保留格式
        - 在原文档中找不到匹配的新段落 → 追加到文档末尾
        - 在新文本中找不到匹配的旧段落 → 清空文本
        """
        doc = Document(original_file_path)
        sep = "\n\n" if "\n\n" in new_text else "\n"
        new_paragraphs = [p for p in new_text.split(sep)]
        # 只取正文段落，排除表格单元格内的段落
        from docx.oxml.ns import qn

        def _is_body_para(p):
            parent = p._element.getparent()
            while parent is not None:
                if parent.tag == qn("w:tc"):
                    return False
                parent = parent.getparent()
            return True

        original_paras = [p for p in doc.paragraphs if _is_body_para(p)]
        # 如果过滤后为空，回退到全部段落
        if not original_paras:
            original_paras = list(doc.paragraphs)

        MATCH_THRESHOLD = 0.35
        LOOKAHEAD = 3

        oi = 0  # 原始段落索引
        ni = 0  # 新文本段落索引
        extra: list[str] = []  # 无法定位的插入段落，追加到末尾

        while oi < len(original_paras) and ni < len(new_paragraphs):
            sim = _text_similarity(original_paras[oi].text, new_paragraphs[ni])

            if sim >= MATCH_THRESHOLD:
                # -- 直接匹配：替换文本，保留格式 --
                _set_para_text(original_paras[oi], new_paragraphs[ni])
                oi += 1
                ni += 1
                continue

            # -- 探查：当前新段落是否匹配后续原始段落？--
            # 命中说明中间的原始段落已被用户删除
            orig_skip = None
            for off in range(1, LOOKAHEAD + 1):
                if oi + off < len(original_paras):
                    s = _text_similarity(
                        original_paras[oi + off].text, new_paragraphs[ni]
                    )
                    if s >= MATCH_THRESHOLD:
                        orig_skip = off
                        break

            if orig_skip is not None:
                for _ in range(orig_skip):
                    _set_para_text(original_paras[oi], "")
                    oi += 1
                continue  # 不消耗 ni，重新用同一新段落匹配

            # -- 探查：当前原始段落是否匹配后续新段落？--
            # 命中说明中间的新段落是用户插入的
            new_skip = None
            for off in range(1, LOOKAHEAD + 1):
                if ni + off < len(new_paragraphs):
                    s = _text_similarity(
                        original_paras[oi].text, new_paragraphs[ni + off]
                    )
                    if s >= MATCH_THRESHOLD:
                        new_skip = off
                        break

            if new_skip is not None:
                for _ in range(new_skip):
                    extra.append(new_paragraphs[ni])
                    ni += 1
                continue  # 不消耗 oi，重新用同一原始段落匹配

            # -- 都探查不到 → 当作内容修改处理 --
            _set_para_text(original_paras[oi], new_paragraphs[ni])
            oi += 1
            ni += 1

        # 清空剩余未匹配的原始段落（新文本较短）
        while oi < len(original_paras):
            _set_para_text(original_paras[oi], "")
            oi += 1

        # 追加剩余新段落（原文档较短）和探查到的插入段落
        while ni < len(new_paragraphs):
            extra.append(new_paragraphs[ni])
            ni += 1

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
