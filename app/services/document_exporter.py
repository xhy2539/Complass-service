"""文档导出服务，将纯文本或解析后的文档结构导出为 docx 文件。"""

import logging
import re
from io import BytesIO
from typing import Optional

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt
from docx.text.paragraph import Paragraph

logger = logging.getLogger(__name__)

# 表格标记常量（与 document_parser.py 保持一致）
TABLE_START_MARKER = "[TABLE_START]"
TABLE_END_MARKER = "[TABLE_END]"
TABLE_TITLE_MARKER = "【表格】"
TABLE_ROW_SEP = "\n"


def _set_para_text(para: Paragraph, text: str) -> None:
    """替换段落文本，保留格式（字体、加粗、字号等由原有 run 继承）。"""
    runs = para.runs
    if runs:
        for run in runs[1:]:
            run.text = ""
        runs[0].text = text
    else:
        para.text = text


def _get_para_text_from_elem(elem) -> str:
    """从 CT_P XML 元素提取纯文本（遍历所有 w:t 子元素）。"""
    from docx.oxml.ns import qn

    return "".join(t.text or "" for t in elem.iter(qn("w:t")))


def _remove_table_markers(doc: Document) -> None:
    """删除DOCX中包含表格标记的段落块（从 [TABLE_START] 到 [TABLE_END]），
    同时将原始表格元素保留并移回 body 正确位置。

    标记格式：[TABLE_START]【表格】... [TABLE_END]
    支持文档中的多个表格块。
    """
    from docx.oxml.ns import qn

    TABLE_START_PATTERN = re.compile(re.escape(TABLE_START_MARKER))
    TABLE_END_PATTERN = re.compile(re.escape(TABLE_END_MARKER))

    body = doc.element.body
    body_children = list(body)  # snapshot for index calculation

    # 第一步：找出所有 [TABLE_START] ~ [TABLE_END] 表格块的索引范围
    table_blocks: list[list[int]] = []  # 每个元素为 [start_idx, end_idx]
    i = 0
    while i < len(body_children):
        child = body_children[i]
        if child.tag == qn("w:p") and TABLE_START_PATTERN.search(
            _get_para_text_from_elem(child).strip()
        ):
            start_idx = i
            j = start_idx
            while j < len(body_children):
                child_j = body_children[j]
                if child_j.tag == qn("w:p") and TABLE_END_PATTERN.search(
                    _get_para_text_from_elem(child_j).strip()
                ):
                    table_blocks.append([start_idx, j])
                    i = j  # 跳过已扫描区域，从下一位置继续查找
                    break
                j += 1
        i += 1

    if not table_blocks:
        return

    # 第二步：收集所有表格块内待删除的段落和其中嵌入的表格元素
    paras_to_remove: list[tuple[int, object]] = []
    table_elements: list[tuple[int, object]] = []
    for start_idx, end_idx in table_blocks:
        for idx in range(start_idx, end_idx + 1):
            child = body_children[idx]
            paras_to_remove.append((idx, child))
            for sub_child in child:
                if sub_child.tag == qn("w:tbl"):
                    table_elements.append((idx, sub_child))
                    break

    # 第三步：按索引降序删除段落（避免删除后索引变化影响未删除元素）
    for idx, elem in reversed(paras_to_remove):
        elem.getparent().remove(elem)

    # 第四步：将表格元素插入 body 正确位置
    # 删除后表格被 reparent 到 body 末尾，位置已漂移
    # new_idx = 原始idx - 删除发生在原始idx之前的次数
    deleted_indices = {idx for idx, _ in paras_to_remove}
    for tbl_orig_idx, table_elem in sorted(table_elements):
        deletions_before = sum(1 for d in deleted_indices if d < tbl_orig_idx)
        new_idx = tbl_orig_idx - deletions_before
        body.insert(new_idx, table_elem)


def _text_similarity(t1: str, t2: str) -> float:
    """基于字符级 Jaccard 相似度的文本比较。"""
    if not t1 or not t2:
        return 0.0
    s1 = set(t1.strip())
    s2 = set(t2.strip())
    if not s1 or not s2:
        return 0.0
    return len(s1 & s2) / len(s1 | s2)


