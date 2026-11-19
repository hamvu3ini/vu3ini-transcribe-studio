"""Source credits and bundled third-party components shown in Help > About and written to licences/."""

SOURCES = [
    {"name": "OpenAI Whisper", "repo": "openai/whisper", "url": "https://github.com/openai/whisper", "licence": "MIT"},
    {"name": "AI4Bharat IndicWhisper (Vistaar)", "repo": "AI4Bharat/vistaar", "url": "https://github.com/AI4Bharat/vistaar", "licence": "MIT (code); see each model pack for model terms"},
    {"name": "AI4Bharat IndicTrans2", "repo": "AI4Bharat/IndicTrans2", "url": "https://github.com/AI4Bharat/IndicTrans2", "licence": "MIT"},
    {"name": "faster-whisper", "repo": "SYSTRAN/faster-whisper", "url": "https://github.com/SYSTRAN/faster-whisper", "licence": "MIT"},
    {"name": "sherpa-onnx (speaker diarization)", "repo": "k2-fsa/sherpa-onnx", "url": "https://github.com/k2-fsa/sherpa-onnx", "licence": "Apache-2.0"},
]

COMPONENTS = [
    ("Python 3.12 (conda-forge build)", "PSF-2.0"),
    ("CTranslate2", "MIT"),
    ("faster-whisper (includes Silero VAD model)", "MIT"),
    ("PyTorch (CPU)", "BSD-3-Clause"),
    ("Hugging Face transformers", "Apache-2.0"),
    ("Hugging Face tokenizers", "Apache-2.0"),
    ("sentencepiece", "Apache-2.0"),
    ("ONNX Runtime", "MIT"),
    ("sherpa-onnx", "Apache-2.0"),
    ("FastAPI", "MIT"),
    ("Starlette", "BSD-3-Clause"),
    ("Uvicorn", "BSD-3-Clause"),
    ("Pydantic", "MIT"),
    ("NumPy", "BSD-3-Clause"),
    ("soundfile / libsndfile", "BSD-3-Clause / LGPL-2.1"),
    ("PyAV / FFmpeg libraries", "BSD-3-Clause / LGPL-2.1"),
    ("FFmpeg (LGPL build, conda-forge)", "LGPL-2.1-or-later"),
    ("Indic NLP Library", "MIT"),
    ("python-docx", "MIT"),
    ("fpdf2", "LGPL-3.0"),
    ("uharfbuzz / HarfBuzz", "Apache-2.0 / MIT"),
    ("Noto Sans, Noto Sans Bengali, Noto Sans Devanagari fonts", "SIL OFL-1.1"),
    ("pystray", "LGPL-3.0"),
    ("Pillow", "MIT-CMU (HPND)"),
    ("psutil", "BSD-3-Clause"),
]
