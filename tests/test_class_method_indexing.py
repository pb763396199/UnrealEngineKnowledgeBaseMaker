"""
回归测试：类方法必须被索引到 function_index

覆盖 session audit 发现的 3 个关键缺陷：
1. get_function_implementation 找不到类方法的 impl 文件
2. search_functions 搜不到类方法
3. 类方法的 impl_file_path 必须被填充
"""

import os
import json
import sqlite3
import tempfile
import shutil
from pathlib import Path

import pytest

from ue5_kb.parsers.cpp_parser import CppParser
from ue5_kb.builders.module_graph_builder import ModuleGraphBuilder
from ue5_kb.core.config import Config
from ue5_kb.core.function_index import FunctionIndex


# ---------------------------------------------------------------------------
# 测试用 UE5 风格源码
# ---------------------------------------------------------------------------

HEADER_CONTENT = """\
#pragma once

#include "CoreMinimal.h"
#include "MyTestClass.generated.h"

UCLASS()
class MYMODULE_API AMyTestActor : public AActor
{
    GENERATED_BODY()
public:
    UFUNCTION(BlueprintCallable, Category="Test")
    void PostProcessGeoSources();

    void Initialize(int32 InParam);

    float GetValue() const;
};

struct MYMODULE_API FAesBuildingGeoSourceMarkerProducer
{
    void ProduceMarkers(const TArray<FVector>& Points);

    bool IsValid() const;
};
"""

CPP_CONTENT = """\
#include "MyTestClass.h"

void AMyTestActor::PostProcessGeoSources()
{
    // 处理地理资源
    UE_LOG(LogTemp, Log, TEXT("PostProcessGeoSources called"));
}

void AMyTestActor::Initialize(int32 InParam)
{
    // 初始化
}

float AMyTestActor::GetValue() const
{
    return 0.0f;
}

void FAesBuildingGeoSourceMarkerProducer::ProduceMarkers(const TArray<FVector>& Points)
{
    // 生产标记
}

bool FAesBuildingGeoSourceMarkerProducer::IsValid() const
{
    return true;
}
"""


@pytest.fixture
def module_dir(tmp_path):
    """创建带 .h 和 .cpp 的临时模块目录"""
    src = tmp_path / "Source" / "MyModule"
    src.mkdir(parents=True)

    (src / "MyTestClass.h").write_text(HEADER_CONTENT, encoding="utf-8")
    (src / "MyTestClass.cpp").write_text(CPP_CONTENT, encoding="utf-8")

    return src


@pytest.fixture
def config(tmp_path):
    """创建最小配置"""
    kb_path = tmp_path / "KnowledgeBase"
    kb_path.mkdir()
    (kb_path / "global_index").mkdir()
    (kb_path / "module_graphs").mkdir()

    cfg = Config(base_path=str(kb_path))
    return cfg


# ---------------------------------------------------------------------------
# 回归测试 #1：类方法必须出现在 function_index 中
# ---------------------------------------------------------------------------

class TestClassMethodIndexing:
    """验证 module_graph_builder 将类方法写入 function_index"""

    def test_class_methods_indexed(self, module_dir, config):
        """类方法（有 class_name 的函数）必须出现在 function_index.db"""
        builder = ModuleGraphBuilder(config)
        graph = builder.build_module_graph("MyModule", str(module_dir))

        func_idx_path = Path(config.storage_base_path) / "global_index" / "function_index.db"
        assert func_idx_path.exists(), "function_index.db 未创建"

        func_idx = FunctionIndex(str(func_idx_path))

        # 回归用例 1: PostProcessGeoSources 必须可查到
        results = func_idx.query_by_name("PostProcessGeoSources")
        assert len(results) > 0, "PostProcessGeoSources 应该在 function_index 中"
        assert any(r.get("class_name") == "AMyTestActor" for r in results)

        func_idx.close()

    def test_impl_file_path_populated(self, module_dir, config):
        """类方法的 impl_file_path 必须指向 .cpp 文件"""
        builder = ModuleGraphBuilder(config)
        graph = builder.build_module_graph("MyModule", str(module_dir))

        func_idx_path = Path(config.storage_base_path) / "global_index" / "function_index.db"
        func_idx = FunctionIndex(str(func_idx_path))

        results = func_idx.query_by_name("PostProcessGeoSources")
        # 至少有一条记录的 impl_file_path 非空
        has_impl = any(r.get("impl_file_path") for r in results)
        assert has_impl, "PostProcessGeoSources 至少有一条记录应有 impl_file_path"

        # impl_file_path 应指向 .cpp
        for r in results:
            if r.get("impl_file_path"):
                assert r["impl_file_path"].endswith(".cpp"), \
                    f"impl_file_path 应为 .cpp 文件，实际: {r['impl_file_path']}"

        func_idx.close()

    def test_search_functions_finds_class_methods(self, module_dir, config):
        """回归用例 2: search_functions 必须能搜到类方法"""
        builder = ModuleGraphBuilder(config)
        graph = builder.build_module_graph("MyModule", str(module_dir))

        func_idx_path = Path(config.storage_base_path) / "global_index" / "function_index.db"
        func_idx = FunctionIndex(str(func_idx_path))

        # 搜索 FAesBuildingGeoSourceMarkerProducer 的方法
        results = func_idx.search_by_keyword("ProduceMarkers", 50)
        assert len(results) > 0, "search_functions 应能搜到 ProduceMarkers"

        func_idx.close()

    def test_multiple_class_methods_all_indexed(self, module_dir, config):
        """一个类的所有方法都应该被索引"""
        builder = ModuleGraphBuilder(config)
        graph = builder.build_module_graph("MyModule", str(module_dir))

        func_idx_path = Path(config.storage_base_path) / "global_index" / "function_index.db"
        func_idx = FunctionIndex(str(func_idx_path))

        expected_methods = [
            ("PostProcessGeoSources", "AMyTestActor"),
            ("Initialize", "AMyTestActor"),
            ("GetValue", "AMyTestActor"),
            ("ProduceMarkers", "FAesBuildingGeoSourceMarkerProducer"),
            ("IsValid", "FAesBuildingGeoSourceMarkerProducer"),
        ]

        for func_name, class_name in expected_methods:
            results = func_idx.query_by_name(func_name)
            matching = [r for r in results if r.get("class_name") == class_name]
            assert len(matching) > 0, \
                f"{class_name}::{func_name} 应在 function_index 中"

        func_idx.close()
