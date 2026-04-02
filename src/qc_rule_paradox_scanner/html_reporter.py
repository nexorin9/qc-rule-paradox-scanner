"""HTML 报告生成器

使用 Jinja2 模板生成可视化 HTML 冲突图谱报告
"""

import json
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .conflict_detector import ConflictReport, Conflict, ConflictType
from .priority_resolver import PriorityResolver, PRIORITY_LABELS


# 风险评级配置
RISK_RATINGS = {
    "high": {"label": "高风险", "color": "#dc3545", "icon": "⚠️"},
    "medium": {"label": "中等风险", "color": "#fd7e14", "icon": "⚡"},
    "low": {"label": "低风险", "color": "#28a745", "icon": "ℹ️"},
}


def get_risk_rating(confidence: float, conflict_type: ConflictType) -> dict:
    """根据置信度和冲突类型计算风险等级"""
    if conflict_type == ConflictType.PRIORITY_CONFLICT:
        # 优先级冲突通常是同来源内部矛盾，风险较高
        base_risk = confidence
    else:
        base_risk = confidence

    if base_risk >= 0.8:
        return RISK_RATINGS["high"]
    elif base_risk >= 0.6:
        return RISK_RATINGS["medium"]
    else:
        return RISK_RATINGS["low"]


def conflict_to_dict(conflict: Conflict, index: int) -> dict:
    """将 Conflict 对象转换为字典格式（用于 JSON 序列化）"""
    risk = get_risk_rating(conflict.confidence, conflict.conflict_type)

    # 生成稳定的冲突ID：基于条款ID和类型
    conflict_id = f"conflict_{index}_{conflict.triple_a.clause_id}_{conflict.triple_b.clause_id}_{conflict.conflict_type.name}"

    return {
        "id": conflict_id,
        "index": index,
        "type": conflict.conflict_type.value,
        "type_key": conflict.conflict_type.name,
        "confidence": conflict.confidence,
        "confidence_pct": f"{conflict.confidence * 100:.0f}%",
        "description": conflict.description,
        "suggestion": conflict.suggestion,
        "risk_label": risk["label"],
        "risk_color": risk["color"],
        "risk_icon": risk["icon"],
        "triple_a": {
            "subject": conflict.triple_a.subject,
            "condition": conflict.triple_a.condition,
            "action": conflict.triple_a.action,
            "rule_type": conflict.triple_a.rule_type,
            "source": conflict.triple_a.source,
            "clause_id": conflict.triple_a.clause_id,
        },
        "triple_b": {
            "subject": conflict.triple_b.subject,
            "condition": conflict.triple_b.condition,
            "action": conflict.triple_b.action,
            "rule_type": conflict.triple_b.rule_type,
            "source": conflict.triple_b.source,
            "clause_id": conflict.triple_b.clause_id,
        },
    }


def build_graph_data(report: ConflictReport) -> dict:
    """构建冲突图谱的节点和边数据（用于 vis.js）"""
    nodes = []
    edges = []
    node_ids = set()

    # 按来源分组添加节点
    sources = {}
    for conflict in report.conflicts:
        for triple in [conflict.triple_a, conflict.triple_b]:
            source = triple.source
            clause_id = triple.clause_id
            node_key = f"{source}:{clause_id}"

            if node_key not in node_ids:
                node_ids.add(node_key)
                node_color = {
                    "等级评审标准": "#0d6efd",
                    "院内质控规范": "#20c997",
                    "医保规则": "#6f42c1",
                    "未知来源": "#6c757d",
                }.get(source, "#6c757d")

                if source not in sources:
                    sources[source] = []
                sources[source].append({
                    "id": node_key,
                    "label": f"{clause_id}",
                    "source": source,
                    "clause_id": clause_id,
                    "subject": triple.subject,
                    "color": node_color,
                })

    # 添加节点到列表
    for source, items in sources.items():
        nodes.append({
            "id": f"group_{source}",
            "label": source,
            "isGroup": True,
            "color": {
                "等级评审标准": "#0d6efd",
                "院内质控规范": "#20c997",
                "医保规则": "#6f42c1",
                "未知来源": "#6c757d",
            }.get(source, "#6c757d"),
        })
        for item in items:
            nodes.append({
                **item,
                "group": f"group_{source}",
            })

    # 添加边（冲突关系）
    for idx, conflict in enumerate(report.conflicts):
        key_a = f"{conflict.triple_a.source}:{conflict.triple_a.clause_id}"
        key_b = f"{conflict.triple_b.source}:{conflict.triple_b.clause_id}"
        conflict_id = f"conflict_{idx}_{conflict.triple_a.clause_id}_{conflict.triple_b.clause_id}_{conflict.conflict_type.name}"

        edge_color = {
            ConflictType.TEMPORAL_CONFLICT: "#dc3545",
            ConflictType.ACTION_CONFLICT: "#fd7e14",
            ConflictType.SCOPE_OVERLAP: "#ffc107",
            ConflictType.PRIORITY_CONFLICT: "#dc3545",
        }.get(conflict.conflict_type, "#6c757d")

        edges.append({
            "from": key_a,
            "to": key_b,
            "color": edge_color,
            "conflict_type": conflict.conflict_type.value,
            "confidence": conflict.confidence,
            "arrows": "to",
            "conflict_id": conflict_id,
        })

    return {"nodes": nodes, "edges": edges}


