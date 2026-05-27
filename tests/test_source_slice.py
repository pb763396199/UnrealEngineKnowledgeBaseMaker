import os
from pathlib import Path

import pytest

from ue5_kb.query.source_slice import SourceFunctionBlockCache, SourceSliceError, safe_resolve_source_path, slice_source


CPP_CONTENT = """#include "Foo.h"

void FFoo::Run()
{
    int Value = 1;
    if (Value > 0)
    {
        Value++;
    }
}

void FFoo::Other()
{
}
"""


def test_source_slice_context_and_function_modes(tmp_path):
    source_root = tmp_path / "Plugin"
    cpp = source_root / "Source" / "MyModule" / "Private" / "Foo.cpp"
    cpp.parent.mkdir(parents=True)
    cpp.write_text(CPP_CONTENT, encoding="utf-8")

    context = slice_source(
        source_root=source_root,
        relative_file="Source\\MyModule\\Private\\Foo.cpp",
        line_number=5,
        mode="context",
        context_lines=1,
    )
    assert context["mode"] == "context"
    assert context["file"] == "Source/MyModule/Private/Foo.cpp"
    assert "int Value" in context["content"]

    function = slice_source(
        source_root=source_root,
        relative_file="Source/MyModule/Private/Foo.cpp",
        line_number=3,
        mode="function",
    )
    assert function["mode"] == "function"
    assert function["boundary_hit"] is True
    assert function["line_start"] == 3
    assert function["line_end"] == 10
    assert "FFoo::Run" in function["content"]
    assert "FFoo::Other" not in function["content"]
    assert function["truncated"] is False


def test_source_function_block_cache_reuses_one_file_scan_for_multiple_functions():
    lines = CPP_CONTENT.splitlines(keepends=True)
    cache = SourceFunctionBlockCache(lines)

    first = cache.extract_function_block(3)
    second = cache.extract_function_block(12)

    assert cache.scan_count == 1
    assert first is not None
    assert second is not None
    assert "FFoo::Run" in "".join(first[2])
    assert "FFoo::Other" in "".join(second[2])


@pytest.mark.parametrize("line_number", [3, 5, 7])
def test_source_slice_function_mode_finds_enclosing_function_from_body_lines(tmp_path, line_number):
    source_root = tmp_path / "Plugin"
    cpp = source_root / "Source" / "MyModule" / "Private" / "Foo.cpp"
    cpp.parent.mkdir(parents=True)
    cpp.write_text(CPP_CONTENT, encoding="utf-8")

    result = slice_source(
        source_root=source_root,
        relative_file="Source/MyModule/Private/Foo.cpp",
        line_number=line_number,
        mode="function",
    )

    assert result["mode"] == "function"
    assert result["line_start"] == 3
    assert result["line_end"] == 10
    assert "if (Value > 0)" in result["content"]
    assert "FFoo::Other" not in result["content"]


def test_source_slice_function_mode_falls_back_between_functions(tmp_path):
    source_root = tmp_path / "Plugin"
    cpp = source_root / "Source" / "MyModule" / "Private" / "Foo.cpp"
    cpp.parent.mkdir(parents=True)
    cpp.write_text(CPP_CONTENT, encoding="utf-8")

    result = slice_source(
        source_root=source_root,
        relative_file="Source/MyModule/Private/Foo.cpp",
        line_number=11,
        mode="function",
        context_lines=1,
    )

    assert result["mode"] == "context"
    assert result["boundary_hit"] is False
    assert "FFoo::Run" not in result["content"]
    assert "FFoo::Other" in result["content"]


