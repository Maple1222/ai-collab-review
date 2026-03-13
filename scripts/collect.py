#!/usr/bin/env python3
"""
AI協働レビュー データ収集スクリプト

対話履歴を各AIツールから収集し、分析用に整形して標準出力にJSON形式で出力する。

対応ツール:
  - Claude Code (CLI / VS Code拡張)
  - GitHub Copilot Chat
  - Cline
  - Roo Code
  - Windsurf (Cascade)
  - Google Antigravity

使い方:
    python collect.py                          # 全プロジェクト、過去30日（デフォルト）
    python collect.py --days 30                # 過去30日分
    python collect.py --project yonshogen      # 特定プロジェクト
    python collect.py --project yonshogen --days 30

Credits:
    データ収集ロジックは tokoroten/prompt-review の collect.py を基に、
    手動インポート対応・エンコーディング改善等を加えて移植したものです。

    Original code:
      Copyright (c) tokoroten/prompt-review
      Licensed under MIT License
      https://github.com/tokoroten/prompt-review
"""

import argparse
import json
import os
import platform
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# クレデンシャル・シークレット検出パターン
# ---------------------------------------------------------------------------
SECRET_PATTERNS = [
    (r'(?i)(api[_-]?key|apikey)\s*[:=]\s*\S+', "API Key"),
    (r'(?i)(secret|token|password|passwd|pwd)\s*[:=]\s*\S+', "Secret/Token/Password"),
    (r'(?i)(access[_-]?key|secret[_-]?key)\s*[:=]\s*\S+', "Access Key"),
    (r'(?i)(bearer\s+)[A-Za-z0-9\-._~+/]+=*', "Bearer Token"),
    (r'sk-[A-Za-z0-9]{20,}', "OpenAI API Key"),
    (r'sk-ant-[A-Za-z0-9\-]{20,}', "Anthropic API Key"),
    (r'ghp_[A-Za-z0-9]{36,}', "GitHub Personal Access Token"),
    (r'gho_[A-Za-z0-9]{36,}', "GitHub OAuth Token"),
    (r'AIza[A-Za-z0-9\-_]{35}', "Google API Key"),
    (r'(?i)aws[_-]?(access|secret)[_-]?key\S*\s*[:=]\s*\S+', "AWS Key"),
    (r'xox[bpras]-[A-Za-z0-9\-]{10,}', "Slack Token"),
    (r'-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----', "Private Key"),
    (r'(?i)(mongodb(\+srv)?://)\S+:\S+@', "MongoDB Connection String"),
    (r'(?i)(postgres(ql)?://)\S+:\S+@', "PostgreSQL Connection String"),
    (r'(?i)(mysql://)\S+:\S+@', "MySQL Connection String"),
]
_compiled_patterns = [(re.compile(p), label) for p, label in SECRET_PATTERNS]


def scan_secrets(text: str) -> list:
    """テキスト内のクレデンシャル・シークレットを検出する"""
    findings = []
    for pattern, label in _compiled_patterns:
        for match in pattern.finditer(text):
            matched = match.group()
            if len(matched) > 16:
                masked = matched[:8] + "***" + matched[-4:]
            else:
                masked = matched[:4] + "***"
            findings.append({
                "type": label,
                "masked_value": masked,
                "start": match.start(),
                "end": match.end(),
            })
    return findings


def redact_text(text: str) -> tuple:
    """テキスト内のシークレットを検出し、マスク済みテキストとfindingsを返す"""
    findings = scan_secrets(text)
    if not findings:
        return text, []
    # 後ろから置換して位置ズレを防ぐ
    redacted = text
    for f in sorted(findings, key=lambda x: x["start"], reverse=True):
        redacted = redacted[:f["start"]] + f["masked_value"] + redacted[f["end"]:]
    return redacted, findings


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------
def get_appdata_path() -> Path:
    system = platform.system()
    if system == "Windows":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif system == "Darwin":
        return Path.home() / "Library" / "Application Support"
    else:
        return Path.home() / ".config"


def get_claude_dir() -> Path:
    return Path.home() / ".claude"


