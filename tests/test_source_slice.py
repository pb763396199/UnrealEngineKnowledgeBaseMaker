import os
from pathlib import Path

import pytest

from ue5_kb.query.source_slice import SourceSliceError, safe_resolve_source_path, slice_source


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
