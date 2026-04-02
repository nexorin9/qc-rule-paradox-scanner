"""规则三元组提取模块

使用 LLM 将条款文本提取为结构化三元组：对象 + 条件 + 动作
支持 OpenAI 和 Anthropic 兼容 API
以及基于关键词的本地规则引擎（无 LLM 时降级方案）

性能优化版本：
- 支持并发批量提取
- 支持 LLM 批量调用（多条规则合并一次 API 请求）
"""

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Optional

import openai
from openai import OpenAI

from .text_preprocessor import Clause, RuleSourceType


class ExtractionError(Exception):
    """三元组提取失败异常"""
    pass


class LLMProvider(Enum):
    """LLM 提供商"""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


@dataclass
class RuleTriple:
    """规则三元组

    表示规则的核心逻辑结构：
    - subject: 主体（谁）
    - condition: 条件（在什么情况下）
    - action: 动作（做什么/禁止做什么）
    - source: 来源文件
    - clause_id: 条款编号
    - rule_type: 规则类型（要求/禁止/建议）
    """
    subject: str
    condition: str
    action: str
    source: str
    clause_id: Optional[str] = None
    rule_type: str = "要求"  # 要求、禁止、建议
    confidence: float = 1.0  # 置信度 0-1

    def to_dict(self) -> dict:
        return asdict(self)

    def __str__(self) -> str:
        return f"[{self.rule_type}] {self.subject} + {self.condition} -> {self.action}"


# ============ 基于关键词的本地三元组提取器（LLM 降级方案）============

# 主体关键词
SUBJECT_KEYWORDS = {
    "医院": {"医院", "本院", "该院", "医疗机构"},
    "科室": {"科室", "各科室", "临床科室", "医技科室", "职能科室"},
    "执业医师": {"执业医师", "医师", "医生", "大夫", "医士"},
    "护士": {"护士", "护理人员", "护师", "护理"},
    "药师": {"药师", "药剂人员", "药学人员"},
    "患者": {"患者", "病人", "病员"},
    "医务人员": {"医务人员", "医护人员", "医疗人员", "工作人员"},
    "医保患者": {"医保患者", "参保患者", "医保病人"},
}

# 条件关键词
CONDITION_KEYWORDS = {
    "住院": {"住院", "住院患者", "住院期间"},
    "门诊": {"门诊", "门诊患者"},
    "急诊": {"急诊", "急诊患者"},
    "手术": {"手术", "术前", "术中", "术后", "外科手术"},
    "处方": {"处方", "开具处方", "处方时"},
    "医嘱": {"医嘱", "下达医嘱", "医嘱执行"},
    "医保": {"医保", "医疗保险", "参保"},
    "费用": {"费用", "结算", "报销", "收费"},
}

# 动作关键词
ACTION_KEYWORDS = {
    "要求": {"应当", "必须", "需要", "要求", "应", "该当"},
    "禁止": {"禁止", "不得", "严禁", "不许", "不准", "不能", "不可"},
    "建议": {"建议", "推荐", "鼓励", "提倡", "可以考虑"},
}

# 规则类型判断
RULE_TYPE_PATTERNS = [
    (r"禁止|不得|严禁|不许|不准|不能|不可", "禁止"),
    (r"应当|必须|需要|要求|应|该当", "要求"),
    (r"建议|推荐|鼓励|提倡|可以考虑", "建议"),
]


