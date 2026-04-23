"""Tests for promptlog: structured LLM interaction logging."""
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import promptlog as pl


class TestPromptRecord:
    def test_hashing_is_deterministic(self):
        r1 = pl.PromptRecord(prompt="hello", response="world")
        r2 = pl.PromptRecord(prompt="hello", response="world")
        assert r1.prompt_hash == r2.prompt_hash
        assert r1.response_hash == r2.response_hash

    def test_different_prompts_have_different_hashes(self):
        r1 = pl.PromptRecord(prompt="foo", response="bar")
        r2 = pl.PromptRecord(prompt="baz", response="bar")
        assert r1.prompt_hash != r2.prompt_hash

    def test_hash_length(self):
        r = pl.PromptRecord(prompt="test", response="result", model="gpt-4")
        assert len(r.prompt_hash) == 64
        assert len(r.response_hash) == 64

    def test_model_field(self):
        r = pl.PromptRecord(prompt="p", response="r", model="claude-3")
        assert r.model == "claude-3"

    def test_tags_default_empty(self):
        r = pl.PromptRecord(prompt="p", response="r")
        assert r.tags == []


class TestPromptLoggerSQLite:
    def test_log_and_search(self, tmp_path):
        db = str(tmp_path / "test.db")
        with pl.PromptLogger(db, backend="sqlite") as logger:
            rid = logger.log("what is AI?", "AI stands for...", model="gpt-4")
            assert isinstance(rid, int)
            results = logger.search(query="AI")
            assert any("AI" in r.get("prompt", "") for r in results)

    def test_multiple_records(self, tmp_path):
        db = str(tmp_path / "multi.db")
        with pl.PromptLogger(db, backend="sqlite") as logger:
            logger.log("q1", "a1", model="gpt-4")
            logger.log("q2", "a2", model="claude-3")
            all_results = logger.search(limit=10)
            assert len(all_results) == 2

    def test_search_by_model(self, tmp_path):
        db = str(tmp_path / "model.db")
        with pl.PromptLogger(db, backend="sqlite") as logger:
            logger.log("q1", "a1", model="gpt-4")
            logger.log("q2", "a2", model="claude-3")
            gpt_results = logger.search(model="gpt-4")
            assert all(r.get("model") == "gpt-4" for r in gpt_results)

    def test_context_manager(self, tmp_path):
        db = str(tmp_path / "ctx.db")
        with pl.PromptLogger(db, backend="sqlite") as logger:
            assert logger is not None


class TestPromptLoggerJSONL:
    def test_jsonl_creates_file(self, tmp_path):
        jl = str(tmp_path / "log.jsonl")
        with pl.PromptLogger(jl, backend="jsonl") as logger:
            logger.log("hello", "world")
        assert pathlib.Path(jl).exists()

    def test_jsonl_valid_json_lines(self, tmp_path):
        jl = str(tmp_path / "log2.jsonl")
        with pl.PromptLogger(jl, backend="jsonl") as logger:
            logger.log("prompt text", "response text", model="test-model")
        lines = pathlib.Path(jl).read_text().strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["prompt"] == "prompt text"
        assert record["model"] == "test-model"
