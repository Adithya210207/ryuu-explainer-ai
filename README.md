# 🐉 Ryuu Explainer AI

**Ryuu** is a private, offline desktop AI assistant for explaining concepts, debugging code and writing code in any language. It's a single Python/Tkinter file that puts a chat interface on top of local language models served by **Ollama**, running on your own GPU. That includes Intel Arc integrated graphics, through Ollama's **Vulkan** backend.

No accounts, no API keys, no cloud calls: every message, attached file and generated line of code stays on your machine.

---

## ✨ Features

### Models
Ryuu's model menu offers five models. Pick one per chat; switching **immediately unloads the previous model from GPU memory**, so only one model ever sits on the GPU.

| | Model | Tag | Best for | Reads images |
|---|---|---|---|---|
| ✨ | **Gemma 4 12B** *(default)* | `gemma4:12b` | Everyday use: explanations, code, screenshots | ✅ |
| 💻 | **Qwen2.5 Coder 14B** | `qwen2.5-coder:14b` | Writing and debugging larger programs | ❌ |
| 🧠 | **Qwen3.5 9B** | `qwen3.5:9b` | Step-by-step reasoning and chat | ✅ |
| 🔷 | **GPT-OSS 20B** | `gpt-oss:20b` | The hardest problems (13 GB, so close other apps first) | ❌ |
| ⚡ | **Qwen3 8B** | `qwen3:8b` | Quick questions, fastest replies | ❌ |

Models that aren't installed show as *"Not installed"* in the menu, with the `ollama pull` command to get them.

### Images, PDFs and code files
- **Attach** images (`.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`, `.webp`, up to 8 MB), PDFs and 40+ code/text file types with 📎, or **paste an image** from the clipboard with **Ctrl+V**.
- **Automatic vision borrowing:** if you attach an image while using a text-only model, Ryuu borrows the best installed vision model for that one reply (Gemma 4 first, then Qwen 3.5, Qwen3-VL, Qwen2.5-VL), unloads it, and switches back.
- PDF text is extracted with `pypdf`; long files are capped at 24,000 characters.

### Replies
- **Live streaming:** replies appear as they're generated, redrawn in batches every 120 ms so the bubble stays steady instead of flickering.
- **Code blocks:** while streaming they show as monospace text; once the reply finishes they become cards with a language label and a one-click copy button.
- **Auto-continue:** if a reply is cut off by the token or context limit, Ryuu asks the model to carry on from where it stopped, up to 6 times.
- **Hidden reasoning:** the `<think>…</think>` blocks that reasoning models produce are stripped before display.
- **Stop** button to end a reply mid-stream, keeping what has arrived so far.

### Conversations
- Multiple chat threads with rename, delete, clear and search across all chats.
- Edit any of your messages and regenerate, or retry any of Ryuu's replies.
- Export a chat as `.txt` or `.json`.
- **About You** profile and **explanation level** (beginner → advanced) that Ryuu takes into account in every chat.
- Everything is saved locally in your user folder (`.ryuu_conversations.json`, `.ryuu_profile.json`).

---

## 🚀 Setup (Windows)

