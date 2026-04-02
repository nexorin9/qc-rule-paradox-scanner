# 质控规则冲突扫描器

自动扫描医院多套质控规则体系（等级评审标准、院内质控规范、医保规则）之间的逻辑冲突，生成冲突图谱和优先级消解建议。

## 功能特性

- **多格式支持**：支持读取 TXT、DOCX、PDF、Markdown 格式的规则文档
- **三元组提取**：使用 LLM 将条款文本提取为结构化三元组（对象+条件+动作）
- **冲突检测**：检测时序互斥、动作矛盾、范围重叠等多种冲突类型
- **优先级消解**：基于规则来源自动生成冲突优先级消解建议
- **双模式输出**：支持 CLI 和 HTML 两种输出模式
- **降级策略**：无 API Key 时可使用本地规则引擎+关键词匹配

## 安装

```bash
pip install -r requirements.txt
```

## 配置

复制 `.env.example` 为 `.env`，填入您的 API Key：

```bash
cp .env.example .env
```

编辑 `.env`：

```
OPENAI_API_KEY=your_api_key_here
OPENAI_BASE_URL=https://api.openai.com/v1  # 可选，自定义 API 地址
MODEL_NAME=gpt-4  # 可选，默认 gpt-4
```

如不使用 LLM，可使用 `--force-local` 参数强制本地规则引擎：

```bash
qc-scan --force-local --standards data/standards_sample.txt --hospital data/hospital_rules_sample.txt --insurance data/insurance_rules_sample.txt --output output/
```

## 使用方法

### 基本用法

```bash
# 扫描三套规则体系
qc-scan --standards data/standards_sample.txt --hospital data/hospital_rules_sample.txt --insurance data/insurance_rules_sample.txt --output output/

# 指定输出格式
qc-scan --format html --standards data/standards_sample.txt --hospital data/hospital_rules_sample.txt --insurance data/insurance_rules_sample.txt --output output/

# 调整冲突置信度阈值
qc-scan --threshold 0.8 --standards data/standards_sample.txt --hospital data/hospital_rules_sample.txt --insurance data/insurance_rules_sample.txt --output output/

# 仅使用本地规则引擎（无需 API Key）
qc-scan --force-local --standards data/standards_sample.txt --hospital data/hospital_rules_sample.txt --insurance data/insurance_rules_sample.txt --output output/

# 使用通用输入（自动识别来源类型）
qc-scan -i data/standards_sample.txt -i data/hospital_rules_sample.txt -o output/

# 指定并发数和批量大小
qc-scan --standards data/standards_sample.txt --workers 8 --batch-size 20 -o output/

# 检查 API 配置是否正确
qc-scan check-api
qc-scan check-api -v
```

### 参数说明

| 参数 | 说明 |
|------|------|
| `--standards` | 等级评审标准文件路径 |
| `--hospital` | 院内质控规范文件路径 |
| `--insurance` | 医保规则文件路径 |
| `--output` | 输出目录路径 |
| `--format` | 输出格式：`html`（默认）、`json`、`markdown` |
| `--threshold` | 冲突置信度阈值（0-1），默认 0.5 |
| `--force-local` | 强制使用本地规则引擎（不调用 LLM） |
| `--verbose` | 显示详细处理进度 |
| `--workers` | 并发处理的最大工作线程数（默认 4） |
| `--batch-size` | LLM 批量提取的条款数（默认 10） |
| `--version` | 显示版本信息 |
| `--help` | 显示帮助信息 |

## 输出说明

### HTML 报告

HTML 报告包含以下部分：

1. **报告摘要**：冲突总数、各类型分布、风险评级
2. **冲突图谱**：规则-冲突网络图，可点击节点查看详情
3. **冲突列表**：按类型分组，标注来源条款
4. **消解建议**：优先级消解建议和修改方向

### JSON 输出

```json
{
  "summary": {
    "total_conflicts": 5,
    "by_type": {
      "TEMPORAL_CONFLICT": 2,
      "ACTION_CONFLICT": 1,
      "SCOPE_OVERLAP": 2
    },
    "risk_level": "中"
  },
  "conflicts": [...],
  "suggestions": [...]
}
```

## 规则格式说明

支持以下输入格式：

- **TXT**：纯文本，按段落分割
- **DOCX**：Word 文档，提取正文内容
- **PDF**：PDF 文档，提取文本内容
- **Markdown**：Markdown 文档，按标题和段落分割

规则条款建议包含：
- 条款编号
- 条款标题
- 具体要求（对象、条件、动作）

## 降级模式说明

当无法使用 LLM 时，工具提供两种本地规则引擎模式：

1. **`--no-llm`**：仅使用规则引擎+关键词匹配提取三元组，不调用 LLM
2. **`--force-local`**：强制使用本地规则引擎（与 `--no-llm` 等效）

本地模式适用于：
- 无 API Key 或 API 额度用尽时
- 快速测试规则文档
- 简单规则文档的初步扫描

注意：本地模式提取精度可能低于 LLM 模式，建议对重要规则使用 LLM 模式。

## 优先级规则

默认优先级（可配置）：
1. 卫健委标准（最高）
2. 院内规范
3. 医保规则（最低）

## 技术架构

- **规则读取**：python-docx、pdfplumber
- **文本处理**：jieba 分词
- **LLM 提取**：OpenAI API / Anthropic API 兼容
- **CLI**：Typer、Rich
- **报告生成**：Jinja2、Plotly

## 项目结构

```
qc-rule-paradox-scanner/
├── data/               # 示例规则文档
├── templates/          # HTML 报告模板
├── .gitignore
├── .env.example
├── README.md
├── requirements.txt
└── qc_rule_paradox_scanner/
    ├── __init__.py
    ├── cli.py
    ├── readers.py
    ├── preprocessor.py
    ├── extractor.py
    ├── detector.py
    ├── resolver.py
    ├── reporter.py
    └── config.py
```

## 适用场景

- 等级评审材料准备阶段的自查
- 质控办梳理院内规则与上级要求的冲突
- 医保办对规则歧义的预检
- 信息科集成多套规则时的冲突预警

---

## 支持作者

如果您觉得这个项目对您有帮助，欢迎打赏支持！
Wechat:gdgdmp
![Buy Me a Coffee](buymeacoffee.png)

**Buy me a coffee (crypto)**

| 币种 | 地址 |
|------|------|
| BTC | `bc1qc0f5tv577z7yt59tw8sqaq3tey98xehy32frzd` |
| ETH / USDT | `0x3b7b6c47491e4778157f0756102f134d05070704` |
| SOL | `6Xuk373zc6x6XWcAAuqvbWW92zabJdCmN3CSwpsVM6sd` |
