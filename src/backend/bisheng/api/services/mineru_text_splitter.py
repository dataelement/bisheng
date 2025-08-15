import json
import re
from typing import List, Dict, Tuple
from langchain.schema.document import Document
from loguru import logger


class MinerUTextSplitter:
    """专门为MinerU解析结果设计的文本切分器"""
    
    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        separator_patterns: List[str] = None,
        preserve_headers: bool = True,
        preserve_tables: bool = True,
        preserve_formulas: bool = True,
        min_chunk_size: int = 100,
        max_chunk_size: int = 2000
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separator_patterns = separator_patterns or [
            "\n\n",      # 段落分隔
            "\n",        # 行分隔
            "。",        # 中文句号
            "！",        # 中文感叹号
            "？",        # 中文问号
            ". ",        # 英文句号
            "! ",        # 英文感叹号
            "? ",        # 英文问号
            "；",        # 中文分号
            "; ",        # 英文分号
        ]
        self.preserve_headers = preserve_headers
        self.preserve_tables = preserve_tables
        self.preserve_formulas = preserve_formulas
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size
    
    def split_mineru_documents(
        self, 
        documents: List[Document],
        knowledge_id: int = None
    ) -> Tuple[List[Document], List[Dict]]:
        """
        专门处理MinerU返回的Document对象
        
        Args:
            documents: MinerU返回的Document列表
            knowledge_id: 知识库ID
            
        Returns:
            Tuple[List[Document], List[Dict]]: 切分后的文档和元数据
        """
        split_documents = []
        metadatas = []
        
        logger.info(f"Starting MinerU text splitting for {len(documents)} documents")
        
        for doc_index, doc in enumerate(documents):
            logger.info(f"Processing document {doc_index + 1}/{len(documents)}")
            
            # 分析文档结构
            doc_structure = self._analyze_document_structure(doc.page_content)
            
            # 智能切分
            chunks = self._smart_split_text(doc.page_content, doc_structure)
            
            logger.info(f"Document {doc_index + 1} split into {len(chunks)} chunks")
            
            # 为每个chunk创建Document对象
            for chunk_index, chunk in enumerate(chunks):
                chunk_doc = Document(
                    page_content=chunk,
                    metadata={
                        "source": doc.metadata.get("source", ""),
                        "page": doc.metadata.get("page", 1),
                        "chunk_index": chunk_index,
                        "total_chunks": len(chunks),
                        "doc_index": doc_index,
                        "knowledge_id": knowledge_id,
                        "parse_type": "mineru",
                        "chunk_bboxes": doc.metadata.get("chunk_bboxes", []),
                        "bbox": json.dumps({"chunk_bboxes": doc.metadata.get("chunk_bboxes", "")}),
                        "title": doc.metadata.get("title", ""),
                        "extra": "",
                    }
                )
                split_documents.append(chunk_doc)
                
                # 创建对应的metadata
                metadata = {
                    "bbox": json.dumps({"chunk_bboxes": doc.metadata.get("chunk_bboxes", "")}),
                    "page": doc.metadata.get("page", 1),
                    "source": doc.metadata.get("source", ""),
                    "title": doc.metadata.get("title", ""),
                    "chunk_index": chunk_index,
                    "extra": "",
                }
                metadatas.append(metadata)
        
        logger.info(f"MinerU text splitting completed. Total chunks: {len(split_documents)}")
        return split_documents, metadatas
    
    def _analyze_document_structure(self, text: str) -> Dict:
        """分析文档结构，识别标题层级关系、表格、公式和内容段落"""
        structure = {
            "headers": [],
            "header_hierarchy": {},  # 标题层级关系
            "content_sections": [],  # 内容段落
            "tables": [],
            "formulas": [],
            "code_blocks": []  # 代码块
        }
        
        lines = text.split('\n')
        current_header = None
        current_content = []
        in_table = False
        in_formula = False
        in_code_block = False
        current_table = []
        current_formula = []
        current_code_block = []
        
        for line_num, line in enumerate(lines):
            original_line = line
            line = line.strip()
            
            # 检查是否进入或退出代码块
            if line.startswith('```'):
                if in_code_block:
                    # 退出代码块
                    current_code_block.append(original_line)
                    structure["code_blocks"].append({
                        "content": "\n".join(current_code_block),
                        "start_line": current_code_block[0].split('\n')[0] if current_code_block else line_num,
                        "end_line": line_num
                    })
                    current_code_block = []
                    in_code_block = False
                else:
                    # 进入代码块
                    in_code_block = True
                    current_code_block = [original_line]
                continue
            
            # 如果在代码块中，直接添加
            if in_code_block:
                current_code_block.append(original_line)
                continue
            
            # 检查是否进入或退出公式
            if line.startswith('$$') or line.startswith('$'):
                if in_formula:
                    # 退出公式
                    current_formula.append(original_line)
                    structure["formulas"].append({
                        "content": "\n".join(current_formula),
                        "start_line": current_formula[0].split('\n')[0] if current_formula else line_num,
                        "end_line": line_num,
                        "type": "block" if line.startswith('$$') else "inline"
                    })
                    current_formula = []
                    in_formula = False
                else:
                    # 进入公式
                    in_formula = True
                    current_formula = [original_line]
                continue
            
            # 如果在公式中，直接添加
            if in_formula:
                current_formula.append(original_line)
                continue
            
            # 检查表格
            if self._is_table_line(line):
                if not in_table:
                    # 开始新表格
                    in_table = True
                    current_table = [original_line]
                else:
                    # 继续当前表格
                    current_table.append(original_line)
                continue
            elif in_table:
                # 退出表格
                if current_table:
                    structure["tables"].append({
                        "content": "\n".join(current_table),
                        "start_line": current_table[0].split('\n')[0] if current_table else line_num - len(current_table),
                        "end_line": line_num - 1,
                        "rows": len(current_table)
                    })
                    current_table = []
                in_table = False
            
            # 检查标题
            if line.startswith('#'):
                # 保存之前的内容段落
                if current_header and current_content:
                    structure["content_sections"].append({
                        "header": current_header,
                        "content": "\n".join(current_content),
                        "start_line": current_header["line"],
                        "end_line": line_num - 1
                    })
                
                # 识别新标题
                header_level = len(line) - len(line.lstrip('#'))
                header_text = line.lstrip('# ').strip()
                
                current_header = {
                    "level": header_level,
                    "text": header_text,
                    "line": line_num,
                    "full_line": original_line
                }
                
                structure["headers"].append(current_header)
                current_content = []
            else:
                # 非标题行，添加到当前内容
                if current_header:
                    current_content.append(original_line)
                else:
                    # 文档开头没有标题的内容
                    current_content.append(original_line)
        
        # 保存最后一个内容段落
        if current_header and current_content:
            structure["content_sections"].append({
                "header": current_header,
                "content": "\n".join(current_content),
                "start_line": current_header["line"],
                "end_line": len(lines) - 1
            })
        elif current_content and not current_header:
            # 处理没有标题的内容
            structure["content_sections"].append({
                "header": None,
                "content": "\n".join(current_content),
                "start_line": 0,
                "end_line": len(lines) - 1
            })
        
        # 处理未闭合的表格、公式、代码块
        if in_table and current_table:
            structure["tables"].append({
                "content": "\n".join(current_table),
                "start_line": current_table[0].split('\n')[0] if current_table else len(lines) - len(current_table),
                "end_line": len(lines) - 1,
                "rows": len(current_table)
            })
        
        if in_formula and current_formula:
            structure["formulas"].append({
                "content": "\n".join(current_formula),
                "start_line": current_formula[0].split('\n')[0] if current_formula else len(lines) - len(current_formula),
                "end_line": len(lines) - 1,
                "type": "unclosed"
            })
        
        if in_code_block and current_code_block:
            structure["code_blocks"].append({
                "content": "\n".join(current_code_block),
                "start_line": current_code_block[0].split('\n')[0] if current_code_block else len(lines) - len(current_code_block),
                "end_line": len(lines) - 1
            })
        
        logger.info(f"Document structure analysis completed: {len(structure['headers'])} headers, {len(structure['tables'])} tables, {len(structure['formulas'])} formulas, {len(structure['code_blocks'])} code blocks")
        return structure
    
    def _is_table_line(self, line: str) -> bool:
        """判断是否为表格行"""
        # 检查是否包含表格分隔符
        if '|' in line:
            # 计算分隔符数量，至少需要2个分隔符才能形成表格
            pipe_count = line.count('|')
            if pipe_count >= 2:
                return True
        
        # 检查是否包含表格对齐标记（如 :---, ---: 等）
        if re.match(r'^[\s]*:?[-]+:?[\s]*$', line):
            return True
        
        return False
    
    def _smart_split_text(self, text: str, structure: Dict) -> List[str]:
        """智能切分文本，保持标题、表格、公式和内容的完整性"""
        chunks = []
        
        # 基于内容段落进行智能切分
        content_sections = structure.get("content_sections", [])
        tables = structure.get("tables", [])
        formulas = structure.get("formulas", [])
        code_blocks = structure.get("code_blocks", [])
        
        logger.info(f"Found {len(content_sections)} content sections, {len(tables)} tables, {len(formulas)} formulas, {len(code_blocks)} code blocks")
        
        # 处理内容段落
        for i, section in enumerate(content_sections):
            header = section.get("header")
            content = section.get("content", "")
            
            if header:
                # 有标题的段落：标题 + 内容
                section_text = header["full_line"] + "\n" + content if content else header["full_line"]
                logger.info(f"Section {i+1}: Header '{header['text']}' (level {header['level']}) with {len(content)} chars content")
            else:
                # 没有标题的段落：只有内容
                section_text = content
                logger.info(f"Section {i+1}: No header, content length: {len(content)} chars")
            
            if not section_text.strip():
                continue
            
            # 如果单个段落超过限制，需要进一步切分
            if len(section_text) > self.chunk_size:
                logger.info(f"Section {i+1} exceeds chunk size ({len(section_text)} > {self.chunk_size}), splitting...")
                if header:
                    # 有标题的段落，在保持标题完整性的前提下切分
                    sub_chunks = self._split_chunk_with_header_preservation(section_text, header)
                    logger.info(f"Header-preserved splitting resulted in {len(sub_chunks)} sub-chunks")
                    chunks.extend(sub_chunks)
                else:
                    # 没有标题的段落，按句子切分
                    sub_chunks = self._split_long_paragraph(section_text)
                    logger.info(f"Paragraph splitting resulted in {len(sub_chunks)} sub-chunks")
                    chunks.extend(sub_chunks)
            else:
                # 段落大小合适，直接添加
                chunks.append(section_text.strip())
                logger.info(f"Section {i+1} fits in single chunk ({len(section_text)} chars)")
        
        # 处理表格 - 表格应该保持完整，不被分割
        for i, table in enumerate(tables):
            table_content = table["content"]
            if len(table_content) > self.chunk_size:
                logger.warning(f"Table {i+1} is very large ({len(table_content)} chars), attempting to split while preserving structure")
                # 尝试切分表格，保持结构完整性
                table_chunks = self._split_large_table(table_content)
                chunks.extend(table_chunks)
                logger.info(f"Table {i+1} split into {len(table_chunks)} chunks while preserving structure")
            else:
                # 表格作为一个独立的chunk添加
                chunks.append(table_content)
                logger.info(f"Added table {i+1} as complete chunk ({len(table_content)} chars)")
        
        # 处理公式 - 公式应该保持完整
        for i, formula in enumerate(formulas):
            formula_content = formula["content"]
            formula_type = formula.get("type", "unknown")
            
            if len(formula_content) > self.chunk_size:
                logger.warning(f"Formula {i+1} ({formula_type}) is very large ({len(formula_content)} chars), but will be kept intact")
            
            # 公式作为一个独立的chunk添加
            chunks.append(formula_content)
            logger.info(f"Added formula {i+1} ({formula_type}) as complete chunk ({len(formula_content)} chars)")
        
        # 处理代码块 - 代码块应该保持完整
        for i, code_block in enumerate(code_blocks):
            code_content = code_block["content"]
            
            if len(code_content) > self.chunk_size:
                logger.warning(f"Code block {i+1} is very large ({len(code_content)} chars), but will be kept intact")
            
            # 代码块作为一个独立的chunk添加
            chunks.append(code_content)
            logger.info(f"Added code block {i+1} as complete chunk ({len(code_content)} chars)")
        
        # 如果chunks为空，回退到原来的切分方法
        if not chunks:
            logger.warning("No chunks generated from smart splitting, falling back to original method")
            chunks = self._fallback_split_text(text)
        
        # 确保chunk大小在合理范围内
        chunks = self._adjust_chunk_sizes(chunks)
        
        logger.info(f"Smart text splitting completed. Generated {len(chunks)} chunks")
        return chunks
    
    def _split_large_table(self, table_content: str, max_chunk_size: int = None) -> List[str]:
        """切分过大的表格，保持表格结构完整性"""
        if max_chunk_size is None:
            max_chunk_size = self.chunk_size
        
        if len(table_content) <= max_chunk_size:
            return [table_content]
        
        lines = table_content.split('\n')
        chunks = []
        current_chunk = []
        current_size = 0
        
        for line in lines:
            line_size = len(line) + 1  # +1 for newline
            
            # 如果当前行是表格分隔符（如 | --- | --- |），应该与前面的内容保持在一起
            if re.match(r'^[\s]*:?[-]+:?[\s]*$', line):
                # 分隔符行，强制添加到当前chunk
                current_chunk.append(line)
                current_size += line_size
            elif current_size + line_size <= max_chunk_size:
                # 可以添加到当前chunk
                current_chunk.append(line)
                current_size += line_size
            else:
                # 当前chunk已满，保存并开始新的
                if current_chunk:
                    chunks.append('\n'.join(current_chunk))
                
                # 开始新的chunk
                current_chunk = [line]
                current_size = line_size
        
        # 添加最后一个chunk
        if current_chunk:
            chunks.append('\n'.join(current_chunk))
        
        return chunks
    
    def _split_long_paragraph(self, paragraph: str) -> List[str]:
        """切分过长的段落"""
        chunks = []
        current_chunk = ""
        
        # 按句子切分
        sentences = re.split(r'([。！？.!?])', paragraph)
        
        for i in range(0, len(sentences), 2):
            sentence = sentences[i]
            if i + 1 < len(sentences):
                sentence += sentences[i + 1]  # 加上标点符号
            
            if len(current_chunk) + len(sentence) <= self.chunk_size:
                current_chunk += sentence
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = sentence
        
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        return chunks
    
    def _adjust_chunk_sizes(self, chunks: List[str]) -> List[str]:
        """调整chunk大小，确保在合理范围内"""
        adjusted_chunks = []
        
        for chunk in chunks:
            if len(chunk) < self.min_chunk_size:
                # 如果chunk太小，尝试合并
                if adjusted_chunks and len(adjusted_chunks[-1]) + len(chunk) <= self.max_chunk_size:
                    adjusted_chunks[-1] += "\n\n" + chunk
                else:
                    adjusted_chunks.append(chunk)
            elif len(chunk) > self.max_chunk_size:
                # 如果chunk太大，进一步切分
                sub_chunks = self._split_long_paragraph(chunk)
                adjusted_chunks.extend(sub_chunks)
            else:
                adjusted_chunks.append(chunk)
        
        return adjusted_chunks
    
    def _split_chunk_with_header_preservation(self, chunk: str, header: dict) -> List[str]:
        """在保持标题完整性的前提下切分chunk"""
        if not header:
            # 如果没有标题，按段落切分
            return self._split_long_paragraph(chunk)
        
        chunks = []
        lines = chunk.split('\n')
        
        # 找到标题行
        header_index = -1
        for i, line in enumerate(lines):
            if line.strip() == header["full_line"].strip():
                header_index = i
                break
        
        if header_index == -1:
            return [chunk]
        
        # 从标题开始，按段落切分
        current_chunk = header["full_line"]
        current_size = len(header["full_line"])
        
        for i in range(header_index + 1, len(lines)):
            line = lines[i]
            line_size = len(line) + 1  # +1 for newline
            
            if current_size + line_size <= self.chunk_size:
                current_chunk += "\n" + line
                current_size += line_size
            else:
                # 当前chunk已满，保存并开始新的
                if current_chunk:
                    chunks.append(current_chunk.strip())
                
                # 如果下一行也是标题，从标题开始新chunk
                if line.startswith('#'):
                    current_chunk = line
                    current_size = len(line)
                else:
                    # 否则从内容开始，但保持上下文
                    current_chunk = header["full_line"] + "\n" + line
                    current_size = len(header["full_line"]) + 1 + len(line)
        
        # 添加最后一个chunk
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        return chunks
    
    def _fallback_split_text(self, text: str) -> List[str]:
        """回退到原来的切分方法"""
        chunks = []
        current_chunk = ""
        
        # 按段落切分
        paragraphs = text.split('\n\n')
        
        for paragraph in paragraphs:
            if not paragraph.strip():
                continue
                
            # 如果当前chunk加上新段落不超过限制，则添加
            if len(current_chunk) + len(paragraph) <= self.chunk_size:
                if current_chunk:
                    current_chunk += "\n\n" + paragraph
                else:
                    current_chunk = paragraph
            else:
                # 当前chunk已满，保存并开始新的chunk
                if current_chunk:
                    chunks.append(current_chunk.strip())
                
                # 如果单个段落就超过限制，需要进一步切分
                if len(paragraph) > self.chunk_size:
                    sub_chunks = self._split_long_paragraph(paragraph)
                    chunks.extend(sub_chunks)
                    current_chunk = ""
                else:
                    current_chunk = paragraph
        
        # 添加最后一个chunk
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        return chunks