### 1. Install Ollama
```powershell
winget install Ollama.Ollama
```
Or download it from [ollama.com](https://ollama.com).

### 2. Turn on Intel Arc GPU support (Intel integrated graphics only)
By default, Ollama finds an Intel integrated GPU such as the Arc 140V **but skips it** and runs on the CPU. These settings are permanent, so you only set them once:

```powershell
[Environment]::SetEnvironmentVariable("OLLAMA_IGPU_ENABLE", "1", "User")        # use the integrated GPU
[Environment]::SetEnvironmentVariable("OLLAMA_VULKAN", "1", "User")             # use the Vulkan backend
[Environment]::SetEnvironmentVariable("GGML_VK_DISABLE_COOPMAT", "1", "User")   # prevents garbled output on Arc 140V
[Environment]::SetEnvironmentVariable("GGML_VK_DISABLE_COOPMAT2", "1", "User")
[Environment]::SetEnvironmentVariable("OLLAMA_MAX_LOADED_MODELS", "1", "User")  # optional: one model on the GPU at a time
```

Then **quit Ollama from the system tray and close every terminal**, so the new settings are picked up. NVIDIA and AMD discrete GPUs don't need this step.

### 3. Pull the models
```powershell
ollama pull gemma4:12b           # default: images + code
ollama pull qwen2.5-coder:14b    # coding
ollama pull qwen3.5:9b           # reasoning + images
ollama pull gpt-oss:20b          # optional: heavyweight reasoning (13 GB)
ollama pull qwen3:8b             # optional: fast chat
```

### 4. Check it's running on the GPU
```powershell
ollama run gemma4:12b "Say hello in one sentence."
ollama ps
```
The `PROCESSOR` column should read **`100% GPU`**.

> **Note:** on GPUs that share system memory (like the Arc 140V), `ollama ps` may show a much smaller `SIZE` than the model file, such as 1.5 GB for Gemma 4's 8 GB. That's normal; the full model is still loaded. Check **Task Manager → Performance → GPU → Shared GPU memory** for the real figure.

### 5. Install the Python packages
```powershell
python -m pip install -r requirements.txt
```
`Pillow` (image paste and previews) and `pypdf` (PDF reading) are optional; Ryuu runs without them and turns those features off.

### 6. Launch Ryuu
```powershell
python Ryuu_ai.py
```
If Ollama isn't already running, Ryuu starts it, and stops it again when you close Ryuu. A server that was already running is left alone.

Optional flags: `--model gpt-oss:20b`, `--ctx 32768`, `--temperature 0.3`, `--history 16`, `--max-tokens -1`, `--no-stream`.

---

## 📦 Build a Windows `.exe`
```powershell
python -m pip install pyinstaller pillow pypdf
python -m PyInstaller --noconfirm --onefile --windowed --name Ryuu --icon "Ryuu_ai_Logo.ico" Ryuu_ai.py
```
The app is created at `dist\Ryuu.exe`. It doesn't need Python installed, but it does need Ollama and the models.

---

## 🛠️ Troubleshooting

| Problem | Fix |
|---|---|
| `ollama ps` shows CPU, or the server log says *"dropping integrated GPU"* | Set `OLLAMA_IGPU_ENABLE=1` (step 2), quit Ollama and restart it. |
| Replies are scrambled characters | Check the model file isn't damaged: run `Get-FileHash` on its blob in your models folder and compare the result with the file's name (`sha256-…`). If they differ, delete the blob and pull the model again. If every model is scrambled, make sure the two `GGML_VK_DISABLE_COOPMAT` settings are in place. |
| Ryuu stays on *"connecting"* | The Ollama server isn't running. Start it from the Start menu or with `ollama serve`. |
| A model is slow and `ollama ps` shows a CPU/GPU split | The GPU's shared memory is full. Close browsers and other heavy apps, or use a smaller model. 12–14B models fit comfortably; GPT-OSS 20B needs most of the memory. |
| Port 11434 already in use | Another Ollama is still running: `Get-Process ollama* \| Stop-Process -Force`. |

---

## 📁 Repository Structure
```
.
├── Ryuu_ai.py             # The application: GUI, Ollama client, rendering
├── Ryuu_ai_Logo.ico       # Icon for the .exe
├── Ryuu_ai_Logo.png       # Logo
├── Ryuu_Documentary.pptx  # Architecture and design presentation
├── Ryuu_Setup_Guide.pptx  # Step-by-step setup presentation
├── requirements.txt       # Python packages
└── README.md
```

## 🧱 Tech Stack
- **Interface:** Python `tkinter` (no web view or Electron)
- **Inference:** Ollama REST API on `localhost:11434` (`/api/chat`, `/api/tags`, `/api/generate`)
- **GPU acceleration:** Ollama's Vulkan backend (Intel Arc, AMD, NVIDIA)
- **Optional:** `Pillow` (images), `pypdf` (PDFs)
- **Storage:** local JSON files, no database

---

## 📄 Copyright & Terms of Use

**© 2026 Adithya V. All Rights Reserved.**

This repository is published for portfolio, demonstration, and educational viewing purposes only. You are welcome to view the source code to understand the implementation.

**You MAY** download, install and run it on your own computer for your own **personal, non-commercial use**.

### You may NOT:

- Copy or reproduce substantial portions of this project.
- Redistribute, republish, or mirror this repository.
- Use this code in commercial projects without prior written permission.
- Submit this code, or substantially similar code, as your own for academic purposes.
- Remove copyright notices or claim this work as your own.
- Share, sell or re-upload it (including copies downloaded for personal use), or change the source code and use or share the changed version.

If you would like to use any part of this project, please contact me first for permission.

The full legal terms are in the [**LICENSE**](LICENSE) file.
