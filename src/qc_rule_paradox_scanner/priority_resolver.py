"""优先级消解建议模块

基于规则来源和类型，生成冲突优先级消解建议
支持用户自定义优先级规则
"""

from dataclasses import dataclass, field
from typing import Optional

from .text_preprocessor import RuleSourceType
from .conflict_detector import Conflict, ConflictType, ConflictReport
from .triple_extractor import RuleTriple


# 默认优先级配置：卫健委标准 > 院内规范 > 医保规则
DEFAULT_PRIORITY_RULES = {
    RuleSourceType.NATIONAL_STANDARD: 100,  # 最高优先级
    RuleSourceType.HOSPITAL_INTERNAL: 50,   # 中等优先级
    RuleSourceType.INSURANCE: 25,           # 较低优先级
    RuleSourceType.UNKNOWN: 10,              # 最低优先级
}

# 优先级描述
PRIORITY_LABELS = {
    RuleSourceType.NATIONAL_STANDARD: "卫健委/等级评审标准",
    RuleSourceType.HOSPITAL_INTERNAL: "院内质控规范",
    RuleSourceType.INSURANCE: "医保规则",
    RuleSourceType.UNKNOWN: "未知来源",
}


@dataclass
class PriorityRule:
    """优先级规则配置

    支持用户自定义各来源规则的优先级数值
    """
    source: RuleSourceType
    priority: int  # 数值越高优先级越高
    label: str = ""  # 可读标签

    def __post_init__(self):
        if not self.label:
            self.label = PRIORITY_LABELS.get(self.source, "未知来源")

    def __repr__(self) -> str:
        return f"PriorityRule({self.label}, priority={self.priority})"