class KeywordBasedTripleExtractor:
    """基于关键词的本地三元组提取器

    当 LLM 不可用时，使用关键词匹配规则提取三元组
    适用于结构较清晰的规则文档
    """

    def __init__(self):
        """初始化提取器"""
        pass

    def extract_single(self, clause: Clause) -> list[RuleTriple]:
        """提取单一条款的三元组

        Args:
            clause: Clause 对象

        Returns:
            RuleTriple 列表
        """
        triples = []
        text = clause.content or clause.raw_text

        # 提取主体
        subject = self._extract_subject(text)

        # 提取条件
        condition = self._extract_condition(text)

        # 提取动作和规则类型
        action, rule_type = self._extract_action_and_type(text)

        if action:  # 至少要有动作
            triple = RuleTriple(
                subject=subject,
                condition=condition,
                action=action,
                source=clause.source_file or clause.source.value if clause.source else "未知",
                clause_id=clause.clause_id,
                rule_type=rule_type,
                confidence=0.6,  # 关键词提取置信度较低
            )
            triples.append(triple)

        return triples

    def _extract_subject(self, text: str) -> str:
        """从文本中提取主体"""
        # 检查是否包含医保相关
        if any(kw in text for kw in CONDITION_KEYWORDS["医保"]):
            if "患者" in text or "病人" in text:
                return "医保患者"

        # 检查各种主体关键词
        for subject, keywords in SUBJECT_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                return subject

        # 默认主体推断
        if "医院" in text:
            return "医院"
        elif "科室" in text or "部门" in text:
            return "科室"

        return "未知主体"

    def _extract_condition(self, text: str) -> str:
        """从文本中提取条件"""
        for condition, keywords in CONDITION_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                return condition
        return "无"

    def _extract_action_and_type(self, text: str) -> tuple[str, str]:
        """从文本中提取动作和规则类型"""
        # 首先判断规则类型
        rule_type = "要求"  # 默认
        action_start = 0

        for pattern, rtype in RULE_TYPE_PATTERNS:
            match = re.search(pattern, text)
            if match:
                rule_type = rtype
                action_start = match.end()
                break

        # 提取动作内容（规则类型后面的部分）
        action_text = text[action_start:].strip()

        # 清理动作文本
        action_text = re.sub(r"^[，,、\s]+", "", action_text)  # 去除开头的标点
        action_text = re.sub(r"[。.，,、\s]+$", "", action_text)  # 去除结尾的标点

        # 截取适当长度
        if len(action_text) > 100:
            action_text = action_text[:100] + "..."

        return action_text, rule_type

    def extract_batch(self, clauses: list[Clause]) -> list[RuleTriple]:
        """批量提取多条款的三元组（串行）

        Args:
            clauses: Clause 对象列表

        Returns:
            RuleTriple 列表
        """
        all_triples = []

        for clause in clauses:
            try:
                triples = self.extract_single(clause)
                all_triples.extend(triples)
            except Exception:
                continue

        return all_triples

    def extract_batch_concurrent(
        self,
        clauses: list[Clause],
        max_workers: int = 4,
        progress_callback: Optional[callable] = None,
    ) -> list[RuleTriple]:
        """并发批量提取多条款的三元组

        Args:
            clauses: Clause 对象列表
            max_workers: 最大并发数
            progress_callback: 进度回调函数，签名为 callback(completed: int, total: int)

        Returns:
            RuleTriple 列表
        """
        all_triples = []
        total = len(clauses)
        completed = 0

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_clause = {
                executor.submit(self.extract_single, clause): clause
                for clause in clauses
            }

            for future in as_completed(future_to_clause):
                completed += 1
                if progress_callback:
                    progress_callback(completed, total)

                clause = future_to_clause[future]
                try:
                    triples = future.result()
                    all_triples.extend(triples)
                except Exception:
                    continue

        return all_triples


# 系统提示词 - 指导 LLM 提取三元组
SYSTEM_PROMPT = """你是一个医院规则分析助手，负责从医疗规则文本中提取结构化的三元组信息。

## 任务
将每条规则条款提取为以下格式的三元组：
- subject（主体）：规则约束的对象，如"执业医师"、"医院"、"科室"、"医保患者"
- condition（条件）：规则生效的条件或范围，如"在开具处方时"、"住院患者"、"手术前"
- action（动作）：规则要求的动作或行为，如"需要"、"禁止"、"应当"，包括具体操作内容
- rule_type（类型）：规则的性质，"要求"、"禁止"、"建议"之一

## 规则类型定义
- 要求：必须执行的正向义务（应当、需要、必须）
- 禁止：必须避免的负向约束（禁止、不得、严禁）
- 建议：推荐但不强制的行为（建议、推荐、鼓励）

## 输出格式
每条规则输出为一行 JSON：
{"subject": "主体", "condition": "条件", "action": "动作", "rule_type": "类型"}

## 注意事项
1. 保持原文语义，不要过度推断
2. 条件为空时用"无"表示
3. 动作要具体，包含关键动词
4. 一条条款可能包含多个三元组（用换行分隔的多个 JSON）
5. 只输出 JSON，不做其他解释
6. 确保 JSON 格式合法

## 示例

输入：1. 医院应定期开展医疗质量自查。
输出：{"subject": "医院", "condition": "无", "action": "定期开展医疗质量自查", "rule_type": "要求"}

输入：2. 禁止执业医师开具空白处方。
输出：{"subject": "执业医师", "condition": "无", "action": "开具空白处方", "rule_type": "禁止"}

输入：3. 医保患者住院费用应在出院后7日内完成结算。
输出：{"subject": "医保患者", "condition": "住院", "action": "在出院后7日内完成费用结算", "rule_type": "要求"}

输入：4. 建议科室每周召开医疗质量分析会。
输出：{"subject": "科室", "condition": "无", "action": "每周召开医疗质量分析会", "rule_type": "建议"}
"""


