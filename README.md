# 🎨 Seamless Cover-Art Generator CLI

A powerful, AI-driven Command Line Interface (CLI) tool that generates premium, seamless, and mathematically precise 2D flat artworks. It is specifically optimized for printing high-quality, edge-to-edge square wraps (e.g., lighter covers) using **Google's Imagen 4.0 Ultra** model.

## ✨ Features
* **AI-Powered Generation:** Utilizes Google's state-of-the-art `imagen-4.0-ultra-generate-001` via the Gemini API.
* **Smart Interactive Mode:** If run without arguments, the CLI boots into a user-friendly Q&A mode with editable default values (powered by `prompt_toolkit`).
* **JSON Pre-filling:** Load existing configurations (`cfg.json` or `args.json`) to skip typing and perfectly reproduce previous designs.
* **Flexible Image Input:** Accepts local files, entire directories, or direct Web URLs as reference images.
* **Auto-Documentation:** Every generated image is saved in a unique UUID folder alongside a JSON file containing the exact parameters used to create it.
* **Standalone Ready:** Can be compiled into a single `.exe` file for Windows users without requiring a Python installation.

---

## 🚀 Getting Started

### Option A: For Windows Users (No Installation Required)
If you have the compiled `.exe` file, simply open your **PowerShell**, paste the following command, and hit Enter. This will download and run the tool instantly:
```powershell
cd $env:USERPROFILE\Downloads; curl.exe -L -o cover-generator.exe "[https://github.com/YOUR_USERNAME/YOUR_REPO/releases/download/init/gem.exe](https://github.com/YOUR_USERNAME/YOUR_REPO/releases/download/init/gem.exe)"; .\cover-generator.exe