class PriorityResolver:
    """优先级消解器

    基于规则来源和类型，生成冲突优先级消解建议
    """

    def __init__(self, custom_priority: Optional[dict[RuleSourceType, int]] = None):
        """初始化优先级消解器

        Args:
            custom_priority: 自定义优先级配置，覆盖默认配置
                            格式为 {RuleSourceType: priority_value}
        """
        if custom_priority:
            self.priority_map = custom_priority.copy()
        else:
            self.priority_map = DEFAULT_PRIORITY_RULES.copy()

    def _resolve_source(self, source: str) -> RuleSourceType:
        """将字符串来源解析为 RuleSourceType 枚举

        Args:
            source: 来源字符串（如"等级评审标准"、"院内规范"等）

        Returns:
            对应的 RuleSourceType 枚举值
        """
        # 直接匹配
        for st in RuleSourceType:
            if st.value == source or st.name == source:
                return st

        # 模糊匹配
        source_lower = source.lower()
        if '等级评审' in source or '卫健委' in source or '国家标准' in source or '国家' in source_lower:
            return RuleSourceType.NATIONAL_STANDARD
        if '院内' in source or '医院' in source_lower and '规范' in source:
            return RuleSourceType.HOSPITAL_INTERNAL
        if '医保' in source:
            return RuleSourceType.INSURANCE

        return RuleSourceType.UNKNOWN

    def get_priority(self, source: str | RuleSourceType) -> int:
        """获取某来源规则的优先级数值

        Args:
            source: 来源（可以是字符串或 RuleSourceType 枚举）
        """
        if isinstance(source, str):
            source = self._resolve_source(source)
        return self.priority_map.get(source, 0)

    def get_priority_label(self, source: str | RuleSourceType) -> str:
        """获取某来源规则的可读标签

        Args:
            source: 来源（可以是字符串或 RuleSourceType 枚举）
        """
        if isinstance(source, str):
            source = self._resolve_source(source)
        return PRIORITY_LABELS.get(source, "未知来源")

    def compare_priority(
        self,
        triple_a: RuleTriple,
        triple_b: RuleTriple,
    ) -> tuple[int, RuleTriple, RuleTriple]:
        """比较两个规则的优先级

        Returns:
            (优先级差, 高优先级规则, 低优先级规则)
        """
        priority_a = self.get_priority(triple_a.source)
        priority_b = self.get_priority(triple_b.source)

        if priority_a >= priority_b:
            return (priority_a - priority_b, triple_a, triple_b)
        else:
            return (priority_b - priority_a, triple_b, triple_a)

    def resolve_conflict(self, conflict: Conflict) -> str:
        """生成冲突的优先级消解建议

        Args:
            conflict: Conflict 对象

        Returns:
            优先级消解建议文本
        """
        priority_diff, higher_rule, lower_rule = self.compare_priority(
            conflict.triple_a, conflict.triple_b
        )

        # 根据冲突类型生成建议
        if conflict.conflict_type == ConflictType.TEMPORAL_CONFLICT:
            return self._resolve_temporal_conflict(conflict, higher_rule, lower_rule)
        elif conflict.conflict_type == ConflictType.ACTION_CONFLICT:
            return self._resolve_action_conflict(conflict, higher_rule, lower_rule)
        elif conflict.conflict_type == ConflictType.SCOPE_OVERLAP:
            return self._resolve_scope_overlap(conflict, higher_rule, lower_rule)
        elif conflict.conflict_type == ConflictType.PRIORITY_CONFLICT:
            return self._resolve_priority_conflict(conflict)
        else:
            return self._generate_generic_suggestion(higher_rule, lower_rule)

    def _resolve_temporal_conflict(
        self,
        conflict: Conflict,
        higher_rule: RuleTriple,
        lower_rule: RuleTriple,
    ) -> str:
        """生成时序冲突的消解建议"""
        higher_label = self.get_priority_label(higher_rule.source)
        lower_label = self.get_priority_label(lower_rule.source)

        suggestion = f"【时序冲突消解建议】\n"
        suggestion += f"根据优先级：「{higher_label}」（条款{higher_rule.clause_id}）优先于「{lower_label}」（条款{lower_rule.clause_id}）。\n\n"

        # 如果高优先级规则有时序要求
        if higher_rule.condition:
            suggestion += f"执行建议：以「{higher_rule.action}」的时间要求为准。\n"

        # 如果低优先级规则与高优先级冲突
        suggestion += f"后续处理：请向「{lower_label}」的制定部门反馈，建议修订条款{lower_rule.clause_id}以与上级标准保持一致。"

        return suggestion

    def _resolve_action_conflict(
        self,
        conflict: Conflict,
        higher_rule: RuleTriple,
        lower_rule: RuleTriple,
    ) -> str:
        """生成动作冲突的消解建议"""
        higher_label = self.get_priority_label(higher_rule.source)
        lower_label = self.get_priority_label(lower_rule.source)

        # 判断高优先级规则是"要求"还是"禁止"
        if higher_rule.rule_type == "禁止":
            # 高优先级是禁止规则，更需要遵守
            suggestion = f"【动作冲突消解建议】\n"
            suggestion += f"根据优先级：「{higher_label}」（条款{higher_rule.clause_id}）规定禁止行为，优先于低级别规则的要求。\n\n"
            suggestion += f"执行建议：「{higher_rule.action}」属于禁止项，应严格遵守。\n"
            suggestion += f"若因业务需要必须执行「{lower_rule.action}」，需通过正式流程申请制定例外条款或修订上级标准。"
        else:
            # 高优先级是要求规则
            suggestion = f"【动作冲突消解建议】\n"
            suggestion += f"根据优先级：「{higher_label}」（条款{higher_rule.clause_id}）要求「{higher_rule.action}」，优先于「{lower_label}」的限制。\n\n"
            suggestion += f"执行建议：按「{higher_label}」要求执行。\n"
            suggestion += f"如「{lower_label}」（条款{lower_rule.clause_id}）确需限制，应向其制定部门申请修订。"

        return suggestion

    def _resolve_scope_overlap(
        self,
        conflict: Conflict,
        higher_rule: RuleTriple,
        lower_rule: RuleTriple,
    ) -> str:
        """生成范围重叠的消解建议"""
        higher_label = self.get_priority_label(higher_rule.source)
        lower_label = self.get_priority_label(lower_rule.source)

        suggestion = f"【范围重叠消解建议】\n"
        suggestion += f"「{conflict.triple_a.subject}」在「{conflict.triple_a.condition}」条件下同时被多个规则覆盖。\n\n"
        suggestion += f"优先级：「{higher_label}」（条款{higher_rule.clause_id}）>「{lower_label}」（条款{lower_rule.clause_id}）。\n\n"
        suggestion += f"建议：\n"
        suggestion += f"1. 优先适用「{higher_label}」的规定；\n"
        suggestion += f"2. 如两项规则存在具体差异，建议梳理明确适用范围；\n"
        suggestion += f"3. 如需统一管理，建议由优先级高的规则制定部门牵头修订。"

        return suggestion

    def _resolve_priority_conflict(self, conflict: Conflict) -> str:
        """生成优先级冲突的消解建议（同一来源内部的冲突）"""
        suggestion = f"【优先级冲突消解建议】\n"
        suggestion += f"同一来源「{conflict.triple_a.source}」内部存在矛盾条款：\n"
        suggestion += f"  - 条款{conflict.triple_a.clause_id}：{conflict.triple_a.rule_type}「{conflict.triple_a.action}」\n"
        suggestion += f"  - 条款{conflict.triple_b.clause_id}：{conflict.triple_b.rule_type}「{conflict.triple_b.action}」\n\n"
        suggestion += f"建议：\n"
        suggestion += f"1. 核对两项条款的制定时间和适用范围；\n"
        suggestion += f"2. 原则上以最新制定的条款为准，或以解释口径更明确的条款为准；\n"
        suggestion += f"3. 如无法判断，请咨询条款制定部门或上级主管部门。"

        return suggestion

    def _generate_generic_suggestion(
        self,
        higher_rule: RuleTriple,
        lower_rule: RuleTriple,
    ) -> str:
        """生成通用消解建议"""
        higher_label = self.get_priority_label(higher_rule.source)
        lower_label = self.get_priority_label(lower_rule.source)

        return (
            f"【消解建议】\n"
            f"根据规则优先级：「{higher_label}」（条款{higher_rule.clause_id}）优先于「{lower_label}」（条款{lower_rule.clause_id}）。\n"
            f"建议优先遵循高优先级规则的规定，同时与低优先级规则的制定部门沟通协调。"
        )

    def resolve_report(
        self,
        report: ConflictReport,
        update_existing: bool = True,
    ) -> ConflictReport:
        """对整个冲突报告进行优先级消解

        Args:
            report: ConflictReport 对象
            update_existing: 是否更新已有建议（True）或替换（False）

        Returns:
            更新后的 ConflictReport
        """
        for conflict in report.conflicts:
            if update_existing:
                # 在现有建议基础上追加优先级建议
                priority_suggestion = self.resolve_conflict(conflict)
                conflict.suggestion = (
                    f"{conflict.suggestion}\n\n---\n{priority_suggestion}"
                )
            else:
                # 完全替换为优先级建议
                conflict.suggestion = self.resolve_conflict(conflict)

        return report


