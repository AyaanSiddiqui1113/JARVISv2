# JARVIS Local Helper Agent

This is the local Python program that gives JARVIS hands on your computer.
The web UI talks to this agent (running on `127.0.0.1:7337`) every time it
needs to actually do something — run a command, open a file, search your
disk, install software, etc.

## Setup

```bash
python -m pip install fastapi uvicorn psutil selenium pyautogui pillow pyperclip pywinauto pytesseract
python jarvis_agent.py
```

Leave the terminal window open. In the JARVIS web app, the **LOCAL AGENT**
status indicator should turn cyan within ~5 seconds.

## What it can do

| Tool | What happens |
|---|---|
| `run_command` | Runs any shell command (master tool — installs, scripts, anything) |
| `open_path` | Opens a file/folder/app in its default handler |
| `open_url` | Opens a URL in your default browser |
| `list_dir` | Lists files in a directory |
| `search_files` | Recursively searches files by name |
| `read_file` | Reads a text file |
| `write_file` | Writes/overwrites a text file |
| `system_info` | Returns OS/CPU/RAM/disk info |
| `browser_*` | **Cowork mode** — JARVIS drives your installed Chrome with Selenium and a glowing red cursor overlay; you use the same window with your normal cursor |
| `desktop_*` | **Desktop cowork mode** — JARVIS inspects the active desktop app and uses mouse/keyboard control for launchers, installers, settings windows, etc. |

**Desktop OCR (REQUIRED for game launchers, custom canvases, Java apps like TLauncher).** Windows UI Automation cannot see custom-drawn buttons, so JARVIS falls back to OCR. Install the Tesseract OCR desktop app:
- **Windows:** https://github.com/UB-Mannheim/tesseract/wiki — install to the default path, then restart the agent. JARVIS auto-locates `tesseract.exe` in `C:\Program Files\Tesseract-OCR\`.
- **macOS:** `brew install tesseract`
- **Linux:** `sudo apt install tesseract-ocr`

Without Tesseract, JARVIS can't read buttons like "Enter the Game" in TLauncher.

## ⚠️ Security

This agent runs **arbitrary shell commands** the web UI tells it to. Treat
it like a remote-code-execution endpoint — because that's what it is.

- It binds to `127.0.0.1` only (not exposed to your network)
- Only run it while you're actively using JARVIS
- Don't expose port 7337 to the internet
- You'll be asked to confirm destructive actions in chat, but ultimately
  you control what JARVIS executes

## Examples to try

> "What OS am I on?"
> "Open my Downloads folder"
> "Search my home folder for files containing 'invoice'"
> "Install ripgrep using my system package manager"
> "Open github.com in my browser"
> "Create a new folder ~/jarvis-test and write a hello.txt inside it"