class LLMTripleExtractor:
    """基于 LLM 的三元组提取器"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "gpt-4o-mini",
        provider: LLMProvider = LLMProvider.OPENAI,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ):
        """初始化提取器

        Args:
            api_key: API 密钥，默认从环境变量 OPENAI_API_KEY 读取
            base_url: API 基础 URL（用于兼容 OpenAI 兼容接口）
            model: 模型名称
            provider: LLM 提供商
            max_tokens: 最大输出 token 数
            temperature: 温度参数
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        self.model = model
        self.provider = provider
        self.max_tokens = max_tokens
        self.temperature = temperature

        if not self.api_key:
            raise ExtractionError(
                "未设置 API 密钥，请通过参数或环境变量 OPENAI_API_KEY 设置"
            )

        # 初始化客户端
        if self.base_url:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        else:
            self.client = OpenAI(api_key=self.api_key)

    def extract_single(self, clause: Clause) -> list[RuleTriple]:
        """提取单一条款的三元组

        Args:
            clause: Clause 对象

        Returns:
            RuleTriple 列表
        """
        user_prompt = f"条款编号：{clause.clause_id or '未知'}\n"
        user_prompt += f"条款标题：{clause.title or '无'}\n"
        user_prompt += f"条款内容：{clause.content}"

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )

            content = response.choices[0].message.content.strip()
            return self._parse_response(content, clause)

        except openai.APIError as e:
            raise ExtractionError(f"API 调用失败: {str(e)}")
        except Exception as e:
            raise ExtractionError(f"提取失败: {str(e)}")

    def _parse_response(self, content: str, clause: Clause) -> list[RuleTriple]:
        """解析 LLM 返回的内容

        Args:
            content: LLM 返回的原始文本
            clause: 原始条款对象

        Returns:
            RuleTriple 列表
        """
        triples = []

        # 提取所有 JSON 对象
        # 可能有多行 JSON（每行一个三元组）
        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 尝试提取 JSON
            json_match = re.search(r'\{[^{}]*\}', line)
            if json_match:
                try:
                    data = json.loads(json_match.group())
                    triple = RuleTriple(
                        subject=data.get("subject", "未知"),
                        condition=data.get("condition", "无"),
                        action=data.get("action", "未知"),
                        rule_type=data.get("rule_type", "要求"),
                        source=clause.source_file or clause.source,
                        clause_id=clause.clause_id,
                        confidence=0.9,  # LLM 提取默认置信度
                    )
                    triples.append(triple)
                except json.JSONDecodeError:
                    continue

        return triples

    def extract_batch(
        self,
        clauses: list[Clause],
        max_concurrent: int = 5,
    ) -> list[RuleTriple]:
        """批量提取多条款的三元组（串行）

        Args:
            clauses: Clause 对象列表
            max_concurrent: 最大并发数（目前为串行，后续可扩展为异步）

        Returns:
            RuleTriple 列表
        """
        all_triples = []
        errors = []

        for clause in clauses:
            try:
                triples = self.extract_single(clause)
                all_triples.extend(triples)
            except ExtractionError as e:
                errors.append(f"条款 {clause.clause_id}: {str(e)}")

        if errors:
            print(f"警告：{len(errors)} 个条款提取失败:")
            for err in errors[:5]:  # 只显示前5个错误
                print(f"  - {err}")

        return all_triples

    def extract_batch_concurrent(
        self,
        clauses: list[Clause],
        max_workers: int = 4,
        progress_callback: Optional[callable] = None,
    ) -> list[RuleTriple]:
        """并发批量提取多条款的三元组（每条款一次 API 调用）

        Args:
            clauses: Clause 对象列表
            max_workers: 最大并发 API 调用数
            progress_callback: 进度回调函数，签名为 callback(completed: int, total: int)

        Returns:
            RuleTriple 列表
        """
        all_triples = []
        total = len(clauses)
        completed = 0
        errors = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_clause = {
                executor.submit(self.extract_single, clause): clause
                for clause in clauses
            }

            for future in as_completed(future_to_clause):
                completed += 1
                if progress_callback:
                    progress_callback(completed, total)

                clause = future_to_clause[future]
                try:
                    triples = future.result()
                    all_triples.extend(triples)
                except ExtractionError as e:
                    errors.append(f"条款 {clause.clause_id}: {str(e)}")

        if errors:
            print(f"警告：{len(errors)} 个条款提取失败:")
            for err in errors[:5]:
                print(f"  - {err}")

        return all_triples

    def extract_batch_llm(
        self,
        clauses: list[Clause],
        batch_size: int = 10,
        progress_callback: Optional[callable] = None,
    ) -> list[RuleTriple]:
        """批量提取：多条规则合并到一次 LLM API 调用中

        通过将多个条款合并为一个 prompt，显著减少 API 调用次数。

        Args:
            clauses: Clause 对象列表
            batch_size: 每个批次的条款数量
            progress_callback: 进度回调函数，签名为 callback(completed: int, total: int)

        Returns:
            RuleTriple 列表
        """
        all_triples = []
        total_batches = (len(clauses) + batch_size - 1) // batch_size

        for batch_idx in range(total_batches):
            start = batch_idx * batch_size
            end = min(start + batch_size, len(clauses))
            batch_clauses = clauses[start:end]

            if progress_callback:
                progress_callback(batch_idx + 1, total_batches)

            # 构建批量 prompt
            user_prompt = self._build_batch_prompt(batch_clauses)

            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=self.max_tokens * len(batch_clauses),
                    temperature=self.temperature,
                )

                content = response.choices[0].message.content.strip()
                triples = self._parse_batch_response(content, batch_clauses)
                all_triples.extend(triples)

            except openai.APIError as e:
                print(f"批量 {batch_idx + 1} API 调用失败: {str(e)}")
                # 回退到逐条提取
                for clause in batch_clauses:
                    try:
                        clause_triples = self.extract_single(clause)
                        all_triples.extend(clause_triples)
                    except ExtractionError:
                        continue

        return all_triples

    def _build_batch_prompt(self, clauses: list[Clause]) -> str:
        """构建批量提取的 prompt

        Args:
            clauses: Clause 对象列表

        Returns:
            合并后的 prompt 文本
        """
        prompt_parts = ["请提取以下所有规则的 JSON 三元组：\n"]

        for i, clause in enumerate(clauses, 1):
            prompt_parts.append(f"\n--- 规则 {i} ---")
            prompt_parts.append(f"条款编号：{clause.clause_id or '未知'}")
            if clause.title:
                prompt_parts.append(f"条款标题：{clause.title}")
            prompt_parts.append(f"条款内容：{clause.content}")

        prompt_parts.append("\n\n请为每条规则输出一个 JSON 对象，格式为：")
        prompt_parts.append('{"subject": "主体", "condition": "条件", "action": "动作", "rule_type": "类型"}')
        prompt_parts.append("每个 JSON 占一行，共 " + str(len(clauses)) + " 行。")

        return "".join(prompt_parts)

    def _parse_batch_response(self, content: str, clauses: list[Clause]) -> list[RuleTriple]:
        """解析批量 LLM 返回的内容

        Args:
            content: LLM 返回的原始文本
            clauses: 原始条款对象列表

        Returns:
            RuleTriple 列表
        """
        triples = []
        clause_map = {i: clause for i, clause in enumerate(clauses)}

        # 按行解析 JSON
        lines = content.split('\n')
        clause_idx = 0

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 尝试提取 JSON（支持更灵活的格式）
            json_match = re.search(r'\{[^{}]*\}', line)
            if json_match:
                try:
                    data = json.loads(json_match.group())
                    # 使用轮询方式分配给条款
                    clause = clause_map.get(clause_idx, clauses[0])
                    triple = RuleTriple(
                        subject=data.get("subject", "未知"),
                        condition=data.get("condition", "无"),
                        action=data.get("action", "未知"),
                        rule_type=data.get("rule_type", "要求"),
                        source=clause.source_file or clause.source.value if clause.source else "未知",
                        clause_id=clause.clause_id,
                        confidence=0.9,
                    )
                    triples.append(triple)
                    clause_idx = (clause_idx + 1) % len(clauses)
                except json.JSONDecodeError:
                    continue

        return triples


