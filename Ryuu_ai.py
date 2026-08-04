"""
ryuu_gui.py — Ryuu (AI Explainer & Coding Assistant) — Tkinter GUI
Local chatbot powered by Ollama, built to explain things clearly, debug code,
and write code in whatever language you need.

Features:
  - Multiple, separate conversation threads (like ChatGPT/Claude "chats")
  - Attach images, PDFs, and code/text files — Ryuu reads them before answering
  - Paste an image straight from the clipboard (Ctrl+V) if Pillow is installed
  - Large context window + long/unbounded response length by default

Run: python ryuu_gui.py

Optional dependencies (app still works without them, with graceful fallback):
  pip install pypdf      -> lets Ryuu read text out of attached PDFs
  pip install Pillow     -> lets you paste images from the clipboard
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
import threading
import re
import uuid
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Deque, List, Optional
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, simpledialog, filedialog
import tkinter.font as tkfont

try:
    from PIL import ImageGrab, Image, ImageTk, ImageDraw, ImageOps
    import io as _io
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import speech_recognition as sr
    SR_AVAILABLE = True
except ImportError:
    SR_AVAILABLE = False

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OLLAMA_URL       = "http://localhost:11434"
DEFAULT_MODEL    = "qwen3:8b"
DEFAULT_TOKENS   = -1          # -1 = let the model finish its full answer
DEFAULT_CTX      = 32768       # context window (tokens Ryuu can "see" at once)
DEFAULT_TEMP     = 0.5
DEFAULT_HISTORY  = 16          # turns of prior messages kept in memory
DEFAULT_STREAM   = True
REQUEST_TIMEOUT  = 900         # seconds — generous, for long generations
MAX_CONTINUATIONS = 6          # safety cap on auto-continue rounds (see chat())

# Model name fragments known to support vision (image) input in Ollama.
# If the active model doesn't match one of these, Ryuu will warn you before
# sending images, since a text-only model will just ignore/hallucinate them.
VISION_MODEL_HINTS = [
    "llava", "bakllava", "moondream", "minicpm-v", "qwen2-vl", "qwen2.5vl",
    "qwen2.5-vl", "llama3.2-vision", "llama3.2-vl", "gemma3", "pixtral",
    "vision", "vl",
]


def is_vision_model(name: str) -> bool:
    n = (name or "").lower()
    return any(h in n for h in VISION_MODEL_HINTS)

# Curated models shown in the model picker (Claude-style list), in this order.
# "name" must match (or prefix-match) the tag Ollama reports for that model.
MODEL_CATALOG = [
    {
        "name": "qwen3:8b",
        "label": "Qwen3 8B",
        "desc": "General reasoning & everyday chat",
        "icon": "🧠",
    },
    {
        "name": "qwen2.5-coder:7b",
        "label": "Qwen2.5 Coder 7B",
        "desc": "Writing & debugging code",
        "icon": "💻",
    },
    {
        "name": "qwen2.5vl:7b",
        "label": "Qwen2.5-VL 7B",
        "desc": "Vision — can read attached images",
        "icon": "🖼",
    },
]

OLLAMA_SEARCH_DIRS = [
    r"C:\Users",
    r"C:\Program Files",
    r"C:\Program Files (x86)",
    os.path.expanduser("~\\Downloads"),
    os.path.expanduser("~\\Desktop"),
]

MAX_FILE_CHARS  = 24000            # cap per attached text/code/pdf file
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB cap per attached image

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}

LANG_MAP = {
    ".py": "python", ".js": "javascript", ".jsx": "jsx", ".ts": "typescript",
    ".tsx": "tsx", ".mjs": "javascript", ".cjs": "javascript",
    ".java": "java", ".c": "c", ".h": "c", ".cpp": "cpp",
    ".hpp": "cpp", ".cs": "csharp", ".go": "go", ".rb": "ruby", ".php": "php",
    ".rs": "rust", ".kt": "kotlin", ".swift": "swift", ".html": "html",
    ".htm": "html", ".css": "css", ".scss": "scss", ".json": "json",
    ".xml": "xml", ".yml": "yaml", ".yaml": "yaml", ".md": "markdown",
    ".sh": "bash", ".bash": "bash", ".ps1": "powershell",
    ".sql": "sql", ".csv": "csv", ".txt": "",
    ".vue": "vue", ".svelte": "svelte", ".dart": "dart", ".lua": "lua",
    ".r": "r", ".scala": "scala", ".pl": "perl", ".m": "matlab",
    ".env": "", ".toml": "toml", ".ini": "ini", ".dockerfile": "dockerfile",
    ".gradle": "groovy", ".proto": "protobuf", ".graphql": "graphql",
}

# Pretty display names for the language chip shown in the header of a
# rendered code block (Claude-style), keyed by the lowercase fence tag.
LANG_DISPLAY = {
    "python": "Python", "py": "Python",
    "javascript": "JavaScript", "js": "JavaScript", "mjs": "JavaScript", "cjs": "JavaScript",
    "jsx": "JSX", "typescript": "TypeScript", "ts": "TypeScript", "tsx": "TSX",
    "java": "Java", "c": "C", "cpp": "C++", "c++": "C++", "h": "C", "hpp": "C++",
    "csharp": "C#", "cs": "C#", "go": "Go", "golang": "Go",
    "ruby": "Ruby", "rb": "Ruby", "php": "PHP", "rust": "Rust", "rs": "Rust",
    "kotlin": "Kotlin", "kt": "Kotlin", "swift": "Swift",
    "html": "HTML", "css": "CSS", "scss": "SCSS", "json": "JSON", "xml": "XML",
    "yaml": "YAML", "yml": "YAML", "markdown": "Markdown", "md": "Markdown",
    "bash": "Bash", "sh": "Bash", "powershell": "PowerShell", "ps1": "PowerShell",
    "sql": "SQL", "csv": "CSV", "txt": "Text", "vue": "Vue", "svelte": "Svelte",
    "dart": "Dart", "lua": "Lua", "r": "R", "scala": "Scala", "perl": "Perl",
    "matlab": "MATLAB", "toml": "TOML", "ini": "INI", "dockerfile": "Dockerfile",
    "groovy": "Groovy", "protobuf": "Protocol Buffers", "graphql": "GraphQL",
}

FILE_TYPES = [
    ("All supported", "*.png *.jpg *.jpeg *.gif *.bmp *.webp *.pdf *.py *.js "
                       "*.mjs *.cjs *.jsx *.ts *.tsx *.java *.c *.cpp *.h *.hpp "
                       "*.cs *.go *.rb *.php *.rs *.kt *.swift *.html *.htm "
                       "*.css *.scss *.json *.xml *.yml *.yaml *.md *.txt *.sh "
                       "*.bash *.ps1 *.sql *.csv *.vue *.svelte *.dart *.lua "
                       "*.r *.scala *.pl *.m *.env *.toml *.ini *.gradle "
                       "*.proto *.graphql"),
    ("Images", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
    ("PDF", "*.pdf"),
    ("Code files", "*.py *.js *.mjs *.cjs *.jsx *.ts *.tsx *.java *.c *.cpp "
                    "*.h *.hpp *.cs *.go *.rb *.php *.rs *.kt *.swift *.sql "
                    "*.sh *.bash *.ps1 *.vue *.svelte *.dart *.lua *.r *.scala "
                    "*.pl *.m"),
    ("Text / Markup / Config", "*.html *.htm *.css *.scss *.json *.xml *.yml "
                       "*.yaml *.md *.txt *.csv *.env *.toml *.ini *.gradle "
                       "*.proto *.graphql"),
    ("All files", "*.*"),
]

# ---------------------------------------------------------------------------
# Colors — dojo / study theme
# ---------------------------------------------------------------------------

BG_DARK        = "#161512"   # main window background
BG_PANEL       = "#1e1c18"   # chat area background
RYUU_BUBBLE    = "#7a2e2e"   # Ryuu's message bubble (deep red / hanko)
USER_BUBBLE    = "#2b4a6f"   # User message bubble (indigo blue)
RYUU_NAME_CLR  = "#e0a458"   # "RYUU" label color (gold)
USER_NAME_CLR  = "#8fb8e0"   # "YOU" label color
TIMESTAMP_CLR  = "#a39e93"   # timestamp grey
INPUT_BG       = "#26241f"   # input box background
BUTTON_SEND    = "#b3542f"   # Send button (terracotta)
SIDEBAR_BG     = "#100f0d"   # left/right sidebar
TITLE_CLR      = "#e0a458"
HEADER_BG      = "#0d0c0a"
STATUS_CLR     = "#a39e93"
NEUTRAL_BTN    = "#3a372f"
STOP_BTN_OFF   = "#3a372f"   # Stop button while nothing is generating (looks neutral)
STOP_BTN_ON    = "#8a3030"   # Stop button while Ryuu is generating (clickable, warm red)
LEVEL_CLR      = "#e0a458"
CHIP_BG        = "#33302a"
CONV_ACTIVE_BG = "#3a2a22"

# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are Ryuu, a calm, patient AI teacher and coding assistant.
You are not a roleplay character — you are a genuine explainer, debugger, and
study/coding companion.

## Teaching style
- Break concepts into small, logical steps.
- Lead with the simplest correct mental model, then add nuance/exceptions.
- Use concrete examples or analogies whenever they help.
- Prefer plain language over jargon; if you must use a technical term, define it
  the first time you use it.
- Keep answers focused — don't pad with filler or unnecessary caveats.
- When useful, structure answers with short headers, numbered steps, or bullet
  points, but don't over-format simple answers.
- If a question is ambiguous or could be answered at different depths, briefly
  state the assumption you're making and answer anyway rather than stalling.
- End with a one-line check-in only when it genuinely helps (e.g. offering to
  go deeper, show an example, or simplify further) — not on every reply.

## File & code understanding
- When the user attaches files (code, PDFs, text, or images), carefully read
  the provided content before answering, and reference specific lines,
  functions, or sections when relevant.
- When debugging code, find the root cause first, explain it briefly, then
  give the corrected code — don't just restate the error message.
- When asked to write code, use exactly the language/framework requested and
  wrap all code in a fenced code block with the correct language tag.
- If an image was attached but the current model cannot actually process
  images, say so plainly instead of guessing at its contents.

## Formatting
- Use **bold** (double asterisks) around key terms, warnings, and the most
  important word or phrase in a sentence — the app renders this as real bold
  text, so use it to help the user's eye land on what matters most.
- Don't bold entire sentences or every line — bold sparingly, only what truly
  needs emphasis.

## Tone
- Encouraging and respectful, never condescending.
- Honest about uncertainty — say so plainly instead of guessing confidently.
- No excessive praise, no filler like "Great question!" on every message.

## Hard rules
1. Never fabricate facts, numbers, or citations.
2. Never break character to say you're "just an AI" unprompted — but never
   pretend to be human either. If asked directly what you are, answer honestly.
3. No unnecessary repetition of the question back to the user.
4. Never invent conversation context, errors, technical problems, or user
   intent that wasn't actually stated. If a message is short or vague (e.g.
   "hey"), just respond naturally to it — don't speculate about connection
   issues or hidden meanings.
5. Answer in as few words as fully answering the question requires. Get to
   the point in the first sentence.
"""

# ---------------------------------------------------------------------------
# Ollama process management
# ---------------------------------------------------------------------------

def _known_ollama_paths() -> list:
    local = os.environ.get("LOCALAPPDATA", "")
    pf = os.environ.get("PROGRAMFILES", "")
    pfx86 = os.environ.get("PROGRAMFILES(X86)", "")
    programdata = os.environ.get("PROGRAMDATA", "")
    candidates = [
        r"C:\ollama-ipex\ollama.exe",
        os.path.join(local, "Programs", "Ollama", "ollama.exe"),
        os.path.join(pf, "Ollama", "ollama.exe"),
        os.path.join(pfx86, "Ollama", "ollama.exe"),
        os.path.join(programdata, "Ollama", "ollama.exe"),
    ]
    return [c for c in candidates if c and os.path.isfile(c)]

def _find_ollama_exe() -> Optional[str]:
    import shutil
    known = _known_ollama_paths()
    if known:
        return known[0]
    found = shutil.which("ollama") or shutil.which("ollama.exe")
    if found:
        return found
    for root in OLLAMA_SEARCH_DIRS:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            depth = dirpath.replace(root, "").count(os.sep)
            if depth > 3:
                dirnames.clear()
                continue
            for fname in filenames:
                if fname.lower() in ("ollama.exe", "ollama"):
                    return os.path.join(dirpath, fname)
    return None


def _ping(url: str) -> bool:
    try:
        urllib.request.urlopen(f"{url}/api/tags", timeout=3)
        return True
    except Exception:
        return False


_ollama_proc: Optional[subprocess.Popen] = None  # only set if WE started ollama


