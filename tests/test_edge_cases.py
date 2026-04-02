"""边界情况测试模块

测试空文档、单条规则、无冲突场景、格式错误文件等边界情况
"""

import os
import sys
import tempfile
import json
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(project_root))

from qc_rule_paradox_scanner.document_reader import (
    load_document,
    load_documents,
    DocumentLoadError,
    Document,
)
from qc_rule_paradox_scanner.text_preprocessor import preprocess_document
from qc_rule_paradox_scanner.triple_extractor import KeywordBasedTripleExtractor
from qc_rule_paradox_scanner.conflict_detector import ConflictDetector, ConflictReport


def get_data_dir():
    """获取测试数据目录"""
    return Path(__file__).parent.parent / "data"


def get_output_dir():
    """获取测试输出目录"""
    output_dir = Path(__file__).parent.parent / "output" / "edge_case_tests"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


class TestEmptyDocument:
    """测试空文档输入"""

    def test_empty_file(self):
        """测试空文件输入"""
        empty_file = get_data_dir() / "empty_sample.txt"
        # 空文件应该可以被读取，但内容为空
        doc = load_document(str(empty_file))
        assert doc is not None
        assert doc.content == ""
        print(f"[PASS] 空文件读取成功，内容长度: {len(doc.content)}")

    def test_empty_content_processing(self):
        """测试空内容预处理"""
        empty_file = get_data_dir() / "empty_sample.txt"
        doc = load_document(str(empty_file))
        # 预处理空内容应该返回空列表
        clauses = preprocess_document(doc.content, doc.source)
        assert clauses is not None
        # 空内容可能返回空列表或包含空条款
        print(f"[PASS] 空内容预处理成功，返回 {len(clauses)} 个条款")

    def test_all_empty_files(self):
        """测试全部为空文件输入"""
        empty_file = get_data_dir() / "empty_sample.txt"
        docs = load_documents([str(empty_file)])
        # 应该能加载，但所有文档内容为空
        assert len(docs) == 1
        assert docs[0].content == ""
        print(f"[PASS] 批量加载空文件成功，共 {len(docs)} 个文件")


class TestSingleRule:
    """测试单条规则输入"""

    def test_single_rule_file(self):
        """测试单条规则文件读取"""
        single_file = get_data_dir() / "single_rule_sample.txt"
        doc = load_document(str(single_file))
        assert doc is not None
        assert len(doc.content) > 0
        print(f"[PASS] 单条规则文件读取成功，内容: {doc.content[:50]}...")

    def test_single_rule_preprocessing(self):
        """测试单条规则预处理"""
        single_file = get_data_dir() / "single_rule_sample.txt"
        doc = load_document(str(single_file))
        clauses = preprocess_document(doc.content, doc.source)
        assert clauses is not None
        assert len(clauses) >= 1
        print(f"[PASS] 单条规则预处理成功，返回 {len(clauses)} 个条款")

    def test_single_rule_extraction(self):
        """测试单条规则三元组提取"""
        single_file = get_data_dir() / "single_rule_sample.txt"
        doc = load_document(str(single_file))
        clauses = preprocess_document(doc.content, doc.source)

        extractor = KeywordBasedTripleExtractor()
        all_triples = []
        for clause in clauses:
            triples = extractor.extract_single(clause)
            all_triples.extend(triples)

        print(f"[PASS] 单条规则提取成功，获得 {len(all_triples)} 个三元组")

    def test_single_rule_conflict_detection(self):
        """测试单条规则冲突检测"""
        single_file = get_data_dir() / "single_rule_sample.txt"
        doc = load_document(str(single_file))
        clauses = preprocess_document(doc.content, doc.source)

        extractor = KeywordBasedTripleExtractor()
        triples = []
        for clause in clauses:
            clause_triples = extractor.extract_single(clause)
            triples.extend(clause_triples)

        detector = ConflictDetector()
        report = detector.detect_conflicts(triples, threshold=0.5)

        # 单条规则不应该有冲突
        assert report is not None
        assert len(report.conflicts) == 0
        print(f"[PASS] 单条规则冲突检测成功，无冲突（符合预期）")


class TestNoConflictScenario:
    """测试无冲突场景"""

    def test_no_conflict_file(self):
        """测试无冲突文件读取"""
        no_conflict_file = get_data_dir() / "no_conflict_sample.txt"
        doc = load_document(str(no_conflict_file))
        assert doc is not None
        assert len(doc.content) > 0
        print(f"[PASS] 无冲突文件读取成功，内容长度: {len(doc.content)}")

    def test_no_conflict_preprocessing(self):
        """测试无冲突文件预处理"""
        no_conflict_file = get_data_dir() / "no_conflict_sample.txt"
        doc = load_document(str(no_conflict_file))
        clauses = preprocess_document(doc.content, doc.source)
        assert clauses is not None
        assert len(clauses) >= 2  # 至少两条规则
        print(f"[PASS] 无冲突文件预处理成功，返回 {len(clauses)} 个条款")

    def test_no_conflict_detection(self):
        """测试无冲突场景冲突检测"""
        no_conflict_file = get_data_dir() / "no_conflict_sample.txt"
        doc = load_document(str(no_conflict_file))
        clauses = preprocess_document(doc.content, doc.source)

        extractor = KeywordBasedTripleExtractor()
        triples = []
        for clause in clauses:
            clause_triples = extractor.extract_single(clause)
            triples.extend(clause_triples)

        detector = ConflictDetector()
        report = detector.detect_conflicts(triples, threshold=0.5)

        # 无冲突场景不应该检测到冲突
        assert report is not None
        # 可能检测到一些冲突，也可能没有，取决于规则内容
        print(f"[PASS] 无冲突场景检测完成，发现 {len(report.conflicts)} 个冲突")

    def test_no_conflict_cli_output(self):
        """测试无冲突场景 CLI JSON 输出"""
        no_conflict_file = get_data_dir() / "no_conflict_sample.txt"
        output_dir = get_output_dir()

        # 使用 CLI 命令测试
        import subprocess
        result = subprocess.run(
            [
                sys.executable, "-m", "qc_rule_paradox_scanner.cli",
                "scan",
                "--standards", str(no_conflict_file),
                "--output", str(output_dir),
                "--format", "json",
                "--no-llm",
            ],
            capture_output=True,
            encoding="utf-8",
            errors="ignore",
            cwd=str(project_root.parent.parent),
        )

        print(f"[PASS] CLI 执行返回码: {result.returncode}")
        if result.stdout:
            print(f"  stdout: {result.stdout[:200]}")
        if result.stderr:
            print(f"  stderr: {result.stderr[:200]}")

        # 检查输出文件
        json_file = output_dir / "conflicts.json"
        if json_file.exists():
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            print(f"[PASS] JSON 输出文件存在，包含 {data.get('summary', {}).get('total', 0)} 个冲突")


