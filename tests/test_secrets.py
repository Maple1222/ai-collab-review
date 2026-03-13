"""シークレット検出とレダクションのテスト"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import collect


class TestScanSecrets:
    def test_openai_key(self):
        text = "My key is sk-abcdefghijklmnopqrstuvwxyz1234567890"
        findings = collect.scan_secrets(text)
        assert len(findings) >= 1
        types = [f["type"] for f in findings]
        assert "OpenAI API Key" in types

    def test_anthropic_key(self):
        text = "token: sk-ant-abcdefghijklmnopqrstuvwxyz"
        findings = collect.scan_secrets(text)
        assert len(findings) >= 1
        types = [f["type"] for f in findings]
        assert "Anthropic API Key" in types

    def test_github_pat(self):
        text = "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890ab"
        findings = collect.scan_secrets(text)
        assert len(findings) >= 1
        types = [f["type"] for f in findings]
        assert "GitHub Personal Access Token" in types

    def test_bearer_token(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc"
        findings = collect.scan_secrets(text)
        assert len(findings) >= 1

    def test_no_secrets(self):
        text = "This is a normal message with no secrets"
        findings = collect.scan_secrets(text)
        assert len(findings) == 0

    def test_connection_string(self):
        text = "mongodb+srv://user:password123@cluster.mongodb.net/db"
        findings = collect.scan_secrets(text)
        assert len(findings) >= 1

    def test_findings_have_spans(self):
        text = "key: sk-abcdefghijklmnopqrstuvwxyz1234567890"
        findings = collect.scan_secrets(text)
        assert len(findings) >= 1
        for f in findings:
            assert "start" in f
            assert "end" in f
            assert f["start"] < f["end"]


class TestRedactText:
    def test_redacts_secret_in_text(self):
        text = "My API key is sk-abcdefghijklmnopqrstuvwxyz1234567890 please use it"
        redacted, findings = collect.redact_text(text)
        assert "sk-abcdefghijklmnopqrstuvwxyz1234567890" not in redacted
        assert "please use it" in redacted
        assert len(findings) >= 1

    def test_no_secrets_returns_original(self):
        text = "Just a normal message"
        redacted, findings = collect.redact_text(text)
        assert redacted == text
        assert len(findings) == 0

    def test_multiple_secrets(self):
        text = "key1: sk-aaaaaaaaaaaaaaaaaaaabbbbbbbbbb key2: ghp_cccccccccccccccccccccccccccccccccccccc"
        redacted, findings = collect.redact_text(text)
        assert "sk-aaaaaaaaaaaaaaaaaaaabbbbbbbbbb" not in redacted
        assert "ghp_cccccccccccccccccccccccccccccccccccccc" not in redacted
        assert len(findings) >= 2

    def test_masked_value_in_redacted(self):
        text = "sk-abcdefghijklmnopqrstuvwxyz1234567890"
        redacted, findings = collect.redact_text(text)
        # masked_value should appear in redacted text
        assert findings[0]["masked_value"] in redacted