def ts_to_iso(ts_ms) -> str:
    try:
        return datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    except (OSError, ValueError, TypeError):
        return "unknown"


def iso_to_ms(iso_str: str):
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except (ValueError, AttributeError):
        return None


def sanitize_text(text: str) -> str:
    return text.encode("utf-8", errors="replace").decode("utf-8")


def extract_user_text(content) -> str:
    if isinstance(content, str):
        return sanitize_text(content.strip())
    elif isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text", "")
                if re.match(r'^<(ide_opened_file|ide_selection|local-command-caveat|local-command-stdout|system-reminder)\b', text):
                    continue
                parts.append(text)
            elif isinstance(item, dict) and item.get("type") == "tool_result":
                continue
        return sanitize_text(" ".join(parts).strip())
    return ""


# ---------------------------------------------------------------------------
# 各ツールからの収集
# ---------------------------------------------------------------------------
def collect_claude_code(cutoff_ms, project_filter) -> dict:
    """Claude Code の history.jsonl およびプロジェクト別セッションファイルから収集"""
    result = {"tool": "Claude Code", "status": "未検出", "messages": [], "period": "",
              "project_filter_support": "full", "has_assistant_messages": False}
    claude_dir = get_claude_dir()
    messages = []
    seen_texts = set()
    skip_patterns = ["/clear", "/help"]

    # ソース1: history.jsonl
    history_path = claude_dir / "history.jsonl"
    collected_session_ids = set()

    if history_path.exists():
        with open(history_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                display = entry.get("display", "").strip()
                timestamp = entry.get("timestamp")
                project = entry.get("project", "")
                session_id = entry.get("sessionId", "")

                if session_id:
                    collected_session_ids.add(session_id)
                if not display:
                    continue
                if any(display.startswith(p) for p in skip_patterns):
                    continue

                stripped = display.replace("\\", "/")
                if display.count("\n") == 0 and len(display) < 300:
                    if stripped.startswith(("/", "C:", "D:", "c:", "d:")) and " " not in stripped and len(stripped.split("/")) > 2:
                        continue

                if cutoff_ms and timestamp and timestamp < cutoff_ms:
                    continue
                if project_filter:
                    project_name = Path(project).name.lower() if project else ""
                    if project_filter.lower() not in project_name:
                        continue

                dedup_key = f"{timestamp}:{display[:100]}"
                seen_texts.add(dedup_key)
                messages.append({
                    "text": display[:500],
                    "timestamp": ts_to_iso(timestamp) if timestamp else "unknown",
                    "timestamp_ms": timestamp or 0,
                    "project": Path(project).name if project else "unknown",
                    "timestamp_source": "message",
                })

    # ソース2: プロジェクト別セッションJSONL
    projects_dir = claude_dir / "projects"
    if projects_dir.exists():
        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue

            dir_name = project_dir.name
            project_name_from_dir = dir_name.rsplit("-", 1)[-1] if "-" in dir_name else dir_name
            if project_filter and project_filter.lower() not in project_name_from_dir.lower():
                if project_filter.lower().replace(" ", "-") not in dir_name.lower():
                    continue

            session_files = sorted(
                [f for f in project_dir.glob("*.jsonl") if f.is_file()],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:50]

            for session_file in session_files:
                session_id = session_file.stem
                if session_id in collected_session_ids:
                    continue
                if cutoff_ms:
                    file_mtime_ms = int(session_file.stat().st_mtime * 1000)
                    if file_mtime_ms < cutoff_ms:
                        continue

                try:
                    msg_count = 0
                    with open(session_file, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                entry = json.loads(line)
                            except json.JSONDecodeError:
                                continue

                            if entry.get("type") != "user":
                                continue
                            if entry.get("isMeta"):
                                continue

                            message = entry.get("message", {})
                            content = message.get("content", "")
                            text = extract_user_text(content)

                            if not text:
                                continue
                            if any(text.startswith(p) for p in skip_patterns):
                                continue

                            ts_str = entry.get("timestamp", "")
                            ts_ms = iso_to_ms(ts_str) if ts_str else None
                            if cutoff_ms and ts_ms and ts_ms < cutoff_ms:
                                continue

                            ts_display = ts_to_iso(ts_ms) if ts_ms else "unknown"
                            dedup_key = f"{ts_ms}:{text[:100]}"
                            if dedup_key in seen_texts:
                                continue
                            seen_texts.add(dedup_key)

                            cwd = entry.get("cwd", "")
                            proj_name = Path(cwd).name if cwd else project_name_from_dir

                            messages.append({
                                "text": text[:500],
                                "timestamp": ts_display,
                                "timestamp_ms": ts_ms or 0,
                                "project": proj_name,
                                "timestamp_source": "message" if ts_ms else "file_mtime",
                            })
                            msg_count += 1
                            if msg_count >= 100:
                                break
                except (OSError, UnicodeDecodeError):
                    continue

    if messages:
        result["status"] = "検出"
        result["messages"] = messages
        timestamps = [m["timestamp"] for m in messages if m["timestamp"] != "unknown"]
        if timestamps:
            result["period"] = f"{min(timestamps)} 〜 {max(timestamps)}"

    return result


def collect_copilot_chat(cutoff_ms, project_filter) -> dict:
    """GitHub Copilot Chat の state.vscdb からプロンプトを収集
    注意: project_filter はワークスペースハッシュしかないため非対応"""
    result = {"tool": "GitHub Copilot Chat", "status": "未検出", "messages": [], "period": "",
              "project_filter_support": "none", "has_assistant_messages": False}
    appdata = get_appdata_path()
    workspace_storage = appdata / "Code" / "User" / "workspaceStorage"
    if not workspace_storage.exists():
        return result

    all_prompts = []
    for vscdb_path in workspace_storage.glob("*/state.vscdb"):
        try:
            conn = sqlite3.connect(str(vscdb_path))
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM ItemTable WHERE key = 'memento/interactive-session'")
            row = cursor.fetchone()
            if row and row[0]:
                try:
                    data = json.loads(row[0])
                    history = data.get("history", {})
                    for mode_key, entries in history.items():
                        if isinstance(entries, list):
                            for entry in entries:
                                text = entry.get("text", "").strip()
                                if text:
                                    file_mtime_ms = int(vscdb_path.stat().st_mtime * 1000)
                                    if cutoff_ms and file_mtime_ms < cutoff_ms:
                                        continue
                                    all_prompts.append({
                                        "text": text[:500],
                                        "timestamp": ts_to_iso(file_mtime_ms),
                                        "timestamp_ms": file_mtime_ms,
                                        "project": vscdb_path.parent.name[:12],
                                        "timestamp_source": "file_mtime",
                                    })
                except (json.JSONDecodeError, AttributeError):
                    pass
            conn.close()
        except sqlite3.Error:
            continue

    if all_prompts:
        result["status"] = "検出"
        result["messages"] = all_prompts
        timestamps = [m["timestamp"] for m in all_prompts if m["timestamp"] != "unknown"]
        if timestamps:
            result["period"] = f"{min(timestamps)} 〜 {max(timestamps)}"
    return result


def collect_cline(cutoff_ms, project_filter=None) -> dict:
    """Cline の api_conversation_history.json からプロンプトを収集"""
    result = {"tool": "Cline", "status": "未検出", "messages": [], "period": "",
              "project_filter_support": "none", "has_assistant_messages": False}
    appdata = get_appdata_path()
    tasks_dir = appdata / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "tasks"
    if not tasks_dir.exists():
        return result

    all_prompts = []
    task_dirs = sorted(tasks_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:20]
    for task_dir in task_dirs:
        history_file = task_dir / "api_conversation_history.json"
        if not history_file.exists():
            continue
        if cutoff_ms:
            file_mtime_ms = int(history_file.stat().st_mtime * 1000)
            if file_mtime_ms < cutoff_ms:
                continue
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for msg in data:
                if msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        text = " ".join(c.get("text", "") for c in content if c.get("type") == "text")
                    else:
                        text = str(content)
                    text = text.strip()
                    if text:
                        file_mtime_ms = int(history_file.stat().st_mtime * 1000)
                        all_prompts.append({
                            "text": text[:500], "timestamp": ts_to_iso(file_mtime_ms),
                            "timestamp_ms": file_mtime_ms, "project": task_dir.name[:12],
                            "timestamp_source": "file_mtime",
                        })
        except (json.JSONDecodeError, OSError):
            continue

    if all_prompts:
        result["status"] = "検出"
        result["messages"] = all_prompts
        timestamps = [m["timestamp"] for m in all_prompts if m["timestamp"] != "unknown"]
        if timestamps:
            result["period"] = f"{min(timestamps)} 〜 {max(timestamps)}"
    return result


def collect_roo_code(cutoff_ms, project_filter=None) -> dict:
    """Roo Code の会話履歴を収集"""
    result = {"tool": "Roo Code", "status": "未検出", "messages": [], "period": "",
              "project_filter_support": "none", "has_assistant_messages": False}
    appdata = get_appdata_path()
    tasks_dir = appdata / "Code" / "User" / "globalStorage" / "RooVeterinaryInc.roo-cline" / "tasks"
    if not tasks_dir.exists():
        return result

    all_prompts = []
    task_dirs = sorted(tasks_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:20]
    for task_dir in task_dirs:
        history_file = task_dir / "api_conversation_history.json"
        if not history_file.exists():
            continue
        if cutoff_ms:
            file_mtime_ms = int(history_file.stat().st_mtime * 1000)
            if file_mtime_ms < cutoff_ms:
                continue
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for msg in data:
                if msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        text = " ".join(c.get("text", "") for c in content if c.get("type") == "text")
                    else:
                        text = str(content)
                    text = text.strip()
                    if text:
                        file_mtime_ms = int(history_file.stat().st_mtime * 1000)
                        all_prompts.append({
                            "text": text[:500], "timestamp": ts_to_iso(file_mtime_ms),
                            "timestamp_ms": file_mtime_ms, "project": task_dir.name[:12],
                            "timestamp_source": "file_mtime",
                        })
        except (json.JSONDecodeError, OSError):
            continue

    if all_prompts:
        result["status"] = "検出"
        result["messages"] = all_prompts
        timestamps = [m["timestamp"] for m in all_prompts if m["timestamp"] != "unknown"]
        if timestamps:
            result["period"] = f"{min(timestamps)} 〜 {max(timestamps)}"
    return result


def collect_windsurf(cutoff_ms, project_filter=None) -> dict:
    """Windsurf のメモリファイルを収集"""
    result = {"tool": "Windsurf", "status": "未検出", "messages": [], "period": "",
              "project_filter_support": "partial", "has_assistant_messages": False}
    memories_dir = Path.home() / ".codeium" / "windsurf" / "memories"
    if not memories_dir.exists():
        return result

    all_entries = []
    for mem_file in sorted(memories_dir.rglob("*"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
        if not mem_file.is_file():
            continue
        proj_name = mem_file.parent.name
        if project_filter and project_filter.lower() not in proj_name.lower():
            continue
        if cutoff_ms:
            file_mtime_ms = int(mem_file.stat().st_mtime * 1000)
            if file_mtime_ms < cutoff_ms:
                continue
        try:
            text = mem_file.read_text(encoding="utf-8").strip()
            if text:
                file_mtime_ms = int(mem_file.stat().st_mtime * 1000)
                all_entries.append({
                    "text": text[:500], "timestamp": ts_to_iso(file_mtime_ms),
                    "timestamp_ms": file_mtime_ms, "project": proj_name,
                    "timestamp_source": "file_mtime",
                    "source_type": "auto_summary",
                    "note": "Cascadeの自動要約メモリ（元のプロンプトではない）",
                })
        except (OSError, UnicodeDecodeError):
            continue

    if all_entries:
        result["status"] = "検出"
        result["messages"] = all_entries
        timestamps = [m["timestamp"] for m in all_entries if m["timestamp"] != "unknown"]
        if timestamps:
            result["period"] = f"{min(timestamps)} 〜 {max(timestamps)}"
    return result


def collect_antigravity(cutoff_ms, project_filter=None) -> dict:
    """Google Antigravity のログを収集"""
    result = {"tool": "Google Antigravity", "status": "未検出", "messages": [], "period": "",
              "project_filter_support": "partial", "has_assistant_messages": False}
    brain_dir = Path.home() / ".gemini" / "antigravity" / "brain"
    if not brain_dir.exists():
        return result

    all_entries = []
    for log_dir in brain_dir.glob("*/.system_generated/logs"):
        proj_name = log_dir.parent.parent.name
        if project_filter and project_filter.lower() not in proj_name.lower():
            continue
        for log_file in sorted(log_dir.rglob("*"), key=lambda p: p.stat().st_mtime, reverse=True)[:10]:
            if not log_file.is_file() or log_file.suffix == ".pb":
                continue
            if cutoff_ms:
                file_mtime_ms = int(log_file.stat().st_mtime * 1000)
                if file_mtime_ms < cutoff_ms:
                    continue
            try:
                text = log_file.read_text(encoding="utf-8").strip()
                if text:
                    file_mtime_ms = int(log_file.stat().st_mtime * 1000)
                    all_entries.append({
                        "text": text[:500], "timestamp": ts_to_iso(file_mtime_ms),
                        "timestamp_ms": file_mtime_ms, "project": proj_name[:12],
                        "timestamp_source": "file_mtime",
                    })
            except (OSError, UnicodeDecodeError):
                continue

    if all_entries:
        result["status"] = "検出"
        result["messages"] = all_entries
        timestamps = [m["timestamp"] for m in all_entries if m["timestamp"] != "unknown"]
        if timestamps:
            result["period"] = f"{min(timestamps)} 〜 {max(timestamps)}"
    return result


# ---------------------------------------------------------------------------
# 手動インポートパーサー
# ---------------------------------------------------------------------------
def parse_chatgpt_export(file_path: Path) -> dict:
    """ChatGPT conversations.json をパースする（user + assistant 両方）"""
    result = {"tool": "ChatGPT（手動インポート）", "status": "未検出", "messages": [], "period": "",
              "project_filter_support": "full", "has_assistant_messages": True}
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        return result

    for conv in data:
        title = conv.get("title", "unknown")
        mapping = conv.get("mapping", {})
        for node in mapping.values():
            msg = node.get("message")
            if msg is None:
                continue
            role = msg.get("author", {}).get("role", "")
            if role not in ("user", "assistant"):
                continue
            content = msg.get("content", {})
            if content.get("content_type") != "text":
                continue
            parts = content.get("parts", [])
            text = " ".join(str(p) for p in parts if isinstance(p, str)).strip()
            if not text:
                continue
            create_time = msg.get("create_time")
            if create_time:
                ts_ms = int(float(create_time) * 1000)
                ts_display = ts_to_iso(ts_ms)
            else:
                ts_ms = 0
                ts_display = "unknown"
            result["messages"].append({
                "text": sanitize_text(text),
                "role": "user" if role == "user" else "assistant",
                "timestamp": ts_display,
                "timestamp_ms": ts_ms,
                "project": title,
                "timestamp_source": "message",
            })

    if result["messages"]:
        result["status"] = "インポート済み"
        timestamps = [m["timestamp"] for m in result["messages"] if m["timestamp"] != "unknown"]
        if timestamps:
            result["period"] = f"{min(timestamps)} 〜 {max(timestamps)}"
    return result


def parse_claude_ai_export(file_path: Path) -> dict:
    """Claude.ai conversations.json をパースする（user + assistant 両方）"""
    result = {"tool": "Claude.ai（手動インポート）", "status": "未検出", "messages": [], "period": "",
              "project_filter_support": "full", "has_assistant_messages": True}
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        return result

    for conv in data:
        name = conv.get("name", "unknown")
        for chat_msg in conv.get("chat_messages", []):
            sender = chat_msg.get("sender", "")
            if sender not in ("human", "assistant"):
                continue
            text = chat_msg.get("text", "").strip()
            if not text:
                continue
            created_at = chat_msg.get("created_at", "")
            ts_ms = iso_to_ms(created_at) if created_at else None
            result["messages"].append({
                "text": sanitize_text(text),
                "role": "user" if sender == "human" else "assistant",
                "timestamp": ts_to_iso(ts_ms) if ts_ms else "unknown",
                "timestamp_ms": ts_ms or 0,
                "project": name,
                "timestamp_source": "message",
            })

    if result["messages"]:
        result["status"] = "インポート済み"
        timestamps = [m["timestamp"] for m in result["messages"] if m["timestamp"] != "unknown"]
        if timestamps:
            result["period"] = f"{min(timestamps)} 〜 {max(timestamps)}"
    return result


def parse_gemini_export(file_path: Path) -> dict:
    """Gemini エクスポート JSON をパースする（user + model 両方）"""
    result = {"tool": "Gemini（手動インポート）", "status": "未検出", "messages": [], "period": "",
              "project_filter_support": "none", "has_assistant_messages": True}
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 単一会話 or 会話リスト
    conversations = data if isinstance(data, list) else [data]

    for conv in conversations:
        conv_time = conv.get("createdTime", "")
        ts_base = iso_to_ms(conv_time) if conv_time else None
        conv_id = conv.get("id", "unknown")
        for msg in conv.get("messages", []):
            role = msg.get("role", "")
            if role not in ("user", "model"):
                continue
            if msg.get("isThought"):
                continue
            parts = msg.get("parts", [])
            text = " ".join(p.get("text", "") for p in parts if isinstance(p, dict) and "text" in p).strip()
            if not text:
                continue
            result["messages"].append({
                "text": sanitize_text(text),
                "role": "user" if role == "user" else "assistant",
                "timestamp": ts_to_iso(ts_base) if ts_base else "unknown",
                "timestamp_ms": ts_base or 0,
                "project": conv_id[:12],
                "timestamp_source": "message" if ts_base else "unknown",
            })

    if result["messages"]:
        result["status"] = "インポート済み"
        timestamps = [m["timestamp"] for m in result["messages"] if m["timestamp"] != "unknown"]
        if timestamps:
            result["period"] = f"{min(timestamps)} 〜 {max(timestamps)}"
    return result


def detect_and_parse_import(file_path: Path) -> dict:
    """ファイルのフォーマットを自動判定してパースする"""
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None  # JSON でなければ SKILL.md の LLM パースにフォールバック

    # ChatGPT: mapping キーを持つ会話配列
    if isinstance(data, list) and data and "mapping" in data[0]:
        return parse_chatgpt_export(file_path)
    # Claude.ai: chat_messages キーを持つ会話配列
    if isinstance(data, list) and data and "chat_messages" in data[0]:
        return parse_claude_ai_export(file_path)
    # Gemini: messages キーを持つ
    if isinstance(data, dict) and "messages" in data:
        return parse_gemini_export(file_path)
    if isinstance(data, list) and data and "messages" in data[0]:
        return parse_gemini_export(file_path)

    return None


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="AI対話履歴を収集・整形して出力する")
    parser.add_argument("--days", type=int, default=30, help="過去N日分に限定（0=全期間、デフォルト: 30）")
    parser.add_argument("--project", type=str, default=None, help="プロジェクト名でフィルタ（部分一致）")
    parser.add_argument("--output", type=str, default=None,
                        help="出力先ファイルパス（省略時は標準出力）")
    parser.add_argument("--import-file", type=str, default=None,
                        help="エクスポートファイルまたはディレクトリをインポート（ChatGPT/Claude.ai/Gemini JSON）")
    args = parser.parse_args()

    cutoff_ms = None
    if args.days and args.days > 0:
        cutoff_dt = datetime.now(tz=timezone.utc) - timedelta(days=args.days)
        cutoff_ms = int(cutoff_dt.timestamp() * 1000)

    # インポートモード
    if args.import_file:
        import_path = Path(args.import_file)
        if not import_path.exists():
            print(f"Error: file not found: {args.import_file}", file=sys.stderr)
            sys.exit(1)

        if import_path.is_dir():
            # ディレクトリ一括読込: .json ファイルを再帰走査
            sources = []
            parsed_count = 0
            skipped_files = []
            for json_file in sorted(import_path.rglob("*.json")):
                source = detect_and_parse_import(json_file)
                if source and source["messages"]:
                    if cutoff_ms:
                        source["messages"] = [
                            m for m in source["messages"]
                            if m.get("timestamp_ms", 0) >= cutoff_ms
                        ]
                    sources.append(source)
                    parsed_count += 1
                else:
                    skipped_files.append(json_file.name)
            if not sources:
                print(f"Error: no parseable JSON files found in {args.import_file}", file=sys.stderr)
                if skipped_files:
                    print(f"Skipped: {', '.join(skipped_files[:10])}", file=sys.stderr)
                sys.exit(1)
            print(f"Parsed {parsed_count} files, skipped {len(skipped_files)}", file=sys.stderr)
        else:
            # 単一ファイル
            source = detect_and_parse_import(import_path)
            if source is None:
                print("Error: unsupported file format (JSON with mapping/chat_messages/messages required)",
                      file=sys.stderr)
                sys.exit(1)
            if cutoff_ms:
                source["messages"] = [m for m in source["messages"] if m.get("timestamp_ms", 0) >= cutoff_ms]
            sources = [source]
    else:
        sources = [
            collect_claude_code(cutoff_ms, args.project),
            collect_copilot_chat(cutoff_ms, args.project),
            collect_cline(cutoff_ms, args.project),
            collect_roo_code(cutoff_ms, args.project),
            collect_windsurf(cutoff_ms, args.project),
            collect_antigravity(cutoff_ms, args.project),
        ]

    total_messages = sum(len(s["messages"]) for s in sources)
    detected = [s["tool"] for s in sources if s["status"] in ("検出", "インポート済み")]

    # project_filter 非対応ソースの警告
    unfiltered_sources = []
    if args.project:
        for s in sources:
            if s["status"] == "検出" and s.get("project_filter_support") in ("none", None):
                unfiltered_sources.append(s["tool"])

    output = {
        "summary": {
            "total_messages": total_messages,
            "detected_tools": detected,
            "filter_days": args.days if args.days > 0 else None,
            "filter_project": args.project,
            "collected_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "project_filter_unsupported": unfiltered_sources if unfiltered_sources else None,
            "sampling_limits": {
                "text_truncation_chars": 500,
                "claude_code_session_files": 50,
                "claude_code_messages_per_session": 100,
                "cline_roo_tasks": 20,
                "windsurf_files": 20,
                "antigravity_logs": 10,
            },
        },
        "sources": sources,
    }

    # シークレット検出 + 本文レダクション
    secret_warnings = []
    for source in sources:
        for msg in source["messages"]:
            redacted, findings = redact_text(msg["text"])
            if findings:
                msg["text"] = redacted  # 本文自体をレダクト済みに置換
                for f in findings:
                    secret_warnings.append({
                        "tool": source["tool"],
                        "project": msg.get("project", "unknown"),
                        "timestamp": msg.get("timestamp", "unknown"),
                        "type": f["type"],
                        "masked_value": f["masked_value"],
                        "prompt_excerpt": redacted[:80].replace("\n", " "),
                    })
    output["secret_warnings"] = secret_warnings

    project_stats = {}
    for source in sources:
        for msg in source["messages"]:
            proj = msg.get("project", "unknown")
            if proj not in project_stats:
                project_stats[proj] = {"count": 0, "tools": set()}
            project_stats[proj]["count"] += 1
            project_stats[proj]["tools"].add(source["tool"])
    output["project_stats"] = {
        k: {"count": v["count"], "tools": list(v["tools"])}
        for k, v in sorted(project_stats.items(), key=lambda x: -x[1]["count"])
    }

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(str(out_path), file=sys.stderr)
    else:
        if sys.platform == "win32":
            sys.stdout.reconfigure(encoding="utf-8")
        json.dump(output, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
