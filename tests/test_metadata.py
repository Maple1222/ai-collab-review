"""コレクターメタデータのテスト（project_filter_support, has_assistant_messages, timestamp_source）"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import collect


class TestCollectorMetadata:
    """各コレクターが正しいメタデータを返すことを確認"""

    def test_claude_code_metadata(self):
        with patch.object(collect, "get_claude_dir", return_value=Path("/nonexistent")):
            result = collect.collect_claude_code(None, None)
        assert result["project_filter_support"] == "full"
        assert result["has_assistant_messages"] is False

    def test_copilot_metadata(self):
        with patch.object(collect, "get_appdata_path", return_value=Path("/nonexistent")):
            result = collect.collect_copilot_chat(None, None)
        assert result["project_filter_support"] == "none"
        assert result["has_assistant_messages"] is False

    def test_cline_metadata(self):
        with patch.object(collect, "get_appdata_path", return_value=Path("/nonexistent")):
            result = collect.collect_cline(None)
        assert result["project_filter_support"] == "none"
        assert result["has_assistant_messages"] is False

    def test_roo_metadata(self):
        with patch.object(collect, "get_appdata_path", return_value=Path("/nonexistent")):
            result = collect.collect_roo_code(None)
        assert result["project_filter_support"] == "none"
        assert result["has_assistant_messages"] is False

    def test_windsurf_metadata(self):
        result = collect.collect_windsurf(None)
        assert result["project_filter_support"] == "partial"
        assert result["has_assistant_messages"] is False

    def test_antigravity_metadata(self):
        result = collect.collect_antigravity(None)
        assert result["project_filter_support"] == "partial"
        assert result["has_assistant_messages"] is False


class TestImportMetadata:
    """インポートパーサーが正しいメタデータを返すことを確認"""

    FIXTURES = Path(__file__).parent / "fixtures"

    def test_chatgpt_has_assistant(self):
        result = collect.parse_chatgpt_export(self.FIXTURES / "chatgpt_conversations.json")
        assert result["has_assistant_messages"] is True

    def test_claude_ai_has_assistant(self):
        result = collect.parse_claude_ai_export(self.FIXTURES / "claude_ai_conversations.json")
        assert result["has_assistant_messages"] is True

    def test_gemini_has_assistant(self):
        result = collect.parse_gemini_export(self.FIXTURES / "gemini_export.json")
        assert result["has_assistant_messages"] is True