class SuggestionGenerator:
    """建议生成器

    生成可读的建议文本，包含详细的上下文信息
    """

    def __init__(self, priority_resolver: Optional[PriorityResolver] = None):
        """初始化建议生成器

        Args:
            priority_resolver: 优先级消解器（可选）
        """
        self.resolver = priority_resolver or PriorityResolver()

    def generate_summary(
        self,
        conflict: Conflict,
        include_context: bool = True,
    ) -> str:
        """生成冲突摘要

        Args:
            conflict: Conflict 对象
            include_context: 是否包含详细上下文

        Returns:
            格式化的冲突摘要文本
        """
        lines = []
        lines.append(f"## {conflict.conflict_type.value}")

        if include_context:
            lines.append(f"**置信度**：{conflict.confidence:.0%}")
            lines.append(f"**规则A**：{conflict.triple_a.source} - 条款{conflict.triple_a.clause_id}")
            lines.append(f"  - 主体：{conflict.triple_a.subject}")
            lines.append(f"  - 条件：{conflict.triple_a.condition}")
            lines.append(f"  - 动作：[{conflict.triple_a.rule_type}] {conflict.triple_a.action}")
            lines.append(f"**规则B**：{conflict.triple_b.source} - 条款{conflict.triple_b.clause_id}")
            lines.append(f"  - 主体：{conflict.triple_b.subject}")
            lines.append(f"  - 条件：{conflict.triple_b.condition}")
            lines.append(f"  - 动作：[{conflict.triple_b.rule_type}] {conflict.triple_b.action}")

        lines.append(f"\n**描述**：{conflict.description}")
        lines.append(f"\n**消解建议**：\n{conflict.suggestion}")

        return "\n".join(lines)

    def generate_table_row(self, conflict: Conflict) -> dict:
        """生成表格行格式的冲突信息

        Args:
            conflict: Conflict 对象

        Returns:
            dict 格式的冲突信息
        """
        priority_diff, higher_rule, lower_rule = self.resolver.compare_priority(
            conflict.triple_a, conflict.triple_b
        )

        return {
            "冲突类型": conflict.conflict_type.value,
            "置信度": f"{conflict.confidence:.0%}",
            "规则A": f"{conflict.triple_a.source} ({conflict.triple_a.clause_id})",
            "规则B": f"{conflict.triple_b.source} ({conflict.triple_b.clause_id})",
            "高优先级": self.resolver.get_priority_label(higher_rule.source),
            "建议": conflict.suggestion[:100] + "..." if len(conflict.suggestion) > 100 else conflict.suggestion,
        }

    def generate_markdown_report(
        self,
        report: ConflictReport,
        title: str = "规则冲突检测报告",
    ) -> str:
        """生成 Markdown 格式的冲突报告

        Args:
            report: ConflictReport 对象
            title: 报告标题

        Returns:
            Markdown 格式的报告文本
        """
        lines = []
        lines.append(f"# {title}\n")

        # 摘要
        summary = report.get_summary()
        lines.append("## 摘要\n")
        lines.append(f"- **冲突总数**：{summary['total']}")
        lines.append(f"- **时序互斥**：{summary['temporal']} 个")
        lines.append(f"- **动作矛盾**：{summary['action']} 个")
        lines.append(f"- **范围重叠**：{summary['scope_overlap']} 个")
        lines.append(f"- **优先级冲突**：{summary['priority']} 个")

        # 优先级说明
        lines.append("\n## 优先级规则\n")
        lines.append("| 来源 | 优先级 |")
        lines.append("|------|--------|")
        for source in [RuleSourceType.NATIONAL_STANDARD, RuleSourceType.HOSPITAL_INTERNAL, RuleSourceType.INSURANCE, RuleSourceType.UNKNOWN]:
            priority = self.resolver.get_priority(source)
            label = self.resolver.get_priority_label(source)
            lines.append(f"| {label} | {priority} |")

        # 冲突详情
        lines.append("\n## 冲突详情\n")

        if report.temporal_conflicts:
            lines.append("### 时序互斥\n")
            for i, conflict in enumerate(report.temporal_conflicts, 1):
                lines.append(f"#### {i}. {conflict.triple_a.clause_id} vs {conflict.triple_b.clause_id}")
                lines.append(f"置信度：{conflict.confidence:.0%}")
                lines.append(f"\n冲突描述：{conflict.description}")
                lines.append(f"\n消解建议：\n{conflict.suggestion}\n")

        if report.action_conflicts:
            lines.append("### 动作矛盾\n")
            for i, conflict in enumerate(report.action_conflicts, 1):
                lines.append(f"#### {i}. {conflict.triple_a.clause_id} vs {conflict.triple_b.clause_id}")
                lines.append(f"置信度：{conflict.confidence:.0%}")
                lines.append(f"\n冲突描述：{conflict.description}")
                lines.append(f"\n消解建议：\n{conflict.suggestion}\n")

        if report.scope_overlaps:
            lines.append("### 范围重叠\n")
            for i, conflict in enumerate(report.scope_overlaps, 1):
                lines.append(f"#### {i}. {conflict.triple_a.clause_id} vs {conflict.triple_b.clause_id}")
                lines.append(f"置信度：{conflict.confidence:.0%}")
                lines.append(f"\n冲突描述：{conflict.description}")
                lines.append(f"\n消解建议：\n{conflict.suggestion}\n")

        if report.priority_conflicts:
            lines.append("### 优先级冲突\n")
            for i, conflict in enumerate(report.priority_conflicts, 1):
                lines.append(f"#### {i}. {conflict.triple_a.clause_id} vs {conflict.triple_b.clause_id}")
                lines.append(f"置信度：{conflict.confidence:.0%}")
                lines.append(f"\n冲突描述：{conflict.description}")
                lines.append(f"\n消解建议：\n{conflict.suggestion}\n")

        if not report.conflicts:
            lines.append("\n*未检测到冲突*")

        return "\n".join(lines)


