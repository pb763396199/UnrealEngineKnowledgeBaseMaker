"""
Architecture Upgrade Test Script

Verify all features from three-phase upgrade
"""

import sys
from pathlib import Path

def test_imports():
    """Test module imports"""
    print("=" * 60)
    print("Test 1: Module Imports")
    print("=" * 60)

    tests = [
        ("Pipeline Base", "from ue5_kb.pipeline.base import PipelineStage"),
        ("Pipeline Coordinator", "from ue5_kb.pipeline.coordinator import PipelineCoordinator"),
        ("Discover Stage", "from ue5_kb.pipeline.discover import DiscoverStage"),
        ("Extract Stage", "from ue5_kb.pipeline.extract import ExtractStage"),
        ("Analyze Stage", "from ue5_kb.pipeline.analyze import AnalyzeStage"),
        ("Build Stage", "from ue5_kb.pipeline.build import BuildStage"),
        ("Generate Stage", "from ue5_kb.pipeline.generate import GenerateStage"),
        ("State Management", "from ue5_kb.pipeline.state import PipelineState"),
        ("LayeredQuery", "from ue5_kb.query.layered_query import LayeredQueryInterface"),
        ("Partitioned Builder", "from ue5_kb.builders.partitioned_builder import PartitionedBuilder"),
    ]

    passed = 0
    failed = 0

    for name, import_stmt in tests:
        try:
            exec(import_stmt)
            print(f"  [PASS] {name}")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")
            failed += 1

    print(f"\nResult: {passed} passed, {failed} failed\n")
    return failed == 0


def test_pipeline_classes():
    """Test Pipeline class instantiation"""
    print("=" * 60)
    print("Test 2: Pipeline Class Instantiation")
    print("=" * 60)

    from ue5_kb.pipeline.discover import DiscoverStage
    from ue5_kb.pipeline.coordinator import PipelineCoordinator
    from pathlib import Path

    test_path = Path("./test_engine")

    tests = [
        ("DiscoverStage", lambda: DiscoverStage(test_path)),
        ("PipelineCoordinator", lambda: PipelineCoordinator(test_path)),
    ]

    passed = 0
    failed = 0

    for name, factory in tests:
        try:
            obj = factory()
            print(f"  ✓ {name}: {obj}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {name}: {e}")
            failed += 1

    print(f"\n结果: {passed} 通过, {failed} 失败\n")
    return failed == 0


def test_layered_query():
    """测试 LayeredQuery 功能"""
    print("=" * 60)
    print("测试 3: LayeredQuery 功能")
    print("=" * 60)

    from ue5_kb.query.layered_query import LayeredQueryInterface

    try:
        lq = LayeredQueryInterface("/tmp/test_kb")

        # 测试 ref_id 生成
        ref_id = lq._generate_ref_id("test_class")
        print(f"  ✓ ref_id 生成: {ref_id}")

        # 测试缓存统计
        stats = lq.get_cache_stats()
        print(f"  ✓ 缓存统计: {stats}")

        print(f"\n结果: 测试通过\n")
        return True

    except Exception as e:
        print(f"  ✗ LayeredQuery 测试失败: {e}")
        print(f"\n结果: 测试失败\n")
        return False


def test_partitioned_builder():
    """测试分区构建器"""
    print("=" * 60)
    print("测试 4: 分区构建器")
    print("=" * 60)

    from ue5_kb.builders.partitioned_builder import PartitionedBuilder, PartitionConfig

    try:
        builder = PartitionedBuilder(Path("./test_engine"))

        # 测试分区配置
        print(f"  ✓ 分区数: {len(PartitionConfig.PARTITIONS)}")

        for name, config in PartitionConfig.PARTITIONS.items():
            print(f"    - {name}: {config['description']}")

        # 测试状态查询
        status = builder.get_partition_status()
        print(f"  ✓ 状态查询: {len(status)} 个分区")

        print(f"\n结果: 测试通过\n")
        return True

    except Exception as e:
        print(f"  ✗ 分区构建器测试失败: {e}")
        print(f"\n结果: 测试失败\n")
        return False


def test_cli_commands():
    """测试 CLI 命令注册"""
    print("=" * 60)
    print("测试 5: CLI 命令注册")
    print("=" * 60)

    import subprocess

    commands = [
        ("pipeline --help", "Pipeline 命令组"),
        ("pipeline run --help", "Pipeline run 命令"),
        ("pipeline status --help", "Pipeline status 命令"),
        ("pipeline clean --help", "Pipeline clean 命令"),
        ("pipeline partitioned --help", "分区构建命令"),
        ("pipeline partition-status --help", "分区状态命令"),
    ]

    passed = 0
    failed = 0

    for cmd, desc in commands:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "ue5_kb.cli"] + cmd.split(),
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                print(f"  ✓ {desc}")
                passed += 1
            else:
                print(f"  ✗ {desc}: 返回码 {result.returncode}")
                failed += 1

        except Exception as e:
            print(f"  ✗ {desc}: {e}")
            failed += 1

    print(f"\n结果: {passed} 通过, {failed} 失败\n")
    return failed == 0


def main():
    """运行所有测试"""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║  UE5 Knowledge Base Maker - 架构升级测试             ║")
    print("║  版本: v2.5.0                                        ║")
    print("╚" + "=" * 58 + "╝")
    print("\n")

    results = []

    # 运行所有测试
    results.append(("模块导入", test_imports()))
    results.append(("类实例化", test_pipeline_classes()))
    results.append(("LayeredQuery", test_layered_query()))
    results.append(("分区构建", test_partitioned_builder()))
    results.append(("CLI 命令", test_cli_commands()))

    # 总结
    print("=" * 60)
    print("测试总结")
    print("=" * 60)

    total_passed = sum(1 for _, result in results if result)
    total_tests = len(results)

    for name, result in results:
        status = "✓ 通过" if result else "✗ 失败"
        print(f"  {status}: {name}")

    print(f"\n总计: {total_passed}/{total_tests} 测试通过")

    if total_passed == total_tests:
        print("\n🎉 所有测试通过！架构升级成功！\n")
        return 0
    else:
        print(f"\n⚠️  {total_tests - total_passed} 个测试失败\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
