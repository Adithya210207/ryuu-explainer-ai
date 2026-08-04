# 🐉 Ryuu Explainer AI

**Ryuu Explainer AI** is an intelligent, multi-modal desktop AI assistant built in Python and Tkinter. Powered by local LLMs (via **Ollama**), Ryuu is designed to help you analyze code, explain complex concepts, parse PDFs, and inspect attached or clipboard-pasted images.

---

## ✨ Features

- **📷 Multi-Modal Vision Support**:
  - Drag & drop or attach images (`.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`).
  - Direct clipboard image pasting (**Ctrl+V**).
  - Automatic vision model detection (e.g. `llava`, `llama3.2-vision`) with fallback warnings.

- **📄 Document & Code Parser**:
  - Attach source code files, PDFs, or plain text files.
  - Context-aware explanations and debugging assistance.

- **⚡ 100% Local & Private**:
  - Connects directly to local Ollama API (`http://localhost:11434`).
  - Zero data sent to third-party servers.

- **🎨 Sleek Dark & Light Themes**:
  - Customizable UI themes, adjustable model parameters (Max Tokens, Temperature, Top-P, Repeat Penalty).
  - Markdown code highlighting, thought chain (`<think>`) toggles, and chat history export.

---

## 📁 Repository Structure

```
.
├── Ryuu_ai.py             # Main Desktop Application GUI
├── Ryuu_ai_Logo.ico       # Application Icon (.ico)
├── Ryuu_ai_Logo.png       # Application Branding Logo (.png)
├── Ryuu_Documentary.pptx  # Architecture & Design Presentation
├── Ryuu_Setup_Guide.pptx  # Backend & Ollama Setup Presentation
├── requirements.txt       # Python dependencies
└── README.md              # Documentation
```

---

## 🚀 Quick Start

### 1. Prerequisites

- **Python 3.8+**
- **Ollama**: Download and install from [ollama.com](https://ollama.com).

### 2. Start Ollama Local Server

Make sure your local Ollama engine is running:

```bash
ollama serve
```

*(For vision features, pull a vision-capable model like `ollama pull llama3.2-vision` or `ollama pull llava`).*

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Run Ryuu AI

Launch the desktop assistant:

```bash
python Ryuu_ai.py
```

---

## 🛠️ Built With

- **Python 3** & **Tkinter / TTK**
- **Pillow (PIL)** for image processing and clipboard handling
- **Ollama REST API** for local LLM inference

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
