# 🐉 Ryuu Explainer AI

**Ryuu Explainer AI** is a high-performance, multi-modal desktop AI assistant built with pure Python and Tkinter. Powered by local LLMs running via **Ollama with Vulkan GPU acceleration**, Ryuu delivers low-latency, fully private AI capabilities directly on your local hardware (including Intel Arc GPUs)—with zero cloud calls, zero API subscription fees, and no data leaving your machine.

---

## ✨ Key Features

- **⚡ Hardware-Accelerated Local Inference (Vulkan Backend)**:
  - Powered by standard Ollama leveraging **Vulkan** compute for cross-platform GPU acceleration (optimized for **Intel Arc** integrated & discrete GPUs, as well as AMD and NVIDIA).
  - Eliminates the constraints of legacy, unmaintained vendor forks (such as older IPEX-LLM builds) while delivering support for the latest open-weights model architectures.
  - Dedicated async GPU memory management: immediately unloads previous models when switching to prevent VRAM overflow.

- **📷 Seamless Multi-Modal & Vision Intelligence**:
  - Full support for drag-and-drop or attaching images (`.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`) and clipboard pasting (**Ctrl+V**).
  - **Default Multimodal Engine (`gemma4:12b`)**: Reads images and writes code out of the box with no model swap required.
  - **Intelligent Vision Borrowing**: If an image is sent while using a text-only model (e.g., `qwen2.5-coder:14b`), Ryuu automatically routes that specific prompt through the best installed vision model (`gemma4`, `qwen3.5`, `qwen3-vl`, `qwen2.5vl`) and returns to your active model seamlessly.

- **💻 Curated Model Catalog**:
  - ✨ **Gemma 4 12B** (`gemma4:12b`) — Default balanced engine for multimodal reasoning, image parsing, and code writing.
  - 💻 **Qwen2.5 Coder 14B** (`qwen2.5-coder:14b`) — Specialized for complex software engineering and debugging.
  - 🧠 **Qwen3.5 9B** (`qwen3.5:9b`) — Fast reasoning and everyday chat with vision support.
  - 🔷 **GPT-OSS 20B** (`gpt-oss:20b`) — Heavyweight reasoning and deep code analysis.
  - ⚡ **Qwen3 8B** (`qwen3:8b`) — Lightweight, ultra-responsive conversational model.

- **🚀 Ultra-Smooth, Flicker-Free UI Engine**:
  - **Throttled Streaming (120ms Batching)**: Eliminates UI lag and stutter by batching token updates.
  - **Lightweight Stream Rendering**: Code blocks render as styled monospace text during streaming, swapping to full cards with one-click copy buttons once finalized.
  - **Open-Fence Markdown Parsing**: Formats partial code blocks mid-stream before the closing ` ``` ` arrives.
  - **Zero-Redraw Blinking Cursor**: Cursor blink toggles color tags rather than rebuilding widgets, keeping text completely still.
  - **Dynamic Bubble Height & Truncation Guard**: Custom `_text_count()` and multi-pass re-layout ensure long responses never cut off prematurely.

- **📄 Document & Context Parser**:
  - Attach source code files, multi-page PDFs, and text documents.
  - Automatic context management: 16K default context window (`16384` tokens) tuned to keep 12B–14B models entirely within GPU VRAM, expandable in Settings.
  - Autonomous multi-turn auto-continuation if model reaches output token limits mid-thought.

- **🎨 Modern Dark & Light Terminal Aesthetic**:
  - Claude-inspired sleek dark theme, collapsible `<think>` thought-process blocks, token usage counters, and persistent conversation history.

---

## 📁 Repository Structure

```
.
├── Ryuu_ai.py             # Main Desktop Application GUI & Engine
├── Ryuu.spec              # PyInstaller Build Specification
├── Ryuu_ai_Logo.ico       # Desktop Icon (.ico)
├── Ryuu_ai_Logo.png       # Application Branding Logo (.png)
├── Ryuu_Documentary.pptx  # Architecture & Design Presentation
├── Ryuu_Setup_Guide.pptx  # Backend & GPU Setup Presentation
├── requirements.txt       # Python dependencies
└── README.md              # Project documentation
```

---

## 🚀 Quick Start

### 1. Prerequisites

- **Python 3.8+**
- **Ollama**: Download and install the latest official release from [ollama.com](https://ollama.com). Standard builds include Vulkan GPU support for modern GPUs (including Intel Arc).

### 2. Pull Recommended Models

Open PowerShell or terminal and pull your preferred models:

```bash
# Default Multimodal Model (Vision + Code + Chat)
ollama pull gemma4:12b

# Advanced Coding Model (Text Only)
ollama pull qwen2.5-coder:14b

# Fast Reasoning & Chat with Vision
ollama pull qwen3.5:9b
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

*(Optional dependencies: `Pillow` for image clipboard/rendering, `pypdf` for PDF parsing).*

### 4. Run Ryuu AI

Launch the desktop assistant:

```bash
python Ryuu_ai.py
```

Ryuu will automatically detect running Ollama instances on `localhost:11434`, locate your GPU-accelerated models, and open the desktop interface ready for chat.

---

## 🛠️ Architecture & Tech Stack

- **GUI Framework**: Python `tkinter` & `ttk` (zero heavyweight web views or Electron bloat)
- **Image Processing**: `Pillow` (PIL) for clipboard paste, thumbnailing, and previewing
- **Inference Runtime**: Ollama REST API (`/api/chat`, `/api/tags`, `/api/generate`)
- **Acceleration Backend**: **Vulkan GPU compute** for high-throughput, cross-vendor GPU execution (Intel Arc, AMD, NVIDIA)

---

## 📄 Copyright & Terms of Use

**© 2026 Adithya V. All Rights Reserved.**

This repository is published for portfolio, demonstration, and educational viewing purposes only. You are welcome to view the source code to understand the implementation.

### You may NOT:

- Copy or reproduce substantial portions of this project.
- Redistribute, republish, or mirror this repository.
- Use this code in commercial projects without prior written permission.
- Submit this code, or substantially similar code, as your own for academic purposes.
- Remove copyright notices or claim this work as your own.

If you would like to use any part of this project, please contact me first for permission.