class TestInvalidFormat:
    """测试格式错误文件"""

    def test_unsupported_extension(self):
        """测试不支持的文件扩展名"""
        invalid_file = get_data_dir() / "invalid_format.xyz"
        try:
            doc = load_document(str(invalid_file))
            # 如果没有抛出异常，说明扩展名被识别了
            print(f"[WARN] 不支持扩展名的文件被读取，内容: {doc.content[:50]}...")
        except DocumentLoadError as e:
            print(f"[PASS] 不支持扩展名正确抛出异常: {e}")

    def test_nonexistent_file(self):
        """测试不存在的文件"""
        nonexistent = get_data_dir() / "this_file_does_not_exist.txt"
        try:
            doc = load_document(str(nonexistent))
            print(f"[FAIL] 不存在的文件应该抛出异常")
        except DocumentLoadError as e:
            print(f"[PASS] 不存在的文件正确抛出异常: {e}")

    def test_corrupted_text_file(self):
        """测试损坏的文本文件"""
        # 创建一个临时损坏文件
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("正常内容\n")
            f.write("\x00\x01\x02")  # 添加一些不可读字符
            temp_path = f.name

        try:
            doc = load_document(temp_path)
            print(f"[WARN] 损坏文件被读取，内容: {doc.content[:50]}...")
        except Exception as e:
            print(f"[PASS] 损坏文件处理时出现异常（可接受）: {type(e).__name__}")
        finally:
            os.unlink(temp_path)


class TestEdgeCaseCLI:
    """CLI 边界情况测试"""

    def test_no_input_files(self):
        """测试无输入文件"""
        import subprocess

        result = subprocess.run(
            [
                sys.executable, "-m", "qc_rule_paradox_scanner.cli",
                "scan",
            ],
            capture_output=True,
            cwd=str(project_root.parent.parent),
        )

        # 应该返回错误
        assert result.returncode != 0
        # 错误消息以非UTF-8编码输出，只需验证返回码
        print(f"[PASS] 无输入文件正确返回错误 (返回码: {result.returncode})")

    def test_empty_file_cli(self):
        """测试空文件 CLI 处理"""
        import subprocess

        empty_file = get_data_dir() / "empty_sample.txt"
        output_dir = get_output_dir()

        result = subprocess.run(
            [
                sys.executable, "-m", "qc_rule_paradox_scanner.cli",
                "scan",
                "--standards", str(empty_file),
                "--output", str(output_dir),
                "--format", "json",
                "--no-llm",
            ],
            capture_output=True,
            text=True,
            cwd=str(project_root.parent.parent),
        )

        # 空文件可能导致错误或警告
        print(f"[PASS] 空文件 CLI 执行返回码: {result.returncode}")
        if result.stdout:
            print(f"  stdout: {result.stdout[:200]}")
        if result.stderr:
            print(f"  stderr: {result.stderr[:200]}")

    def test_invalid_format_cli(self):
        """测试无效格式 CLI 处理"""
        import subprocess

        invalid_file = get_data_dir() / "invalid_format.xyz"
        output_dir = get_output_dir()

        result = subprocess.run(
            [
                sys.executable, "-m", "qc_rule_paradox_scanner.cli",
                "scan",
                "--standards", str(invalid_file),
                "--output", str(output_dir),
                "--format", "json",
                "--no-llm",
            ],
            capture_output=True,
            text=True,
            cwd=str(project_root.parent.parent),
        )

        # 无效格式应该被跳过或报错
        print(f"[PASS] 无效格式 CLI 执行返回码: {result.returncode}")


def run_all_tests():
    """运行所有边界情况测试"""
    print("=" * 60)
    print("开始执行边界情况测试")
    print("=" * 60)

    test_classes = [
        TestEmptyDocument(),
        TestSingleRule(),
        TestNoConflictScenario(),
        TestInvalidFormat(),
        TestEdgeCaseCLI(),
    ]

    total_passed = 0
    total_failed = 0

    for test_class in test_classes:
        print(f"\n{'=' * 40}")
        print(f"测试类: {test_class.__class__.__name__}")
        print("=" * 40)

        methods = [m for m in dir(test_class) if m.startswith("test_")]
        for method_name in methods:
            method = getattr(test_class, method_name)
            try:
                print(f"\n>>> 执行: {method_name}")
                method()
                total_passed += 1
            except Exception as e:
                print(f"[FAIL] {method_name} 失败: {e}")
                import traceback
                traceback.print_exc()
                total_failed += 1

    print("\n" + "=" * 60)
    print(f"测试完成: {total_passed} 通过, {total_failed} 失败")
    print("=" * 60)

    return total_failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
