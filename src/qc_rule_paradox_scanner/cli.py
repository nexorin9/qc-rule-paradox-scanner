"""质控规则冲突扫描器 CLI 模块

使用 Typer 实现命令行入口，支持多模式输出
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

from .document_reader import load_document, load_documents, DocumentLoadError
from .text_preprocessor import preprocess_document, Clause, RuleSourceType
from .triple_extractor import (
    RuleTriple,
    LLMTripleExtractor,
    KeywordBasedTripleExtractor,
    ExtractionError,
    extract_triples,
)
from .conflict_detector import (
    ConflictReport,
    ConflictDetector,
    detect_conflicts,
)
from .priority_resolver import (
    PriorityResolver,
    SuggestionGenerator,
    resolve_conflict_report,
)
from .html_reporter import generate_html_report
from .output_schema import create_output_schema, output_to_json

# 创建 Typer app
app = typer.Typer(
    name="qc-scan",
    help="质控规则冲突扫描器 - 自动扫描医院多套质控规则体系之间的逻辑冲突",
    add_completion=False,
)

# 创建 Rich console
console = Console()


def version_callback(version: bool):
    """显示版本信息"""
    if version:
        console.print("质控规则冲突扫描器 v0.1.0")
        raise typer.Exit()


def load_env_config():
    """加载环境变量配置"""
    from dotenv import load_dotenv
    # 尝试从项目根目录加载 .env 文件
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()


@app.command()
def scan(
    # 通用输入选项
    input_files: Optional[list[str]] = typer.Option(
        None,
        "--input",
        "-i",
        help="通用输入文件（可指定多个，自动识别来源类型）",
    ),
    # 分类输入选项
    standards: Optional[str] = typer.Option(
        None,
        "--standards",
        help="等级评审标准文件（支持 txt, docx, pdf, md）",
    ),
    hospital: Optional[str] = typer.Option(
        None,
        "--hospital",
        help="院内质控规范文件",
    ),
    insurance: Optional[str] = typer.Option(
        None,
        "--insurance",
        help="医保规则文件",
    ),
    # 输出选项
    output: str = typer.Option(
        "output",
        "--output",
        "-o",
        help="输出目录路径",
    ),
    # 格式选项
    format: str = typer.Option(
        "html",
        "--format",
        "-f",
        help="输出格式：html, json, markdown",
    ),
    # 阈值选项
    threshold: float = typer.Option(
        0.5,
        "--threshold",
        "-t",
        help="冲突置信度阈值（0-1），低于此值的冲突将被忽略",
    ),
    # 模式选项
    no_llm: bool = typer.Option(
        False,
        "--no-llm",
        help="仅使用规则引擎，不调用 LLM（用于测试或无 API Key 时）",
    ),
    force_local: bool = typer.Option(
        False,
        "--force-local",
        help="强制使用本地规则引擎（等效于 --no-llm）",
    ),
    # 其他选项
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="显示详细处理进度",
    ),
    # 性能优化选项
    workers: int = typer.Option(
        4,
        "--workers",
        "-w",
        help="并发处理的最大工作线程数（用于本地规则引擎）",
    ),
    batch_size: int = typer.Option(
        10,
        "--batch-size",
        "-b",
        help="LLM 批量提取的条款数（多条规则合并一次 API 调用）",
    ),
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        callback=version_callback,
        help="显示版本信息",
    ),
):
    """扫描规则文件并检测冲突

    示例：

        # 使用分类文件
        qc-scan --standards 等级评审.txt --hospital 院内规范.txt --insurance 医保规则.txt -o output

        # 使用通用输入
        qc-scan -i file1.txt -i file2.docx -i file3.pdf -o output

        # 输出 JSON 格式
        qc-scan --standards 标准.txt --output result --format json

        # 仅使用规则引擎（不调用 LLM）
        qc-scan --standards 标准.txt --no-llm

        # 强制使用本地规则引擎
        qc-scan --standards 标准.txt --force-local
    """
    # 加载环境配置
    load_env_config()

    # 验证输入
    input_sources = []

    # 处理分类输入
    if standards:
        input_sources.append(("standards", standards))
    if hospital:
        input_sources.append(("hospital", hospital))
    if insurance:
        input_sources.append(("insurance", insurance))

    # 处理通用输入
    if input_files:
        for f in input_files:
            input_sources.append(("auto", f))

    if not input_sources:
        console.print("[red]错误：必须指定至少一个输入文件[/red]")
        console.print("使用 --standards, --hospital, --insurance 或 --input 指定输入文件")
        raise typer.Exit(1)

    # 创建输出目录
    output_path = Path(output)
    output_path.mkdir(parents=True, exist_ok=True)

    # 根据来源映射文件到 RuleSourceType
    source_map = {
        "standards": RuleSourceType.NATIONAL_STANDARD,
        "hospital": RuleSourceType.HOSPITAL_INTERNAL,
        "insurance": RuleSourceType.INSURANCE,
        "auto": None,  # 自动检测
    }

    # 处理文档
    if verbose:
        console.print("\n[bold blue]开始处理规则文档...[/bold blue]\n")

    all_clauses: list[Clause] = []
    processed_files = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
        transient=verbose,
    ) as progress:

        # 加载文档任务
        load_task = progress.add_task("[cyan]加载文档...", total=len(input_sources))

        for source_type, file_path in input_sources:
            try:
                if verbose:
                    console.print(f"  加载文件: {file_path}")

                doc = load_document(file_path)

                # 预处理文档
                clauses = preprocess_document(doc.content, doc.source)

                # 如果来源已知，设置来源类型
                mapped_source = source_map.get(source_type)
                if mapped_source:
                    for clause in clauses:
                        clause.source = mapped_source
                        clause.source_file = file_path

                all_clauses.extend(clauses)
                processed_files.append(file_path)

                progress.update(load_task, advance=1)

            except DocumentLoadError as e:
                console.print(f"[yellow]警告：跳过文件 {file_path} - {str(e)}[/yellow]")
                progress.update(load_task, advance=1)
                continue

    if verbose:
        console.print(f"\n[green]成功加载 {len(processed_files)} 个文件，共 {len(all_clauses)} 条规则条款[/green]\n")

    if not all_clauses:
        console.print("[red]错误：没有找到有效的规则条款[/red]")
        raise typer.Exit(1)

    # 提取三元组
    triples: list[RuleTriple] = []

    # 统一处理：force_local 等效于 no_llm
    use_local_mode = no_llm or force_local

    if use_local_mode:
        if verbose:
            console.print(f"[yellow]--no-llm / --force-local 模式：使用本地规则引擎提取三元组（并发数={workers}）[/yellow]")

        try:
            local_extractor = KeywordBasedTripleExtractor()

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console,
                transient=verbose,
            ) as progress:
                extract_task = progress.add_task(
                    f"[cyan]提取三元组 (0/{len(all_clauses)})...",
                    total=len(all_clauses)
                )

                def local_progress_callback(completed: int, total: int):
                    progress.update(
                        extract_task,
                        description=f"[cyan]提取三元组 ({completed}/{total})...",
                        completed=completed
                    )

                # 使用并发批量提取
                triples = local_extractor.extract_batch_concurrent(
                    all_clauses,
                    max_workers=workers,
                    progress_callback=local_progress_callback,
                )

            if verbose:
                console.print(f"\n[green]本地规则引擎成功提取 {len(triples)} 个三元组（使用 {workers} 个并发线程）[/green]\n")

        except Exception as e:
            console.print(f"[red]本地规则引擎提取失败: {e}[/red]")
            console.print("[yellow]回退到占位模式...[/yellow]")
            # 回退到占位三元组（确保流程可以继续）
            for clause in all_clauses:
                triple = RuleTriple(
                    subject="医院/科室",
                    condition=clause.title or "无",
                    action=clause.content[:50] if clause.content else "待定义",
                    source=clause.source.value if clause.source else "未知",
                    clause_id=clause.clause_id or "未知",
                    rule_type="要求",
                    confidence=0.3,
                )
                triples.append(triple)
    else:
        # 检查 API Key
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            console.print("[yellow]警告：未设置 OPENAI_API_KEY，切换到 --no-llm 模式[/yellow]")
            no_llm = True
        else:
            if verbose:
                console.print(f"\n[bold blue]开始提取规则三元组（使用 LLM，批量大小={batch_size}）...[/bold blue]\n")

            try:
                extractor = LLMTripleExtractor(api_key=api_key)

                total_batches = (len(all_clauses) + batch_size - 1) // batch_size

                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TaskProgressColumn(),
                    console=console,
                    transient=verbose,
                ) as progress:
                    extract_task = progress.add_task(
                        f"[cyan]批量提取三元组 (0/{total_batches} 批次)...",
                        total=total_batches
                    )

                    def llm_progress_callback(completed: int, total: int):
                        progress.update(
                            extract_task,
                            description=f"[cyan]批量提取 ({completed}/{total} 批次)...",
                            completed=completed
                        )

                    # 使用 LLM 批量提取（多条规则合并一次 API 调用）
                    triples = extractor.extract_batch_llm(
                        all_clauses,
                        batch_size=batch_size,
                        progress_callback=llm_progress_callback,
                    )

                if verbose:
                    console.print(f"\n[green]成功提取 {len(triples)} 个三元组（批量大小={batch_size}，减少 API 调用次数）[/green]\n")

            except ExtractionError as e:
                console.print(f"[red]LLM 提取失败: {e}[/red]")
                console.print("[yellow]切换到本地规则引擎...[/yellow]")
                # 回退到本地规则引擎
                try:
                    local_extractor = KeywordBasedTripleExtractor()

                    def local_progress_callback(completed: int, total: int):
                        pass  # 静默回调

                    triples = local_extractor.extract_batch_concurrent(
                        all_clauses,
                        max_workers=workers,
                        progress_callback=local_progress_callback,
                    )
                    if verbose:
                        console.print(f"[green]本地规则引擎提取了 {len(triples)} 个三元组[/green]\n")
                except Exception as local_error:
                    console.print(f"[red]本地规则引擎也失败了: {local_error}[/red]")

    # 检测冲突
    if verbose:
        console.print("[bold blue]开始检测冲突...[/bold blue]\n")

    detector = ConflictDetector()
    report = detector.detect_conflicts(triples, threshold=threshold)

    if verbose:
        summary = report.get_summary()
        console.print(f"[green]检测完成：共发现 {summary['total']} 个冲突[/green]")
        console.print(f"  - 时序互斥: {summary['temporal']}")
        console.print(f"  - 动作矛盾: {summary['action']}")
        console.print(f"  - 范围重叠: {summary['scope_overlap']}")
        console.print(f"  - 优先级冲突: {summary['priority']}\n")

    # 生成优先级消解建议
    resolver = PriorityResolver()
    generator = SuggestionGenerator(resolver)

    # 更新冲突建议
    for conflict in report.conflicts:
        priority_suggestion = resolver.resolve_conflict(conflict)
        conflict.suggestion = f"{conflict.suggestion}\n\n---\n{priority_suggestion}"

    # 输出结果
    if verbose:
        console.print("[bold blue]生成报告...[/bold blue]\n")

    output_format = format.lower()
    if output_format == "json":
        output_file = output_path / "conflicts.json"
        schema = create_output_schema(report, resolver=resolver)
        schema.to_file(str(output_file))
        console.print(f"[green]JSON 报告已保存到: {output_file}[/green]")

    elif output_format == "markdown":
        output_file = output_path / "conflicts.md"
        markdown_content = generator.generate_markdown_report(report)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        console.print(f"[green]Markdown 报告已保存到: {output_file}[/green]")

    elif output_format == "html":
        output_file = output_path / "conflicts.html"
        try:
            html_path = generate_html_report(report, str(output_file))
            console.print(f"[green]HTML 报告已保存到: {html_path}[/green]")
        except Exception as e:
            console.print(f"[yellow]HTML 报告生成失败: {e}[/yellow]")
            console.print("[yellow]回退到 JSON 格式输出[/yellow]")
            fallback_file = output_file.with_suffix(".json")
            schema = create_output_schema(report, resolver=resolver)
            schema.to_file(str(fallback_file))
            console.print(f"[green]JSON 报告已保存到: {fallback_file}[/green]")

    else:
        console.print(f"[red]错误：不支持的输出格式 '{format}'[/red]")
        console.print("支持的格式：html, json, markdown")
        raise typer.Exit(1)

    # 显示冲突摘要表格
    if report.conflicts:
        table = Table(title="冲突检测结果摘要")
        table.add_column("类型", style="cyan")
        table.add_column("置信度", style="magenta")
        table.add_column("规则 A", style="green")
        table.add_column("规则 B", style="yellow")

        for conflict in report.conflicts[:10]:  # 最多显示10条
            table.add_row(
                conflict.conflict_type.value,
                f"{conflict.confidence:.0%}",
                f"{conflict.triple_a.source} ({conflict.triple_a.clause_id})",
                f"{conflict.triple_b.source} ({conflict.triple_b.clause_id})",
            )

        console.print("\n")
        console.print(table)

        if len(report.conflicts) > 10:
            console.print(f"\n[dim]... 还有 {len(report.conflicts) - 10} 个冲突，详见完整报告[/dim]")


@app.command()
def check_api(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="显示详细信息"),
):
    """检查 API 配置是否正确

    示例：

        qc-scan check-api
        qc-scan check-api -v
    """
    load_env_config()

    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")

    if not api_key:
        console.print("[red]✗ 未设置 OPENAI_API_KEY[/red]")
        console.print("\n请选择以下方式之一设置 API Key：")
        console.print("  1. 在项目根目录创建 .env 文件，添加：OPENAI_API_KEY=your_key_here")
        console.print("  2. 设置环境变量：export OPENAI_API_KEY=your_key_here")
        console.print("  3. 使用 --no-llm 参数跳过 LLM 调用")
        raise typer.Exit(1)

    if verbose:
        console.print(f"[green]✓ OPENAI_API_KEY 已设置[/green]")
        if base_url:
            console.print(f"[green]✓ OPENAI_BASE_URL: {base_url}[/green]")
        else:
            console.print("[dim]  使用默认 API 端点[/dim]")

    # 尝试调用 API 验证
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=5,
        )
        console.print("[green]✓ API 调用测试成功[/green]")
    except Exception as e:
        console.print(f"[red]✗ API 调用失败: {e}[/red]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()