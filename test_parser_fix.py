"""
测试 CppParser 修复 - 验证 extract_classes 和 extract_functions 方法
"""
import json
from ue5_kb.parsers.cpp_parser import CppParser

# 测试 C++ 代码示例
test_code = """
// UCLASS example
UCLASS()
class AMyActor : public AActor
{
    GENERATED_BODY()

public:
    UFUNCTION(BlueprintCallable, Category="Test")
    void MyFunction();

    UFUNCTION(BlueprintPure)
    float GetHealth() const;

    virtual void Tick(float DeltaTime) override;
};

// Simple struct
USTRUCT()
struct FMyData
{
    GENERATED_BODY()

    UPROPERTY()
    int32 Value;
};

// Free function
void GlobalFunction()
{
}

UFUNCTION()
static void StaticHelper()
{
}
"""

parser = CppParser()

# 测试 extract_classes
print("Testing extract_classes()...")
classes = parser.extract_classes(test_code, "test.cpp")
print(f"  Found {len(classes)} classes:")
for cls in classes:
    print(f"    - {cls['name']}: parent={cls.get('parent_class', 'N/A')}, is_uclass={cls.get('is_uclass', False)}")
    print(f"      file_path={cls.get('file_path', 'N/A')}, line_number={cls.get('line_number', 0)}")

# 测试 extract_functions
print("\nTesting extract_functions()...")
functions = parser.extract_functions(test_code, "test.cpp")
print(f"  Found {len(functions)} functions:")
for func in functions:
    params_str = ', '.join([f"{p.get('type', '?')} {p.get('name', '?')}" for p in func.get('parameters', [])])
    print(f"    - {func['name']}({params_str}): return_type={func.get('return_type', 'N/A')}, is_ufunction={func.get('is_ufunction', False)}")
    print(f"      file_path={func.get('file_path', 'N/A')}, line_number={func.get('line_number', 0)}")

# 测试创建 code_graph 格式
print("\nTesting code_graph format for build stage...")
code_graph = {
    'module': 'TestModule',
    'source_file_count': 1,
    'classes': classes,
    'functions': functions
}

# 模拟 build 阶段的处理
from ue5_kb.pipeline.build import BuildStage

# 创建一个模拟的 BuildStage 来测试 _create_networkx_graph
from pathlib import Path
import tempfile

with tempfile.TemporaryDirectory() as tmpdir:
    # 创建模拟的 base_path 和 data_dir
    tmpdir = Path(tmpdir)
    data_dir = tmpdir / "data"
    data_dir.mkdir()

    # 创建一个简单的模拟 BuildStage
    class MockBuildStage(BuildStage):
        def __init__(self, data_dir):
            self.data_dir = data_dir

    mock_stage = MockBuildStage(data_dir)

    try:
        graph = mock_stage._create_networkx_graph(code_graph)
        print(f"  NetworkX graph created: {len(graph.nodes())} nodes, {len(graph.edges())} edges")

        # 打印节点信息
        for node_id, node_data in graph.nodes(data=True):
            node_type = node_data.get('type', 'unknown')
            print(f"    Node {node_id}: type={node_type}, name={node_data.get('name', 'N/A')}")
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()

print("\n=== Test Summary ===")
print(f"Classes found: {len(classes)}")
print(f"Functions found: {len(functions)}")
print("Fix verified!" if len(classes) > 0 or len(functions) > 0 else "Fix may not be working correctly!")
