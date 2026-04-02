"""规则文本预处理模块

对读取的规则文本进行分段、清洗、标准化，处理条款编号格式不统一问题
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RuleSourceType(Enum):
    """规则来源类型"""
    NATIONAL_STANDARD = "等级评审标准"  # 卫健委/等级评审标准
    HOSPITAL_INTERNAL = "院内规范"       # 院内质控规范
    INSURANCE = "医保规则"               # 医保规则
    UNKNOWN = "未知来源"


class TextPreprocessor:
    """文本预处理器：分段落、分条款"""

    def __init__(self, text: str):
        self.text = text
        self._paragraphs: list[str] = []

    def normalize_whitespace(self) -> str:
        """规范化空白字符"""
        # 将多个空白字符替换为单个空格
        text = re.sub(r'[ \t]+', ' ', self.text)
        # 将换行符规范化
        text = re.sub(r'\r\n', '\n', text)
        return text

    def split_paragraphs(self) -> list[str]:
        """将文本分割为段落"""
        text = self.normalize_whitespace()
        # 按换行分割，过滤空段落
        paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
        self._paragraphs = paragraphs
        return paragraphs

    def split_clauses(self, text: str) -> list[str]:
        """将段落分割为条款

        支持的条款分隔模式：
        - 数字编号：1. 1.2 1.2.3 (1) [1]
        - 中文编号：第一章 第一条 一、
        - 混合：条款1 第1条 规定1
        """
        # 首先尝试按条款分隔符分割
        clause_patterns = [
            # 数字+点：1. 1.2 1.2.3
            r'(?<=\n)(?=\d+\.)',
            # 括号数字：(1) [1]
            r'(?<=\n)(?=\([0-9]+\))',
            r'(?<=\n)(?=\[[0-9]+\])',
            # 中文章条：第一章 第一条
            r'(?<=\n)(?=第[一二三四五六七八九十百千零\d]+[章节条节款项])',
            # 条款/规定/规则+数字
            r'(?<=\n)(?=条款?\d+|规定?\d+|规则?\d+)',
        ]

        parts = [text]
        for pattern in clause_patterns:
            new_parts = []
            for part in parts:
                split_result = re.split(pattern, part)
                new_parts.extend(split_result)
            if len(new_parts) > len(parts):
                parts = new_parts

        # 进一步按行分割未分割的条款
        final_clauses = []
        for part in parts:
            lines = part.split('\n')
            current_clause = []
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue
                # 检查是否是新条款的开始
                is_new_clause = bool(re.match(r'^[\d一二三四五六七八九十]+[、.。)]', stripped))
                if is_new_clause and current_clause:
                    final_clauses.append('\n'.join(current_clause))
                    current_clause = [stripped]
                else:
                    current_clause.append(stripped)
            if current_clause:
                final_clauses.append('\n'.join(current_clause))

        return [c.strip() for c in final_clauses if c.strip()]

    def process(self) -> list[str]:
        """完整处理流程：分段后分条款"""
        paragraphs = self.split_paragraphs()
        all_clauses = []
        for para in paragraphs:
            clauses = self.split_clauses(para)
            all_clauses.extend(clauses)
        return all_clauses


class ClauseExtractor:
    """条款提取器：提取条款编号、标题、内容"""

    # 条款编号正则模式
    CLAUSE_PATTERNS = [
        # 等级评审/国家标准格式：1.2.3, 1.2, 1
        (r'^(?P<num>\d+(?:\.\d+)*)\s*[.、]', 'numeric'),
        # 括号格式：(1) [1]
        (r'^\((?P<num>\d+)\)\s*', 'bracket'),
        (r'^\[(?P<num>\d+)\]\s*', 'bracket'),
        # 中文章条格式：第一章 第一条
        (r'^第(?P<num>[一二三四五六七八九十百千零\d]+)[章节条节款项]\s*', 'chinese'),
        # 条款/规定格式：条款1 规定2
        (r'^(?:条款?|规定?|规则?)(?P<num>\d+)\s*', 'keyword'),
    ]

    def extract_clause_number(self, text: str) -> Optional[str]:
        """提取条款编号"""
        text = text.strip()
        for pattern, ptype in self.CLAUSE_PATTERNS:
            match = re.match(pattern, text)
            if match:
                return match.group('num')
        return None

    def extract_clause_title(self, text: str, clause_num: Optional[str] = None) -> Optional[str]:
        """提取条款标题

        标题通常在编号之后，以冒号、顿号或直接跟正文分隔
        """
        text = text.strip()

        # 如果有条款编号，去除编号部分
        if clause_num:
            # 使用 clause_num 直接构建前缀模式来去除
            prefix_pattern = r'^' + re.escape(clause_num) + r'\s*[.、:\s]+'
            text = re.sub(prefix_pattern, '', text)

        text = text.strip()
        if not text:
            return None

        # 尝试提取标题模式：编号后面的第一个短句（到冒号、逗号或句号）
        # 模式1：标题：内容
        title_match = re.match(r'^([^：:,\n]{2,20})[：:，,]\s*(.*)$', text)
        if title_match:
            title = title_match.group(1).strip()
            # 标题长度限制在2-30字符
            if 2 <= len(title) <= 30:
                return title

        # 模式2：标题 内容（标题在句首，不超过20字符）
        simple_match = re.match(r'^([^，,。.\n]{2,20})(?:[，,]|\s+(?=[\u4e00-\u9fa5]))', text)
        if simple_match:
            return simple_match.group(1).strip()

        return None

    def extract_clause_content(self, text: str, clause_num: Optional[str] = None) -> str:
        """提取条款内容"""
        text = text.strip()

        # 去除编号
        if clause_num:
            # 使用 clause_num 直接构建前缀模式来去除
            prefix_pattern = r'^' + re.escape(clause_num) + r'\s*[.、:\s]+'
            text = re.sub(prefix_pattern, '', text)

        # 去除标题（如果标题和内容在一起）
        title_match = re.match(r'^([^：:,\n]{2,20})[：:，,]\s*(.*)$', text, re.DOTALL)
        if title_match:
            text = title_match.group(2).strip()

        return text

    def extract(self, clause_text: str) -> 'Clause':
        """提取条款的各个部分"""
        clause_num = self.extract_clause_number(clause_text)
        title = self.extract_clause_title(clause_text, clause_num)
        content = self.extract_clause_content(clause_text, clause_num)

        return Clause(
            clause_id=clause_num,
            title=title,
            content=content,
            raw_text=clause_text
        )


@dataclass
class Clause:
    """条款数据类"""
    clause_id: Optional[str] = None
    title: Optional[str] = None
    content: str = ""
    raw_text: str = ""
    source: RuleSourceType = RuleSourceType.UNKNOWN
    source_file: str = ""


class RuleMetadata:
    """规则元数据提取器"""

    # 来源关键词映射
    SOURCE_KEYWORDS = {
        RuleSourceType.NATIONAL_STANDARD: [
            '等级评审', '三级医院', '二级医院', '评审标准', '国家标准',
            '卫生部', '卫健委', '国家卫健委', '三甲', '三乙', '二甲',
            '评审指标', '医院评审', '医疗机构', '质量管理'
        ],
        RuleSourceType.HOSPITAL_INTERNAL: [
            '院内', '本院', '医院规定', '科室', '质控', '规范',
            '管理制度', '操作规程', '医务科', '护理部', '信息科',
            '医务处', '院感', '院内感染', '处方', '医嘱'
        ],
        RuleSourceType.INSURANCE: [
            '医保', '报销', 'DRG', 'DIP', '付费', '结算', '定点',
            '医疗服务', '药品目录', '诊疗项目', '医用耗材',
            '基金', '个人账户', '统筹', '扣除', '自费'
        ]
    }

    def detect_source(self, text: str, file_path: str = "") -> RuleSourceType:
        """检测规则来源类型

        Args:
            text: 规则文本内容
            file_path: 文件路径（用于辅助判断）

        Returns:
            RuleSourceType 枚举值
        """
        text_lower = text.lower()
        file_lower = file_path.lower()

        scores = {source: 0 for source in RuleSourceType}

        # 基于文本内容打分
        for source_type, keywords in self.SOURCE_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text:
                    scores[source_type] += 1
                if keyword in file_lower:
                    scores[source_type] += 2  # 文件路径权重更高

        # 基于文件路径关键词
        if 'standard' in file_lower or '评审' in file_lower:
            scores[RuleSourceType.NATIONAL_STANDARD] += 3
        if 'insurance' in file_lower or '医保' in file_lower:
            scores[RuleSourceType.INSURANCE] += 3
        if 'hospital' in file_lower or '院内' in file_lower:
            scores[RuleSourceType.HOSPITAL_INTERNAL] += 3

        # 最高分来源
        if scores:
            max_source = max(scores, key=scores.get)
            if scores[max_source] > 0:
                return max_source

        return RuleSourceType.UNKNOWN

    def extract_metadata(self, clause: Clause, file_path: str = "") -> Clause:
        """为条款添加元数据"""
        # 检测来源
        source = self.detect_source(clause.raw_text, file_path)
        clause.source = source
        clause.source_file = file_path
        return clause


def preprocess_document(text: str, file_path: str = "") -> list[Clause]:
    """文档预处理统一入口

    Args:
        text: 文档文本内容
        file_path: 文件路径（用于来源判断）

    Returns:
        Clause 列表
    """
    # 分段分条款
    preprocessor = TextPreprocessor(text)
    clause_texts = preprocessor.process()

    # 提取条款
    extractor = ClauseExtractor()
    metadata_extractor = RuleMetadata()

    clauses = []
    for clause_text in clause_texts:
        clause = extractor.extract(clause_text)
        clause = metadata_extractor.extract_metadata(clause, file_path)
        clauses.append(clause)

    return clauses


def preprocess_documents(documents: list) -> dict[str, list[Clause]]:
    """批量预处理文档

    Args:
        documents: Document 对象列表（需包含 content, source 属性）

    Returns:
        dict[str, list[Clause]]: 以文件路径为键的条款列表
    """
    result = {}
    for doc in documents:
        clauses = preprocess_document(doc.content, doc.source)
        result[doc.source] = clauses
    return result


if __name__ == "__main__":
    # 简单测试
    sample_text = """
    等级评审标准
    第一章 医院资质
    1. 医院必须具有有效的医疗机构执业许可证。
    1.1 许可证应在有效期内。
    1.2 许可证副本应悬挂在显眼位置。

    第二章 医疗质量
    2. 医院应建立医疗质量管理制度。
    2.1 科室应定期开展质量自查。
    2.2 医务处应进行季度抽查。

    医保规则
    第三条 费用结算
    (1) 医保患者住院费用应在出院后7日内完成结算。
    (2) 结算时应提供完整的病历资料。

    院内规范
    第一条 处方管理
    条款1 处方权限：执业医师方可开具处方。
    条款2 处方格式：应使用统一处方笺。
    """

    print("=== 测试文本预处理 ===\n")
    clauses = preprocess_document(sample_text, "test_standards.txt")

    for i, clause in enumerate(clauses, 1):
        print(f"条款 {i}:")
        print(f"  编号: {clause.clause_id}")
        print(f"  标题: {clause.title}")
        print(f"  内容: {clause.content[:50]}..." if len(clause.content) > 50 else f"  内容: {clause.content}")
        print(f"  来源: {clause.source.value}")
        print()