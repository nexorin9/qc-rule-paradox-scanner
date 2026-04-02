# QC Rule Paradox Scanner

Automatically scans for logical conflicts between multiple hospital quality control rule systems (hospital grade review standards, internal QC regulations, and insurance rules), generating conflict graphs and priority resolution suggestions.

## Features

- **Multi-format Support**: Reads TXT, DOCX, PDF, and Markdown rule documents
- **Triple Extraction**: Uses LLM to extract structured triples (subject + condition + action) from clause text
- **Conflict Detection**: Detects various conflict types including temporal mutual exclusion, action contradictions, and scope overlaps
- **Priority Resolution**: Automatically generates conflict priority resolution suggestions based on rule source
- **Dual Output Modes**: Supports both CLI and HTML output modes
- **Fallback Strategy**: Uses local rule engine + keyword matching when no API Key is available

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

Copy `.env.example` to `.env` and fill in your API Key:

```bash
cp .env.example .env
```

Edit `.env`:

```
OPENAI_API_KEY=your_api_key_here
OPENAI_BASE_URL=https://api.openai.com/v1  # Optional, custom API endpoint
MODEL_NAME=gpt-4  # Optional, defaults to gpt-4
```

To use without LLM, you can force the local rule engine with the `--force-local` flag:

```bash
qc-scan --force-local --standards data/standards_sample.txt --hospital data/hospital_rules_sample.txt --insurance data/insurance_rules_sample.txt --output output/
```

## Usage

### Basic Usage

```bash
# Scan three rule systems
qc-scan --standards data/standards_sample.txt --hospital data/hospital_rules_sample.txt --insurance data/insurance_rules_sample.txt --output output/

# Specify output format
qc-scan --format html --standards data/standards_sample.txt --hospital data/hospital_rules_sample.txt --insurance data/insurance_rules_sample.txt --output output/

# Adjust conflict confidence threshold
qc-scan --threshold 0.8 --standards data/standards_sample.txt --hospital data/hospital_rules_sample.txt --insurance data/insurance_rules_sample.txt --output output/

# Use local rule engine only (no API Key required)
qc-scan --force-local --standards data/standards_sample.txt --hospital data/hospital_rules_sample.txt --insurance data/insurance_rules_sample.txt --output output/

# Use generic input (auto-detect source type)
qc-scan -i data/standards_sample.txt -i data/hospital_rules_sample.txt -o output/

# Specify concurrency and batch size
qc-scan --standards data/standards_sample.txt --workers 8 --batch-size 20 -o output/

# Check if API configuration is correct
qc-scan check-api
qc-scan check-api -v
```

### Parameter Reference

| Parameter | Description |
|-----------|-------------|
| `--standards` | Hospital grade review standards file path |
| `--hospital` | Internal QC regulations file path |
| `--insurance` | Insurance rules file path |
| `--output` | Output directory path |
| `--format` | Output format: `html` (default), `json`, `markdown` |
| `--threshold` | Conflict confidence threshold (0-1), default 0.5 |
| `--force-local` | Force use of local rule engine (no LLM calls) |
| `--verbose` | Show detailed processing progress |
| `--workers` | Maximum concurrent worker threads (default 4) |
| `--batch-size` | Number of clauses per LLM extraction batch (default 10) |
| `--version` | Show version information |
| `--help` | Show help information |

## Output Description

### HTML Report

The HTML report contains the following sections:

1. **Report Summary**: Total conflicts, distribution by type, risk rating
2. **Conflict Graph**: Rule-conflict network diagram with clickable nodes for details
3. **Conflict List**: Grouped by type with source clause annotations
4. **Resolution Suggestions**: Priority resolution suggestions and modification directions

### JSON Output

```json
{
  "summary": {
    "total_conflicts": 5,
    "by_type": {
      "TEMPORAL_CONFLICT": 2,
      "ACTION_CONFLICT": 1,
      "SCOPE_OVERLAP": 2
    },
    "risk_level": "Medium"
  },
  "conflicts": [...],
  "suggestions": [...]
}
```

## Rule Format Reference

Supported input formats:

- **TXT**: Plain text, split by paragraphs
- **DOCX**: Word document, extracts body content
- **PDF**: PDF document, extracts text content
- **Markdown**: Markdown document, split by headings and paragraphs

Rule clauses should include:
- Clause number
- Clause title
- Specific requirements (subject, conditions, actions)

## Fallback Mode Reference

When LLM is unavailable, the tool provides two local rule engine modes:

1. **`--no-llm`**: Uses rule engine + keyword matching for triple extraction without calling LLM
2. **`--force-local`**: Forces use of local rule engine (equivalent to `--no-llm`)

Local mode is suitable for:
- No API Key or API quota exhausted
- Quick testing of rule documents
- Initial scanning of simple rule documents

Note: Local mode extraction accuracy may be lower than LLM mode. It is recommended to use LLM mode for important rules.

## Priority Rules

Default priorities (configurable):
1. NHC (National Health Commission) standards (highest)
2. Internal hospital regulations
3. Insurance rules (lowest)

## Technical Architecture

- **Rule Reading**: python-docx, pdfplumber
- **Text Processing**: jieba word segmentation
- **LLM Extraction**: OpenAI API / Anthropic API compatible
- **CLI**: Typer, Rich
- **Report Generation**: Jinja2, Plotly

## Project Structure

```
qc-rule-paradox-scanner/
├── data/               # Sample rule documents
├── templates/          # HTML report templates
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

## Use Cases

- Self-check during hospital grade review material preparation
- QC office reviewing conflicts between internal rules and higher-level requirements
- Insurance office pre-checking rule ambiguities
- Information科 (IT department) conflict early warning when integrating multiple rule systems

---

## Support the Author

If you find this project helpful, feel free to buy me a coffee! ☕

![Buy Me a Coffee](buymeacoffee.png)

**Buy me a coffee (crypto)**

| Chain | Address |
|-------|---------|
| BTC | `bc1qc0f5tv577z7yt59tw8sqaq3tey98xehy32frzd` |
| ETH / USDT | `0x3b7b6c47491e4778157f0756102f134d05070704` |
| SOL | `6Xuk373zc6x6XWcAAuqvbWW92zabJdCmN3CSwpsVM6sd` |
