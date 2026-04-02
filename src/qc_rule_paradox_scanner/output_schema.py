"""JSON 结构化输出模块

定义统一的输出格式 OutputSchema，支持输出到文件或 stdout
"""

import json
import sys
from dataclasses import dataclass, field, asdict
from typing import TextIO, Optional

from .conflict_detector import Conflict, ConflictReport
from .priority_resolver import PriorityResolver, SuggestionGenerator


@dataclass
class OutputSchema:
    """JSON 输出格式 schema

    包含：
    - conflicts: 冲突列表
    - summary: 摘要统计
    - suggestions: 优先级消解建议汇总
    - metadata: 输出元数据（版本、生成时间等）
    """
    conflicts: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    suggestions: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return asdict(self)

    def to_json(self, indent: int = 2, ensure_ascii: bool = False) -> str:
        """转换为 JSON 字符串

        Args:
            indent: 缩进空格数
            ensure_ascii: 是否转义非 ASCII 字符

        Returns:
            JSON 格式字符串
        """
        return json.dumps(
            self.to_dict(),
            indent=indent,
            ensure_ascii=ensure_ascii,
        )

    def to_file(self, file_path: str, indent: int = 2, ensure_ascii: bool = False):
        """输出到文件

        Args:
            file_path: 输出文件路径
            indent: 缩进空格数
            ensure_ascii: 是否转义非 ASCII 字符
        """
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(
                self.to_dict(),
                f,
                indent=indent,
                ensure_ascii=ensure_ascii,
            )

    def to_stream(self, stream: TextIO = sys.stdout, indent: int = 2, ensure_ascii: bool = False):
        """输出到流（stdout 或其他 TextIO）

        Args:
            stream: 输出流，默认为 sys.stdout
            indent: 缩进空格数
            ensure_ascii: 是否转义非 ASCII 字符
        """
        json.dump(
            self.to_dict(),
            stream,
            indent=indent,
            ensure_ascii=ensure_ascii,
        )
        stream.flush()


def create_output_schema(
    report: ConflictReport,
    include_suggestions: bool = True,
    resolver: Optional[PriorityResolver] = None,
) -> OutputSchema:
    """从冲突报告创建 OutputSchema

    Args:
        report: ConflictReport 冲突检测报告
        include_suggestions: 是否包含优先级消解建议
        resolver: 优先级消解器（可选）

    Returns:
        OutputSchema 对象
    """
    # 创建默认的优先级消解器（如果未提供）
    if resolver is None:
        resolver = PriorityResolver()

    # 构建冲突列表
    conflicts = [conflict.to_dict() for conflict in report.conflicts]

    # 构建摘要
    summary = report.get_summary()

    # 构建建议列表
    suggestions = []
    if include_suggestions:
        generator = SuggestionGenerator(resolver)
        for conflict in report.conflicts:
            priority_diff, higher_rule, lower_rule = resolver.compare_priority(
                conflict.triple_a, conflict.triple_b
            )
            suggestion = resolver.resolve_conflict(conflict)
            suggestions.append({
                "conflict_type": conflict.conflict_type.value,
                "conflict_id": f"{conflict.triple_a.clause_id}_vs_{conflict.triple_b.clause_id}",
                "higher_priority_rule": {
                    "clause_id": higher_rule.clause_id,
                    "source": higher_rule.source,
                    "action": higher_rule.action,
                    "rule_type": higher_rule.rule_type,
                },
                "lower_priority_rule": {
                    "clause_id": lower_rule.clause_id,
                    "source": lower_rule.source,
                    "action": lower_rule.action,
                    "rule_type": lower_rule.rule_type,
                },
                "priority_difference": priority_diff,
                "suggestion": suggestion,
            })

    # 构建元数据
    import datetime
    metadata = {
        "version": "1.0.0",
        "generator": "质控规则冲突扫描器",
        "generated_at": datetime.datetime.now().isoformat(),
        "conflict_count": len(conflicts),
        "suggestion_count": len(suggestions),
    }

    return OutputSchema(
        conflicts=conflicts,
        summary=summary,
        suggestions=suggestions,
        metadata=metadata,
    )


def output_to_json(
    report: ConflictReport,
    output_path: Optional[str] = None,
    use_stdout: bool = False,
    include_suggestions: bool = True,
    resolver: Optional[PriorityResolver] = None,
    indent: int = 2,
) -> Optional[str]:
    """统一的 JSON 输出函数

    Args:
        report: ConflictReport 冲突检测报告
        output_path: 输出文件路径（可选）
        use_stdout: 是否同时输出到 stdout
        include_suggestions: 是否包含建议
        resolver: 优先级消解器
        indent: JSON 缩进

    Returns:
        如果 output_path 不为 None，返回 JSON 字符串；否则返回 None
    """
    schema = create_output_schema(report, include_suggestions, resolver)

    if use_stdout:
        schema.to_stream(sys.stdout, indent=indent)

    if output_path:
        schema.to_file(output_path, indent=indent)
        return None
    else:
        return schema.to_json(indent=indent)


if __name__ == "__main__":
    # 简单测试
    from .conflict_detector import ConflictType, ConflictReport, detect_conflicts
    from .triple_extractor import RuleTriple

    sample_triples = [
        RuleTriple(
            subject="执业医师",
            condition="开具处方时",
            action="需要核对患者身份",
            source="等级评审标准",
            clause_id="1.2.1",
            rule_type="要求",
        ),
        RuleTriple(
            subject="执业医师",
            condition="开具处方时",
            action="不得开具空白处方",
            source="院内规范",
            clause_id="条款5",
            rule_type="禁止",
        ),
        RuleTriple(
            subject="医院",
            condition="医保患者住院",
            action="在出院后7日内完成费用结算",
            source="医保规则",
            clause_id="第3条",
            rule_type="要求",
        ),
        RuleTriple(
            subject="医院",
            condition="医保患者住院",
            action="应在24小时内完成费用上传",
            source="医保规则",
            clause_id="第5条",
            rule_type="要求",
        ),
    ]

    print("=== 测试 OutputSchema ===\n")

    report = detect_conflicts(sample_triples)
    print(f"检测到 {len(report.conflicts)} 个冲突\n")

    schema = create_output_schema(report)
    print("JSON 输出：")
    print(schema.to_json())