"""质控规则冲突扫描器 - 核心模块"""

from .document_reader import (
    DocumentReader,
    TXTReader,
    DOCXReader,
    PDFReader,
    MarkdownReader,
    load_document,
    load_documents,
    DocumentLoadError,
)

from .text_preprocessor import (
    TextPreprocessor,
    ClauseExtractor,
    RuleMetadata,
    Clause,
    RuleSourceType,
    preprocess_document,
    preprocess_documents,
)

from .triple_extractor import (
    RuleTriple,
    LLMTripleExtractor,
    ExtractionError,
    LLMProvider,
    extract_triples,
)

from .conflict_detector import (
    ConflictType,
    Conflict,
    ConflictReport,
    TemporalConflictDetector,
    ActionConflictDetector,
    ScopeOverlapDetector,
    PriorityConflictDetector,
    ConflictDetector,
    detect_conflicts,
)

from .priority_resolver import (
    PriorityRule,
    PriorityResolver,
    SuggestionGenerator,
    create_priority_resolver,
    resolve_conflict_report,
)

from .html_reporter import (
    HTMLReporter,
    generate_html_report,
    conflict_to_dict,
    build_graph_data,
)

__all__ = [
    # document_reader
    "DocumentReader",
    "TXTReader",
    "DOCXReader",
    "PDFReader",
    "MarkdownReader",
    "load_document",
    "load_documents",
    "DocumentLoadError",
    # text_preprocessor
    "TextPreprocessor",
    "ClauseExtractor",
    "RuleMetadata",
    "Clause",
    "RuleSourceType",
    "preprocess_document",
    "preprocess_documents",
    # triple_extractor
    "RuleTriple",
    "LLMTripleExtractor",
    "ExtractionError",
    "LLMProvider",
    "extract_triples",
    # conflict_detector
    "ConflictType",
    "Conflict",
    "ConflictReport",
    "TemporalConflictDetector",
    "ActionConflictDetector",
    "ScopeOverlapDetector",
    "PriorityConflictDetector",
    "ConflictDetector",
    "detect_conflicts",
    # priority_resolver
    "PriorityRule",
    "PriorityResolver",
    "SuggestionGenerator",
    "create_priority_resolver",
    "resolve_conflict_report",
    # html_reporter
    "HTMLReporter",
    "generate_html_report",
    "conflict_to_dict",
    "build_graph_data",
]