# Whisper Transcription Tool (GUI)
![fig_1](./asset/demo1-1.png)
![fig_2](./asset/demo2-1.png)
![fig_3](./asset/demo3-1.png)

A desktop GUI for transcribing **audio/video files** and **microphone recordings** using [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper) (local inference).

Built with **PySide6** and designed to be simple:
- Drag & drop media files to transcribe
- Record from your microphone and transcribe in-memory
- Export results as `.txt` and/or `.srt`, copy to clipboard, or show a pop-up window
- Manage models and free VRAM automatically after idle (TTL)

## Features
- **Two modes**
  - **File mode**: drag & drop one or multiple files (queued and processed sequentially)
  - **Record mode**: record from your selected microphone and transcribe
- **Whisper model**: `tiny / base / small / medium / large / turbo` (multilingual)
- **Language hint (optional)**: set a language code or name (e.g., `en`, `english`, `zh`...)
- **Output options (multi-select)**
  - Pop-up viewer (editable + copy)
  - Clipboard
  - Save `.txt`
  - Save `.srt`
- **Output folder shortcut**: open the output directory from the UI
- **Model lifecycle management**
  - Lazy load the model on demand
  - Automatically unload after an idle timeout to free GPU memory (VRAM)

## Supported Media Formats
- **Video**: `mp4`, `mkv`, `avi`, `mov`, `webm`
- **Audio**: `mp3`, `wav`, `m4a`, `flac`, `aac`, `ogg`

## Requirements
- **Python**: `>= 3.13`
- **PyAV (bundled FFmpeg)**: provided by faster-whisper (no system FFmpeg required)
- **(Optional) NVIDIA GPU**: for faster transcription via CTranslate2 CUDA on Windows/Linux

> If an NVIDIA GPU is detected, the program will ask whether to download and cache CUDA DLLs in `./cache/dll`. Users do not need to pre-install the CUDA Toolkit.

> model weights will also cached in `./cache/whisper/`.

## Installation & Usage

This project is managed with [`uv`](https://astral.sh/uv/) 

### Automation script

You can use the provided script to install everything, sync dependencies, check for updates, and launch the GUI in one step:

- **Windows**:  
  Run `whisper-transcription-tool-gui.bat`

- **macOS / Linux**:  
  Run `bash whisper-transcription-tool-gui.sh`

The script will:
- Install [`uv`](https://astral.sh/uv/) (if not already installed)
- Sync dependencies via `pyproject.toml`
- Pull the latest changes from the repository
- Launch the transcription GUI

---

### Manual setup (alternative)

If you prefer to do everything manually:

#### 1. Install `uv`
Follow the instructions on the official site:  
https://astral.sh/uv/

#### 2. Sync project dependencies
In the root of this repository:

```bash
uv sync
```
#### 3. Run the GUI

Use uv run to start the application:

```bash
uv run python gui.py
```
