"""规则冲突检测引擎

检测规则三元组之间的各类冲突：
- 时序互斥（TEMPORAL_CONFLICT）
- 动作矛盾（ACTION_CONFLICT）
- 范围重叠（SCOPE_OVERLAP）
- 优先级冲突（PRIORITY_CONFLICT）
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .text_preprocessor import RuleSourceType
from .triple_extractor import RuleTriple


class ConflictType(Enum):
    """冲突类型枚举"""
    TEMPORAL_CONFLICT = "时序互斥"      # 时序要求矛盾
    ACTION_CONFLICT = "动作矛盾"        # 要求做X vs 禁止做X
    SCOPE_OVERLAP = "范围重叠"         # 同一行为被多规则覆盖但优先级不清
    PRIORITY_CONFLICT = "优先级冲突"    # 同级规则对同一事项要求不同


# 动作类型关键词
ACTION_REQUIRE = {"应", "应当", "必须", "需要", "要求", "必须完成", "需要完成", "应当完成"}
ACTION_FORBID = {"禁止", "不得", "严禁", "不许", "不准", "不能", "不可", "不应"}
ACTION_SUGGEST = {"建议", "推荐", "鼓励", "提倡", "可以考虑"}

# 时序关键词
TEMPORAL_KEYWORDS = {
    "前": ["术前", "事前", "前", "之前", "先行"],
    "后": ["术后", "事后", "后", "之后", "完成后再"],
    "期间": ["期间", "过程中", "时", "时须", "时需"],
    "日内": ["日内", "天内", "日内完成", "天内完成"],
    "随时": ["随时", "立即", "即时", "立刻"],
}

# 优先级配置（可配置）
DEFAULT_PRIORITY = {
    RuleSourceType.NATIONAL_STANDARD: 3,  # 卫健委标准最高
    RuleSourceType.HOSPITAL_INTERNAL: 2,  # 院内规范次之
    RuleSourceType.INSURANCE: 1,          # 医保规则最低
    RuleSourceType.UNKNOWN: 0,
}


@dataclass
class Conflict:
    """冲突数据类"""
    conflict_type: ConflictType
    triple_a: RuleTriple
    triple_b: RuleTriple
    confidence: float  # 置信度 0-1
    description: str   # 冲突描述
    suggestion: str    # 消解建议

    def to_dict(self) -> dict:
        return {
            "type": self.conflict_type.value,
            "triple_a": self.triple_a.to_dict(),
            "triple_b": self.triple_b.to_dict(),
            "confidence": self.confidence,
            "description": self.description,
            "suggestion": self.suggestion,
        }


@dataclass
class ConflictReport:
    """冲突检测报告"""
    conflicts: list[Conflict] = field(default_factory=list)
    temporal_conflicts: list[Conflict] = field(default_factory=list)
    action_conflicts: list[Conflict] = field(default_factory=list)
    scope_overlaps: list[Conflict] = field(default_factory=list)
    priority_conflicts: list[Conflict] = field(default_factory=list)

    def add_conflict(self, conflict: Conflict):
        self.conflicts.append(conflict)
        if conflict.conflict_type == ConflictType.TEMPORAL_CONFLICT:
            self.temporal_conflicts.append(conflict)
        elif conflict.conflict_type == ConflictType.ACTION_CONFLICT:
            self.action_conflicts.append(conflict)
        elif conflict.conflict_type == ConflictType.SCOPE_OVERLAP:
            self.scope_overlaps.append(conflict)
        elif conflict.conflict_type == ConflictType.PRIORITY_CONFLICT:
            self.priority_conflicts.append(conflict)

    def get_summary(self) -> dict:
        return {
            "total": len(self.conflicts),
            "temporal": len(self.temporal_conflicts),
            "action": len(self.action_conflicts),
            "scope_overlap": len(self.scope_overlaps),
            "priority": len(self.priority_conflicts),
        }


class TemporalConflictDetector:
    """时序互斥检测器

    检测如：A规则要求24h内完成，B规则要求手术前完成
    """

    def detect(self, triple_a: RuleTriple, triple_b: RuleTriple) -> Optional[Conflict]:
        """检测两条规则是否存在时序互斥

        Args:
            triple_a: 规则三元组A
            triple_b: 规则三元组B

        Returns:
            Conflict 对象或 None（无冲突）
        """
        # 提取时序信息
        time_a = self._extract_temporal(triple_a)
        time_b = self._extract_temporal(triple_b)

        # 如果都没有时序信息，不检测
        if not time_a and not time_b:
            return None

        # 检测矛盾时序
        if time_a and time_b:
            # 术前 vs 术后 矛盾
            if time_a["direction"] == "前" and time_b["direction"] == "后":
                return Conflict(
                    conflict_type=ConflictType.TEMPORAL_CONFLICT,
                    triple_a=triple_a,
                    triple_b=triple_b,
                    confidence=0.9,
                    description=f"时序矛盾：规则A要求「{time_a['keyword']}」完成某动作，"
                               f"规则B要求「{time_b['keyword']}」完成该动作，"
                               f"两项要求存在时序冲突。",
                    suggestion=self._generate_temporal_suggestion(triple_a, triple_b, time_a, time_b),
                )

            # 术后 vs 术前 矛盾
            if time_a["direction"] == "后" and time_b["direction"] == "前":
                return Conflict(
                    conflict_type=ConflictType.TEMPORAL_CONFLICT,
                    triple_a=triple_a,
                    triple_b=triple_b,
                    confidence=0.9,
                    description=f"时序矛盾：规则A要求「{time_a['keyword']}」完成某动作，"
                               f"规则B要求「{time_b['keyword']}」完成该动作，"
                               f"两项要求存在时序冲突。",
                    suggestion=self._generate_temporal_suggestion(triple_b, triple_a, time_b, time_a),
                )

            # 不同时间段矛盾（如7日内 vs 24h内）
            if time_a["direction"] == time_b["direction"]:
                # 检查具体时间是否矛盾
                if time_a.get("duration") and time_b.get("duration"):
                    if time_a["duration"] != time_b["duration"]:
                        return Conflict(
                            conflict_type=ConflictType.TEMPORAL_CONFLICT,
                            triple_a=triple_a,
                            triple_b=triple_b,
                            confidence=0.7,
                            description=f"时序要求冲突：规则A要求「{time_a['keyword']}」"
                                       f"规则B要求「{time_b['keyword']}」，时间要求不一致。",
                            suggestion=f"建议统一时间要求，保留更严格或更合理的时限规定。",
                        )

        return None

    def _extract_temporal(self, triple: RuleTriple) -> Optional[dict]:
        """从三元组中提取时序信息"""
        combined_text = f"{triple.condition} {triple.action}"

        for direction, keywords in TEMPORAL_KEYWORDS.items():
            for keyword in keywords:
                if keyword in combined_text:
                    result = {"direction": direction, "keyword": keyword}

                    # 提取具体时间数值
                    time_match = re.search(r'(\d+)\s*(小时|日|天|周|月|年|min|hour|day|week|month|year)', combined_text)
                    if time_match:
                        result["duration"] = time_match.group(1)
                        result["duration_unit"] = time_match.group(2)

                    return result

        return None

    def _generate_temporal_suggestion(
        self,
        triple_earlier: RuleTriple,
        triple_later: RuleTriple,
        time_earlier: dict,
        time_later: dict,
    ) -> str:
        """生成时序冲突的消解建议"""
        return (
            f"建议明确执行顺序：先执行「{triple_earlier.action}」（{time_earlier['keyword']}），"
            f"再执行「{triple_later.action}」（{time_later['keyword']}）。"
            f"若两者同时要求，应在制度层面明确优先级。"
        )


class ActionConflictDetector:
    """动作矛盾检测器

    检测要求做X vs 禁止做X类型的冲突
    """

    def detect(self, triple_a: RuleTriple, triple_b: RuleTriple) -> Optional[Conflict]:
        """检测两条规则是否存在动作矛盾

        Args:
            triple_a: 规则三元组A
            triple_b: 规则三元组B

        Returns:
            Conflict 对象或 None（无冲突）
        """
        # 检查是否同一主体或相关主体
        if not self._is_related_subject(triple_a.subject, triple_b.subject):
            return None

        # 检查是否同一动作
        action_similarity = self._is_similar_action(triple_a.action, triple_b.action)
        if not action_similarity:
            return None

        # 检测动作矛盾
        # A要求做，B禁止做
        if triple_a.rule_type in ("要求", "建议") and triple_b.rule_type == "禁止":
            return Conflict(
                conflict_type=ConflictType.ACTION_CONFLICT,
                triple_a=triple_a,
                triple_b=triple_b,
                confidence=self._calculate_action_confidence(triple_a, triple_b),
                description=self._generate_action_conflict_desc(triple_a, triple_b, "A"),
                suggestion=self._generate_action_suggestion(triple_a, triple_b),
            )

        # A禁止做，B要求做
        if triple_a.rule_type == "禁止" and triple_b.rule_type in ("要求", "建议"):
            return Conflict(
                conflict_type=ConflictType.ACTION_CONFLICT,
                triple_a=triple_a,
                triple_b=triple_b,
                confidence=self._calculate_action_confidence(triple_b, triple_a),
                description=self._generate_action_conflict_desc(triple_b, triple_a, "B"),
                suggestion=self._generate_action_suggestion(triple_b, triple_a),
            )

        return None

    def _is_related_subject(self, subject_a: str, subject_b: str) -> bool:
        """判断两个主体是否相关（相同、包含或有关联）"""
        # 完全相同
        if subject_a == subject_b:
            return True

        # 包含关系
        subjects = {subject_a, subject_b}
        keywords = {"医院", "科室", "医师", "护士", "药师", "患者", "医务人员", "执业"}

        for kw in keywords:
            if kw in subject_a and kw in subject_b:
                return True

        # 同一机构内的主体
        # 简化判断：都包含机构相关词
        institution_keywords = {"本院", "院内", "医院", "科室"}
        a_inst = any(kw in subject_a for kw in institution_keywords)
        b_inst = any(kw in subject_b for kw in institution_keywords)
        if a_inst and b_inst:
            return True

        return False

    def _is_similar_action(self, action_a: str, action_b: str) -> bool:
        """判断两个动作是否相似（可能冲突）"""
        # 提取动作核心词
        # 移除常见的修饰词
        stopwords = {"应", "应当", "必须", "不得", "禁止", "应当", "需要", "建议"}

        def normalize(action: str) -> str:
            for sw in stopwords:
                action = action.replace(sw, "")
            return action.strip().lower()

        norm_a = normalize(action_a)
        norm_b = normalize(action_b)

        # 完全相同
        if norm_a == norm_b:
            return True

        # 包含关系
        if norm_a in norm_b or norm_b in norm_a:
            return True

        # 共同关键词超过2个
        words_a = set(norm_a)
        words_b = set(norm_b)
        common = words_a & words_b
        if len(common) >= 2:
            return True

        return False

    def _calculate_action_confidence(
        self,
        triple_require: RuleTriple,
        triple_forbid: RuleTriple,
    ) -> float:
        """计算动作矛盾的置信度"""
        base_confidence = 0.8

        # 同一来源置信度更高
        if triple_require.source == triple_forbid.source:
            base_confidence = 0.95

        # 主体完全相同置信度更高
        if triple_require.subject == triple_forbid.subject:
            base_confidence += 0.05

        return min(base_confidence, 1.0)

    def _generate_action_conflict_desc(
        self,
        triple_require: RuleTriple,
        triple_forbid: RuleTriple,
        conflict_side: str,
    ) -> str:
        """生成动作矛盾描述"""
        if conflict_side == "A":
            return (
                f"动作矛盾：规则A（「{triple_require.source}」{triple_require.clause_id}）"
                f"要求「{triple_require.subject}」{triple_require.action}，"
                f"但规则B（「{triple_forbid.source}」{triple_forbid.clause_id}）"
                f"禁止「{triple_forbid.subject}」{triple_forbid.action}。"
            )
        else:
            return (
                f"动作矛盾：规则A（「{triple_forbid.source}」{triple_forbid.clause_id}）"
                f"禁止「{triple_forbid.subject}」{triple_forbid.action}，"
                f"但规则B（「{triple_require.source}」{triple_require.clause_id}）"
                f"要求「{triple_require.subject}」{triple_require.action}。"
            )

    def _generate_action_suggestion(
        self,
        triple_require: RuleTriple,
        triple_forbid: RuleTriple,
    ) -> str:
        """生成动作矛盾的消解建议"""
        return (
            f"建议明确适用范围：若「{triple_forbid.action}」在特定条件下被允许，"
            f"应在规则中增加例外条款；"
            f"若「{triple_require.action}」确有必要，应修订原禁止性规则，"
            f"或提高其优先级（如院内规范 vs 国家标准）。"
        )


class ScopeOverlapDetector:
    """范围重叠检测器

    检测同一行为被多规则覆盖但优先级不清的情况
    """

    def detect(self, triple_a: RuleTriple, triple_b: RuleTriple) -> Optional[Conflict]:
        """检测两条规则是否存在范围重叠

        Args:
            triple_a: 规则三元组A
            triple_b: 规则三元组B

        Returns:
            Conflict 对象或 None（无冲突）
        """
        # 检查主体重叠
        if not self._is_subject_overlap(triple_a.subject, triple_b.subject):
            return None

        # 检查条件重叠
        if not self._is_condition_overlap(triple_a.condition, triple_b.condition):
            return None

        # 检查动作有一定相关性但不完全相同
        action_similarity = self._is_partially_overlapping_action(
            triple_a.action, triple_b.action
        )
        if not action_similarity:
            return None

        # 检查来源优先级
        priority_a = DEFAULT_PRIORITY.get(triple_a.source, 0)
        priority_b = DEFAULT_PRIORITY.get(triple_b.source, 0)

        # 同级或优先级相近时可能存在冲突
        if abs(priority_a - priority_b) <= 1:
            return Conflict(
                conflict_type=ConflictType.SCOPE_OVERLAP,
                triple_a=triple_a,
                triple_b=triple_b,
                confidence=0.6,
                description=(
                    f"范围重叠：「{triple_a.subject}」在「{triple_a.condition}」条件下，"
                    f"同时被「{triple_a.source}」（{triple_a.clause_id}）"
                    f"和「{triple_b.source}」（{triple_b.clause_id}）覆盖，"
                    f"具体要求可能存在差异。优先级：{priority_a} vs {priority_b}。"
                ),
                suggestion=(
                    f"建议明确适用范围：区分两项规则的具体适用场景，"
                    f"或统一优先级标准（{triple_a.source} vs {triple_b.source}）。"
                ),
            )

        return None

    def _is_subject_overlap(self, subject_a: str, subject_b: str) -> bool:
        """判断主体是否重叠"""
        if subject_a == subject_b:
            return True

        # 主体的包含关系
        if subject_a in subject_b or subject_b in subject_a:
            return True

        # 机构主体
        institution_keywords = {"医院", "科室", "病区", "部门", "机构"}
        a_is_inst = any(kw in subject_a for kw in institution_keywords)
        b_is_inst = any(kw in subject_b for kw in institution_keywords)
        if a_is_inst and b_is_inst:
            return True

        return False

    def _is_condition_overlap(self, condition_a: str, condition_b: str) -> bool:
        """判断条件是否重叠"""
        if condition_a == "无" or condition_b == "无":
            return True  # 无条件意味着全范围

        if condition_a == condition_b:
            return True

        # 包含关系
        if condition_a in condition_b or condition_b in condition_a:
            return True

        # 共同关键词
        common_keywords = {
            "住院", "门诊", "急诊", "手术", "处方", "医嘱",
            "医保", "自费", "特殊", "一般",
        }
        for kw in common_keywords:
            if kw in condition_a and kw in condition_b:
                return True

        return False

    def _is_partially_overlapping_action(
        self, action_a: str, action_b: str
    ) -> bool:
        """判断动作是否部分重叠（不完全相同但有关联）"""
        # 完全相同则由 ActionConflictDetector 处理
        if action_a == action_b:
            return False

        # 提取动词
        verbs_a = self._extract_verbs(action_a)
        verbs_b = self._extract_verbs(action_b)

        # 有一个共同动词
        if verbs_a & verbs_b:
            return True

        # 名词重叠
        nouns_a = self._extract_nouns(action_a)
        nouns_b = self._extract_nouns(action_b)
        if nouns_a & nouns_b:
            return True

        return False

    def _extract_verbs(self, text: str) -> set:
        """简单提取动词"""
        verbs = set()
        verb_keywords = {
            "完成", "进行", "开展", "执行", "落实", "实施",
            "记录", "登记", "报告", "提交", "上传", "报送",
            "审核", "审批", "批准", "确认", "核查", "检查",
            "评估", "评价", "分析", "总结", "汇报",
        }
        for kw in verb_keywords:
            if kw in text:
                verbs.add(kw)
        return verbs

    def _extract_nouns(self, text: str) -> set:
        """简单提取名词"""
        nouns = set()
        noun_keywords = {
            "病历", "处方", "医嘱", "报告", "单据", "资料",
            "费用", "结算", "报销", "检查", "检验", "手术",
            "治疗", "护理", "药品", "耗材", "设备",
        }
        for kw in noun_keywords:
            if kw in text:
                nouns.add(kw)
        return nouns


class PriorityConflictDetector:
    """优先级冲突检测器

    检测同级规则对同一事项要求不同优先级
    """

    def detect(
        self,
        triple_a: RuleTriple,
        triple_b: RuleTriple,
    ) -> Optional[Conflict]:
        """检测两条规则是否存在优先级冲突

        Args:
            triple_a: 规则三元组A
            triple_b: 规则三元组B

        Returns:
            Conflict 对象或 None（无冲突）
        """
        # 必须主体、动作都重叠
        if not self._is_same_requirement(triple_a, triple_b):
            return None

        # 检查是否为同一来源
        if triple_a.source != triple_b.source:
            return None

        # 检查条件是否相同
        if triple_a.condition != triple_b.condition:
            return None

        # 同一来源的同一事项有两种互相矛盾的要求
        if triple_a.rule_type != triple_b.rule_type:
            return Conflict(
                conflict_type=ConflictType.PRIORITY_CONFLICT,
                triple_a=triple_a,
                triple_b=triple_b,
                confidence=0.95,
                description=(
                    f"优先级冲突：同一来源「{triple_a.source}」的同一事项，"
                    f"同时存在「{triple_a.rule_type}」和「{triple_b.rule_type}」两种不同要求，"
                    f"条款：{triple_a.clause_id} vs {triple_b.clause_id}。"
                ),
                suggestion=(
                    f"建议修订条款，明确何者优先。"
                    f"若「{triple_a.rule_type}」为正确解释，应修改「{triple_b.rule_type}」条款；"
                    f"反之亦然。"
                ),
            )

        return None

    def _is_same_requirement(
        self, triple_a: RuleTriple, triple_b: RuleTriple
    ) -> bool:
        """判断是否为同一要求事项"""
        # 主体相同
        if triple_a.subject != triple_b.subject:
            return False

        # 动作相似
        if triple_a.action != triple_b.action:
            # 检查核心动词
            verbs_a = self._extract_verbs_from_text(triple_a.action)
            verbs_b = self._extract_verbs_from_text(triple_b.action)
            if not verbs_a & verbs_b:
                return False

        return True

    @staticmethod
    def _extract_verbs_from_text(text: str) -> set:
        """从文本中提取动词（静态方法，供 PriorityConflictDetector 使用）"""
        verbs = set()
        verb_keywords = {
            "完成", "进行", "开展", "执行", "落实", "实施",
            "记录", "登记", "报告", "提交", "上传", "报送",
            "审核", "审批", "批准", "确认", "核查", "检查",
            "评估", "评价", "分析", "总结", "汇报",
        }
        for kw in verb_keywords:
            if kw in text:
                verbs.add(kw)
        return verbs


class ConflictDetector:
    """冲突检测主引擎

    整合所有冲突检测器，对规则三元组进行全量冲突检测
    """

    def __init__(self, priority_rules: Optional[dict] = None):
        """初始化冲突检测引擎

        Args:
            priority_rules: 自定义优先级规则，格式为 {RuleSourceType: priority_value}
        """
        self.temporal_detector = TemporalConflictDetector()
        self.action_detector = ActionConflictDetector()
        self.scope_detector = ScopeOverlapDetector()
        self.priority_detector = PriorityConflictDetector()

        # 优先级配置
        if priority_rules:
            self.priority_rules = priority_rules
        else:
            self.priority_rules = DEFAULT_PRIORITY.copy()

    def detect_conflicts(
        self,
        triples: list[RuleTriple],
        threshold: float = 0.5,
    ) -> ConflictReport:
        """检测规则三元组之间的冲突

        Args:
            triples: 规则三元组列表
            threshold: 冲突置信度阈值，低于此值的冲突将被忽略

        Returns:
            ConflictReport 冲突检测报告
        """
        report = ConflictReport()

        # 两两比对所有三元组
        for i in range(len(triples)):
            for j in range(i + 1, len(triples)):
                triple_a = triples[i]
                triple_b = triples[j]

                # 时序冲突检测
                temporal_conflict = self.temporal_detector.detect(triple_a, triple_b)
                if temporal_conflict and temporal_conflict.confidence >= threshold:
                    report.add_conflict(temporal_conflict)

                # 动作冲突检测
                action_conflict = self.action_detector.detect(triple_a, triple_b)
                if action_conflict and action_conflict.confidence >= threshold:
                    report.add_conflict(action_conflict)

                # 范围重叠检测
                scope_conflict = self.scope_detector.detect(triple_a, triple_b)
                if scope_conflict and scope_conflict.confidence >= threshold:
                    report.add_conflict(scope_conflict)

                # 优先级冲突检测
                priority_conflict = self.priority_detector.detect(triple_a, triple_b)
                if priority_conflict and priority_conflict.confidence >= threshold:
                    report.add_conflict(priority_conflict)

        return report

    def get_priority(self, source: RuleSourceType) -> int:
        """获取某来源规则的优先级"""
        return self.priority_rules.get(source, 0)


def detect_conflicts(
    triples: list[RuleTriple],
    threshold: float = 0.5,
) -> ConflictReport:
    """冲突检测统一入口

    Args:
        triples: 规则三元组列表
        threshold: 冲突置信度阈值

    Returns:
        ConflictReport 冲突检测报告
    """
    engine = ConflictDetector()
    return engine.detect_conflicts(triples, threshold)


if __name__ == "__main__":
    # 简单测试
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

    print("=== 测试冲突检测引擎 ===\n")

    report = detect_conflicts(sample_triples)

    print(f"检测到 {len(report.conflicts)} 个冲突：\n")

    for i, conflict in enumerate(report.conflicts, 1):
        print(f"冲突 {i}：{conflict.conflict_type.value}")
        print(f"  置信度：{conflict.confidence}")
        print(f"  描述：{conflict.description}")
        print(f"  建议：{conflict.suggestion}")
        print()