def _parse_table_marker(text: str) -> list[list[str]] | None:
    """解析表格标记文本，返回单元格二维数组。

    支持两种格式：
    - [TABLE_START]【表格】\ncell1 | cell2\n[TABLE_END]
    - 【表格】\ncell1 | cell2  （无 TABLE_START/END 包裹）
    """
    # 提取 TABLE_START 到 TABLE_END 之间的内容
    start = text.find(TABLE_START_MARKER)
    end = text.find(TABLE_END_MARKER)
    if start != -1 and end != -1:
        content = text[start + len(TABLE_START_MARKER) : end]
    else:
        content = text

    # 去掉 【表格】 标记
    content = content.strip()
    if content.startswith(TABLE_TITLE_MARKER):
        content = content[len(TABLE_TITLE_MARKER) :].strip()

    if not content:
        return None

    # 兼容旧格式 |||TABLE_ROW|||，转为 \n 统一处理
    content = content.replace("|||TABLE_ROW|||", "\n")
    lines = [line.strip() for line in content.split("\n") if line.strip()]
    rows = []
    for line in lines:
        cells = [c.strip() for c in line.split("|")]
        if cells:
            rows.append(cells)

    return rows if rows else None


def _write_table_content(table, cells: list[list[str]]) -> None:
    """将单元格数据写入 python-docx Table 对象。

    保留现有行列数，不增删行列。如 cells 行列少于表格，只覆盖前 N 行/列；
    如 cells 行列多于表格，忽略超出的部分。
    """
    for r, row in enumerate(cells):
        if r >= len(table.rows):
            break
        for c, cell_text in enumerate(row):
            if c >= len(table.rows[r].cells):
                break
            table.rows[r].cells[c].text = cell_text


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
    def _parse_table_block(text: str):
        """解析【表格】标记块，返回 (headers, rows) 或 None。"""
        idx = text.find("【表格】")
        if idx < 0:
            return None
        after = text[idx + 4 :].strip()
        lines = [ln.strip() for ln in after.split("\n") if ln.strip() and "|" in ln]
        if len(lines) < 2:
            return None
        headers = [c.strip() for c in lines[0].split("|")]
        rows = [[c.strip() for c in ln.split("|")] for ln in lines[1:]]
        if not headers or any(len(r) != len(headers) for r in rows):
            return None
        return (headers, rows)

    @staticmethod
    def _update_template_table(tbl, headers, rows):
        """用解析后的表头和数据行填充模板表格，自动补齐/清空行。"""
        need = 1 + len(rows)
        while len(tbl.rows) < need:
            tbl.add_row()
        for ri in range(len(tbl.rows)):
            for c in tbl.rows[ri].cells:
                for p in c.paragraphs:
                    for run in p.runs:
                        run.text = ""
        col_count = min(len(headers), len(tbl.columns))
        for ci in range(col_count):
            tbl.rows[0].cells[ci].paragraphs[0].runs[0].text = (
                headers[ci] if tbl.rows[0].cells[ci].paragraphs[0].runs else ""
            )
            if not tbl.rows[0].cells[ci].paragraphs[0].runs:
                tbl.rows[0].cells[ci].text = headers[ci]
        for ri, row_data in enumerate(rows):
            for ci in range(min(len(row_data), col_count)):
                cell = tbl.rows[ri + 1].cells[ci]
                if cell.paragraphs[0].runs:
                    cell.paragraphs[0].runs[0].text = row_data[ci]
                else:
                    cell.text = row_data[ci]

    @classmethod
    def _extract_and_strip_tables(cls, text: str, template_tables):
        """提取【表格】块写回原模板表格，多余表格追加到extra_tables供调用方处理。"""
        TABLE_MARKER = "【表格】"
        lines = text.split("\n")
        result: list[str] = []
        parsed_tables: list[tuple[list[str], list[list[str]]]] = []

        i = 0
        while i < len(lines):
            stripped = lines[i].strip()
            if stripped.startswith(TABLE_MARKER):
                table_lines = []
                j = i + 1
                while j < len(lines):
                    ln = lines[j].strip()
                    if ln and "|" in ln:
                        table_lines.append(ln)
                    elif ln:
                        break
                    j += 1
                if len(table_lines) >= 2:
                    headers = [c.strip() for c in table_lines[0].split("|")]
                    rows = [
                        [c.strip() for c in ln.split("|")] for ln in table_lines[1:]
                    ]
                    if all(len(r) == len(headers) for r in rows):
                        parsed_tables.append((headers, rows))
                # 回删所有连续 tab 分隔行（与表格内容重复）
                while result and result[-1].strip() == "":
                    result.pop()
                while result and "\t" in result[-1]:
                    popped = result.pop().strip()
                    if not popped:
                        break
                i = j
                continue
            result.append(lines[i])
            i += 1

        # 写入模板表格（按序对应）
        for k, (headers, rows) in enumerate(parsed_tables):
            if k < len(template_tables):
                cls._update_template_table(template_tables[k], headers, rows)
        # 返回纯文本 + 额外表格数据
        return "\n".join(result), parsed_tables[len(template_tables) :]

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

        表格处理：检测 [TABLE_START] 标记 → 跳过相似度匹配，直接通过
        python-docx 的 table API 逐单元格写入，完全保留表格原样和格式。
        """
        doc = Document(original_file_path)
        # 提取【表格】块写回原模板表格，返回去表纯文本和额外表格
        clean_text, extra_tables = DocumentExporter._extract_and_strip_tables(
            new_text, doc.tables
        )
        sep = "\n\n" if "\n\n" in clean_text else "\n"
        new_paragraphs = [p for p in clean_text.split(sep)]
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

        # 移除标题前的模板 tab 行：先清空，再从匹配列表剔除
        title_text = new_paragraphs[0].strip() if new_paragraphs else ""
        first_body = -1
        for idx, p in enumerate(original_paras):
            if p.text.strip() and _text_similarity(p.text.strip(), title_text) > 0.5:
                first_body = idx
                break
        for p in original_paras[:first_body]:
            _set_para_text(p, "")
        if first_body > 0:
            original_paras = original_paras[first_body:]

        logger.info(
            "export_text_to_docx_preserve_format: original_file=%s, "
            "new_text_len=%d, sep=%r, "
            "new_paragraphs=%d, original_paras=%d, doc_tables=%d",
            original_file_path,
            len(new_text),
            sep,
            len(new_paragraphs),
            len(original_paras),
            len(doc.tables),
        )

        # ---- 第一步：从 new_text 中提取表格块，替换为占位符 ----
        table_cells_list: list[list[list[str]]] = []  # 每个元素是一张表的 cells
        clean_new_paras: list[str | None] = []  # None 表示表格占位
        for para in new_paragraphs:
            # 检测表格标记：支持三种格式
            # 1. [TABLE_START]【表格】\n...\n[TABLE_END]（后端标准格式）
            # 2. 【表格】\n...（前端 syncTableEdit 格式）
            # 3. 【表格】\n... 开头且包含 |（直接编辑格式）
            is_table = TABLE_START_MARKER in para or (
                para.strip().startswith(TABLE_TITLE_MARKER)
                and ("|" in para or TABLE_ROW_SEP in para)
            )
            if is_table:
                cells = _parse_table_marker(para)
                if cells:
                    table_cells_list.append(cells)
                    clean_new_paras.append(None)  # 占位，不参与相似度匹配
                else:
                    clean_new_paras.append(para)
            else:
                clean_new_paras.append(para)

        logger.info(
            "  table detection: detected %d table blocks in new_text, "
            "clean_new_paras has %d entries (%d tables, %d text)",
            len(table_cells_list),
            len(clean_new_paras),
            sum(1 for p in clean_new_paras if p is None),
            sum(1 for p in clean_new_paras if p is not None),
        )
        for ti, cells in enumerate(table_cells_list):
            logger.info(
                "  table[%d]: %d rows x %d cols",
                ti,
                len(cells),
                max(len(r) for r in cells) if cells else 0,
            )

        # ---- 第二步：计算原始 docx 中每个表格后的起始 oi 位置 ----
        # doc.paragraphs 只包含 w:p 元素，不包含 w:tbl。
        # 因此表格在匹配循环中是"不可见的"——新文本中的表格占位(None)
        # 消耗 ni 但不消耗 oi，导致表格后的内容被写入表格前的段落中。
        # 解决：扫描 body children，对每个 w:tbl 记录其前有多少个 w:p，
        #       匹配循环遇到表格时直接将 oi 跳到表格后的第一个段落。
        from docx.oxml.ns import qn as _qn

        _wp_count = 0
        _table_oi_after: list[int] = []  # table_idx → 表格后第一个段落的 oi
        for _child in doc.element.body:
            if _child.tag == _qn("w:tbl"):
                _table_oi_after.append(_wp_count)  # 表格前有 _wp_count 个段落
            elif _child.tag == _qn("w:p"):
                _wp_count += 1
        logger.info(
            "  body children scan: %d w:p total, %d tables, table_oi_after=%s",
            _wp_count,
            len(_table_oi_after),
            _table_oi_after,
        )

        # ---- 第三步：相似度匹配（跳过表格段落） ----
        MATCH_THRESHOLD = 0.35
        LOOKAHEAD = 3

        oi = 0  # 原始段落索引
        ni = 0  # 新文本段落索引
        extra: list[str] = []  # 无法定位的插入段落，追加到末尾

        while oi < len(original_paras) and ni < len(clean_new_paras):
            # -- 表格段落：写入对应表格，同时将 oi 跳至表格后的第一个段落 --
            if clean_new_paras[ni] is None:
                if table_cells_list:
                    table_idx = sum(1 for p in clean_new_paras[:ni] if p is None)
                    if table_idx < len(doc.tables):
                        logger.info(
                            "  writing table[%d] to doc.tables[%d] (%d rows x %d cols)",
                            table_idx,
                            table_idx,
                            len(table_cells_list[table_idx]),
                            max(len(r) for r in table_cells_list[table_idx])
                            if table_cells_list[table_idx]
                            else 0,
                        )
                        _write_table_content(
                            doc.tables[table_idx], table_cells_list[table_idx]
                        )
                    else:
                        logger.warning(
                            "  table_idx %d out of range (doc has %d tables), skipping",
                            table_idx,
                            len(doc.tables),
                        )
                    # 关键修复：将 oi 跳过表格在 body 中占据的段落偏移
                    if table_idx < len(_table_oi_after):
                        _target_oi = _table_oi_after[table_idx]
                        if oi < _target_oi:
                            logger.info(
                                "  advancing oi %d -> %d for table[%d]",
                                oi,
                                _target_oi,
                                table_idx,
                            )
                            oi = _target_oi
                ni += 1
                continue

            sim = _text_similarity(original_paras[oi].text, clean_new_paras[ni])

            if sim >= MATCH_THRESHOLD:
                # -- 直接匹配：替换文本，保留格式 --
                logger.debug(
                    "  MATCH oi=%d ni=%d sim=%.3f: orig=%.50s -> new=%.50s",
                    oi,
                    ni,
                    sim,
                    original_paras[oi].text,
                    clean_new_paras[ni],
                )
                _set_para_text(original_paras[oi], clean_new_paras[ni])
                oi += 1
                ni += 1
                continue

            # -- 探查：当前新段落是否匹配后续原始段落？--
            # 命中说明中间的原始段落已被用户删除
            orig_skip = None
            for off in range(1, LOOKAHEAD + 1):
                if oi + off < len(original_paras):
                    s = _text_similarity(
                        original_paras[oi + off].text, clean_new_paras[ni]
                    )
                    if s >= MATCH_THRESHOLD:
                        orig_skip = off
                        break

            if orig_skip is not None:
                logger.debug(
                    "  ORIG_SKIP oi=%d ni=%d skip=%d: matched new=%.50s at oi+%d",
                    oi,
                    ni,
                    orig_skip,
                    clean_new_paras[ni],
                    orig_skip,
                )
                for _ in range(orig_skip):
                    _set_para_text(original_paras[oi], "")
                    oi += 1
                continue  # 不消耗 ni，重新用同一新段落匹配

            # -- 探查：当前原始段落是否匹配后续新段落？--
            # 命中说明中间的新段落是用户插入的
            new_skip = None
            for off in range(1, LOOKAHEAD + 1):
                if ni + off < len(clean_new_paras):
                    s = _text_similarity(
                        original_paras[oi].text, clean_new_paras[ni + off]
                    )
                    if s >= MATCH_THRESHOLD:
                        new_skip = off
                        break

            if new_skip is not None:
                logger.debug(
                    "  NEW_SKIP oi=%d ni=%d skip=%d: unmatched new=%.50s added to extra",
                    oi,
                    ni,
                    new_skip,
                    clean_new_paras[ni],
                )
                for _ in range(new_skip):
                    extra.append(clean_new_paras[ni])
                    ni += 1
                continue  # 不消耗 oi，重新用同一原始段落匹配

            # -- 都探查不到 → 当作内容修改处理 --
            _set_para_text(original_paras[oi], clean_new_paras[ni])
            oi += 1
            ni += 1

        # 清空剩余未匹配的原始段落（新文本较短）
        while oi < len(original_paras):
            _set_para_text(original_paras[oi], "")
            oi += 1

        # 追加剩余新段落（原文档较短）和探查到的插入段落
        while ni < len(clean_new_paras):
            if clean_new_paras[ni] is not None:
                extra.append(clean_new_paras[ni])
            ni += 1

        for text in extra:
            if text.strip():
                doc.add_paragraph(text)

        # 新增的表格（无对应模板表格）渲染到末尾
        for headers, rows in extra_tables:
            tbl = doc.add_table(rows=1 + len(rows), cols=len(headers))
            tbl.style = "Table Grid"
            for ci, header in enumerate(headers):
                tbl.rows[0].cells[ci].text = header
                for p in tbl.rows[0].cells[ci].paragraphs:
                    for run in p.runs:
                        run.bold = True
            for ri, row_data in enumerate(rows):
                for ci, cell_text in enumerate(row_data):
                    tbl.rows[ri + 1].cells[ci].text = cell_text
            doc.add_paragraph()

        buffer = BytesIO()
        doc.save(buffer)
        buffer.seek(0)

        logger.info(
            "  export done: %d extra paragraphs appended, "
            "oi=%d/%d final, ni=%d/%d final",
            len(extra),
            oi,
            len(original_paras),
            ni,
            len(clean_new_paras),
        )
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
