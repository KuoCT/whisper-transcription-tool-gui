# Whisper Transcription Tool (GUI)
![fig_1](./asset/demo1-1.png)
![fig_2](./asset/demo2-1.png)
![fig_3](./asset/demo3-1.png)

A desktop GUI for transcribing **audio/video files** and **microphone recordings** using [**faster-whisper**](https://github.com/SYSTRAN/faster-whisper) (local inference).

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
- **Language hint (optional)**: set a language code or name (e.g., `en`, `english`, `zh`), comma-separated hints enable multilingual mode
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
- **(Windows) CUDA DLLs**: app can download cuDNN/cuBLAS (CUDA 12) into `./cache/dll`

> This app uses PyAV (bundled FFmpeg) to decode and resample media into a Whisper-friendly waveform.

## Installation (Recommended: uv)

This project is managed with **uv**:
- Fast dependency resolution
- Reproducible installs via `pyproject.toml`

### 1. Install uv
See the official instructions: https://astral.sh/uv/

### 2. Install dependencies
Clone this repository, then run in the repository root:

```bash
uv sync
```

## Usage
Windows: `whisper-transcription-tool-gui.bat`  
macOS/Linux: `bash whisper-transcription-tool-gui.sh`

```bash
uv run python gui.py
```
On first run, faster-whisper may download model weights (cached in `./cache/whisper/`).