def create_priority_resolver(
    custom_priority: Optional[dict[RuleSourceType, int]] = None,
) -> PriorityResolver:
    """创建优先级消解器的工厂函数

    Args:
        custom_priority: 自定义优先级配置

    Returns:
        PriorityResolver 实例
    """
    return PriorityResolver(custom_priority)


def resolve_conflict_report(
    report: ConflictReport,
    custom_priority: Optional[dict[RuleSourceType, int]] = None,
) -> ConflictReport:
    """消解冲突报告的统一入口

    Args:
        report: ConflictReport 对象
        custom_priority: 自定义优先级配置

    Returns:
        更新后的 ConflictReport
    """
    resolver = PriorityResolver(custom_priority)
    return resolver.resolve_report(report)


if __name__ == "__main__":
    # 简单测试
    from conflict_detector import Conflict, ConflictType, ConflictReport, detect_conflicts
    from triple_extractor import RuleTriple

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

    print("=== 测试优先级消解建议模块 ===\n")

    # 检测冲突
    report = detect_conflicts(sample_triples)
    print(f"检测到 {len(report.conflicts)} 个冲突\n")

    # 创建优先级消解器
    resolver = PriorityResolver()
    generator = SuggestionGenerator(resolver)

    # 逐一处理冲突
    for i, conflict in enumerate(report.conflicts, 1):
        print(f"--- 冲突 {i} ---")
        print(f"类型：{conflict.conflict_type.value}")
        print(f"原有建议：{conflict.suggestion[:80]}...")

        # 生成优先级消解建议
        priority_suggestion = resolver.resolve_conflict(conflict)
        print(f"\n优先级消解建议：\n{priority_suggestion}")
        print()

    # 测试自定义优先级
    print("\n=== 测试自定义优先级 ===")
    custom_priority = {
        RuleSourceType.NATIONAL_STANDARD: 100,
        RuleSourceType.HOSPITAL_INTERNAL: 80,  # 调高院内规范优先级
        RuleSourceType.INSURANCE: 50,
        RuleSourceType.UNKNOWN: 10,
    }
    resolver_custom = PriorityResolver(custom_priority)
    print("自定义优先级配置：")
    for source in RuleSourceType:
        print(f"  {resolver_custom.get_priority_label(source)}: {resolver_custom.get_priority(source)}")