def ensure_ollama_running() -> bool:
    global _ollama_proc
    if _ping(OLLAMA_URL):
        return True  # already running (not ours) -> leave it alone on exit
    exe = _find_ollama_exe()
    if not exe:
        return False
    _ollama_proc = subprocess.Popen(
        [exe, "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    for _ in range(15):
        time.sleep(1)
        if _ping(OLLAMA_URL):
            return True
    return False


def stop_ollama():
    """Terminate the Ollama server, but only if this app started it."""
    global _ollama_proc
    if _ollama_proc is None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(_ollama_proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            _ollama_proc.terminate()
        try:
            _ollama_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _ollama_proc.kill()
    except Exception:
        pass
    finally:
        _ollama_proc = None


def list_models() -> List[str]:
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=5) as r:
            return [m["name"] for m in json.loads(r.read()).get("models", [])]
    except Exception:
        return []


def pick_model(preferred: Optional[str] = None) -> Optional[str]:
    available = list_models()
    if not available:
        return None
    preferred = preferred or DEFAULT_MODEL
    for name in available:
        if preferred in name or name.startswith(preferred):
            return name
    return available[0]


def pick_vision_model() -> Optional[str]:
    """Return an installed model that can actually read images, if any."""
    for name in list_models():
        if is_vision_model(name):
            return name
    return None

# ---------------------------------------------------------------------------
# File / attachment helpers
# ---------------------------------------------------------------------------

def lang_for(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return LANG_MAP.get(ext, "")


def read_text_file(path: str, max_chars: int = MAX_FILE_CHARS) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception as e:
        return f"[Could not read file: {e}]"
    if len(content) > max_chars:
        content = content[:max_chars] + f"\n... [truncated, {len(content) - max_chars} more characters]"
    return content


def extract_pdf_text(path: str, max_chars: int = MAX_FILE_CHARS) -> str:
    try:
        try:
            from pypdf import PdfReader
        except ImportError:
            from PyPDF2 import PdfReader  # type: ignore
    except ImportError:
        return ("[PDF reading requires the 'pypdf' package. Install it with:\n"
                 "    pip install pypdf\nthen re-attach the file.]")
    try:
        reader = PdfReader(path)
        parts = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                continue
        text = "\n".join(parts).strip()
        if not text:
            return "[No extractable text found in this PDF — it may be scanned/image-based.]"
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n... [truncated, {len(text) - max_chars} more characters]"
        return text
    except Exception as e:
        return f"[Could not read PDF: {e}]"

# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

@dataclass
class Message:
    role: str
    content: str
    images: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {"role": self.role, "content": self.content}
        if self.images:
            d["images"] = self.images
        return d


@dataclass
class RyuuSession:
    model: str
    max_history: int
    max_tokens: int
    temperature: float
    stream: bool
    num_ctx: int = DEFAULT_CTX
    history: Deque[Message] = field(default_factory=deque)
    level_hint: str = ""  # e.g. "beginner", "advanced"
    about_text: str = ""  # persistent user profile, shown to Ryuu every chat

    def add(self, role: str, content: str, images: Optional[List[str]] = None) -> None:
        if role == "user":
            # A new user turn means any images from earlier turns are now
            # "old news" — the model already replied to them once, and that
            # reply's text is already in history carrying the memory forward.
            # Drop the raw image bytes so they aren't silently re-uploaded
            # (and re-billed against num_ctx) on every future turn.
            for m in self.history:
                if m.images:
                    m.images = []
        self.history.append(Message(role, content, images or []))
        while len(self.history) > self.max_history * 2:
            self.history.popleft()

    def messages(self) -> List[dict]:
        sys_content = SYSTEM_PROMPT
        if self.about_text.strip():
            sys_content += (
                f"\n## About the user (always true, every conversation)\n"
                f"{self.about_text.strip()}\n"
                f"Keep this in mind naturally — don't repeat it back or announce "
                f"that you 'know' it unless it's relevant to the answer.\n"
            )
        if self.level_hint:
            sys_content += (
                f"\n## Current learner level\n"
                f"Explain at a {self.level_hint} level unless the user says otherwise.\n"
            )
        out = [{"role": "system", "content": sys_content}]
        out.extend(m.to_dict() for m in self.history)
        return out

# ---------------------------------------------------------------------------
# HTTP / Ollama chat API
# ---------------------------------------------------------------------------

class OllamaError(Exception):
    pass


def _token_from(obj: dict) -> str:
    return (obj.get("message", {}).get("content") or obj.get("response") or "")


# qwen3 (and similar "reasoning" models) emit a <think>...</think> block
# before the real answer. We never want that shown to the user or saved
# into history/context — only the final answer matters.
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_THINK_OPEN_RE  = re.compile(r"<think>", re.IGNORECASE)


def strip_think(text: str) -> str:
    """Remove <think>...</think> reasoning blocks from model output,
    including a still-open block (e.g. mid-stream or a truncated reply),
    so only the final answer remains."""
    text = _THINK_BLOCK_RE.sub("", text)
    text = _THINK_OPEN_RE.split(text)[0]
    return text.strip()


def _stream(payload: dict, callback: Callable[[str], None], timeout: int = REQUEST_TIMEOUT,
            stop_event: Optional[threading.Event] = None):
    """Stream one reply from Ollama.

    Returns (raw_text, done_reason). done_reason is "length" when Ollama
    cut the reply off because it hit num_predict or ran out of num_ctx —
    as opposed to "stop", which means the model actually finished. chat()
    uses this to decide whether to automatically ask Ryuu to keep going.

    If stop_event is set mid-stream (the user hit Stop), the read loop
    breaks immediately and whatever text arrived so far is returned —
    closing the `with` block aborts the underlying connection."""
    payload = {**payload, "stream": True}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    chunks: List[str] = []
    done_reason = ""
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw in r:
            if stop_event is not None and stop_event.is_set():
                break
            line = raw.strip()
            if not line:
                continue
            obj = json.loads(line)
            token = _token_from(obj)
            if token:
                callback(token)
                chunks.append(token)
            if obj.get("done"):
                done_reason = obj.get("done_reason", "") or ""
                break
    return "".join(chunks), done_reason


def _post(payload: dict, timeout: int = REQUEST_TIMEOUT) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def unload_model(name: str, timeout: int = 30) -> None:
    """Ask Ollama to drop a model from memory right away (keep_alive: 0).
    Best-effort — failures are silently ignored (e.g. model wasn't loaded)."""
    if not name:
        return
    try:
        data = json.dumps({"model": name, "keep_alive": 0}).encode()
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout):
            pass
    except Exception:
        pass


def chat(session: RyuuSession, user_input: str,
         images: Optional[List[str]] = None,
         stream_callback: Optional[Callable[[str], None]] = None,
         model_override: Optional[str] = None,
         stop_event: Optional[threading.Event] = None) -> str:
    user_input = user_input.strip()
    images = images or []
    if not user_input and not images:
        return "Ask Ryuu anything — a concept, a topic, a bug, or code to write."
    session.add("user", user_input, images)

    base_messages = session.messages()
    raw_text = ""       # everything the model has produced so far, unstripped
    done_reason = ""
    extra: List[dict] = []  # transient "continue" turns — never saved to history

    # A reply can get cut off mid-answer if Ollama hits num_predict, or
    # runs out of num_ctx (very common with reasoning models like qwen3,
    # whose hidden <think> block can eat most of the budget before the
    # real answer even starts). When that happens Ollama reports
    # done_reason == "length" instead of "stop". As long as the user
    # hasn't deliberately capped the reply length (max_tokens == -1 means
    # "let Ryuu finish"), automatically ask it to keep going from exactly
    # where it left off, rather than silently showing a truncated answer.
    for _ in range(MAX_CONTINUATIONS):
        if stop_event is not None and stop_event.is_set():
            break
        payload = {
            "model":    model_override or session.model,
            "messages": base_messages + extra,
            "options":  {
                "temperature": session.temperature,
                "num_predict":  session.max_tokens,
                "num_ctx":      session.num_ctx,
            },
            "stream":   False,
        }
        if session.stream and stream_callback:
            piece, done_reason = _stream(payload, callback=stream_callback, stop_event=stop_event)
        else:
            result = _post(payload)
            piece = _token_from(result)
            if not piece:
                piece = result.get("message", {}).get("content", "")
            done_reason = result.get("done_reason", "") or ""

        raw_text += piece

        if stop_event is not None and stop_event.is_set():
            break
        if done_reason != "length" or session.max_tokens != -1:
            break  # finished naturally, errored, or user wanted a hard cap

        extra = [
            {"role": "assistant", "content": raw_text},
            {"role": "user", "content": (
                "Continue your previous reply exactly where it left off. "
                "Do not repeat anything already said and do not restart "
                "the answer — just pick up mid-sentence or mid-code."
            )},
        ]

    text = strip_think(raw_text).strip()
    stopped = stop_event is not None and stop_event.is_set()
    if not text:
        text = "*(Stopped before Ryuu could respond.)*" if stopped else \
               "Ryuu didn't catch that clearly — could you rephrase?"
    elif stopped:
        text += "\n\n*(stopped)*"
    session.add("assistant", text)
    return text

# ---------------------------------------------------------------------------
# Persistent conversation storage (multi-thread chat history)
# ---------------------------------------------------------------------------

CONV_FILE = os.path.join(os.path.expanduser("~"), ".ryuu_conversations.json")
PROFILE_FILE = os.path.join(os.path.expanduser("~"), ".ryuu_profile.json")


def load_profile() -> str:
    """User's persistent 'about me' text — injected into every chat's system
    prompt, in every conversation, old and new, so Ryuu always knows it."""
    try:
        if os.path.exists(PROFILE_FILE):
            with open(PROFILE_FILE, "r", encoding="utf-8") as f:
                return json.load(f).get("about", "")
    except Exception:
        pass
    return ""


def save_profile(text: str) -> None:
    try:
        with open(PROFILE_FILE, "w", encoding="utf-8") as f:
            json.dump({"about": text}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_conversations() -> dict:
    try:
        if os.path.exists(CONV_FILE):
            with open(CONV_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_conversations(data: dict) -> None:
    try:
        with open(CONV_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def new_conversation() -> dict:
    now = datetime.now().isoformat()
    return {
        "id": uuid.uuid4().hex[:8],
        "title": "New Chat",
        "created": now,
        "updated": now,
        "messages": [],  # each: {time, role: USER|RYUU, text, display}
    }

def _lighten(hex_color: str, amt: int = 20) -> str:
    hex_color = hex_color.lstrip("#")
    try:
        r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return f"#{hex_color}"
    r, g, b = (min(255, c + amt) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def _darken(hex_color: str, amt: int = 20) -> str:
    hex_color = hex_color.lstrip("#")
    try:
        r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return f"#{hex_color}"
    r, g, b = (max(0, c - amt) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def _round_rect_points(x1, y1, x2, y2, r):
    """Point list for a rounded rectangle, for use with create_polygon(smooth=True)."""
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    return [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]



# ---------------------------------------------------------------------------
# Embedded icon art (user-supplied reference icons for the edit/retry
# action buttons). Stored as small cropped grayscale PNGs, base64-encoded
# so the script stays a single file. Brightness of each pixel is used as
# an alpha mask at render time so the icon can be tinted to match the
# current icon_color / icon_color_hover (see _tinted_icon_image below).
# ---------------------------------------------------------------------------
_ICON_RETRY_PNG_B64 = (
    "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"
    "LhJhiYkBIPwXVwaoPPogORkAAAAASUVORK5CYII="
)

_ICON_EDIT_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAACUAAAAlCAAAAADg9X/fAAAC/UlEQVR4nI2UzW9bRRTFz52Z5/fsxElKm5IqpLaqKG6QYMdHoKJp"
    "oCQWi0r9EwEJsWrlqGqsokoNsGDHigUVC1IRSkIc+ev5vZm5c1n4I0mTSMxq3uin847OmblUwf9Y6qJDOrWlS6kRRgBxIADmIoYM"
    "m3fbe4rZQQWALqIg+tb706bX3C+W0sv+SHDzn8RzVHxQ1Wwucy9Y2Sgk3++W4s+vpRogAr2ZROxlZUN1nxzK7TVRO6+VthdoOa6u"
    "hddPupH/80WU1BfcVODzVLi1GRArb6Z5r8nxViUVOU/dvpsqmdqcP1YJHew4/ggFdZbKgq6tT/Gz3bxYX7LBdo5/Kd24GjI5QxXs"
    "zQ0MHh38+mMSb73VKl8JnOQzLjqrFa3WffvbIx/tNbLyw3cG6eJd1/k9Lp2llrdceM5xt+he/Sx669rSPbjnxuQneZk8rqyV+9sd"
    "QIIAtQ12M7bTCNbJSds5KutRaP5bAEgDeMlfKKsbGZzQCRVXNtFr7s9ko2+fJL69PVBWIDTyRaisU97Ynxk2KcB7n/Wy7Uz1ZHK/"
    "IiU374fWbie2DABeSfVjGWxbZgPQqEdJF+8H+WFfEYcAQGXVuk5fDDwLAYAogGArdd15/DcRCyEAUnsAbvwBLwTIuMfFLwPvHkY9"
    "5qHLat2673xCMn4mBhAskHp0zCEJEJSsX72nWs3gtZvEbQBgIW5106AUCMj98h012Okh+DChFAR0o9RKg9IEALz8lW09PjSBAyA0"
    "XEYxJOr8VfBKAACrd9podsvHBSjIKS2qej50zDoSna18KPppJv1IAKjxXTAMmUOeIwEh4dVPTfxNn6ycGgIAjNdyHdmAPASofRDx"
    "111tRQ+bGk8M4wvhCnJrZuer12dD1G6myp17DWaayldD/HAuUsE5nf7UFSYinDgHAKMtAr3NNof3Ry//ccIEwptawv63mmofHLzq"
    "JkfTQbGQjLmJHi0RaVYK/VnVR6lVFBAUCAJgEj5VRvNOaHRKMsnzVKqAACKEIX7OEwD8B0pZcfDiVZhnAAAAAElFTkSuQmCC"
)


def _tinted_icon_image(b64data: str, color_hex: str, target_px: int):
    """Decode an embedded grayscale PNG and recolor it to color_hex, using
    each pixel's brightness as its alpha (so the dark background disappears
    and only the icon strokes remain), then scale it to target_px so it
    fits neatly inside an IconButton canvas of a given size."""
    if not PIL_AVAILABLE:
        return None
    raw = base64.b64decode(b64data)
    src = Image.open(_io.BytesIO(raw)).convert("L")

    color_hex = color_hex.lstrip("#")
    r = int(color_hex[0:2], 16)
    g = int(color_hex[2:4], 16)
    b = int(color_hex[4:6], 16)

    # The reference art isn't pure black/white, and its background isn't
    # pure 0 either (some crops sit on dark gray, ~20-35/255). A plain
    # min/max autocontrast gets thrown off by one or two stray
    # interpolation pixels near 0/255, leaving the *true* background level
    # un-stretched -- which renders as a faint, uniform box that never
    # fully disappears into the UI background. Instead, use the image's
    # own histogram: its median is overwhelmingly background (icons are
    # thin strokes on a big flat field), and a high percentile captures the
    # brightest stroke pixels. Stretching between those two anchors -- done
    # BEFORE resizing, so resize interpolation can't reintroduce a halo --
    # reliably drives the background to true 0 alpha (fully transparent)
    # and the strokes to full opacity.
    px = list(src.getdata())
    px_sorted = sorted(px)
    n = len(px_sorted)
    bg_level = px_sorted[int(n * 0.5)]
    fg_level = px_sorted[int(n * 0.99)]
    if fg_level <= bg_level:
        fg_level = max(px_sorted[-1], bg_level + 1)

    def _stretch(p, lo=bg_level, hi=fg_level):
        if p <= lo:
            return 0
        if p >= hi:
            return 255
        return round((p - lo) * 255 / (hi - lo))

    src = src.point(_stretch)

    w, h = src.size
    scale = target_px / max(w, h)
    new_size = (max(1, round(w * scale)), max(1, round(h * scale)))
    src = src.resize(new_size, Image.LANCZOS)
    # Resize interpolation can slightly over/undershoot near hard edges;
    # clamp low values back to 0 so no residual halo survives downscaling.
    src = src.point(lambda p: 0 if p < 12 else p)

    # A smooth 0-255 ramp across the whole stroke leaves interior pixels at
    # partial opacity, which -- once composited over the dark UI background
    # -- reads as a lighter/duller shade than the other, fully-opaque
    # vector icons (like "copy"). Steepen the curve so anything past a low
    # cutoff snaps to full opacity, keeping a soft ramp only in the last
    # few levels for edge anti-aliasing. This makes the icon's color read
    # as the same solid shade as the rest of the icon set.
    cutoff = 80
    src = src.point(lambda p: 255 if p > cutoff else round(p * 255 / cutoff))

    solid = Image.new("RGBA", src.size, (r, g, b, 255))
    solid.putalpha(src)  # brightness -> alpha
    return ImageTk.PhotoImage(solid)


class IconButton(tk.Canvas):
    """A small, borderless icon-only button drawn with vector lines (no emoji,
    no background box) — mirrors the minimal edit-pencil / copy-duplicate
    icon buttons used in Claude's message and code-block action rows.
    A soft rounded highlight appears behind the icon on hover only; the
    icon itself never has a background."""

    def __init__(self, parent, kind: str, command: Callable, bg: str,
                 size: int = 24, icon_color: str = "#b7b4ac",
                 icon_color_hover: str = "#ffffff", hover_bg: Optional[str] = None):
        super().__init__(parent, width=size, height=size, bg=bg,
                          highlightthickness=0, bd=0, cursor="hand2")
        self._kind = kind
        self._command = command
        self._size = size
        self._bg = bg
        self._hover_bg = hover_bg or _lighten(bg, 18)
        self._icon_color = icon_color
        self._icon_color_hover = icon_color_hover

        # For "edit"/"retry" we use the user-supplied reference icon art
        # (tinted to match the button's normal/hover colors) instead of the
        # hand-drawn vector shapes below. Keep references on self so Tk
        # doesn't garbage-collect the PhotoImages.
        self._img_normal = None
        self._img_hover = None
        if self._kind in ("edit", "retry"):
            b64 = _ICON_EDIT_PNG_B64 if self._kind == "edit" else _ICON_RETRY_PNG_B64
            target_px = max(10, round(size * 0.62))
            self._img_normal = _tinted_icon_image(b64, icon_color, target_px)
            self._img_hover = _tinted_icon_image(b64, icon_color_hover, target_px)

        self._draw(False)
        self.bind("<Enter>", lambda e: self._draw(True))
        self.bind("<Leave>", lambda e: self._draw(False))
        self.bind("<Button-1>", lambda e: self._command())

    def _draw(self, hover: bool):
        self.delete("all")
        s = self._size
        color = self._icon_color_hover if hover else self._icon_color
        if hover:
            pts = _round_rect_points(1, 1, s - 1, s - 1, 6)
            self.create_polygon(pts, smooth=True, fill=self._hover_bg, outline="")
        cx, cy = s / 2.0, s / 2.0

        if self._kind in ("edit", "retry") and (self._img_normal is not None):
            img = self._img_hover if hover else self._img_normal
            self.create_image(cx, cy, image=img, anchor="center")
            return

        if self._kind == "copy":
            # Two overlapping rounded squares — back one outlined, front one
            # outlined with its fill matching the current backdrop so it
            # visually "cuts into" the back square, like Claude's icon.
            back = _round_rect_points(cx - 6.5, cy - 6.5, cx + 2.5, cy + 1.5, 2)
            self.create_polygon(back, smooth=True, outline=color, fill="", width=1.4)
            front_fill = self._hover_bg if hover else self._bg
            front = _round_rect_points(cx - 2.5, cy - 1.5, cx + 6.5, cy + 6.5, 2)
            self.create_polygon(front, smooth=True, outline=color, fill=front_fill, width=1.4)

        elif self._kind == "edit":
            # Solid pencil, built from filled shapes (not thin lines) so it
            # reads clearly at small sizes, matching a lucide "square-pen"
            # style icon: a diagonal shaft, a pointed tip, and a small
            # angled cap at the tail end.
            import math
            ang = math.radians(45)
            dx, dy = math.cos(ang), -math.sin(ang)   # shaft direction (tail -> tip)
            px, py = -dy, dx                          # perpendicular to the shaft
            hw = 2.3                                   # shaft half-width

            tail = (cx - 5.0, cy + 5.0)
            tip_base = (cx + 4.2, cy - 4.2)
            tip = (cx + 7.2, cy - 7.2)

            def _offset(pt, sx, sy, amt):
                return (pt[0] + sx * amt, pt[1] + sy * amt)

            c1 = _offset(tail, px, py, hw)
            c2 = _offset(tail, px, py, -hw)
            c3 = _offset(tip_base, px, py, -hw)
            c4 = _offset(tip_base, px, py, hw)

            # Shaft.
            self.create_polygon(c2, c1, c4, c3, fill=color, outline=color)
            # Pointed tip.
            self.create_polygon(c3, c4, tip, fill=color, outline=color)
            # Small cap at the tail (the pencil's blunt end).
            cap_far1 = _offset(c1, -dx, -dy, 2.6)
            cap_far2 = _offset(c2, -dx, -dy, 2.6)
            self.create_polygon(c2, c1, cap_far1, cap_far2, fill=color, outline=color)

        elif self._kind == "refresh":
            self.create_arc(cx - 6.5, cy - 6.5, cx + 6.5, cy + 6.5,
                             start=25, extent=270, style=tk.ARC,
                             outline=color, width=1.6)
            self.create_polygon(cx + 5.8, cy - 6.2, cx + 9.2, cy - 6.0, cx + 7.4, cy - 2.6,
                                 fill=color, outline=color)

        elif self._kind == "retry":
            # Two mirrored arcs, each capped with an arrowhead, forming a
            # balanced circular "retry" loop (rather than "refresh"'s
            # single long arrow sweeping most of the circle).
            self.create_arc(cx - 6.5, cy - 6.5, cx + 6.5, cy + 6.5,
                             start=15, extent=140, style=tk.ARC,
                             outline=color, width=1.6)
            self.create_polygon(cx + 6.0, cy - 5.6, cx + 9.4, cy - 5.0, cx + 7.2, cy - 2.0,
                                 fill=color, outline=color)

            self.create_arc(cx - 6.5, cy - 6.5, cx + 6.5, cy + 6.5,
                             start=195, extent=140, style=tk.ARC,
                             outline=color, width=1.6)
            self.create_polygon(cx - 6.0, cy + 5.6, cx - 9.4, cy + 5.0, cx - 7.2, cy + 2.0,
                                 fill=color, outline=color)


def _compute_text_height_lines(widget: tk.Text, fnt: tkfont.Font) -> int:
    """How many height-units a Text widget needs to show all of its
    content without clipping anything off the bottom.

    Text.count(..., "displaylines") only counts wrapped *text* lines, and
    treats an embedded window (e.g. one of our code-block cards, created
    via window_create) as exactly one line regardless of how tall that
    card actually is. A reply containing a multi-line code block would
    therefore get sized for ~1 extra line while the card itself might be
    10+ lines tall, silently clipping most of the code off the bottom of
    the bubble.

    Text.count(..., "ypixels") instead measures actual vertical pixels,
    which correctly includes embedded windows at their real height.
    Converting that back into the widget's own line units (via the
    prose font's line spacing) gives a height that fits everything.
    """
    try:
        total_px = int(widget.count("1.0", "end", "ypixels")[0])
    except Exception:
        try:
            return int(widget.count("1.0", "end", "displaylines")[0])
        except Exception:
            return 1
    line_px = max(1, fnt.metrics("linespace"))
    return max(1, -(-total_px // line_px))  # ceil division


def _make_text_readonly(widget: tk.Text):
    """Make a Text widget read-only WITHOUT using state=tk.DISABLED.

    state=tk.DISABLED blocks all interaction with a Text widget, including
    mouse-drag selection and Ctrl+C copying -- not just typing. That made
    every rendered message bubble (and code block inside it) impossible to
    select or copy.

    This instead renames the widget's underlying Tcl command and installs a
    thin proxy in its place that silently no-ops "insert" and "delete"
    calls but forwards everything else (selection, scrolling, get,
    clipboard copy, etc.) straight through untouched. The widget stays in
    its normal, fully-interactive state the whole time.
    """
    orig_name = widget._w + "_readonly_orig"
    widget.tk.call("rename", widget._w, orig_name)

    def _proxy(*args):
        cmd = args[0] if args else ""
        if cmd in ("insert", "delete"):
            return ""  # silently swallow edits
        try:
            return widget.tk.call((orig_name,) + args)
        except tk.TclError:
            return ""

    widget.tk.createcommand(widget._w, _proxy)


_DRAGON_ICON_CACHE: dict = {}

# Base64-encoded PNG of the Ryuu dragon logo (the yin-yang tribal dragon
# artwork), pre-processed into a gold-on-transparent icon so it matches
# RYUU_NAME_CLR and drops onto any of the app's dark backgrounds with no
# visible box around it.
_DRAGON_LOGO_B64 = """
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
6HsmkY7oCAAAAABJRU5ErkJggg==
""".strip()


def _dragon_icon(size: int = 20, bg: str = "#1e1c18"):
    """The Ryuu dragon logo, rendered at the requested size. Falls back to
    None (caller shows a 🐉 emoji instead) if Pillow isn't installed or the
    embedded logo can't be decoded for some reason."""
    key = (size, bg)
    if key in _DRAGON_ICON_CACHE:
        return _DRAGON_ICON_CACHE[key]
    if not PIL_AVAILABLE:
        return None
    try:
        raw = base64.b64decode(_DRAGON_LOGO_B64)
        img = Image.open(_io.BytesIO(raw)).convert("RGBA")
        img = img.resize((size, size), Image.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        _DRAGON_ICON_CACHE[key] = photo
        return photo
    except Exception:
        return None

# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class RyuuApp(tk.Tk):
    def __init__(self, session: RyuuSession):
        super().__init__()
        self.session = session
        self.pending_attachments: List[dict] = []
        self.is_typing = False
        self.current_level = "Beginner"

        data = load_conversations()
        self.conversations: List[dict] = data.get("conversations") or [new_conversation()]
        active = data.get("active_id")
        ids = [c["id"] for c in self.conversations]
        self.active_id = active if active in ids else self.conversations[0]["id"]
        self._conv_order: List[str] = []

        self.title("Ryuu — AI Explainer & Coding Assistant")
        self.configure(bg=BG_DARK)
        self.geometry("1200x760")
        self.minsize(880, 560)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._switch_conversation(self.active_id, greet_if_empty=True)

    def _on_close(self):
        self._save_conversations()
        stop_ollama()
        self.destroy()

    def _hoverify(self, widget, amt: int = 20):
        # `_normal_bg` is the button's current *resting* color. Reading it
        # fresh on every Enter/Leave (rather than capturing `cget("bg")`
        # once here) means code that later recolors the button — e.g. the
        # Stop button switching between grey/red — can just update
        # `widget._normal_bg` and hovering will keep lightening/restoring
        # the right color instead of an old one baked in at bind time.
        widget._normal_bg = widget.cget("bg")

        def _enter(e):
            if str(widget.cget("state")) == "disabled":
                return
            widget.config(bg=_lighten(widget._normal_bg, amt))

        def _leave(e):
            if str(widget.cget("state")) == "disabled":
                return
            widget.config(bg=widget._normal_bg)

        widget.bind("<Enter>", _enter)
        widget.bind("<Leave>", _leave)

    # ------------------------------------------------------------------
    # Conversation helpers
    # ------------------------------------------------------------------

    def _active_conv(self) -> dict:
        for c in self.conversations:
            if c["id"] == self.active_id:
                return c
        # fallback — shouldn't happen
        c = new_conversation()
        self.conversations.insert(0, c)
        self.active_id = c["id"]
        return c

    def _save_conversations(self):
        save_conversations({"active_id": self.active_id, "conversations": self.conversations})

    def _new_conversation(self):
        conv = new_conversation()
        self.conversations.insert(0, conv)
        self._switch_conversation(conv["id"], greet_if_empty=True)

    def _delete_conversation(self):
        sel = self.conv_listbox.curselection()
        if not sel:
            return
        conv_id = self._conv_order[sel[0]]
        conv = next((c for c in self.conversations if c["id"] == conv_id), None)
        if not conv:
            return
        if not messagebox.askyesno(
            "Delete Conversation",
            f"Delete \"{conv.get('title', 'this chat')}\"? This cannot be undone.",
            parent=self
        ):
            return
        self.conversations = [c for c in self.conversations if c["id"] != conv_id]
        if not self.conversations:
            self.conversations = [new_conversation()]
        if self.active_id == conv_id:
            self._switch_conversation(self.conversations[0]["id"], greet_if_empty=True)
        else:
            self._save_conversations()
            self._refresh_conv_list()

    def _rename_conversation(self):
        sel = self.conv_listbox.curselection()
        if not sel:
            self.status_var.set("Select a chat first, then Rename.")
            return
        conv_id = self._conv_order[sel[0]]
        conv = next((c for c in self.conversations if c["id"] == conv_id), None)
        if not conv:
            return
        new_title = simpledialog.askstring(
            "Rename Chat", "New name for this chat:",
            initialvalue=conv.get("title", "New Chat"), parent=self
        )
        if new_title and new_title.strip():
            conv["title"] = new_title.strip()[:60]
            self._save_conversations()
            self._refresh_conv_list()
            self.status_var.set("Chat renamed.")

    def _switch_conversation(self, conv_id: str, greet_if_empty: bool = False):
        self.active_id = conv_id
        conv = self._active_conv()

        # Rebuild in-memory model context from this conversation's recent messages
        self.session.history.clear()
        recent = conv["messages"][-(self.session.max_history * 2):]
        for m in recent:
            role = "user" if m["role"] == "USER" else "assistant"
            self.session.history.append(Message(role, m.get("text", "")))

        # Repaint bubbles
        for w in self.messages_frame.winfo_children():
            w.destroy()
        for i, m in enumerate(conv["messages"]):
            role = "user" if m["role"] == "USER" else "ryuu"
            self._add_bubble(role, m.get("display", m.get("text", "")), m.get("time", ""),
                              attachments=m.get("attachments"),
                              msg_index=i)

        self._save_conversations()
        self._refresh_conv_list()

        if greet_if_empty and not conv["messages"]:
            self._post_greeting()

    def _refresh_conv_list(self):
        self.conversations.sort(key=lambda c: c.get("updated", ""), reverse=True)
        self.conv_listbox.delete(0, tk.END)
        self._conv_order = []
        for c in self.conversations:
            title = c.get("title") or "New Chat"
            self.conv_listbox.insert(tk.END, " " + title[:26])
            self._conv_order.append(c["id"])
        if self.active_id in self._conv_order:
            idx = self._conv_order.index(self.active_id)
            self.conv_listbox.selection_clear(0, tk.END)
            self.conv_listbox.selection_set(idx)
            self.conv_listbox.itemconfig(idx, bg=CONV_ACTIVE_BG)

    def _on_conv_select(self, _event=None):
        sel = self.conv_listbox.curselection()
        if not sel:
            return
        conv_id = self._conv_order[sel[0]]
        if conv_id != self.active_id:
            self._switch_conversation(conv_id)

    # ------------------------------------------------------------------
    # UI Build
    # ------------------------------------------------------------------

    def _build_ui(self):
        # ── Header bar ──────────────────────────────────────────────
        header = tk.Frame(self, bg=HEADER_BG, height=66)
        header.pack(fill=tk.X, side=tk.TOP)
        header.pack_propagate(False)

        title_col = tk.Frame(header, bg=HEADER_BG)
        title_col.pack(side=tk.LEFT, padx=18, pady=8)
        tk.Label(title_col, text="龍  Ryuu", bg=HEADER_BG, fg=TITLE_CLR,
                 font=("Segoe UI", 16, "bold")).pack(anchor="w")
        tk.Label(title_col, text="AI Explainer & Coding Assistant",
                 bg=HEADER_BG, fg=STATUS_CLR,
                 font=("Segoe UI", 9)).pack(anchor="w")

        self.level_btn = tk.Button(
            header, text=f"  Level: {self.current_level}  ",
            bg=NEUTRAL_BTN, fg="#ffffff",
            font=("Segoe UI", 10), relief=tk.FLAT,
            bd=0, padx=8, pady=4,
            cursor="hand2",
            command=self._change_level
        )
        self.level_btn.pack(side=tk.RIGHT, padx=(4, 14), pady=10)
        self._hoverify(self.level_btn)

        self.about_btn = tk.Button(
            header, text="  👤 About You  ",
            bg=NEUTRAL_BTN, fg="#ffffff",
            font=("Segoe UI", 10), relief=tk.FLAT,
            bd=0, padx=8, pady=4,
            cursor="hand2",
            command=self._open_about_you
        )
        self.about_btn.pack(side=tk.RIGHT, padx=4, pady=10)
        self._hoverify(self.about_btn)

        self.model_btn = tk.Button(
            header, text=self._model_btn_text(),
            bg=NEUTRAL_BTN, fg="#ffffff",
            font=("Segoe UI", 10), relief=tk.FLAT,
            bd=0, padx=8, pady=4,
            cursor="hand2",
            command=self._open_model_menu
        )
        self.model_btn.pack(side=tk.RIGHT, padx=4, pady=10)
        self._hoverify(self.model_btn)

        settings_holder = tk.Frame(header, bg=HEADER_BG, width=34, height=34)
        settings_holder.pack(side=tk.RIGHT, padx=4, pady=10)
        settings_holder.pack_propagate(False)

        settings_btn = tk.Button(
            settings_holder, text="⚙",
            bg=NEUTRAL_BTN, fg="#ffffff",
            font=("Segoe UI", 11), relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            command=self._open_settings
        )
        settings_btn.pack(fill=tk.BOTH, expand=True)
        self._hoverify(settings_btn)

        clear_btn = tk.Button(
            header, text="🗑 Clear",
            bg=NEUTRAL_BTN, fg="#ffffff",
            font=("Segoe UI", 10, "bold"), relief=tk.FLAT,
            bd=0, padx=10, pady=4,
            cursor="hand2",
            command=self._clear_chat
        )
        clear_btn.pack(side=tk.RIGHT, padx=4, pady=10)
        self._hoverify(clear_btn)

        search_btn = tk.Button(
            header, text="📋 Search",
            bg=NEUTRAL_BTN, fg="#ffffff",
            font=("Segoe UI", 10, "bold"), relief=tk.FLAT,
            bd=0, padx=10, pady=4,
            cursor="hand2",
            command=self._show_history
        )
        search_btn.pack(side=tk.RIGHT, padx=4, pady=10)
        self._hoverify(search_btn)

        # The gear icon can render at a different intrinsic size than the
        # text buttons depending on the OS's emoji/symbol font fallback, so
        # rather than guess a fixed pixel size, measure a real sibling
        # button once the header has actually been laid out and force the
        # icon button's frame to that exact square size.
        def _sync_settings_btn_size():
            header.update_idletasks()
            h = clear_btn.winfo_height()
            if h > 1:
                settings_holder.config(width=h, height=h)
        self.after(50, _sync_settings_btn_size)

        # ── Main content area ────────────────────────────────────────
        content = tk.Frame(self, bg=BG_DARK)
        content.pack(fill=tk.BOTH, expand=True)

        left_frame = tk.Frame(content, bg=BG_DARK)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        chat_outer = tk.Frame(left_frame, bg=BG_PANEL)
        chat_outer.pack(fill=tk.BOTH, expand=True)

        self.chat_canvas = tk.Canvas(chat_outer, bg=BG_PANEL,
                                      highlightthickness=0, bd=0)
        self.chat_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(chat_outer, orient=tk.VERTICAL,
                                  command=self.chat_canvas.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.chat_canvas.configure(yscrollcommand=scrollbar.set)

        self.messages_frame = tk.Frame(self.chat_canvas, bg=BG_PANEL)
        self.chat_canvas_window = self.chat_canvas.create_window(
            (0, 0), window=self.messages_frame, anchor="nw")
        self.chat_canvas.bind("<Configure>", self._on_canvas_resize)

        self.chat_canvas.bind("<MouseWheel>",
            lambda e: self.chat_canvas.yview_scroll(-1 * (e.delta // 120), "units"))
        self.messages_frame.bind("<MouseWheel>",
            lambda e: self.chat_canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        # ── Attachment chip bar (shown above input when files are staged) ──
        self.attach_bar = tk.Frame(left_frame, bg=HEADER_BG)
        # not packed until there's something to show

        # ── Input row ───────────────────────────────────────────────
        # Height grows a little as the message wraps onto more lines
        # (see _autosize_input_bar), clamped between these two bounds.
        self._input_min_h = 112
        self._input_max_h = 170

        input_frame = tk.Frame(left_frame, bg=HEADER_BG, height=self._input_min_h)
        input_frame.pack(fill=tk.X, side=tk.BOTTOM)
        input_frame.pack_propagate(False)
        self._input_frame = input_frame  # kept for attach_bar positioning (see _input_frame_ref)

        self.input_box = tk.Text(
            input_frame, bg=INPUT_BG, fg="#ffffff", insertbackground="#ffffff",
            relief=tk.FLAT, font=("Segoe UI", 11),
            bd=0, height=2, wrap=tk.WORD, undo=True
        )
        self.input_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                             padx=(10, 6), pady=6)
        self.input_box.bind("<Return>", self._on_return_key)
        self.input_box.bind("<Shift-Return>", lambda e: None)  # allow newline
        self.input_box.bind("<Control-v>", self._paste_handler)
        self.input_box.bind("<<Paste>>", self._paste_handler)
        self.input_box.bind("<KeyRelease>", self._autosize_input_bar)

        btn_col = tk.Frame(input_frame, bg=HEADER_BG)
        btn_col.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8), pady=6)

        def _make_btn(parent, text, cmd, icon="", color=BUTTON_SEND):
            b = tk.Button(parent, text=f"{icon} {text}" if icon else text,
                          bg=color, fg="#ffffff",
                          font=("Segoe UI", 10, "bold"),
                          relief=tk.FLAT, bd=0,
                          padx=10, pady=2,
                          cursor="hand2",
                          activebackground="#c9663d",
                          activeforeground="#ffffff",
                          command=cmd)
            b.pack(side=tk.TOP, padx=0, pady=1, fill=tk.BOTH, expand=True)
            self._hoverify(b, 16)
            return b

        _make_btn(btn_col, "Send",   self._send)
        _make_btn(btn_col, "Attach", self._attach_files, "📎", NEUTRAL_BTN)
        self.stop_btn = _make_btn(btn_col, "Stop", self._stop_generation, "⏹", STOP_BTN_OFF)
        self.stop_btn.config(state=tk.DISABLED)

        # ── Status bar ──────────────────────────────────────────────
        self.status_var = tk.StringVar(value="Ready — ask Ryuu anything.")
        status_bar = tk.Label(self, textvariable=self.status_var,
                               bg=HEADER_BG, fg=STATUS_CLR,
                               font=("Segoe UI", 9), anchor="w")
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

        # ── Right sidebar — conversations ──────────────────────────
        sidebar = tk.Frame(content, bg=SIDEBAR_BG, width=240)
        sidebar.pack(side=tk.RIGHT, fill=tk.Y)
        sidebar.pack_propagate(False)

        self._build_sidebar(sidebar)

    def _build_sidebar(self, sidebar: tk.Frame):
        badge = tk.Canvas(sidebar, width=220, height=90,
                           bg=SIDEBAR_BG, highlightthickness=1,
                           highlightbackground="#7a2e2e")
        badge.pack(padx=10, pady=(14, 6))
        badge.create_text(110, 45, text="龍  RYUU",
                           fill="#e0a458", font=("Segoe UI", 18, "bold"),
                           justify="center")

        self.model_lbl = tk.Label(
            sidebar, text=self._model_label_text(),
            bg=SIDEBAR_BG, fg=STATUS_CLR, font=("Segoe UI", 9),
            wraplength=210, justify="center"
        )
        self.model_lbl.pack(pady=(0, 10))

        conv_header = tk.Frame(sidebar, bg=SIDEBAR_BG)
        conv_header.pack(fill=tk.X, padx=10, pady=(4, 4))
        tk.Label(conv_header, text="Conversations", bg=SIDEBAR_BG,
                 fg=LEVEL_CLR, font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)

        new_btn = tk.Button(conv_header, text="+ New", bg=BUTTON_SEND, fg="#ffffff",
                             font=("Segoe UI", 9, "bold"), relief=tk.FLAT, bd=0,
                             padx=8, pady=2, cursor="hand2",
                             activebackground="#c9663d",
                             command=self._new_conversation)
        new_btn.pack(side=tk.RIGHT)
        self._hoverify(new_btn, 16)

        list_frame = tk.Frame(sidebar, bg=SIDEBAR_BG)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(4, 4))

        conv_scroll = tk.Scrollbar(list_frame, orient=tk.VERTICAL)
        conv_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.conv_listbox = tk.Listbox(
            list_frame, bg=INPUT_BG, fg="#ffffff",
            selectbackground=CONV_ACTIVE_BG, selectforeground="#ffffff",
            relief=tk.FLAT, bd=0, highlightthickness=0,
            font=("Segoe UI", 10), activestyle="none",
            yscrollcommand=conv_scroll.set
        )
        self.conv_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        conv_scroll.config(command=self.conv_listbox.yview)
        self.conv_listbox.bind("<<ListboxSelect>>", self._on_conv_select)
        self.conv_listbox.bind("<Double-Button-1>", lambda e: self._rename_conversation())

        action_row = tk.Frame(sidebar, bg=SIDEBAR_BG)
        action_row.pack(fill=tk.X, padx=10, pady=(0, 4))

        rename_btn = tk.Button(action_row, text="✎ Rename",
                                bg=NEUTRAL_BTN, fg="#ffffff",
                                font=("Segoe UI", 9), relief=tk.FLAT, bd=0,
                                padx=8, pady=5, cursor="hand2",
                                activebackground="#4a473d",
                                command=self._rename_conversation)
        rename_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self._hoverify(rename_btn, 16)

        del_btn = tk.Button(action_row, text="🗑 Delete",
                             bg=NEUTRAL_BTN, fg="#ffffff",
                             font=("Segoe UI", 9), relief=tk.FLAT, bd=0,
                             padx=8, pady=5, cursor="hand2",
                             activebackground="#4a473d",
                             command=self._delete_conversation)
        del_btn.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._hoverify(del_btn, 16)

        export_btn = tk.Button(sidebar, text="📤 Export This Chat",
                                bg=NEUTRAL_BTN, fg="#ffffff",
                                font=("Segoe UI", 9), relief=tk.FLAT, bd=0,
                                padx=8, pady=5, cursor="hand2",
                                activebackground="#4a473d",
                                command=self._export_current_conversation)
        export_btn.pack(fill=tk.X, padx=10, pady=(4, 0))
        self._hoverify(export_btn, 16)

        tip = tk.Label(
            sidebar,
            text="Tip: attach files with 📎, or ask \"go deeper\" / "
                 "\"explain like I'm new to this\" any time.",
            bg=SIDEBAR_BG, fg=STATUS_CLR, font=("Segoe UI", 8, "italic"),
            wraplength=210, justify="left"
        )
        tip.pack(padx=10, pady=(0, 10), anchor="w")

    def _model_label_text(self) -> str:
        tag = "🖼 vision-capable" if is_vision_model(self.session.model) else "text-only"
        return f"Model: {self.session.model}\n({tag})"

    def _model_btn_text(self) -> str:
        icon = "🖼" if is_vision_model(self.session.model) else "🧠"
        return f"  {icon} {self.session.model}  ▾  "

    def _resolve_installed(self, catalog_name: str, installed: List[str]) -> Optional[str]:
        """Match a MODEL_CATALOG entry to the actual tag Ollama has installed
        (handles case differences like 'qwen2.5-Coder:7b' vs 'qwen2.5-coder:7b',
        and suffix variants like 'qwen3:8b-instruct-q4_0')."""
        target = catalog_name.lower()
        target_base = target.split(":")[0] + ":"
        for name in installed:
            n = name.lower()
            if n == target or n.startswith(target_base):
                return name
        return None

    def _open_model_menu_from(self, anchor: tk.Widget):
        self._open_model_menu(anchor=anchor)

    def _open_model_menu(self, anchor: Optional[tk.Widget] = None):
        """Claude-style model picker: a clean floating card listing the
        curated models (qwen3, qwen2.5-coder, qwen2.5vl), not a native menu."""
        anchor = anchor or self.model_btn

        popup = tk.Toplevel(self)
        popup.overrideredirect(True)
        popup.configure(bg=INPUT_BG)
        popup.attributes("-topmost", True)

        card = tk.Frame(popup, bg=INPUT_BG, highlightthickness=1,
                         highlightbackground="#4a473d", highlightcolor="#4a473d")
        card.pack(fill=tk.BOTH, expand=True)

        tk.Label(card, text="MODEL", bg=INPUT_BG, fg=STATUS_CLR,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=14, pady=(10, 4))

        rows_container = tk.Frame(card, bg=INPUT_BG)
        rows_container.pack(fill=tk.X)

        tk.Frame(card, bg="#4a473d", height=1).pack(fill=tk.X, pady=(4, 4))
        more = tk.Label(card, text="More models installed in Ollama? Set one in ⚙ Settings.",
                         bg=INPUT_BG, fg=STATUS_CLR, font=("Segoe UI", 8, "italic"),
                         wraplength=280, justify="left")
        more.pack(anchor="w", padx=14, pady=(0, 10))

        def _reposition():
            popup.update_idletasks()
            x = anchor.winfo_rootx()
            y = anchor.winfo_rooty() + anchor.winfo_height() + 4
            w = max(300, popup.winfo_reqwidth())
            popup.geometry(f"{w}x{popup.winfo_reqheight()}+{x}+{y}")

        def _close(_e=None):
            self.unbind_all("<Button-1>")
            try:
                popup.destroy()
            except Exception:
                pass

        def w_children(widget):
            out = []
            for c in widget.winfo_children():
                out.append(c)
                out.extend(w_children(c))
            return out

        def _build_rows(installed: List[str]):
            for w in rows_container.winfo_children():
                w.destroy()

            for entry in MODEL_CATALOG:
                actual = self._resolve_installed(entry["name"], installed)
                is_current = actual == self.session.model if actual else False
                is_avail = actual is not None

                row = tk.Frame(rows_container, bg=INPUT_BG, cursor="hand2" if is_avail else "arrow")
                row.pack(fill=tk.X, padx=6, pady=1)

                fg_label = "#ffffff" if is_avail else "#6f6b60"
                fg_desc  = STATUS_CLR if is_avail else "#55524a"

                text_col = tk.Frame(row, bg=INPUT_BG)
                text_col.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8, pady=7)

                name_row = tk.Frame(text_col, bg=INPUT_BG)
                name_row.pack(anchor="w", fill=tk.X)
                tk.Label(name_row, text=f"{entry['icon']}  {entry['label']}",
                         bg=INPUT_BG, fg=fg_label,
                         font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
                if is_current:
                    tk.Label(name_row, text="✓", bg=INPUT_BG, fg=RYUU_NAME_CLR,
                             font=("Segoe UI", 10, "bold")).pack(side=tk.RIGHT, padx=(6, 0))

                desc_text = entry["desc"] if is_avail else f"Not installed — ollama pull {entry['name']}"
                tk.Label(text_col, text=desc_text, bg=INPUT_BG, fg=fg_desc,
                         font=("Segoe UI", 8), justify="left",
                         wraplength=260).pack(anchor="w")

                widgets = [row, text_col, name_row]

                def _enter(_e, r=row, widgets=widgets, is_avail=is_avail):
                    if not is_avail:
                        return
                    for w in widgets:
                        w.configure(bg=CONV_ACTIVE_BG)
                    for w in w_children(r):
                        try:
                            w.configure(bg=CONV_ACTIVE_BG)
                        except Exception:
                            pass

                def _leave(_e, r=row, widgets=widgets, is_avail=is_avail):
                    if not is_avail:
                        return
                    for w in widgets:
                        w.configure(bg=INPUT_BG)
                    for w in w_children(r):
                        try:
                            w.configure(bg=INPUT_BG)
                        except Exception:
                            pass

                if is_avail:
                    def _pick(_e, n=actual):
                        _close()
                        self._set_model(n)
                    for w in [row] + w_children(row):
                        w.bind("<Button-1>", _pick)
                        w.bind("<Enter>", _enter)
                        w.bind("<Leave>", _leave)

            _reposition()

        # Show instantly with whatever we last knew (or an empty/loading
        # state on first run) instead of blocking the UI thread on the
        # network call to Ollama — that stall was the "takes 5 seconds
        # and nothing works" bug.
        cached = getattr(self, "_models_cache", None)
        if cached is not None:
            _build_rows(cached)
        else:
            loading_lbl = tk.Label(rows_container, text="Loading installed models…",
                                    bg=INPUT_BG, fg=STATUS_CLR, font=("Segoe UI", 9, "italic"))
            loading_lbl.pack(anchor="w", padx=14, pady=10)
            _reposition()

        def _fetch():
            installed = list_models()
            def _apply():
                if not popup.winfo_exists():
                    return
                self._models_cache = installed
                _build_rows(installed)
            self.after(0, _apply)

        threading.Thread(target=_fetch, daemon=True).start()

        # Click anywhere outside the popup closes it. (Previously this used
        # grab_set(), which blocked the main window from ever receiving the
        # click that would have closed the popup — so it stayed open until
        # a model was actually clicked.)
        def _on_global_click(e):
            try:
                wx, wy = popup.winfo_rootx(), popup.winfo_rooty()
                ww, wh = popup.winfo_width(), popup.winfo_height()
                if not (wx <= e.x_root <= wx + ww and wy <= e.y_root <= wy + wh):
                    _close()
            except tk.TclError:
                pass

        popup.bind("<Escape>", _close)
        popup.focus_force()
        self.after(50, lambda: self.bind_all("<Button-1>", _on_global_click, add="+"))

    def _set_model(self, name: str):
        if name == self.session.model:
            return
        self.session.model = name
        self.model_btn.config(text=self._model_btn_text())
        self.model_lbl.config(text=self._model_label_text())
        settings_btn = getattr(self, "_settings_model_btn", None)
        if settings_btn is not None:
            try:
                settings_btn.config(text=self._model_btn_text())
            except tk.TclError:
                pass  # settings window was closed
        self.status_var.set(f"Model switched to {name}.")
        self.status_var.set(f"Model switched to {name}.")

    def _on_canvas_resize(self, event):
        self.chat_canvas.itemconfig(self.chat_canvas_window, width=event.width)
        self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))

    # ------------------------------------------------------------------
    # Message bubbles
    # ------------------------------------------------------------------

    def _bind_main_scroll(self, widget):
        def _scroll(e):
            self.chat_canvas.yview_scroll(-1 * (e.delta // 120), "units")
        def _up(e):
            self.chat_canvas.yview_scroll(-1, "units")
        def _down(e):
            self.chat_canvas.yview_scroll(1, "units")
        widget.bind("<MouseWheel>", _scroll, add="+")
        widget.bind("<Button-4>",   _up,    add="+")
        widget.bind("<Button-5>",   _down,  add="+")
        for child in widget.winfo_children():
            self._bind_main_scroll(child)

    def _rich_text_widget(self, parent, text, bg, fg, wrap_px):
        """A read-only Text widget that renders **bold** / `code` spans and
        auto-sizes to its content, standing in for a plain Label."""
        font_normal = ("Segoe UI", 11)
        fnt = tkfont.Font(family=font_normal[0], size=font_normal[1])
        avg = fnt.measure("abcdefghijklmnopqrstuvwxyz0123456789") / 36.0
        chars = max(15, int(wrap_px / max(avg, 1)))

        widget = tk.Text(
            parent, bg=bg, fg=fg, font=font_normal, wrap=tk.WORD,
            bd=0, highlightthickness=0, padx=0, pady=0,
            width=chars, height=1, cursor="xterm", relief=tk.FLAT,
            selectbackground="#4a4a4a",
        )
        widget.tag_configure("bold", font=(font_normal[0], font_normal[1], "bold"))
        widget.tag_configure("code", font=("Consolas", 11), background=_darken(bg, 24))
        self._insert_markdown(widget, text)
        # Trim a trailing blank line — Text widgets always keep one implicit
        # final line, and if the inserted content itself ends with "\n" that
        # adds a second blank row on top of it, leaving empty space under
        # the visible text (the "bubble taller than the message" bug).
        while widget.get("end-2c", "end-1c") == "\n":
            widget.delete("end-2c", "end-1c")
        # Make read-only via a Tcl-command proxy (see _make_text_readonly)
        # rather than state=tk.DISABLED, so mouse-drag selection, Ctrl+C,
        # Shift+arrow selection, etc. all keep working exactly like a normal
        # widget. Must happen AFTER the insert/delete calls above that build
        # the actual content.
        _make_text_readonly(widget)
        # IMPORTANT: the widget must be packed/mapped *before* we ask Tk how
        # many display lines it wraps to — measuring an unmapped widget gives
        # nonsense counts (seen as high as 20+ for a one-line message), which
        # produced huge blank bubbles. Packing first fixes that.
        widget.pack(anchor="w")
        widget.update_idletasks()
        height = _compute_text_height_lines(widget, fnt)
        widget.configure(height=height)
        # A message with an embedded code-block card (see _embed_code_block)
        # doesn't report its true height after just one update_idletasks():
        # the card's own children need an extra geometry pass to settle,
        # so the very first measurement can come back too small. That left
        # the bubble sized too short for its content, with the leftover
        # text only reachable by scrolling *inside* the Text widget instead
        # of the bubble growing to show it. Re-measure a few times and keep
        # growing the widget until the reported height stops increasing.
        for _ in range(4):
            widget.update_idletasks()
            new_height = _compute_text_height_lines(widget, fnt)
            if new_height <= height:
                break
            height = new_height
            widget.configure(height=height)
        return widget

    # Fenced blocks (```lang\n...\n```) are pulled out first. If this ran in
    # the same pass as inline `code`, a fence's three backticks get read as
    # a broken single-backtick pair, and the *next* stray backtick then
    # hunts forward for whatever backtick it can find — often the next
    # fence — swallowing everything between (headers, **bold**, etc.) into
    # one literal blob. Handling fences separately avoids that entirely.
    # Group 1 captures the fence's language tag (e.g. "python") so it can be
    # shown as a header chip; group 2 is the code body itself.
    _MD_FENCE_RE = re.compile(r"```[ \t]*([A-Za-z0-9_+#.-]*)[ \t]*\n?(.*?)```", re.DOTALL)
    _MD_SPAN_RE  = re.compile(r"(\*\*(.+?)\*\*|`([^`]+)`)", re.DOTALL)

    def _insert_markdown(self, widget: tk.Text, text: str):
        pos = 0
        for fm in self._MD_FENCE_RE.finditer(text):
            self._insert_inline_markdown(widget, text[pos:fm.start()])
            lang = (fm.group(1) or "").strip()
            code = fm.group(2)
            if code.endswith("\n"):
                code = code[:-1]
            if widget.index(tk.END) != "1.0":
                widget.insert(tk.END, "\n")
            self._embed_code_block(widget, lang, code)
            widget.insert(tk.END, "\n")
            pos = fm.end()
        self._insert_inline_markdown(widget, text[pos:])

    def _embed_code_block(self, widget: tk.Text, lang: str, code_text: str):
        """Embed a Claude-style code block: a header bar (language chip +
        icon-only copy button) sitting flush on top of the code itself.

        The code is rendered in its own dedicated, non-wrapping Text
        widget rather than as a background-colored tag inside the prose
        widget above. Tagging text inside the prose widget meant the
        highlight only ever painted behind actual characters on each
        display line — any mismatch between the prose font's average
        character width (used to size the widget) and the code font's
        real, monospaced width made lines wrap unpredictably, leaving the
        highlighted rectangles jagged and uneven. A dedicated widget with
        its own solid background sidesteps that entirely: every line gets
        the exact same, full-width highlight.

        The language label lives in its own Label widget and is never
        concatenated into code_text, so it can never end up in a copy or
        paste of the code."""
        try:
            code_bg = _darken(widget.cget("bg"), 24)
        except tk.TclError:
            code_bg = _darken(BG_PANEL, 24)
        header_bg = _darken(code_bg, 8)

        code_lines = code_text.split("\n")
        max_len = max((len(ln) for ln in code_lines), default=0)

        try:
            fnt = tkfont.Font(font=("Consolas", 11))
            char_w = fnt.measure("0")
        except Exception:
            char_w = 7
        # Match the header's width to the code widget beneath it (which
        # gets padx=10 on each side) so the two form one continuous card.
        width_px = max(90, min(680, max_len * char_w + 20))

        card = tk.Frame(widget, bg=code_bg)

        header = tk.Frame(card, bg=header_bg, height=26, width=width_px)
        header.pack_propagate(False)
        header.pack(fill=tk.X)

        label_text = LANG_DISPLAY.get(lang.lower(), lang.capitalize() if lang else "Code")
        tk.Label(header, text=f"<{label_text}>", bg=header_bg, fg="#a9a6a0",
                 font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(10, 4))

        IconButton(header, "copy",
                   lambda: self._copy_to_clipboard(code_text, "Code copied to clipboard."),
                   bg=header_bg, size=22).pack(side=tk.RIGHT, padx=(0, 4))

        code_box = tk.Text(
            card, bg=code_bg, fg="#e8e6e1", font=("Consolas", 11),
            wrap=tk.NONE, bd=0, highlightthickness=0,
            padx=10, pady=6, width=max(1, max_len), height=max(1, len(code_lines)),
            cursor="xterm", relief=tk.FLAT, selectbackground="#4a4a4a",
            # A little breathing room above/below each line — with zero
            # spacing the monospaced font otherwise reads as one dense
            # block, especially next to the airier prose text above it.
            spacing1=2, spacing3=2,
        )
        code_box.insert("1.0", code_text)
        _make_text_readonly(code_box)
        code_box.pack(fill=tk.X)
        self._bind_main_scroll(card)

        widget.window_create(tk.END, window=card)

    def _copy_to_clipboard(self, text: str, status_msg: str = "Copied to clipboard."):
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update()  # keeps clipboard contents after focus changes on some platforms
        except tk.TclError:
            pass
        self.status_var.set(status_msg)

    def _insert_inline_markdown(self, widget: tk.Text, text: str):
        pos = 0
        for m in self._MD_SPAN_RE.finditer(text):
            widget.insert(tk.END, text[pos:m.start()])
            if m.group(2) is not None:
                widget.insert(tk.END, m.group(2), "bold")
            else:
                widget.insert(tk.END, m.group(3), "code")
            pos = m.end()
        widget.insert(tk.END, text[pos:])

    def _add_attachment_chips(self, parent, attachments, anchor="w"):
        if not attachments:
            return
        row = tk.Frame(parent, bg=BG_PANEL)
        row.pack(anchor=anchor, pady=(4, 0))
        for a in attachments:
            icon = "🖼" if a.get("type") == "image" else "📄"
            chip = tk.Button(
                row, text=f"{icon} {a.get('name', 'file')[:22]}",
                bg=CHIP_BG, fg="#ffffff", font=("Segoe UI", 8),
                relief=tk.FLAT, bd=0, padx=6, pady=2, cursor="hand2",
                activebackground="#454138",
                command=lambda att=a: self._preview_attachment(att)
            )
            chip.pack(side=tk.LEFT, padx=2)

    def _preview_attachment(self, a: dict):
        """View an attachment's actual contents — before or after sending."""
        win = tk.Toplevel(self)
        win.title(f"📎 {a.get('name', 'Attachment')}")
        win.configure(bg=BG_DARK)

        if a.get("type") == "image":
            win.geometry("580x540")
            if PIL_AVAILABLE:
                try:
                    raw = base64.b64decode(a["data"])
                    img = Image.open(_io.BytesIO(raw))
                    img.thumbnail((540, 460))
                    photo = ImageTk.PhotoImage(img)
                    lbl = tk.Label(win, image=photo, bg=BG_DARK)
                    lbl.image = photo  # keep a reference alive
                    lbl.pack(padx=12, pady=12)
                    w, h = img.size
                    tk.Label(win, text=f"{a.get('name', '')}  ({w}×{h})",
                             bg=BG_DARK, fg=STATUS_CLR,
                             font=("Segoe UI", 9)).pack(pady=(0, 8))
                except Exception as e:
                    tk.Label(win, text=f"Could not preview image: {e}",
                             bg=BG_DARK, fg="#ffffff", wraplength=520,
                             justify="left").pack(padx=12, pady=20)
            else:
                tk.Label(
                    win, text="Install Pillow to preview images inline:\n"
                              "    pip install Pillow",
                    bg=BG_DARK, fg="#ffffff", wraplength=520, justify="left",
                    font=("Segoe UI", 10)
                ).pack(padx=12, pady=30)
        else:
            win.geometry("680x560")
            tk.Label(win, text=a.get("name", ""), bg=BG_DARK, fg=TITLE_CLR,
                     font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=10, pady=(10, 4))
            txt = scrolledtext.ScrolledText(
                win, bg=INPUT_BG, fg="#ffffff", insertbackground="#ffffff",
                wrap=tk.WORD, font=("Consolas", 10), relief=tk.FLAT, bd=0
            )
            txt.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
            txt.insert("1.0", a.get("content", "(no content)"))
            txt.configure(state=tk.DISABLED)

    def _add_bubble(self, role: str, text: str, timestamp: str = "",
                     attachments: Optional[list] = None,
                     msg_index: Optional[int] = None):
        """Add a chat bubble. role = 'user' | 'ryuu'"""
        if not timestamp:
            timestamp = datetime.now().strftime("%H:%M")

        outer = tk.Frame(self.messages_frame, bg=BG_PANEL)
        outer.pack(fill=tk.X, padx=10, pady=4)

        if role == "ryuu":
            bubble_frame = tk.Frame(outer, bg=BG_PANEL)
            bubble_frame.pack(anchor="w", fill=tk.X)

            name_row = tk.Frame(bubble_frame, bg=BG_PANEL)
            name_row.pack(anchor="w")
            tk.Label(name_row, text="Ryuu", bg=BG_PANEL, fg=RYUU_NAME_CLR,
                     font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT)

            bubble = tk.Frame(bubble_frame, bg=RYUU_BUBBLE, padx=12, pady=8)
            bubble.pack(anchor="w")

            msg_widget = self._rich_text_widget(bubble, text, RYUU_BUBBLE, "#ffffff", 680)

            tk.Label(bubble, text=timestamp,
                     bg=RYUU_BUBBLE, fg=TIMESTAMP_CLR,
                     font=("Segoe UI", 8)).pack(anchor="e")

            self._add_attachment_chips(bubble_frame, attachments, anchor="w")

            action_row = tk.Frame(bubble_frame, bg=BG_PANEL)
            action_row.pack(anchor="w", pady=(2, 0))
            IconButton(action_row, "copy", lambda: self._copy_to_clipboard(text),
                       bg=BG_PANEL).pack(side=tk.LEFT)
            if msg_index is not None:
                IconButton(action_row, "retry",
                           lambda idx=msg_index: self._retry_ryuu_message(idx),
                           bg=BG_PANEL).pack(side=tk.LEFT, padx=(6, 0))
        else:
            bubble_frame = tk.Frame(outer, bg=BG_PANEL)
            bubble_frame.pack(anchor="e")

            name_row = tk.Frame(bubble_frame, bg=BG_PANEL)
            name_row.pack(anchor="e")
            tk.Label(name_row, text="You", bg=BG_PANEL, fg=USER_NAME_CLR,
                     font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=2)

            bubble = tk.Frame(bubble_frame, bg=USER_BUBBLE, padx=12, pady=8)
            bubble.pack(anchor="e")

            msg_widget = self._rich_text_widget(bubble, text, USER_BUBBLE, "#ffffff", 480)

            tk.Label(bubble, text=timestamp,
                     bg=USER_BUBBLE, fg=TIMESTAMP_CLR,
                     font=("Segoe UI", 8)).pack(anchor="e")

            self._add_attachment_chips(bubble_frame, attachments, anchor="e")

            action_row = tk.Frame(bubble_frame, bg=BG_PANEL)
            action_row.pack(anchor="e", pady=(2, 0))
            if msg_index is not None:
                IconButton(action_row, "edit",
                           lambda idx=msg_index: self._start_edit_message(idx),
                           bg=BG_PANEL).pack(side=tk.RIGHT, padx=(6, 0))
            IconButton(action_row, "copy", lambda: self._copy_to_clipboard(text),
                       bg=BG_PANEL).pack(side=tk.RIGHT)

        self._bind_main_scroll(outer)
        self._scroll_bottom()
        return msg_widget

    def _scroll_bottom(self):
        self.messages_frame.update_idletasks()
        self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))
        self.chat_canvas.yview_moveto(1.0)

    # ------------------------------------------------------------------
    # Streaming bubble
    # ------------------------------------------------------------------

    def _add_streaming_bubble(self):
        timestamp = datetime.now().strftime("%H:%M")
        self._stream_timestamp = timestamp
        outer = tk.Frame(self.messages_frame, bg=BG_PANEL)
        outer.pack(fill=tk.X, padx=10, pady=4)
        self._stream_outer = outer

        name_stream_row = tk.Frame(outer, bg=BG_PANEL)
        name_stream_row.pack(anchor="w")
        tk.Label(name_stream_row, text="Ryuu", bg=BG_PANEL,
                 fg=RYUU_NAME_CLR, font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT)

        bubble = tk.Frame(outer, bg=RYUU_BUBBLE, padx=12, pady=8)
        bubble.pack(anchor="w")

        # Live-rendering Text widget (not a plain Label) so **bold** / `code`
        # spans show as real formatting *while tokens are still streaming
        # in*, instead of staying as literal asterisks until the reply
        # finishes and gets swapped for the finalized rich-text bubble.
        font_normal = ("Segoe UI", 11)
        fnt = tkfont.Font(family=font_normal[0], size=font_normal[1])
        self._stream_font = fnt
        avg = fnt.measure("abcdefghijklmnopqrstuvwxyz0123456789") / 36.0
        chars = max(15, int(680 / max(avg, 1)))

        self._stream_label = tk.Text(
            bubble, bg=RYUU_BUBBLE, fg="#ffffff", font=font_normal,
            wrap=tk.WORD, bd=0, highlightthickness=0, padx=0, pady=0,
            width=chars, height=1, cursor="arrow", relief=tk.FLAT,
            selectbackground="#4a4a4a",
        )
        self._stream_label.tag_configure(
            "bold", font=(font_normal[0], font_normal[1], "bold"))
        self._stream_label.tag_configure(
            "code", font=("Consolas", 11), background=_darken(RYUU_BUBBLE, 24))
        self._stream_label.insert("1.0", "▌")
        self._stream_label.configure(state=tk.DISABLED)
        self._stream_label.pack(anchor="w", fill=tk.X)

        self._stream_ts = tk.Label(bubble, text=timestamp,
                                    bg=RYUU_BUBBLE, fg=TIMESTAMP_CLR,
                                    font=("Segoe UI", 8))
        self._stream_ts.pack(anchor="e")

        self._stream_text = ""
        self._cursor_visible = True
        self._blink_job = self.after(500, self._blink_cursor)
        self._scroll_bottom()

    def _blink_cursor(self):
        if not hasattr(self, "_stream_label") or not self._stream_label.winfo_exists():
            return
        self._cursor_visible = not self._cursor_visible
        self._update_stream_label()
        self._blink_job = self.after(500, self._blink_cursor)

    def _append_stream_token(self, token: str):
        """Called from background thread — schedules UI update."""
        self._stream_text += token
        self._cursor_visible = True  # keep it solid while new tokens land
        self.after(0, self._update_stream_label)

    def _update_stream_label(self):
        if hasattr(self, "_stream_label") and self._stream_label.winfo_exists():
            display = strip_think(self._stream_text)
            if not display and _THINK_OPEN_RE.search(self._stream_text):
                display = "…thinking"
            cursor = "▌" if self._cursor_visible else " "

            # Re-render as markdown on every token so **bold** / `code`
            # spans turn into real formatting as soon as their closing
            # marker arrives, instead of waiting for the message to finish
            # and get swapped for the finalized rich-text bubble.
            widget = self._stream_label
            widget.configure(state=tk.NORMAL)
            widget.delete("1.0", tk.END)
            self._insert_markdown(widget, display + cursor)
            while widget.get("end-2c", "end-1c") == "\n":
                widget.delete("end-2c", "end-1c")
            widget.configure(state=tk.DISABLED)
            widget.configure(height=_compute_text_height_lines(widget, self._stream_font))
        self._scroll_bottom()

    def _finalize_stream(self, final_text: Optional[str] = None):
        if hasattr(self, "_blink_job") and self._blink_job is not None:
            try:
                self.after_cancel(self._blink_job)
            except Exception:
                pass
            self._blink_job = None
        text = final_text if final_text is not None else strip_think(self._stream_text)
        if not text:
            text = "Ryuu didn't catch that clearly — could you rephrase?"
        ts = getattr(self, "_stream_timestamp", "")
        if hasattr(self, "_stream_outer") and self._stream_outer.winfo_exists():
            self._stream_outer.destroy()
        self._add_bubble("ryuu", text, ts)

    # ------------------------------------------------------------------
    # Attachments
    # ------------------------------------------------------------------

    def _attach_files(self):
        paths = filedialog.askopenfilenames(title="Attach files", filetypes=FILE_TYPES)
        if not paths:
            return
        added = 0
        for p in paths:
            ext = os.path.splitext(p)[1].lower()
            name = os.path.basename(p)
            try:
                if ext in IMAGE_EXTS:
                    if os.path.getsize(p) > MAX_IMAGE_BYTES:
                        self.status_var.set(f"Skipped {name}: image larger than 8MB.")
                        continue
                    with open(p, "rb") as f:
                        b64 = base64.b64encode(f.read()).decode()
                    self.pending_attachments.append({"type": "image", "name": name, "data": b64})
                elif ext == ".pdf":
                    text = extract_pdf_text(p)
                    self.pending_attachments.append({"type": "text", "name": name, "lang": "", "content": text})
                else:
                    text = read_text_file(p)
                    self.pending_attachments.append({"type": "text", "name": name, "lang": lang_for(p), "content": text})
                added += 1
            except Exception as e:
                self.status_var.set(f"Failed to attach {name}: {e}")
                continue
        self._refresh_attach_bar()
        if added:
            self.status_var.set(f"{added} file(s) attached — type a message (or none) and hit Send.")

    def _paste_handler(self, event=None):
        if not PIL_AVAILABLE:
            return  # let default text paste happen
        try:
            img = ImageGrab.grabclipboard()
        except Exception:
            return
        if isinstance(img, Image.Image):
            buf = _io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            idx = len(self.pending_attachments) + 1
            self.pending_attachments.append({"type": "image", "name": f"pasted_image_{idx}.png", "data": b64})
            self._refresh_attach_bar()
            self.status_var.set("Pasted image attached.")
            return "break"  # don't also try to paste as text
        return None  # not an image — fall through to normal text paste

    def _refresh_attach_bar(self):
        for w in self.attach_bar.winfo_children():
            w.destroy()
        if not self.pending_attachments:
            self.attach_bar.pack_forget()
            return
        self.attach_bar.pack(fill=tk.X, side=tk.BOTTOM, padx=8, pady=(4, 0),
                              before=self._input_frame_ref())
        for i, a in enumerate(self.pending_attachments):
            chip = tk.Frame(self.attach_bar, bg=CHIP_BG, padx=6, pady=3)
            chip.pack(side=tk.LEFT, padx=3, pady=3)

            thumb_photo = None
            if a["type"] == "image" and PIL_AVAILABLE:
                try:
                    raw = base64.b64decode(a["data"])
                    img = Image.open(_io.BytesIO(raw))
                    img.thumbnail((28, 28))
                    thumb_photo = ImageTk.PhotoImage(img)
                except Exception:
                    thumb_photo = None

            if thumb_photo is not None:
                thumb_lbl = tk.Label(chip, image=thumb_photo, bg=CHIP_BG, cursor="hand2")
                thumb_lbl.image = thumb_photo  # keep a reference alive
                thumb_lbl.pack(side=tk.LEFT, padx=(0, 4))
                thumb_lbl.bind("<Button-1>", lambda e, att=a: self._preview_attachment(att))
            else:
                icon = "🖼" if a["type"] == "image" else "📄"
                tk.Label(chip, text=icon, bg=CHIP_BG, fg="#ffffff",
                         font=("Segoe UI", 10)).pack(side=tk.LEFT, padx=(0, 4))

            name_lbl = tk.Label(chip, text=a['name'][:24], bg=CHIP_BG, fg="#ffffff",
                                 cursor="hand2", font=("Segoe UI", 8))
            name_lbl.pack(side=tk.LEFT)
            name_lbl.bind("<Button-1>", lambda e, att=a: self._preview_attachment(att))
            tk.Button(chip, text="✕", bg=CHIP_BG, fg=STATUS_CLR, relief=tk.FLAT,
                      bd=0, font=("Segoe UI", 8, "bold"), cursor="hand2",
                      command=lambda idx=i: self._remove_attachment(idx)
                      ).pack(side=tk.LEFT, padx=(6, 0))

    def _input_frame_ref(self):
        # Direct reference to the input row, set when it was created.
        # (Previously this guessed the widget's internal Tk name, which
        # didn't reliably match and made the attach bar's position unstable.)
        return getattr(self, "_input_frame", self.attach_bar)

    def _remove_attachment(self, idx: int):
        if 0 <= idx < len(self.pending_attachments):
            self.pending_attachments.pop(idx)
        self._refresh_attach_bar()

    # ------------------------------------------------------------------
    # Send / Chat
    # ------------------------------------------------------------------

    def _set_stop_btn_active(self, active: bool):
        """Enable the Stop button (bright red, clickable) while Ryuu is
        generating a reply; grey it back out once the reply is done."""
        if not hasattr(self, "stop_btn") or not self.stop_btn.winfo_exists():
            return
        color = STOP_BTN_ON if active else STOP_BTN_OFF
        self.stop_btn.config(state=tk.NORMAL if active else tk.DISABLED,
                              bg=color, activebackground="#a83f3f")
        self.stop_btn._normal_bg = color  # keep _hoverify's resting color in sync

    def _stop_generation(self):
        """User hit Stop — signal the background thread to bail out of the
        streaming read loop. Whatever text has arrived so far is kept."""
        if not self.is_typing or not hasattr(self, "_stop_event"):
            return
        self._stop_event.set()
        self.status_var.set("Stopping...")
        self._set_stop_btn_active(False)  # prevent repeat clicks while it winds down

    def _autosize_input_bar(self, event=None):
        """Grow the input row as the message wraps onto more lines, and
        shrink it back down when text is deleted — clamped between
        _input_min_h and _input_max_h so it can't swallow the whole
        window. Past the max, the Text widget just scrolls internally."""
        try:
            fnt = tkfont.Font(font=self.input_box.cget("font"))
            lines = _compute_text_height_lines(self.input_box, fnt)
            line_px = max(1, fnt.metrics("linespace"))
            new_h = lines * line_px + 24  # + top/bottom pady (12 + 12)
            new_h = max(self._input_min_h, min(new_h, self._input_max_h))
            if new_h != int(self._input_frame.cget("height")):
                self._input_frame.config(height=new_h)
        except Exception:
            pass

    def _on_return_key(self, event):
        if event.state & 0x0001:  # Shift held -> allow newline
            return None
        self._send()
        return "break"

    def _send(self):
        if self.is_typing:
            return
        text = self.input_box.get("1.0", "end-1c").strip()
        if not text and not self.pending_attachments:
            return

        attachments = self.pending_attachments

        has_images = any(a["type"] == "image" for a in attachments)
        model_override = None
        if has_images and not is_vision_model(self.session.model):
            vision_model = pick_vision_model()
            if vision_model:
                # Automatic swap: default model (e.g. qwen3:8b) unloads,
                # vision model loads just for this reply, then swaps back —
                # keeps only one model in RAM at a time.
                model_override = vision_model
            else:
                proceed = messagebox.askyesno(
                    "Model can't see images",
                    f"'{self.session.model}' isn't a vision model, so it can't "
                    "actually look at attached images — it will only see your "
                    "text.\n\nFor real image understanding, pull a vision "
                    "model, e.g.:\n"
                    "    ollama pull qwen2.5vl:7b\n"
                    "    ollama pull llava:13b\n"
                    "then send the image again.\n\n"
                    "Send anyway (image will be ignored by the model)?",
                    parent=self
                )
                if not proceed:
                    return

        self.pending_attachments = []
        self._refresh_attach_bar()
        self.input_box.delete("1.0", "end")
        self._autosize_input_bar()

        conv = self._active_conv()
        self._dispatch_user_message(conv, text, attachments, model_override=model_override)

    def _dispatch_user_message(self, conv: dict, text: str, attachments: list,
                                model_override: Optional[str] = None):
        """Append a user message to `conv`, render its bubble, and kick off
        the background thread that fetches Ryuu's reply. Shared by normal
        sends (_send) and the edit-message-and-regenerate flow."""
        names = [a["name"] for a in attachments]
        display_text = text if text else "(sent attachment)"
        if names:
            display_text += "\n📎 " + ", ".join(names)

        combined = text
        images_b64: List[str] = []
        for a in attachments:
            if a["type"] == "image":
                images_b64.append(a["data"])
            else:
                lang = a.get("lang", "")
                combined += f"\n\n--- Attached file: {a['name']} ---\n```{lang}\n{a['content']}\n```"
        if not combined.strip() and images_b64:
            combined = "Please look at the attached image(s) and help me with them."
        if images_b64 and not model_override and not is_vision_model(self.session.model):
            combined += ("\n\n[Note: if your model isn't vision-capable, tell the user "
                         "plainly instead of guessing at the image contents.]")

        ts = datetime.now().strftime("%H:%M")
        msg_index = len(conv["messages"])
        conv["messages"].append({
            "time": ts, "role": "USER", "text": combined, "display": display_text,
            "attachments": attachments,  # kept for post-send preview
        })
        conv["updated"] = datetime.now().isoformat()
        if conv.get("title", "New Chat") == "New Chat" and text:
            conv["title"] = text[:40].strip()
        self._save_conversations()
        self._refresh_conv_list()

        self._add_bubble("user", display_text, ts, attachments=attachments, msg_index=msg_index)

        self.is_typing = True
        self._stop_event = threading.Event()
        self.after(0, self._set_stop_btn_active, True)
        default_model = self.session.model
        if model_override:
            self.status_var.set(
                f"🖼 Unloading {default_model} → loading {model_override} for this photo..."
            )
        else:
            self.status_var.set("Ryuu is thinking...")

        def run():
            stop_event = self._stop_event
            try:
                if model_override:
                    # Free RAM: drop the default model before the vision
                    # model needs to load.
                    unload_model(default_model)

                if self.session.stream:
                    self.after(0, self._add_streaming_bubble)
                    time.sleep(0.05)
                    reply = chat(self.session, combined, images=images_b64,
                                 stream_callback=self._append_stream_token,
                                 model_override=model_override,
                                 stop_event=stop_event)
                    self.after(0, lambda: self._finalize_stream(reply))
                else:
                    reply = chat(self.session, combined, images=images_b64,
                                 model_override=model_override,
                                 stop_event=stop_event)
                    self.after(0, lambda: self._add_bubble("ryuu", reply))

                if model_override:
                    # Swap back: free the vision model so the default model
                    # is the only one in memory again, ready for next turn.
                    self.after(0, lambda: self.status_var.set(
                        f"🔄 Switching back to {default_model}..."
                    ))
                    unload_model(model_override)
            except Exception as e:
                reply = f"[Error: {e}]"
                self.after(0, lambda: self._add_bubble("ryuu", reply))

            ts2 = datetime.now().strftime("%H:%M")
            conv["messages"].append({"time": ts2, "role": "RYUU", "text": reply, "display": reply})
            conv["updated"] = datetime.now().isoformat()
            self._save_conversations()

            self.after(0, self._refresh_conv_list)
            self.after(0, lambda: self.status_var.set("Ready — ask Ryuu anything."))
            self.after(0, lambda: setattr(self, "is_typing", False))
            self.after(0, self._set_stop_btn_active, False)

        threading.Thread(target=run, daemon=True).start()

    # ------------------------------------------------------------------
    # Edit message
    # ------------------------------------------------------------------

    def _start_edit_message(self, msg_index: int):
        """Replace a user bubble with an inline editable box (Save &
        Regenerate / Cancel), matching Claude's edit-message flow."""
        if self.is_typing:
            self.status_var.set("Wait for Ryuu to finish replying before editing.")
            return
        conv = self._active_conv()
        if msg_index >= len(conv["messages"]):
            return
        msg = conv["messages"][msg_index]
        original_text = msg.get("text", msg.get("display", ""))

        for w in self.messages_frame.winfo_children():
            w.destroy()
        for i, m in enumerate(conv["messages"][:msg_index]):
            role = "user" if m["role"] == "USER" else "ryuu"
            self._add_bubble(role, m.get("display", m.get("text", "")), m.get("time", ""),
                              attachments=m.get("attachments"),
                              msg_index=i)

        self._render_edit_box(msg_index, original_text)

    def _render_edit_box(self, msg_index: int, original_text: str):
        outer = tk.Frame(self.messages_frame, bg=BG_PANEL)
        outer.pack(fill=tk.X, padx=10, pady=4)

        bubble_frame = tk.Frame(outer, bg=BG_PANEL)
        bubble_frame.pack(anchor="e")

        name_row = tk.Frame(bubble_frame, bg=BG_PANEL)
        name_row.pack(anchor="e")
        tk.Label(name_row, text="Editing…", bg=BG_PANEL, fg=USER_NAME_CLR,
                 font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=2)

        bubble = tk.Frame(bubble_frame, bg=USER_BUBBLE, padx=12, pady=8)
        bubble.pack(anchor="e")

        edit_box = tk.Text(
            bubble, width=48, height=max(2, min(10, original_text.count("\n") + 2)),
            wrap=tk.WORD, bg=_darken(USER_BUBBLE, 10), fg="#ffffff",
            insertbackground="#ffffff", relief=tk.FLAT, bd=0,
            font=("Segoe UI", 11),
        )
        edit_box.insert("1.0", original_text)
        edit_box.pack(fill=tk.X)
        edit_box.focus_set()
        edit_box.mark_set("insert", "end")

        btn_row = tk.Frame(bubble, bg=USER_BUBBLE)
        btn_row.pack(anchor="e", pady=(6, 0))

        def _cancel():
            self._switch_conversation(self.active_id)

        def _save():
            new_text = edit_box.get("1.0", "end-1c").strip()
            if not new_text:
                return
            self._commit_edit(msg_index, new_text)

        tk.Button(btn_row, text="Cancel", font=("Segoe UI", 9), relief=tk.FLAT, bd=0,
                  bg=_darken(USER_BUBBLE, 10), fg="#ffffff", cursor="hand2",
                  padx=10, pady=3, command=_cancel).pack(side=tk.RIGHT, padx=(6, 0))
        tk.Button(btn_row, text="Save & Regenerate", font=("Segoe UI", 9, "bold"),
                  relief=tk.FLAT, bd=0, bg=RYUU_NAME_CLR, fg="#1a1a1a", cursor="hand2",
                  padx=10, pady=3, command=_save).pack(side=tk.RIGHT)

        self._bind_main_scroll(outer)
        self._scroll_bottom()

    def _commit_edit(self, msg_index: int, new_text: str):
        conv = self._active_conv()
        # Drop the edited message and everything after it — its context is
        # about to change, so any later turns are no longer valid.
        conv["messages"] = conv["messages"][:msg_index]

        self.session.history.clear()
        recent = conv["messages"][-(self.session.max_history * 2):]
        for m in recent:
            role = "user" if m["role"] == "USER" else "assistant"
            self.session.history.append(Message(role, m.get("text", "")))

        for w in self.messages_frame.winfo_children():
            w.destroy()
        for i, m in enumerate(conv["messages"]):
            role = "user" if m["role"] == "USER" else "ryuu"
            self._add_bubble(role, m.get("display", m.get("text", "")), m.get("time", ""),
                              attachments=m.get("attachments"),
                              msg_index=i)

        self._dispatch_user_message(conv, new_text, [])

    # ------------------------------------------------------------------
    # Retry a Ryuu reply
    # ------------------------------------------------------------------

    def _retry_ryuu_message(self, msg_index: int):
        """Regenerate one of Ryuu's replies from scratch: drop that reply
        (and anything after it, since it's no longer the latest turn) and
        re-ask using the same user message that prompted it — Claude's
        "retry response" flow."""
        if self.is_typing:
            self.status_var.set("Wait for Ryuu to finish replying before retrying.")
            return
        conv = self._active_conv()
        if msg_index >= len(conv["messages"]):
            return

        # Walk backwards to find the user message this reply answered.
        user_idx = msg_index - 1
        while user_idx >= 0 and conv["messages"][user_idx]["role"] != "USER":
            user_idx -= 1
        if user_idx < 0:
            return

        user_msg = conv["messages"][user_idx]
        original_text = user_msg.get("text", user_msg.get("display", ""))
        attachments = user_msg.get("attachments", [])

        conv["messages"] = conv["messages"][:user_idx]

        self.session.history.clear()
        recent = conv["messages"][-(self.session.max_history * 2):]
        for m in recent:
            role = "user" if m["role"] == "USER" else "assistant"
            self.session.history.append(Message(role, m.get("text", "")))

        for w in self.messages_frame.winfo_children():
            w.destroy()
        for i, m in enumerate(conv["messages"]):
            role = "user" if m["role"] == "USER" else "ryuu"
            self._add_bubble(role, m.get("display", m.get("text", "")), m.get("time", ""),
                              attachments=m.get("attachments"),
                              msg_index=i)

        self._dispatch_user_message(conv, original_text, attachments)

    # ------------------------------------------------------------------
    # Greeting
    # ------------------------------------------------------------------

    def _post_greeting(self):
        greeting = (
            "Hi, I'm Ryuu. Ask me to explain a concept, debug some code, or "
            "write code in any language. You can also attach images, PDFs, "
            "or code files with 📎 and I'll read them before answering."
        )
        self.after(300, lambda: self._add_bubble(
            "ryuu", greeting, datetime.now().strftime("%H:%M")
        ))

    # ------------------------------------------------------------------
    # Dialogs
    # ------------------------------------------------------------------

    def _open_about_you(self):
        """Shown as a panel inside the main window (place()'d over the whole
        app), not a separate OS-level Toplevel window."""
        existing = getattr(self, "_about_overlay", None)
        if existing is not None and existing.winfo_exists():
            existing.destroy()

        overlay = tk.Frame(self, bg="#000000")
        self._about_overlay = overlay
        overlay.place(x=0, y=0, relwidth=1, relheight=1)
        # dim the app behind the card a little
        try:
            overlay.configure(bg=_darken(BG_DARK, 0))
        except Exception:
            pass

        card = tk.Frame(overlay, bg=BG_DARK, highlightthickness=1,
                         highlightbackground="#4a473d", highlightcolor="#4a473d")
        card.place(relx=0.5, rely=0.5, anchor="center", width=480, height=460)

        header = tk.Frame(card, bg=BG_DARK)
        header.pack(fill=tk.X, padx=14, pady=(12, 0))
        tk.Label(header, text="👤 About You", bg=BG_DARK, fg=TITLE_CLR,
                 font=("Segoe UI", 11, "bold")).pack(side=tk.LEFT)
        close_btn = tk.Button(header, text="✕", bg=BG_DARK, fg=STATUS_CLR,
                               relief=tk.FLAT, bd=0, font=("Segoe UI", 10, "bold"),
                               cursor="hand2", command=overlay.destroy)
        close_btn.pack(side=tk.RIGHT)

        tk.Label(
            card, text="Tell Ryuu about yourself once — it'll remember this\n"
                      "in every chat, old and new (stored only on this computer).",
            bg=BG_DARK, fg=STATUS_CLR, font=("Segoe UI", 9),
            justify="left"
        ).pack(anchor="w", padx=14, pady=(10, 6))

        tk.Label(
            card, text="e.g. your name, role/skill level, languages you work in, "
                      "preferences (concise answers, lots of examples, etc.)",
            bg=BG_DARK, fg=STATUS_CLR, font=("Segoe UI", 8, "italic"),
            wraplength=440, justify="left"
        ).pack(anchor="w", padx=14, pady=(0, 8))

        # Reserve the button row's space at the BOTTOM before the scrollable
        # text box is packed — otherwise a box with fill/expand=True claims
        # all remaining space in the fixed-height card and pushes Save
        # completely off-screen, which is why nothing ever got saved.
        btn_row = tk.Frame(card, bg=BG_DARK)
        btn_row.pack(side=tk.BOTTOM, fill=tk.X, padx=14, pady=(0, 14))

        box = scrolledtext.ScrolledText(
            card, bg=INPUT_BG, fg="#ffffff", insertbackground="#ffffff",
            wrap=tk.WORD, font=("Segoe UI", 10), relief=tk.FLAT, bd=0
        )
        box.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 10))
        box.insert("1.0", self.session.about_text)
        box.focus_set()

        def _save():
            about = box.get("1.0", "end-1c").strip()
            self.session.about_text = about
            save_profile(about)
            overlay.destroy()
            self.status_var.set(f"Saved to {PROFILE_FILE} — Ryuu will remember this in every chat.")

        save_btn = tk.Button(btn_row, text="Save", bg=BUTTON_SEND, fg="#ffffff",
                              relief=tk.FLAT, bd=0, font=("Segoe UI", 10, "bold"),
                              padx=16, pady=6, cursor="hand2", command=_save)
        save_btn.pack(side=tk.RIGHT)
        self._hoverify(save_btn, 16)

        def _close_overlay(_e=None):
            self.unbind("<Escape>")
            overlay.destroy()

        close_btn.config(command=_close_overlay)
        overlay.bind("<Button-1>", lambda e: _close_overlay() if e.widget is overlay else None)
        self.bind("<Escape>", _close_overlay)

    def _change_level(self):
        level = simpledialog.askstring(
            "Set Explain Level",
            "Enter level for Ryuu's explanations "
            "(e.g. 'beginner', 'intermediate', 'advanced', 'explain like I'm 12'):",
            parent=self
        )
        if level:
            self.current_level = level.strip().capitalize()
            self.session.level_hint = level.strip()
            self.level_btn.config(text=f"  Level: {self.current_level}  ")

    def _open_settings(self):
        win = tk.Toplevel(self)
        win.title("⚙ Settings")
        win.configure(bg=BG_DARK)
        win.geometry("380x340")
        win.resizable(False, False)

        def row(label, var, row_n, hint=""):
            tk.Label(win, text=label, bg=BG_DARK, fg="#ffffff",
                     font=("Segoe UI", 10)).grid(
                row=row_n, column=0, padx=16, pady=6, sticky="w")
            e = tk.Entry(win, textvariable=var, bg=INPUT_BG, fg="#ffffff",
                         insertbackground="#ffffff", relief=tk.FLAT, width=16)
            e.grid(row=row_n, column=1, padx=16, pady=6)
            if hint:
                tk.Label(win, text=hint, bg=BG_DARK, fg=STATUS_CLR,
                         font=("Segoe UI", 8, "italic"), wraplength=340,
                         justify="left").grid(row=row_n + 1, column=0, columnspan=2,
                                               padx=16, sticky="w")

        temp_var  = tk.StringVar(value=str(self.session.temperature))
        tok_var   = tk.StringVar(value=str(self.session.max_tokens))
        ctx_var   = tk.StringVar(value=str(self.session.num_ctx))
        hist_var  = tk.StringVar(value=str(self.session.max_history))

        row("Temperature:", temp_var, 0)
        row("Max response tokens:", tok_var, 1, "-1 = let Ryuu finish the full answer, uncapped.")
        row("Context window (num_ctx):", ctx_var, 3, "How much conversation/attached text Ryuu can see at once.")
        row("History (turns):", hist_var, 5)

        tk.Label(win, text="Model:", bg=BG_DARK, fg="#ffffff",
                 font=("Segoe UI", 10)).grid(row=6, column=0, padx=16, pady=6, sticky="w")
        model_pick_btn = tk.Button(
            win, text=self._model_btn_text(),
            bg=NEUTRAL_BTN, fg="#ffffff", font=("Segoe UI", 9),
            relief=tk.FLAT, bd=0, padx=8, pady=4, cursor="hand2",
            command=lambda: self._open_model_menu_from(model_pick_btn)
        )
        model_pick_btn.grid(row=6, column=1, padx=16, pady=6, sticky="w")
        self._hoverify(model_pick_btn)
        # Keep this button's label in sync if the model changes while open.
        self._settings_model_btn = model_pick_btn

        def save():
            try:
                self.session.temperature = float(temp_var.get())
                self.session.max_tokens  = int(tok_var.get())
                self.session.num_ctx     = int(ctx_var.get())
                self.session.max_history = int(hist_var.get())
                win.destroy()
                self.status_var.set("Settings saved.")
            except ValueError:
                messagebox.showerror("Error", "Invalid value.", parent=win)

        tk.Button(win, text="Save", bg=BUTTON_SEND, fg="#ffffff",
                  relief=tk.FLAT, font=("Segoe UI", 10, "bold"),
                  padx=16, pady=6, command=save,
                  cursor="hand2").grid(row=7, column=0, columnspan=2, pady=14)

    # CHAT HISTORY — search across all conversations
    def _show_history(self):
        existing = getattr(self, "_history_overlay", None)
        if existing is not None and existing.winfo_exists():
            existing.destroy()

        win = tk.Frame(self, bg=BG_DARK)
        self._history_overlay = win
        win.place(x=0, y=0, relwidth=1, relheight=1)

        toolbar = tk.Frame(win, bg=HEADER_BG, pady=6)
        toolbar.pack(fill=tk.X)

        tk.Label(toolbar, text="📋 Search Chat History",
                 bg=HEADER_BG, fg=TITLE_CLR,
                 font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT, padx=(12, 14))

        tk.Label(toolbar, text="Search:",
                 bg=HEADER_BG, fg=STATUS_CLR,
                 font=("Segoe UI", 10)).pack(side=tk.LEFT, padx=(0, 4))

        search_var = tk.StringVar()
        search_box = tk.Entry(toolbar, textvariable=search_var,
                               bg=INPUT_BG, fg="#ffffff",
                               insertbackground="#ffffff",
                               relief=tk.FLAT, font=("Segoe UI", 10))
        search_box.pack(side=tk.LEFT, padx=4, ipady=4, fill=tk.X, expand=True)

        def _btn_hist(parent, text, cmd, color=BUTTON_SEND):
            b = tk.Button(parent, text=text, bg=color, fg="#ffffff",
                          font=("Segoe UI", 9, "bold"),
                          relief=tk.FLAT, bd=0, padx=10, pady=4,
                          cursor="hand2",
                          activebackground="#c9663d",
                          activeforeground="#ffffff",
                          command=cmd)
            b.pack(side=tk.LEFT, padx=3)
            return b

        _btn_hist(toolbar, "Search", lambda: _populate(search_var.get().strip().lower()))

        def _clear_all():
            if not any(c["messages"] for c in self.conversations):
                messagebox.showinfo("Nothing to Clear", "History is already empty.", parent=win)
                return
            if not messagebox.askyesno(
                "Clear All History",
                "This will permanently delete every conversation.\n"
                "Ryuu won't remember any past chats.\n\nAre you sure?",
                parent=win
            ):
                return
            self.conversations = [new_conversation()]
            self._switch_conversation(self.conversations[0]["id"], greet_if_empty=True)
            _populate("")
            self.status_var.set("All history cleared.")

        _btn_hist(toolbar, "🗑 Clear All", _clear_all, NEUTRAL_BTN)

        def _on_close():
            _unbind_scroll(win)
            win.unbind_all("<Escape>")
            win.destroy()

        close_btn = tk.Button(toolbar, text="✕", bg=HEADER_BG, fg=STATUS_CLR,
                               font=("Segoe UI", 11, "bold"), relief=tk.FLAT, bd=0,
                               padx=8, cursor="hand2", command=lambda: _on_close())
        close_btn.pack(side=tk.RIGHT, padx=(4, 12))

        frame = tk.Frame(win, bg=BG_PANEL)
        frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        canvas = tk.Canvas(frame, bg=BG_PANEL, highlightthickness=0)
        scrollbar = tk.Scrollbar(frame, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = tk.Frame(canvas, bg=BG_PANEL)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_canvas_resize(e):
            canvas.itemconfig(win_id, width=e.width)
        canvas.bind("<Configure>", _on_canvas_resize)

        def _on_inner_resize(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        inner.bind("<Configure>", _on_inner_resize)

        def _on_mousewheel(e):
            canvas.yview_scroll(-1 * (e.delta // 120), "units")
        def _on_scroll_up(e):
            canvas.yview_scroll(-1, "units")
        def _on_scroll_down(e):
            canvas.yview_scroll(1, "units")

        def _bind_scroll(widget):
            widget.bind_all("<MouseWheel>", _on_mousewheel)
            widget.bind_all("<Button-4>", _on_scroll_up)
            widget.bind_all("<Button-5>", _on_scroll_down)

        def _unbind_scroll(widget):
            widget.unbind_all("<MouseWheel>")
            widget.unbind_all("<Button-4>")
            widget.unbind_all("<Button-5>")

        ROLE_STYLE = {
            "RYUU": (RYUU_BUBBLE, RYUU_NAME_CLR, RYUU_NAME_CLR, "#ffffff"),
            "USER": (USER_BUBBLE, USER_NAME_CLR, USER_NAME_CLR, "#ffffff"),
        }

        def _jump_to(conv_id):
            _unbind_scroll(win)
            win.unbind_all("<Escape>")
            win.destroy()
            self._switch_conversation(conv_id)

        def _populate(query: str = ""):
            for w in inner.winfo_children():
                w.destroy()

            convs = sorted(self.conversations, key=lambda c: c.get("updated", ""), reverse=True)
            any_shown = False

            for conv in convs:
                title = conv.get("title") or "New Chat"
                msgs = conv["messages"]
                if query:
                    title_match = query in title.lower()
                    msgs_f = [m for m in msgs if query in m.get("display", m.get("text", "")).lower()]
                    if not title_match and not msgs_f:
                        continue
                    shown_msgs = msgs if title_match else msgs_f
                else:
                    shown_msgs = msgs

                any_shown = True
                head = tk.Button(inner, text=f"💬  {title}", bg=BG_PANEL, fg=TITLE_CLR,
                                  font=("Segoe UI", 10, "bold"), relief=tk.FLAT, bd=0,
                                  anchor="w", cursor="hand2",
                                  command=lambda cid=conv["id"]: _jump_to(cid))
                head.pack(fill=tk.X, padx=8, pady=(10, 2))

                for entry in shown_msgs:
                    role = entry.get("role", "USER")
                    text = entry.get("display", entry.get("text", ""))
                    ts   = entry.get("time", "")
                    style = ROLE_STYLE.get(role, ROLE_STYLE["USER"])
                    bb, nc, ic, tc = style

                    outer_f = tk.Frame(inner, bg=BG_PANEL)
                    outer_f.pack(fill=tk.X, padx=8, pady=2)

                    if role == "USER":
                        bf = tk.Frame(outer_f, bg=BG_PANEL)
                        bf.pack(anchor="e")
                        tk.Label(bf, text=f"YOU  {ts}", bg=BG_PANEL, fg=nc,
                                 font=("Segoe UI", 7, "bold")).pack(anchor="e")
                        bubble = tk.Frame(bf, bg=bb, padx=10, pady=6)
                        bubble.pack(anchor="e")
                        tk.Label(bubble, text=text, bg=bb, fg=tc,
                                 font=("Segoe UI", 10),
                                 wraplength=420, justify=tk.LEFT).pack(anchor="w")
                    else:
                        bf = tk.Frame(outer_f, bg=BG_PANEL)
                        bf.pack(anchor="w")
                        tk.Label(bf, text=f"Ryuu  {ts}", bg=BG_PANEL, fg=nc,
                                 font=("Segoe UI", 7, "bold")).pack(anchor="w", padx=2)
                        bubble = tk.Frame(bf, bg=bb, padx=10, pady=6)
                        bubble.pack(anchor="w")
                        tk.Label(bubble, text=text, bg=bb, fg=tc,
                                 font=("Segoe UI", 10),
                                 wraplength=500, justify=tk.LEFT).pack(anchor="w")

            if not any_shown:
                tk.Label(inner, text="No messages found.",
                         bg=BG_PANEL, fg=STATUS_CLR,
                         font=("Segoe UI", 10, "italic")).pack(pady=20)

        _populate()
        _bind_scroll(win)
        search_box.bind("<Return>", lambda e: _populate(search_var.get().strip().lower()))
        win.bind_all("<Escape>", lambda e: _on_close())
        win.focus_set()

    def _conversation_to_transcript(self, conv: dict) -> str:
        """Render a conversation as a clean, readable transcript — Ryuu's
        take on 'export this chat', not a raw JSON dump."""
        title = conv.get("title") or "New Chat"
        lines = [f"🐉 RYUU — {title}", f"Exported {datetime.now().strftime('%Y-%m-%d %H:%M')}", "=" * 50, ""]
        for m in conv.get("messages", []):
            role = "YOU" if m.get("role") == "USER" else "RYUU"
            ts = m.get("time", "")
            text = m.get("display", m.get("text", ""))
            lines.append(f"[{ts}] {role}:")
            lines.append(text)
            lines.append("")
        return "\n".join(lines)

    def _export_current_conversation(self):
        conv = self._active_conv()
        if not conv.get("messages"):
            messagebox.showinfo("Nothing to Export", "This chat is empty.", parent=self)
            return

        existing = getattr(self, "_export_overlay", None)
        if existing is not None and existing.winfo_exists():
            existing.destroy()

        overlay = tk.Frame(self, bg="#000000")
        self._export_overlay = overlay
        overlay.place(x=0, y=0, relwidth=1, relheight=1)

        card = tk.Frame(overlay, bg=BG_DARK, highlightthickness=1,
                         highlightbackground="#4a473d", highlightcolor="#4a473d")
        card.place(relx=0.5, rely=0.5, anchor="center", width=380, height=220)

        chat_title = conv.get("title") or "New Chat"

        header = tk.Frame(card, bg=BG_DARK)
        header.pack(fill=tk.X, padx=14, pady=(12, 0))
        tk.Label(header, text="⬇ Export Chat", bg=BG_DARK, fg=TITLE_CLR,
                 font=("Segoe UI", 11, "bold")).pack(side=tk.LEFT)
        tk.Button(header, text="✕", bg=BG_DARK, fg=STATUS_CLR,
                  relief=tk.FLAT, bd=0, font=("Segoe UI", 10, "bold"),
                  cursor="hand2", command=overlay.destroy).pack(side=tk.RIGHT)

        tk.Label(card, text=chat_title, bg=BG_DARK, fg=RYUU_NAME_CLR,
                 font=("Segoe UI", 9, "bold"), wraplength=340, justify="left"
                 ).pack(anchor="w", padx=14, pady=(8, 0))

        tk.Label(card, text="Pick a format to save this chat as:",
                 bg=BG_DARK, fg=STATUS_CLR, font=("Segoe UI", 9)
                 ).pack(anchor="w", padx=14, pady=(4, 14))

        btn_row = tk.Frame(card, bg=BG_DARK)
        btn_row.pack(padx=14)

        def _pick(fmt):
            overlay.destroy()
            self._do_export(conv, fmt)

        json_btn = tk.Button(btn_row, text="🗂  .json", bg=BUTTON_SEND, fg="#ffffff",
                              relief=tk.FLAT, bd=0, font=("Segoe UI", 10, "bold"),
                              padx=24, pady=10, cursor="hand2",
                              command=lambda: _pick("json"))
        json_btn.pack(side=tk.LEFT, padx=(0, 10))
        self._hoverify(json_btn, 24)

        txt_btn = tk.Button(btn_row, text="📄  .txt", bg=NEUTRAL_BTN, fg="#ffffff",
                             relief=tk.FLAT, bd=0, font=("Segoe UI", 10, "bold"),
                             padx=24, pady=10, cursor="hand2",
                             command=lambda: _pick("txt"))
        txt_btn.pack(side=tk.LEFT)
        self._hoverify(txt_btn, 24)

        overlay.bind("<Button-1>", lambda e: overlay.destroy() if e.widget is overlay else None)
        self.bind("<Escape>", lambda e: overlay.destroy())

    def _do_export(self, conv: dict, fmt: str):
        safe_title = re.sub(r"[^\w\-]+", "_", conv.get("title") or "chat").strip("_") or "chat"
        ext = ".json" if fmt == "json" else ".txt"
        default_name = f"ryuu_{safe_title}{ext}"
        filetypes = ([("JSON file", "*.json"), ("All files", "*.*")] if fmt == "json"
                     else [("Text file", "*.txt"), ("All files", "*.*")])
        path = filedialog.asksaveasfilename(
            parent=self, title=f"Export Chat as {ext}",
            initialfile=default_name, defaultextension=ext, filetypes=filetypes
        )
        if not path:
            return
        try:
            if fmt == "json":
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(conv, f, ensure_ascii=False, indent=2)
            else:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self._conversation_to_transcript(conv))
            self.status_var.set(f"Chat exported to {path}")
        except Exception as e:
            messagebox.showerror("Error", str(e), parent=self)

    def _clear_chat(self):
        conv = self._active_conv()
        result = messagebox.askyesno(
            "Clear Chat",
            f"This will permanently delete all messages in \"{conv.get('title', 'this chat')}\".\n"
            "Continue?",
            parent=self
        )
        if result:
            conv["messages"] = []
            conv["title"] = "New Chat"
            self.session.history.clear()
            for widget in self.messages_frame.winfo_children():
                widget.destroy()
            self._save_conversations()
            self._refresh_conv_list()
            self.status_var.set("Chat cleared.")
            self._post_greeting()

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Ryuu — AI Explainer & Coding Assistant GUI")
    parser.add_argument("--model",       default=None)
    parser.add_argument("--history",     default=DEFAULT_HISTORY, type=int)
    parser.add_argument("--max-tokens",  default=DEFAULT_TOKENS,  type=int)
    parser.add_argument("--ctx",         default=DEFAULT_CTX,     type=int)
    parser.add_argument("--temperature", default=DEFAULT_TEMP,    type=float)
    parser.add_argument("--no-stream",   action="store_true")
    args = parser.parse_args()

    session = RyuuSession(
        model       = args.model or DEFAULT_MODEL,
        max_history = args.history,
        max_tokens  = args.max_tokens,
        temperature = args.temperature,
        stream      = not args.no_stream,
        num_ctx     = args.ctx,
        about_text  = load_profile(),
    )

    app = RyuuApp(session)

    def _startup_check():
        # Runs quietly in the background — window is already open and usable.
        try:
            ensure_ollama_running()
            model = pick_model(args.model or DEFAULT_MODEL)
            if model:
                session.model = model
        except Exception:
            pass

    threading.Thread(target=_startup_check, daemon=True).start()

    try:
        app.mainloop()
    finally:
        stop_ollama()


if __name__ == "__main__":
    main()