def test_source_slice_function_mode_handles_namespace_and_class_wrappers(tmp_path):
    source_root = tmp_path / "Plugin"
    cpp = source_root / "Source" / "MyModule" / "Private" / "Wrapped.cpp"
    cpp.parent.mkdir(parents=True)
    cpp.write_text(
        "namespace N\n"
        "{\n"
        "class FLocal\n"
        "{\n"
        "public:\n"
        "    void InlineRun()\n"
        "    {\n"
        "        int Value = 0;\n"
        "        if (Value == 0)\n"
        "        {\n"
        "            Value++;\n"
        "        }\n"
        "    }\n"
        "};\n"
        "}\n",
        encoding="utf-8",
    )

    result = slice_source(
        source_root=source_root,
        relative_file="Source/MyModule/Private/Wrapped.cpp",
        line_number=11,
        mode="function",
    )

    assert result["mode"] == "function"
    assert result["line_start"] == 6
    assert result["line_end"] == 13
    assert "void InlineRun" in result["content"]
    assert "class FLocal" not in result["content"]


def test_source_slice_function_mode_falls_back_when_no_function_block_exists(tmp_path):
    source_root = tmp_path / "Plugin"
    header = source_root / "Source" / "MyModule" / "Public" / "Types.h"
    header.parent.mkdir(parents=True)
    header.write_text("struct FThing\n{\n    int32 Value;\n};\n", encoding="utf-8")

    result = slice_source(
        source_root=source_root,
        relative_file="Source/MyModule/Public/Types.h",
        line_number=3,
        mode="function",
        context_lines=1,
    )

    assert result["mode"] == "context"
    assert result["boundary_hit"] is False
    assert "int32 Value" in result["content"]


@pytest.mark.parametrize(
    "bad_path",
    [
        "",
        "../Foo.cpp",
        "Source/../Foo.cpp",
        "/absolute/Foo.cpp",
        "\\absolute\\Foo.cpp",
        "C:\\Temp\\Foo.cpp",
        "C:Temp\\Foo.cpp",
        "\\\\server\\share\\Foo.cpp",
        "Source/Foo.cpp\x00",
    ],
)
def test_source_slice_rejects_unsafe_paths(tmp_path, bad_path):
    source_root = tmp_path / "Plugin"
    source_root.mkdir()
    with pytest.raises(SourceSliceError):
        safe_resolve_source_path(source_root, bad_path)


def test_source_slice_rejects_symlink_escape(tmp_path):
    source_root = tmp_path / "Plugin"
    source_root.mkdir()
    outside = tmp_path / "Outside.cpp"
    outside.write_text("void Escaped() {}", encoding="utf-8")
    link = source_root / "Escaped.cpp"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not available on this platform")

    with pytest.raises(SourceSliceError):
        safe_resolve_source_path(source_root, "Escaped.cpp")


def test_source_slice_clamps_large_context_lines(tmp_path):
    source_root = tmp_path / "Plugin"
    cpp = source_root / "Source" / "MyModule" / "Private" / "LargeContext.cpp"
    cpp.parent.mkdir(parents=True)
    cpp.write_text("".join(f"line {index}\n" for index in range(1, 101)), encoding="utf-8")

    result = slice_source(
        source_root=source_root,
        relative_file="Source/MyModule/Private/LargeContext.cpp",
        line_number=50,
        mode="context",
        context_lines=1000,
        max_context_lines=3,
        max_output_chars=1000,
    )

    assert result["truncated"] is True
    assert "max_context_lines" in result["truncation_reasons"]
    assert result["line_start"] == 47
    assert result["line_end"] == 53
    assert len(result["content"].splitlines()) == 7


def test_source_slice_truncates_large_function_body(tmp_path):
    source_root = tmp_path / "Plugin"
    cpp = source_root / "Source" / "MyModule" / "Private" / "LargeFunction.cpp"
    cpp.parent.mkdir(parents=True)
    body = "".join(f"    Value += {index};\n" for index in range(1000))
    cpp.write_text(f"void FBig::Run()\n{{\n{body}}}\n", encoding="utf-8")

    result = slice_source(
        source_root=source_root,
        relative_file="Source/MyModule/Private/LargeFunction.cpp",
        line_number=1,
        mode="function",
        max_output_chars=200,
    )

    assert result["mode"] == "function"
    assert result["boundary_hit"] is True
    assert result["truncated"] is True
    assert "max_output_chars" in result["truncation_reasons"]
    assert len(result["content"]) == 200
    assert result["original_line_end"] > result["line_end"]
