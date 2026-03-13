"""手動インポートパーサーのテスト"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import collect

FIXTURES = Path(__file__).parent / "fixtures"


class TestChatGPTParser:
    def test_parses_user_and_assistant(self):
        result = collect.parse_chatgpt_export(FIXTURES / "chatgpt_conversations.json")
        assert result["status"] == "インポート済み"
        roles = [m["role"] for m in result["messages"]]
        assert "user" in roles
        assert "assistant" in roles

    def test_skips_system_messages(self):
        result = collect.parse_chatgpt_export(FIXTURES / "chatgpt_conversations.json")
        roles = [m["role"] for m in result["messages"]]
        assert "system" not in roles

    def test_skips_null_messages(self):
        result = collect.parse_chatgpt_export(FIXTURES / "chatgpt_conversations.json")
        # Should not crash on null message nodes
        assert result["status"] == "インポート済み"

    def test_skips_non_text_content(self):
        result = collect.parse_chatgpt_export(FIXTURES / "chatgpt_conversations.json")
        texts = [m["text"] for m in result["messages"]]
        # image_asset_pointer should be skipped
        assert all(len(t) > 0 for t in texts)

    def test_has_assistant_messages_flag(self):
        result = collect.parse_chatgpt_export(FIXTURES / "chatgpt_conversations.json")
        assert result["has_assistant_messages"] is True

    def test_timestamp_source_is_message(self):
        result = collect.parse_chatgpt_export(FIXTURES / "chatgpt_conversations.json")
        for m in result["messages"]:
            assert m["timestamp_source"] == "message"

    def test_project_is_title(self):
        result = collect.parse_chatgpt_export(FIXTURES / "chatgpt_conversations.json")
        projects = set(m["project"] for m in result["messages"])
        assert "Test Conversation" in projects

    def test_has_period(self):
        result = collect.parse_chatgpt_export(FIXTURES / "chatgpt_conversations.json")
        assert result["period"] != ""
        assert "〜" in result["period"]


class TestClaudeAIParser:
    def test_parses_user_and_assistant(self):
        result = collect.parse_claude_ai_export(FIXTURES / "claude_ai_conversations.json")
        assert result["status"] == "インポート済み"
        roles = [m["role"] for m in result["messages"]]
        assert "user" in roles
        assert "assistant" in roles

    def test_role_normalization(self):
        result = collect.parse_claude_ai_export(FIXTURES / "claude_ai_conversations.json")
        roles = set(m["role"] for m in result["messages"])
        # "human" should be normalized to "user"
        assert "human" not in roles
        assert "user" in roles

    def test_has_assistant_messages_flag(self):
        result = collect.parse_claude_ai_export(FIXTURES / "claude_ai_conversations.json")
        assert result["has_assistant_messages"] is True

    def test_project_is_name(self):
        result = collect.parse_claude_ai_export(FIXTURES / "claude_ai_conversations.json")
        projects = set(m["project"] for m in result["messages"])
        assert "Claude Test Chat" in projects


class TestGeminiParser:
    def test_parses_user_and_model(self):
        result = collect.parse_gemini_export(FIXTURES / "gemini_export.json")
        assert result["status"] == "インポート済み"
        roles = [m["role"] for m in result["messages"]]
        assert "user" in roles
        assert "assistant" in roles

    def test_role_normalization(self):
        result = collect.parse_gemini_export(FIXTURES / "gemini_export.json")
        roles = set(m["role"] for m in result["messages"])
        # "model" should be normalized to "assistant"
        assert "model" not in roles

    def test_skips_thought_messages(self):
        result = collect.parse_gemini_export(FIXTURES / "gemini_export.json")
        texts = [m["text"] for m in result["messages"]]
        assert "internal reasoning..." not in texts

    def test_message_count(self):
        result = collect.parse_gemini_export(FIXTURES / "gemini_export.json")
        # 2 user + 2 model (1 thought skipped) = 4
        assert len(result["messages"]) == 4


class TestDetectAndParseImport:
    def test_detects_chatgpt(self):
        result = collect.detect_and_parse_import(FIXTURES / "chatgpt_conversations.json")
        assert result is not None
        assert "ChatGPT" in result["tool"]

    def test_detects_claude_ai(self):
        result = collect.detect_and_parse_import(FIXTURES / "claude_ai_conversations.json")
        assert result is not None
        assert "Claude.ai" in result["tool"]

    def test_detects_gemini(self):
        result = collect.detect_and_parse_import(FIXTURES / "gemini_export.json")
        assert result is not None
        assert "Gemini" in result["tool"]

    def test_returns_none_for_non_json(self):
        # Create a temp non-json file
        tmp = FIXTURES / "_test_plain.txt"
        tmp.write_text("Just plain text", encoding="utf-8")
        try:
            result = collect.detect_and_parse_import(tmp)
            assert result is None
        finally:
            tmp.unlink()


class TestDirectoryImport:
    """ディレクトリ一括読込のテスト"""

    def test_parses_all_json_in_directory(self):
        """fixtures ディレクトリ内の全 JSON を一括パース"""
        results = []
        for json_file in sorted(FIXTURES.rglob("*.json")):
            source = collect.detect_and_parse_import(json_file)
            if source and source["messages"]:
                results.append(source)
        # fixtures に chatgpt, claude_ai, gemini の3ファイルがある
        assert len(results) == 3
        tool_names = " ".join(r["tool"] for r in results)
        assert "ChatGPT" in tool_names
        assert "Claude.ai" in tool_names
        assert "Gemini" in tool_names

    def test_skips_non_parseable_files(self):
        """パース不能な JSON はスキップされる"""
        tmp = FIXTURES / "_test_invalid.json"
        tmp.write_text('{"random_key": 123}', encoding="utf-8")
        try:
            source = collect.detect_and_parse_import(tmp)
            assert source is None
        finally:
            tmp.unlink()

    def test_directory_import_cli(self):
        """CLI の --import-file でディレクトリを渡す E2E テスト"""
        import subprocess
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent.parent / "scripts" / "collect.py"),
             "--import-file", str(FIXTURES), "--days", "0"],
            capture_output=True, encoding="utf-8"
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["summary"]["total_messages"] > 0
        assert len(data["sources"]) == 3
