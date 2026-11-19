VU3INI Transcribe Studio  v{{VERSION}}
By Sasanka Boruah -VU3INI  ·  hamvu3ini@gmail.com
=====================================================================

Offline speech-to-text for Assamese, Hindi, Bengali, English and more,
built on OpenAI Whisper, AI4Bharat IndicWhisper and IndicTrans2.
Everything runs on your own PC. Nothing is sent to the internet.


1. INSTALL (clean Windows 10 or 11, 64-bit)
-------------------------------------------
 a. Run  VU3INI-Transcribe-Studio-Setup-v{{VERSION}}.exe
    (If you received the zip in parts, first run the JOIN-....bat file in the
     folder with all parts; it joins them and checks the SHA-256.)
 b. If Windows SmartScreen says "Windows protected your PC", click
    "More info" -> "Run anyway" (the installer is not code-signed).
 c. Accept the terms and keep the default folder:
      %LOCALAPPDATA%\Programs\VU3INI Transcribe Studio
    No administrator rights are needed. Shortcuts are added to the
    Start Menu and the Desktop.
 d. Start "VU3INI Transcribe Studio". Your browser opens the app and a
    VU3INI icon appears in the system tray (Open / Stop / Exit).


2. ADD SPEECH MODELS (model packs) — needed once
------------------------------------------------
 The installer contains no speech models, so it stays small.
 a. Start the app and open the "Model packs" tab.
 b. Under "Get model packs", tick what you need. Recommended:
      Whisper large-v3-turbo   (main engine, all languages)   ~1.6 GB
      IndicWhisper Hindi / Bengali (optional, better accuracy)  ~1.5 GB each
      Speaker diarization       (identify speakers)            ~40 MB
      IndicTrans2 packs         (translation)                  ~0.9 GB each
      NVIDIA GPU runtime        (use your RTX graphics card)   ~1.9 GB
    For Assamese you can add a community model under "Add a custom Hugging
    Face speech model", e.g.  anuragshas/whisper-large-v2-as
 c. IndicTrans2 is "gated" on Hugging Face: accept its terms on the model
    page, create an access token (huggingface.co -> Settings -> Access
    Tokens) and paste it in the token box. It is not saved.
 d. Click "Download and install". This is the only step that uses the
    internet. Progress shows in the queue on the Transcribe tab.
 e. Tick "Also keep the .vtpack files" to get copies you can install on
    an offline PC with "Install pack from file".

3. USE
------
 Help -> User guide inside the app has step-by-step instructions for every
 feature, with a live search box. Press F1 at any time.


4. UNINSTALL
------------
 Settings -> Apps -> "VU3INI Transcribe Studio" -> Uninstall
 (you will be asked whether to keep your projects and model packs).


5. REBUILD THE NEXT VERSION (developer)
---------------------------------------
 On Linux (or WSL) with Python 3.11+ and internet:
     pip install packaging zstandard
     python packaging/build.py              # 1.0.0 -> 1.0.1, builds everything
     python packaging/build.py --no-bump    # rebuild the same version
 The script downloads Windows Python + FFmpeg (conda-forge), the Windows
 wheels (PyPI) and NSIS, stamps the version into the app, the About box and
 the file names, and writes the zip (split into parts if over 500 MB) to
 build/out/.


6. REPLACE THE LOGO
-------------------
 Put a square PNG (at least 512x512) at
     app/web/assets/logo-original.png
 in the source folder and run:  python packaging/make_icons.py
 It regenerates logo.png, logo-96.png, favicon.png and app.ico (used by the
 header, splash, About, tray, exe and shortcuts). Then rebuild.


Data locations
--------------
 Projects, settings, packs, logs:  %LOCALAPPDATA%\VU3INI Transcribe Studio