def extract_triples(
    clauses: list[Clause],
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: str = "gpt-4o-mini",
) -> list[RuleTriple]:
    """提取三元组的统一入口

    Args:
        clauses: Clause 列表
        api_key: API 密钥
        base_url: API 基础 URL
        model: 模型名称

    Returns:
        RuleTriple 列表
    """
    extractor = LLMTripleExtractor(
        api_key=api_key,
        base_url=base_url,
        model=model,
    )
    return extractor.extract_batch(clauses)


if __name__ == "__main__":
    # 简单测试
    from text_preprocessor import Clause, RuleSourceType

    sample_clauses = [
        Clause(
            clause_id="1",
            title="医院资质",
            content="医院必须具有有效的医疗机构执业许可证，且许可证应在有效期内。",
            raw_text="1. 医院必须具有有效的医疗机构执业许可证。",
            source=RuleSourceType.NATIONAL_STANDARD,
            source_file="test_standards.txt"
        ),
        Clause(
            clause_id="2",
            title="处方权限",
            content="执业医师方可开具处方。",
            raw_text="2. 执业医师方可开具处方。",
            source=RuleSourceType.HOSPITAL_INTERNAL,
            source_file="test_hospital.txt"
        ),
    ]

    # 检查是否有 API key
    if os.getenv("OPENAI_API_KEY"):
        print("=== 测试 LLM 三元组提取 ===\n")
        triples = extract_triples(sample_clauses)

        for i, triple in enumerate(triples, 1):
            print(f"三元组 {i}: {triple}")
    else:
        print("未设置 OPENAI_API_KEY，跳过 LLM 测试")