import sqlite3
from pathlib import Path

from ue5_kb.core.files_fts_index import FilesFtsIndex, build_files_fts_index, search_files


def _make_source_tree(root):
    source = root / "Source" / "MyModule" / "Private"
    source.mkdir(parents=True)
    (source / "Foo.cpp").write_text(
        "void BeginPlay() {\n  RegisterComponent();\n}\n",
        encoding="utf-8",
    )
    (root / "Source" / "MyModule" / "MyModule.Build.cs").write_text(
        "PublicDependencyModuleNames.AddRange(new string[] { \"Core\" });",
        encoding="utf-8",
    )
    return source / "Foo.cpp"


def test_files_fts_builds_and_searches_with_fts_or_like(tmp_path):
    source_root = tmp_path / "Plugin"
    _make_source_tree(source_root)
    db_path = tmp_path / "KnowledgeBase" / "global_index" / "files_fts.db"

    stats = build_files_fts_index(source_root, db_path)
    result = search_files(db_path, "BeginPlay", limit=10)

    assert stats["indexed_count"] >= 2
    assert result["found_count"] >= 1
    assert result["results"][0]["path"].startswith("Source/")
    assert "BeginPlay" in result["results"][0]["snippet"]


def test_files_fts_like_fallback_when_fts_disabled(tmp_path):
    source_root = tmp_path / "Plugin"
    _make_source_tree(source_root)
    db_path = tmp_path / "KnowledgeBase" / "global_index" / "files_fts.db"

    stats = build_files_fts_index(source_root, db_path, force_disable_fts=True)
    result = search_files(db_path, "RegisterComponent", limit=10)

    assert stats["fts_enabled"] is False
    assert result["fallback"] == "like_no_fts"
    assert result["found_count"] == 1
    assert "RegisterComponent" in result["results"][0]["snippet"]


def test_files_fts_match_error_falls_back_to_like(tmp_path, monkeypatch):
    source_root = tmp_path / "Plugin"
    _make_source_tree(source_root)
    db_path = tmp_path / "KnowledgeBase" / "global_index" / "files_fts.db"
    build_files_fts_index(source_root, db_path, force_disable_fts=True)

    index = FilesFtsIndex(db_path)
    index._fts_enabled = True

    def fail_match(keyword, limit):
        raise sqlite3.OperationalError("mock match failure")

    monkeypatch.setattr(index, "_search_fts", fail_match)
    result = index.search("BeginPlay", 10)
    index.close()

    assert result["fallback"] == "like_after_match_error"
    assert result["found_count"] == 1