class HTMLReporter:
    """HTML 报告生成器"""

    def __init__(self, template_dir: Optional[str] = None):
        """初始化报告生成器

        Args:
            template_dir: 模板目录路径，默认使用内置模板
        """
        if template_dir:
            self.env = Environment(
                loader=FileSystemLoader(template_dir),
                autoescape=select_autoescape(['html', 'xml']),
            )
        else:
            # 使用内置模板
            self.env = Environment(
                autoescape=select_autoescape(['html', 'xml']),
            )
            self._register_inline_template()

        self.env.filters["conflict_to_dict"] = conflict_to_dict

    def _register_inline_template(self):
        """注册内置 Jinja2 模板"""
        template_content = self._get_inline_template()
        self.env.template_string = template_content

    def _get_inline_template(self) -> str:
        """获取内置 HTML 模板"""
        return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>质控规则冲突检测报告</title>
    <script type="text/javascript" src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js"></script>
    <style>
        :root {
            --primary-color: #2563eb;
            --success-color: #16a34a;
            --warning-color: #ca8a04;
            --danger-color: #dc2626;
            --info-color: #0891b2;
            --gray-50: #f9fafb;
            --gray-100: #f3f4f6;
            --gray-200: #e5e7eb;
            --gray-300: #d1d5db;
            --gray-500: #6b7280;
            --gray-700: #374151;
            --gray-900: #111827;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
            color: var(--gray-900);
            background-color: var(--gray-50);
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }

        /* 头部样式 */
        .report-header {
            background: linear-gradient(135deg, var(--primary-color) 0%, #1d4ed8 100%);
            color: white;
            padding: 40px;
            border-radius: 12px;
            margin-bottom: 30px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }

        .report-header h1 {
            font-size: 2rem;
            font-weight: 600;
            margin-bottom: 8px;
        }

        .report-header .subtitle {
            opacity: 0.9;
            font-size: 1.1rem;
        }

        .report-header .timestamp {
            margin-top: 16px;
            font-size: 0.9rem;
            opacity: 0.8;
        }

        /* 工具栏 */
        .toolbar {
            display: flex;
            gap: 12px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }

        .export-btn {
            padding: 10px 20px;
            background: var(--primary-color);
            color: white;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.95rem;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            transition: all 0.2s;
        }

        .export-btn:hover {
            background: #1d4ed8;
            transform: translateY(-1px);
        }

        .export-btn:disabled {
            background: var(--gray-300);
            cursor: not-allowed;
            transform: none;
        }

        /* 摘要卡片 */
        .summary-section {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 16px;
            margin-bottom: 30px;
        }

        .summary-card {
            background: white;
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
            border-left: 4px solid var(--primary-color);
            transition: transform 0.2s;
        }

        .summary-card:hover {
            transform: translateY(-2px);
        }

        .summary-card.danger {
            border-left-color: var(--danger-color);
        }

        .summary-card.warning {
            border-left-color: var(--warning-color);
        }

        .summary-card.success {
            border-left-color: var(--success-color);
        }

        .summary-card.highlight {
            background: linear-gradient(135deg, #fef2f2 0%, #fff 100%);
        }

        .summary-card .card-value {
            font-size: 2.2rem;
            font-weight: 700;
            color: var(--gray-900);
            line-height: 1.2;
        }

        .summary-card .card-label {
            color: var(--gray-500);
            font-size: 0.9rem;
            margin-top: 4px;
        }

        .summary-card .card-trend {
            font-size: 0.8rem;
            margin-top: 8px;
            padding-top: 8px;
            border-top: 1px solid var(--gray-100);
        }

        .summary-card .card-trend.high {
            color: var(--danger-color);
        }

        .summary-card .card-trend.medium {
            color: var(--warning-color);
        }

        /* 风险分布条 */
        .risk-distribution {
            margin-top: 12px;
        }

        .risk-bar {
            height: 8px;
            border-radius: 4px;
            overflow: hidden;
            display: flex;
        }

        .risk-bar-segment {
            height: 100%;
            transition: width 0.3s;
        }

        .risk-bar-segment.high {
            background: var(--danger-color);
        }

        .risk-bar-segment.medium {
            background: var(--warning-color);
        }

        .risk-bar-segment.low {
            background: var(--success-color);
        }

        .risk-legend {
            display: flex;
            gap: 16px;
            margin-top: 8px;
            font-size: 0.8rem;
            color: var(--gray-500);
        }

        .risk-legend-item {
            display: flex;
            align-items: center;
            gap: 4px;
        }

        .risk-legend-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
        }

        /* 优先级说明 */
        .priority-legend {
            background: white;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 30px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        }

        .priority-legend h3 {
            font-size: 1.1rem;
            margin-bottom: 16px;
            color: var(--gray-700);
        }

        .priority-list {
            display: flex;
            gap: 24px;
            flex-wrap: wrap;
        }

        .priority-item {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .priority-dot {
            width: 12px;
            height: 12px;
            border-radius: 50%;
        }

        .priority-item .label {
            font-weight: 500;
        }

        .priority-item .value {
            color: var(--gray-500);
            font-size: 0.9rem;
        }

        /* 主内容区域 */
        .main-content {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 30px;
        }

        @media (max-width: 1024px) {
            .main-content {
                grid-template-columns: 1fr;
            }
        }

        /* 图谱区域 */
        .graph-section {
            background: white;
            border-radius: 10px;
            padding: 24px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        }

        .graph-section h2 {
            font-size: 1.2rem;
            margin-bottom: 16px;
            color: var(--gray-700);
        }

        #conflict-graph {
            width: 100%;
            height: 450px;
            border: 1px solid var(--gray-200);
            border-radius: 8px;
            background: var(--gray-50);
        }

        .graph-legend {
            display: flex;
            gap: 16px;
            flex-wrap: wrap;
            margin-top: 16px;
            padding-top: 16px;
            border-top: 1px solid var(--gray-200);
        }

        .graph-legend-item {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 0.85rem;
            color: var(--gray-600);
        }

        .graph-legend-line {
            width: 24px;
            height: 3px;
            border-radius: 2px;
        }

        /* 冲突列表 */
        .conflict-list-section {
            background: white;
            border-radius: 10px;
            padding: 24px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
            max-height: 600px;
            overflow-y: auto;
        }

        .conflict-list-section h2 {
            font-size: 1.2rem;
            margin-bottom: 16px;
            color: var(--gray-700);
        }

        /* 冲突卡片 */
        .conflict-card {
            border: 2px solid var(--gray-200);
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 16px;
            transition: all 0.2s;
        }

        .conflict-card:hover {
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }

        .conflict-card.highlighted {
            border-color: var(--primary-color);
            box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.2);
        }

        .conflict-card.faded {
            opacity: 0.4;
        }

        .conflict-card-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 12px;
        }

        .conflict-type {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            font-weight: 600;
            font-size: 0.95rem;
        }

        .conflict-type.temporal { color: #b91c1c; }
        .conflict-type.action { color: #b45309; }
        .conflict-type.scope { color: #a16207; }
        .conflict-type.priority { color: #7c3aed; }

        .conflict-confidence {
            font-size: 0.85rem;
            color: var(--gray-500);
        }

        .conflict-description {
            color: var(--gray-700);
            margin-bottom: 12px;
            font-size: 0.95rem;
            line-height: 1.5;
        }

        /* 规则对比 */
        .rule-comparison {
            display: grid;
            grid-template-columns: 1fr auto 1fr;
            gap: 12px;
            align-items: stretch;
            margin-bottom: 12px;
        }

        .rule-box {
            padding: 12px;
            border-radius: 6px;
            font-size: 0.9rem;
        }

        .rule-box.rule-a {
            background-color: #eff6ff;
            border: 1px solid #bfdbfe;
        }

        .rule-box.rule-b {
            background-color: #f0fdf4;
            border: 1px solid #bbf7d0;
        }

        .rule-box .rule-source {
            font-size: 0.8rem;
            color: var(--gray-500);
            margin-bottom: 4px;
        }

        .rule-box .rule-clause {
            font-weight: 600;
            margin-bottom: 6px;
        }

        .rule-box .rule-content {
            font-size: 0.85rem;
            line-height: 1.4;
        }

        .rule-box .rule-type {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 600;
            margin-top: 6px;
        }

        .rule-box .rule-type.require {
            background-color: #dbeafe;
            color: #1d4ed8;
        }

        .rule-box .rule-type.forbid {
            background-color: #fee2e2;
            color: #dc2626;
        }

        .rule-box .rule-type.suggest {
            background-color: #fef9c3;
            color: #a16207;
        }

        .vs-divider {
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            color: var(--gray-400);
            font-size: 0.9rem;
        }

        /* 消解建议 */
        .suggestion-box {
            background-color: #fffbeb;
            border: 1px solid #fde68a;
            border-radius: 6px;
            padding: 12px;
        }

        .suggestion-box h4 {
            font-size: 0.85rem;
            color: #92400e;
            margin-bottom: 6px;
        }

        .suggestion-box p {
            font-size: 0.9rem;
            color: #78350f;
            line-height: 1.5;
            white-space: pre-wrap;
        }

        /* 筛选器 */
        .filter-section {
            margin-bottom: 16px;
        }

        .filter-group {
            margin-bottom: 12px;
        }

        .filter-group:last-child {
            margin-bottom: 0;
        }

        .filter-row {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            align-items: center;
        }

        .filter-label {
            font-weight: 500;
            color: var(--gray-700);
            margin-right: 4px;
            font-size: 0.9rem;
        }

        .filter-btn {
            padding: 5px 12px;
            border: 1px solid var(--gray-300);
            border-radius: 6px;
            background: white;
            cursor: pointer;
            font-size: 0.85rem;
            transition: all 0.2s;
        }

        .filter-btn:hover {
            background: var(--gray-50);
        }

        .filter-btn.active {
            background: var(--primary-color);
            color: white;
            border-color: var(--primary-color);
        }

        /* 节点详情弹窗 */
        .node-tooltip {
            position: fixed;
            background: white;
            border: 1px solid var(--gray-200);
            border-radius: 8px;
            padding: 12px 16px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
            z-index: 1000;
            max-width: 280px;
            font-size: 0.9rem;
            display: none;
        }

        .node-tooltip.visible {
            display: block;
        }

        .node-tooltip h4 {
            font-size: 0.95rem;
            margin-bottom: 8px;
            color: var(--gray-700);
        }

        .node-tooltip p {
            margin: 4px 0;
            color: var(--gray-600);
            font-size: 0.85rem;
        }

        .node-tooltip .source-tag {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 600;
            margin-top: 6px;
        }

        /* 空状态 */
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: var(--gray-500);
        }

        .empty-state .icon {
            font-size: 3rem;
            margin-bottom: 16px;
        }

        .empty-state h3 {
            font-size: 1.2rem;
            margin-bottom: 8px;
            color: var(--gray-700);
        }

        /* 页脚 */
        .report-footer {
            text-align: center;
            padding: 30px;
            color: var(--gray-500);
            font-size: 0.9rem;
        }

        /* 响应式 */
        @media (max-width: 768px) {
            .container {
                padding: 12px;
            }

            .report-header {
                padding: 24px;
            }

            .report-header h1 {
                font-size: 1.5rem;
            }

            .rule-comparison {
                grid-template-columns: 1fr;
            }

            .vs-divider {
                padding: 8px 0;
            }

            .summary-section {
                grid-template-columns: repeat(2, 1fr);
            }
        }
    </style>
</head>
<body>
    <div class="container" id="report-content">
        <!-- 报告头部 -->
        <div class="report-header">
            <h1>🏥 质控规则冲突检测报告</h1>
            <p class="subtitle">自动扫描医院多套质控规则体系之间的逻辑冲突</p>
            <p class="timestamp">生成时间：{{ timestamp }}</p>
        </div>

        <!-- 工具栏 -->
        <div class="toolbar">
            <button class="export-btn" id="export-pdf-btn" onclick="exportToPDF()">
                📄 导出 PDF
            </button>
            <button class="export-btn" onclick="window.print()">
                🖨️ 打印报告
            </button>
        </div>

        <!-- 摘要卡片 -->
        <div class="summary-section">
            <div class="summary-card {% if summary.total > 0 %}danger{% else %}success{% endif %}">
                <div class="card-value">{{ summary.total }}</div>
                <div class="card-label">冲突总数</div>
                {% if summary.total > 0 %}
                <div class="card-trend high">⚠️ 需要关注</div>
                {% endif %}
            </div>
            <div class="summary-card {% if summary.temporal > 0 %}warning{% endif %}">
                <div class="card-value">{{ summary.temporal }}</div>
                <div class="card-label">时序互斥</div>
            </div>
            <div class="summary-card {% if summary.action > 0 %}warning{% endif %}">
                <div class="card-value">{{ summary.action }}</div>
                <div class="card-label">动作矛盾</div>
            </div>
            <div class="summary-card {% if summary.scope_overlap > 0 %}warning{% endif %}">
                <div class="card-value">{{ summary.scope_overlap }}</div>
                <div class="card-label">范围重叠</div>
            </div>
            <div class="summary-card {% if summary.priority > 0 %}danger{% endif %}">
                <div class="card-value">{{ summary.priority }}</div>
                <div class="card-label">优先级冲突</div>
            </div>
        </div>

        <!-- 风险分布 -->
        {% if conflicts %}
        <div class="summary-card" style="margin-bottom: 20px;">
            <div class="card-label">风险分布</div>
            <div class="risk-distribution">
                <div class="risk-bar">
                    <div class="risk-bar-segment high" id="risk-high-bar" style="width: 0%"></div>
                    <div class="risk-bar-segment medium" id="risk-medium-bar" style="width: 0%"></div>
                    <div class="risk-bar-segment low" id="risk-low-bar" style="width: 0%"></div>
                </div>
                <div class="risk-legend">
                    <div class="risk-legend-item">
                        <span class="risk-legend-dot" style="background: var(--danger-color);"></span>
                        <span>高风险 (<span id="high-count">0</span>)</span>
                    </div>
                    <div class="risk-legend-item">
                        <span class="risk-legend-dot" style="background: var(--warning-color);"></span>
                        <span>中风险 (<span id="medium-count">0</span>)</span>
                    </div>
                    <div class="risk-legend-item">
                        <span class="risk-legend-dot" style="background: var(--success-color);"></span>
                        <span>低风险 (<span id="low-count">0</span>)</span>
                    </div>
                </div>
            </div>
        </div>
        {% endif %}

        <!-- 优先级说明 -->
        <div class="priority-legend">
            <h3>📋 优先级规则（由高到低）</h3>
            <div class="priority-list">
                <div class="priority-item">
                    <span class="priority-dot" style="background: #0d6efd;"></span>
                    <span class="label">卫健委/等级评审标准</span>
                    <span class="value">（优先级 100）</span>
                </div>
                <div class="priority-item">
                    <span class="priority-dot" style="background: #20c997;"></span>
                    <span class="label">院内质控规范</span>
                    <span class="value">（优先级 50）</span>
                </div>
                <div class="priority-item">
                    <span class="priority-dot" style="background: #6f42c1;"></span>
                    <span class="label">医保规则</span>
                    <span class="value">（优先级 25）</span>
                </div>
            </div>
        </div>

        <!-- 主内容区域 -->
        {% if conflicts %}
        <div class="main-content">
            <!-- 图谱区域 -->
            <div class="graph-section">
                <h2>🔗 冲突关系图谱（点击节点查看详情）</h2>
                <div id="conflict-graph"></div>
                <div class="graph-legend">
                    <div class="graph-legend-item">
                        <span class="graph-legend-line" style="background: #dc3545;"></span>
                        <span>时序互斥</span>
                    </div>
                    <div class="graph-legend-item">
                        <span class="graph-legend-line" style="background: #fd7e14;"></span>
                        <span>动作矛盾</span>
                    </div>
                    <div class="graph-legend-item">
                        <span class="graph-legend-line" style="background: #ffc107;"></span>
                        <span>范围重叠</span>
                    </div>
                    <div class="graph-legend-item">
                        <span class="graph-legend-line" style="background: #dc3545; border-style: dashed;"></span>
                        <span>优先级冲突</span>
                    </div>
                </div>
            </div>

            <!-- 冲突列表 -->
            <div class="conflict-list-section">
                <h2>📋 冲突详情列表</h2>

                <!-- 筛选器 -->
                <div class="filter-section">
                    <div class="filter-group">
                        <div class="filter-row">
                            <span class="filter-label">类型：</span>
                            <button class="filter-btn active" data-filter="all" data-filter-type="type">全部</button>
                            <button class="filter-btn" data-filter="temporal" data-filter-type="type">时序互斥</button>
                            <button class="filter-btn" data-filter="action" data-filter-type="type">动作矛盾</button>
                            <button class="filter-btn" data-filter="scope" data-filter-type="type">范围重叠</button>
                            <button class="filter-btn" data-filter="priority" data-filter-type="type">优先级冲突</button>
                        </div>
                    </div>
                    <div class="filter-group">
                        <div class="filter-row">
                            <span class="filter-label">来源：</span>
                            <button class="filter-btn active" data-filter="all" data-filter-type="source">全部</button>
                            <button class="filter-btn" data-filter="等级评审标准" data-filter-type="source">等级评审标准</button>
                            <button class="filter-btn" data-filter="院内质控规范" data-filter-type="source">院内质控规范</button>
                            <button class="filter-btn" data-filter="医保规则" data-filter-type="source">医保规则</button>
                        </div>
                    </div>
                </div>

                <div id="conflict-list">
                    {% for conflict in conflicts %}
                    <div class="conflict-card"
                         data-id="{{ conflict.id }}"
                         data-type="{{ conflict.type_key|lower }}"
                         data-source-a="{{ conflict.triple_a.source }}"
                         data-source-b="{{ conflict.triple_b.source }}">
                        <div class="conflict-card-header">
                            <span class="conflict-type {{ conflict.type_key|lower }}">
                                {{ conflict.type }}
                            </span>
                            <div style="display: flex; align-items: center; gap: 8px;">
                                <span class="risk-badge {% if conflict.confidence >= 0.8 %}high{% elif conflict.confidence >= 0.6 %}medium{% else %}low{% endif %}">
                                    {% if conflict.confidence >= 0.8 %}⚠️{% elif conflict.confidence >= 0.6 %}⚡{% else %}ℹ️{% endif %}
                                    {{ conflict.risk_label }}
                                </span>
                                <span class="conflict-confidence">{{ conflict.confidence_pct }}</span>
                            </div>
                        </div>

                        <p class="conflict-description">{{ conflict.description }}</p>

                        <div class="rule-comparison">
                            <div class="rule-box rule-a">
                                <div class="rule-source">{{ conflict.triple_a.source }}</div>
                                <div class="rule-clause">{{ conflict.triple_a.clause_id }}</div>
                                <div class="rule-content">
                                    {{ conflict.triple_a.subject }}在{{ conflict.triple_a.condition }}条件下{{ conflict.triple_a.action }}
                                </div>
                                <span class="rule-type {% if conflict.triple_a.rule_type == '要求' %}require{% elif conflict.triple_a.rule_type == '禁止' %}forbid{% else %}suggest{% endif %}">
                                    {{ conflict.triple_a.rule_type }}
                                </span>
                            </div>

                            <div class="vs-divider">VS</div>

                            <div class="rule-box rule-b">
                                <div class="rule-source">{{ conflict.triple_b.source }}</div>
                                <div class="rule-clause">{{ conflict.triple_b.clause_id }}</div>
                                <div class="rule-content">
                                    {{ conflict.triple_b.subject }}在{{ conflict.triple_b.condition }}条件下{{ conflict.triple_b.action }}
                                </div>
                                <span class="rule-type {% if conflict.triple_b.rule_type == '要求' %}require{% elif conflict.triple_b.rule_type == '禁止' %}forbid{% else %}suggest{% endif %}">
                                    {{ conflict.triple_b.rule_type }}
                                </span>
                            </div>
                        </div>

                        <div class="suggestion-box">
                            <h4>💡 消解建议</h4>
                            <p>{{ conflict.suggestion }}</p>
                        </div>
                    </div>
                    {% endfor %}
                </div>
            </div>
        </div>
        {% else %}
        <!-- 空状态 -->
        <div class="empty-state">
            <div class="icon">✅</div>
            <h3>未检测到冲突</h3>
            <p>恭喜！您导入的规则文档之间不存在逻辑冲突。</p>
        </div>
        {% endif %}

        <!-- 页脚 -->
        <div class="report-footer">
            <p>质控规则冲突扫描器 v0.1.0 | 自动生成</p>
        </div>
    </div>

    <!-- 节点详情弹窗 -->
    <div class="node-tooltip" id="node-tooltip">
        <h4 id="tooltip-title">条款详情</h4>
        <p id="tooltip-clause"></p>
        <p id="tooltip-subject"></p>
        <p id="tooltip-action"></p>
        <span class="source-tag" id="tooltip-source"></span>
    </div>

    <script type="text/javascript">
        var network = null;

        // 初始化风险分布
        function initRiskDistribution() {
            var cards = document.querySelectorAll('.conflict-card');
            var highCount = 0, mediumCount = 0, lowCount = 0;

            cards.forEach(function(card) {
                var badge = card.querySelector('.risk-badge');
                if (badge.classList.contains('high')) highCount++;
                else if (badge.classList.contains('medium')) mediumCount++;
                else lowCount++;
            });

            var total = highCount + mediumCount + lowCount;
            if (total > 0) {
                document.getElementById('risk-high-bar').style.width = (highCount / total * 100) + '%';
                document.getElementById('risk-medium-bar').style.width = (mediumCount / total * 100) + '%';
                document.getElementById('risk-low-bar').style.width = (lowCount / total * 100) + '%';
            }

            document.getElementById('high-count').textContent = highCount;
            document.getElementById('medium-count').textContent = mediumCount;
            document.getElementById('low-count').textContent = lowCount;
        }

        // 初始化图谱
        function initGraph() {
            {% if graph_data.nodes %}
            var nodes = new vis.DataSet({{ graph_data.nodes | tojson | safe }});
            var edges = new vis.DataSet({{ graph_data.edges | tojson | safe }});

            var container = document.getElementById('conflict-graph');

            var data = {
                nodes: nodes,
                edges: edges
            };

            var options = {
                nodes: {
                    shape: 'dot',
                    size: 14,
                    font: {
                        size: 11,
                        color: '#374151'
                    },
                    borderWidth: 2,
                    shadow: true
                },
                edges: {
                    width: 2,
                    shadow: true,
                    smooth: {
                        type: 'continuous'
                    }
                },
                groups: {
                    {% for source in ["等级评审标准", "院内质控规范", "医保规则", "未知来源"] %}
                    'group_{{ source }}': {
                        color: {
                            background: {
                                {% if source == "等级评审标准" %}'#dbeafe'{% elif source == "院内质控规范" %}'#d1fae5'{% elif source == "医保规则" %}'#e9d5ff'{% else %}'#f3f4f6'{% endif %}
                            },
                            border: {
                                {% if source == "等级评审标准" %}'#0d6efd'{% elif source == "院内质控规范" %}'#20c997'{% elif source == "医保规则" %}'#6f42c1'{% else %}'#6c757d'{% endif %}
                            }
                        }
                    },
                    {% endfor %}
                },
                physics: {
                    enabled: true,
                    solver: 'repulsion',
                    repulsion: {
                        nodeDistance: 180,
                        centralGravity: 0.5
                    },
                    stabilization: {
                        iterations: 100
                    }
                },
                interaction: {
                    hover: true,
                    tooltipDelay: 200
                }
            };

            network = new vis.Network(container, data, options);

            // 节点点击事件 - 高亮相关冲突卡片并显示详情
            network.on('click', function(params) {
                var cards = document.querySelectorAll('.conflict-card');
                var tooltip = document.getElementById('node-tooltip');

                // 重置所有卡片
                cards.forEach(function(card) {
                    card.classList.remove('highlighted', 'faded');
                });
                tooltip.classList.remove('visible');

                if (params.nodes.length > 0) {
                    var nodeId = params.nodes[0];
                    var node = nodes.get(nodeId);

                    if (node && !node.isGroup) {
                        // 查找相关的边
                        var relatedEdges = edges.get({
                            filter: function(edge) {
                                return edge.from === nodeId || edge.to === nodeId;
                            }
                        });

                        // 收集相关的冲突ID
                        var relatedConflictIds = [];
                        relatedEdges.forEach(function(edge) {
                            if (edge.conflict_id) {
                                relatedConflictIds.push(edge.conflict_id);
                            }
                        });

                        // 高亮相关卡片，模糊其他卡片
                        cards.forEach(function(card) {
                            var cardId = card.getAttribute('data-id');
                            if (relatedConflictIds.includes(cardId)) {
                                card.classList.add('highlighted');
                                card.classList.remove('faded');
                            } else {
                                card.classList.add('faded');
                                card.classList.remove('highlighted');
                            }
                        });

                        // 滚动到第一个相关卡片
                        var firstMatch = document.querySelector('.conflict-card.highlighted');
                        if (firstMatch) {
                            firstMatch.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        }

                        // 显示节点详情
                        showNodeTooltip(node, params.event);
                    }
                }
            });

            // 鼠标悬停显示节点标签
            network.on('hoverNode', function(params) {
                var node = nodes.get(params.node);
                if (node && !node.isGroup && node.clause_id) {
                    container.style.cursor = 'pointer';
                }
            });

            network.on('blurNode', function(params) {
                container.style.cursor = 'default';
            });
            {% endif %}
        }

        // 显示节点详情弹窗
        function showNodeTooltip(node, event) {
            var tooltip = document.getElementById('node-tooltip');
            var title = document.getElementById('tooltip-title');
            var clause = document.getElementById('tooltip-clause');
            var subject = document.getElementById('tooltip-subject');
            var action = document.getElementById('tooltip-action');
            var source = document.getElementById('tooltip-source');

            if (node.clause_id) {
                title.textContent = '条款: ' + node.clause_id;
                clause.textContent = '来源: ' + (node.source || '未知');
                subject.textContent = '对象: ' + (node.subject || '通用');
                action.textContent = '完整内容已在上方卡片展示';
                action.style.fontStyle = 'italic';

                // 设置来源标签颜色
                var sourceColors = {
                    '等级评审标准': 'background: #dbeafe; color: #1d4ed8;',
                    '院内质控规范': 'background: #d1fae5; color: #047857;',
                    '医保规则': 'background: #e9d5ff; color: #6b21a8;',
                    '未知来源': 'background: #f3f4f6; color: #6b7280;'
                };
                source.style.cssText = sourceColors[node.source] || sourceColors['未知来源'];
                source.textContent = node.source || '未知来源';

                // 定位弹窗
                tooltip.style.left = (event.center.x + 15) + 'px';
                tooltip.style.top = (event.center.y + 15) + 'px';
                tooltip.classList.add('visible');
            }
        }

        // 筛选功能
        function initFilters() {
            var typeFilterBtns = document.querySelectorAll('[data-filter-type="type"]');
            var sourceFilterBtns = document.querySelectorAll('[data-filter-type="source"]');
            var cards = document.querySelectorAll('.conflict-card');

            var currentTypeFilter = 'all';
            var currentSourceFilter = 'all';

            function applyFilters() {
                cards.forEach(function(card) {
                    var typeMatch = currentTypeFilter === 'all' || card.getAttribute('data-type') === currentTypeFilter;
                    var sourceA = card.getAttribute('data-source-a');
                    var sourceB = card.getAttribute('data-source-b');
                    var sourceMatch = currentSourceFilter === 'all' || sourceA === currentSourceFilter || sourceB === currentSourceFilter;

                    if (typeMatch && sourceMatch) {
                        card.style.display = 'block';
                    } else {
                        card.style.display = 'none';
                    }
                });
            }

            typeFilterBtns.forEach(function(btn) {
                btn.addEventListener('click', function() {
                    typeFilterBtns.forEach(function(b) { b.classList.remove('active'); });
                    this.classList.add('active');
                    currentTypeFilter = this.getAttribute('data-filter');
                    applyFilters();
                });
            });

            sourceFilterBtns.forEach(function(btn) {
                btn.addEventListener('click', function() {
                    sourceFilterBtns.forEach(function(b) { b.classList.remove('active'); });
                    this.classList.add('active');
                    currentSourceFilter = this.getAttribute('data-filter');
                    applyFilters();
                });
            });
        }

        // PDF导出功能
        function exportToPDF() {
            var btn = document.getElementById('export-pdf-btn');
            btn.disabled = true;
            btn.textContent = '正在生成...';

            var reportContent = document.getElementById('report-content');
            var graphContainer = document.getElementById('conflict-graph');

            // 临时隐藏图谱区域以提高性能
            var originalHeight = graphContainer.style.height;
            graphContainer.style.height = '0px';

            html2canvas(reportContent, {
                scale: 2,
                useCORS: true,
                logging: false,
                backgroundColor: '#f9fafb'
            }).then(function(canvas) {
                graphContainer.style.height = originalHeight;

                var imgData = canvas.toDataURL('image/png');
                var pdf = new jspdf.jsPDF('p', 'mm', 'a4');
                var imgWidth = 210;
                var pageHeight = 297;
                var imgHeight = (canvas.height * imgWidth) / canvas.width;
                var heightLeft = imgHeight;
                var position = 0;

                pdf.addImage(imgData, 'PNG', 0, position, imgWidth, imgHeight);
                heightLeft -= pageHeight;

                while (heightLeft >= 0) {
                    position = heightLeft - imgHeight;
                    pdf.addPage();
                    pdf.addImage(imgData, 'PNG', 0, position, imgWidth, imgHeight);
                    heightLeft -= pageHeight;
                }

                pdf.save('质控规则冲突检测报告_' + new Date().toISOString().slice(0,10) + '.pdf');
                btn.disabled = false;
                btn.textContent = '📄 导出 PDF';
            }).catch(function(err) {
                graphContainer.style.height = originalHeight;
                btn.disabled = false;
                btn.textContent = '📄 导出 PDF';
                alert('PDF导出失败: ' + err.message);
            });
        }

        // 页面加载完成后初始化
        document.addEventListener('DOMContentLoaded', function() {
            initRiskDistribution();
            initGraph();
            initFilters();
        });
    </script>
</body>
</html>
'''

        self.env.template_string = template_content

    def render(self, report: ConflictReport, output_path: str) -> str:
        """生成 HTML 报告

        Args:
            report: ConflictReport 对象
            output_path: 输出文件路径

        Returns:
            生成的 HTML 文件路径
        """
        from datetime import datetime

        summary = report.get_summary()
        conflicts = [conflict_to_dict(c, i) for i, c in enumerate(report.conflicts)]
        graph_data = build_graph_data(report)

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 准备冲突数据用于 JSON 序列化
        conflicts_json = json.dumps(conflicts, ensure_ascii=False)
        graph_data_json = json.dumps(graph_data, ensure_ascii=False)

        # 使用模板渲染
        if hasattr(self.env, 'template_string'):
            template = self.env.from_string(self.env.template_string)
        else:
            template = self.env.get_template('report.html')

        html_content = template.render(
            summary=summary,
            conflicts=conflicts,
            graph_data=graph_data,
            timestamp=timestamp,
            conflicts_json=conflicts_json,
            graph_data_json=graph_data_json,
        )

        # 写入文件
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)

        return str(output_file)


def generate_html_report(
    report: ConflictReport,
    output_path: str,
    template_dir: Optional[str] = None,
) -> str:
    """生成 HTML 报告的快捷函数

    Args:
        report: ConflictReport 对象
        output_path: 输出文件路径
        template_dir: 模板目录（可选）

    Returns:
        生成的 HTML 文件路径
    """
    reporter = HTMLReporter(template_dir)
    return reporter.render(report, output_path)


if __name__ == "__main__":
    # 简单测试
    from conflict_detector import Conflict, ConflictType, ConflictReport
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
    ]

    # 创建冲突报告
    report = ConflictReport()
    conflict = Conflict(
        conflict_type=ConflictType.ACTION_CONFLICT,
        triple_a=sample_triples[0],
        triple_b=sample_triples[1],
        confidence=0.85,
        description="动作矛盾：规则A要求核对患者身份，规则B禁止开具空白处方",
        suggestion="建议明确执行顺序和适用范围",
    )
    report.add_conflict(conflict)

    # 生成 HTML 报告
    output_path = "test_report.html"
    result_path = generate_html_report(report, output_path)
    print(f"HTML 报告已生成: {result_path}")