def test_files_fts_falls_back_to_like_for_camel_substring(tmp_path):
    source_root = tmp_path / "Plugin"
    source = source_root / "Source" / "MyModule" / "Private"
    source.mkdir(parents=True)
    (source / "AtlasRegistry.cpp").write_text(
        "class AesMarkerAtlasBuilder { void Build(); };\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "KnowledgeBase" / "global_index" / "files_fts.db"

    stats = build_files_fts_index(source_root, db_path)
    result = search_files(db_path, "MarkerAtlas", limit=10)

    assert result["found_count"] == 1
    if stats["fts_enabled"]:
        assert result["fallback"] == "like_after_match_empty"
    else:
        assert result["fallback"] == "like_no_fts"
    assert result["results"][0]["ranking_reason"] == "like_fallback"
    assert "AesMarkerAtlasBuilder" in result["results"][0]["snippet"]


def test_files_fts_like_fallback_escapes_special_input(tmp_path):
    source_root = tmp_path / "Plugin"
    source = source_root / "Source" / "MyModule" / "Private"
    source.mkdir(parents=True)
    (source / "Special.cpp").write_text(
        "namespace N { void operator++(); const char* Token = \"Percent%Token Under_score\"; }\n",
        encoding="utf-8",
    )
    (source / "Plain.cpp").write_text("void PlainToken() {}\n", encoding="utf-8")
    db_path = tmp_path / "KnowledgeBase" / "global_index" / "files_fts.db"
    build_files_fts_index(source_root, db_path, force_disable_fts=True)

    percent = search_files(db_path, "%", limit=10)
    underscore = search_files(db_path, "_", limit=10)
    operator = search_files(db_path, "operator++", limit=10)
    namespace = search_files(db_path, "namespace", limit=10)

    assert percent["found_count"] == 1
    assert underscore["found_count"] == 1
    assert operator["found_count"] == 1
    assert namespace["found_count"] == 1
    assert all(row["path"].endswith("Special.cpp") for row in percent["results"])
    assert all(row["path"].endswith("Special.cpp") for row in underscore["results"])


def test_files_fts_skips_large_files(tmp_path):
    source_root = tmp_path / "Plugin"
    source = source_root / "Source" / "MyModule" / "Private"
    source.mkdir(parents=True)
    (source / "Huge.cpp").write_text("A" * 128, encoding="utf-8")
    db_path = tmp_path / "KnowledgeBase" / "global_index" / "files_fts.db"

    stats = build_files_fts_index(source_root, db_path, max_file_bytes=10)
    result = search_files(db_path, "AAAA", limit=10)

    assert stats["skipped"]["large_file"] == 1
    assert result["found_count"] == 0


def test_files_fts_skips_generated_dirs_case_insensitively(tmp_path):
    source_root = tmp_path / "Plugin"
    generated = source_root / "intermediate" / "Build"
    generated.mkdir(parents=True)
    (generated / "Generated.cpp").write_text("void ShouldNotIndex() {}", encoding="utf-8")
    db_path = tmp_path / "KnowledgeBase" / "global_index" / "files_fts.db"

    stats = build_files_fts_index(source_root, db_path)
    result = search_files(db_path, "ShouldNotIndex", limit=10)

    assert stats["skipped"]["skipped_directory"] == 1
    assert result["found_count"] == 0


def test_files_fts_skips_history_source_files(tmp_path):
    source_root = tmp_path / "Plugin"
    _make_source_tree(source_root)
    history_source = source_root / ".history" / "Source" / "MyModule" / "Private"
    history_source.mkdir(parents=True)
    (history_source / "Foo_20260526191300.cpp").write_text(
        "void ShouldNotIndexHistory() {}",
        encoding="utf-8",
    )
    db_path = tmp_path / "KnowledgeBase" / "global_index" / "files_fts.db"

    stats = build_files_fts_index(source_root, db_path)
    result = search_files(db_path, "ShouldNotIndexHistory", limit=10)

    assert stats["skipped"]["skipped_directory"] == 1
    assert result["found_count"] == 0


def test_files_fts_prunes_skipped_directories_before_descent(tmp_path, monkeypatch):
    source_root = tmp_path / "Plugin"
    visible = source_root / "Source" / "MyModule" / "Private"
    hidden = source_root / "Intermediate" / "Deep" / "Private"
    visible.mkdir(parents=True)
    hidden.mkdir(parents=True)
    (visible / "Visible.cpp").write_text("void ShouldIndex() {}", encoding="utf-8")
    (hidden / "Hidden.cpp").write_text("void ShouldNotEnter() {}", encoding="utf-8")
    db_path = tmp_path / "KnowledgeBase" / "global_index" / "files_fts.db"

    from ue5_kb.core import files_fts_index

    original_walk = files_fts_index.os.walk
    visited = []

    def walk_spy(*args, **kwargs):
        for current_dir, dirs, filenames in original_walk(*args, **kwargs):
            visited.append(Path(current_dir).relative_to(source_root).as_posix())
            yield current_dir, dirs, filenames

    monkeypatch.setattr(files_fts_index.os, "walk", walk_spy)
    stats = build_files_fts_index(source_root, db_path)
    result = search_files(db_path, "ShouldNotEnter", limit=10)

    assert "Intermediate" not in visited
    assert not any(path.startswith("Intermediate/") for path in visited)
    assert stats["skipped"]["skipped_directory"] == 1
    assert result["found_count"] == 0
