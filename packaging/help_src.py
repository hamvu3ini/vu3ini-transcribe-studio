"""Source of the in-app user guide. Run to regenerate app/web/help.json."""
import json, pathlib

H = []
def sec(id, title, body): H.append({"id": id, "title": title, "body": body.strip()})

sec("start", "Starting and closing the app", """
<ol><li>Double-click <b>VU3INI Transcribe Studio</b> on the Desktop or in the Start Menu. No terminal window appears.</li>
<li>The app starts its local engine, puts a VU3INI icon in the system tray (near the clock) and opens in your default browser at an address like <code>http://127.0.0.1:PORT</code>.</li>
<li>Read the Terms of Use in the start-up window. The <b>Agree / OK</b> button becomes active after 3 seconds; click it to continue, or click <b>Exit</b> to close the app completely.</li>
<li>If you launch the app again while it is running, it simply brings the existing app back into view.</li>
<li>To close: click <b>Shut down</b> in the top bar, or right-click the tray icon and choose <b>Stop / Exit</b>. Every background process stops; nothing is left running.</li>
<li>Tray icon → <b>Open</b> reopens the app in your browser if you closed the tab.</li></ol>""")

sec("packs", "Model packs: what to install first", """
<p>The speech, speaker and translation models are <b>model packs</b>. Get them once from the <b>Model packs</b> tab (internet needed for that step only), or install <code>.vtpack</code> files you already have.</p>
<ul><li><b>Whisper large-v3-turbo</b> (about 1.6 GB) — the main multilingual engine and language detector. Install this first.</li>
<li><b>IndicWhisper Hindi / Bengali</b> — AI4Bharat models tuned for one language each. When installed, the app automatically uses them for that language.</li>
<li><b>Speaker diarization</b> (about 40 MB) — needed for "Identify speakers".</li>
<li><b>IndicTrans2 en→indic and indic→en</b> — needed for translation.</li>
<li><b>NVIDIA GPU runtime</b> (about 1.9 GB) — lets the app use your NVIDIA graphics card for much faster transcription.</li></ul>
<p>Assamese is transcribed by Whisper large-v3, because AI4Bharat has not published an IndicWhisper checkpoint for Assamese.</p>""")

sec("make-packs", "Getting model packs inside the app", """
<p>This is the only part of the app that uses the internet, and only when you click the button.</p>
<ol><li>Open the <b>Model packs</b> tab. The <b>Get model packs</b> list shows every available pack with its size; installed ones are marked <b>Installed</b>.</li>
<li>Tick the packs you want (for example Whisper large-v3-turbo, Speaker diarization and the two IndicTrans2 packs).</li>
<li>For a community model, open <b>Add a custom Hugging Face speech model</b>, enter its id (for example <code>anuragshas/whisper-large-v2-as</code> for Assamese), keep the model type <b>Whisper model — convert for speed</b>, and choose its language.</li>
<li>Gated models (the IndicTrans2 packs) need a Hugging Face access token: open the model's page on huggingface.co, accept its terms, create a token under Settings → Access Tokens and paste it into the token box. The token is used for this download only and is never saved.</li>
<li>Tick <b>Also keep the .vtpack files</b> if you want copies to install on another PC.</li>
<li>Click <b>Download and install</b>. Progress (downloaded MB, converting, installing) shows in the queue on the Transcribe tab; you can keep working or cancel. Each pack is installed as soon as it is ready.</li></ol>""")

sec("install-packs", "Installing and removing packs", """
<ol><li>Click the <b>Model packs</b> tab.</li>
<li>Click <b>Install pack from file…</b> and choose a <code>.vtpack</code> file, <i>or</i> paste the file's full path (for example <code>D:\\packs\\whisper-large-v3-turbo.vtpack</code>) and click <b>Install from path</b>. Installing from a path is faster for big packs because the file is not copied through the browser.</li>
<li>Progress shows in the queue on the <b>Transcribe</b> tab. When it finishes, the pack appears in the table.</li>
<li>To remove a pack, click <b>Remove</b> on its row. You can reinstall it later from the same file.</li></ol>""")

sec("lang-engines", "Choosing the engine for each language", """
<ol><li>Open the <b>Model packs</b> tab and scroll to <b>Engine for each language</b>.</li>
<li>Each language (Assamese, Hindi, Bengali, English…) has a dropdown. Packs that support the language are listed first under "Supports …"; any other installed speech pack is listed under "Other packs".</li>
<li><b>Automatic</b> (the default) shows in brackets which pack it would use: a language-specific pack such as IndicWhisper Hindi when installed, otherwise the multilingual Whisper pack.</li>
<li>Pick a pack for any language you want to fix, then click <b>Save choices</b>. <b>Reset all to Automatic</b> clears every choice.</li>
<li>Your choice is used whenever the Engine is set to Automatic — for files, folders, Live mode and "Transcribe again". The queue shows a note such as "Using IndicWhisper Hindi for Hindi (your choice in Model packs)".</li>
<li>With the language set to Automatic, the language is detected first and then the pack chosen for that language is used.</li>
<li>If you remove a chosen pack, that language goes back to Automatic and the dropdown says so.</li></ol>""")

sec("transcribe", "Transcribing a file", """
<ol><li>Open the <b>Transcribe</b> tab.</li>
<li>Choose the <b>Language</b> (Automatic, Assamese, Hindi, Bengali, English…) and the <b>Engine</b> (Automatic routes each language to the best installed pack).</li>
<li>Optional: tick <b>Identify speakers</b> (and set the number of speakers if you know it; 0 = automatic), <b>Reduce noise</b>, <b>Normalise loudness</b> or <b>Trim long silences</b>.</li>
<li>Drag audio or video files onto the box, or click it to choose files. Several files can be added at once.</li>
<li>Each file joins the <b>Queue</b> with a progress bar and an estimate of the time left.</li>
<li>When a job finishes, click <b>Open</b> to edit the transcript. It is also listed under Recent projects.</li></ol>""")

sec("languages", "Languages, engines and mixed-language speech", """
<ul><li><b>Automatic language</b>: the first 30 seconds are checked by Whisper's language detector, then the job is routed to the best pack for that language.</li>
<li><b>Engine = Automatic</b>: a language-specific pack (such as IndicWhisper Hindi) is preferred when installed; otherwise the multilingual Whisper pack is used.</li>
<li><b>Mixed-language speech</b> (Settings): when the language is Automatic, each segment's language is detected separately, which helps with Assamese/Hindi/English mixed in one conversation.</li>
<li>Choose a fixed language when you know it — it is faster and avoids wrong detections on short clips.</li></ul>""")

sec("batch", "Transcribing a whole folder", """
<ol><li>On the <b>Transcribe</b> tab, open <b>Transcribe a whole folder</b>.</li>
<li>Paste the folder path, for example <code>D:\\Recordings\\Interviews</code>. Tick <b>Include sub-folders</b> if needed.</li>
<li>Set the language and options above as usual, then click <b>Add folder to queue</b>.</li>
<li>Every audio/video file is copied into the app and transcribed one after another. Your original files are never changed.</li></ol>""")

sec("queue", "The queue: pause, resume and cancel", """
<ul><li>Jobs run one at a time so they never fight over the graphics card.</li>
<li><b>Pause queue</b> stops new jobs from starting (the running job finishes). <b>Resume queue</b> continues.</li>
<li><b>Cancel</b> stops a queued or running job.</li>
<li><b>Clear finished</b> removes finished, failed and cancelled jobs from the list.</li>
<li>If the GPU runs out of memory, the job automatically continues on the CPU and the queue shows a note.</li></ul>""")

sec("editor", "Editing a transcript", """
<ol><li>Open a project from the queue, Recent projects or the <b>Projects</b> tab.</li>
<li>Click any <b>word</b> to play the audio from that word. Click the <b>time</b> at the left of a line to play from the start of that segment.</li>
<li>Click into the text to correct it. Word timings are kept for unchanged lines and spread evenly over edited lines.</li>
<li>Hover a line to show its tools: <b>✂ Split</b> at the cursor (or press Ctrl+Enter), <b>⤓ Merge</b> with the next line, <b>🗑 Delete</b>.</li>
<li>Rename the project in the title box and add <b>Tags</b> (comma-separated) to organise projects.</li>
<li>Click <b>Save</b> (or press Ctrl+S). "● unsaved" shows when you have changes.</li>
<li><b>History ▾</b> lists earlier saved versions. Choose one to restore it; the current text is kept as another version.</li></ol>""")

sec("player", "Player and waveform", """
<ul><li>Use <b>▶ Play</b>, <b>⏪ 5s</b> and <b>5s ⏩</b>, or the keyboard shortcuts.</li>
<li><b>Speed</b> changes playback speed from 0.5× to 2× for careful proofreading.</li>
<li>Click the waveform to jump to that point and select the segment there.</li>
<li><b>Fix segment timing</b>: select a segment, then drag the dark handles at its start or end on the waveform.</li>
<li><b>Zoom</b> enlarges the waveform; scroll the mouse wheel over it to move through the audio. <b>Follow</b> keeps the playing line and the current text in view.</li></ul>""")

sec("speakers", "Speakers (diarization)", """
<ol><li>Install the <b>Speaker diarization</b> pack.</li>
<li>Tick <b>Identify speakers</b> before transcribing, or in the editor click <b>Find speakers again</b> on an existing project.</li>
<li>Speakers appear as "Speaker 1", "Speaker 2"… In the <b>Speakers</b> panel, type real names; they change everywhere at once.</li>
<li>Change who is speaking on any line with the speaker chip at the left of the text. <b>+ Add speaker</b> creates a new name.</li>
<li><b>Talk time</b> shows how long and how many turns each person spoke.</li></ol>""")

sec("find", "Find and replace, custom vocabulary and corrections", """
<ul><li>In the editor, type in <b>Find…</b> to highlight every match; type a replacement and click <b>Replace all</b>.</li>
<li><b>Custom vocabulary</b> (Settings): list names, places, call signs or technical terms, one per line. They are given to the model as hints so they are recognised and spelled correctly.</li>
<li><b>Automatic corrections</b> (Settings): one rule per line as <code>wrong => right</code>. They are applied to every new transcript.</li></ul>""")

sec("confidence", "Confidence heatmap", """
<p>Tick <b>Confidence heatmap</b> in the editor. Words the model was unsure about are shaded: red (very unsure), orange, then yellow. Hover a word to see its confidence and time. Check shaded words first when proofreading.</p>""")

sec("script", "Roman script view", """
<p>Set <b>Show</b> to <b>Roman script</b> to see Assamese, Bengali or Hindi text transliterated into Latin letters (ITRANS style), useful for readers who do not read the native script. This view is read-only; switch back to <b>Original</b> to edit.</p>""")

sec("translate", "Translation (IndicTrans2)", """
<ol><li>Install the IndicTrans2 pack for the direction you need: <b>en→indic</b> (English to Assamese/Hindi/Bengali…), <b>indic→en</b>, or <b>indic→indic</b>.</li>
<li>Open a project, choose the target language in the <b>Translate</b> panel and click <b>Translate</b>.</li>
<li>When it finishes, set <b>Show</b> to <b>Translation</b> or <b>Original + translation</b>.</li>
<li>Exports can contain the original, the translation, or both (Export ▾ → Text).</li>
<li>If you edit, split or merge lines afterwards, translate again to keep the translation in step.</li></ol>""")

sec("export", "Exporting", """
<ol><li>In the editor, click <b>Export ▾</b>.</li>
<li>Choose what text to export (Original, Translation or Both) and whether to include speaker names and timestamps.</li>
<li>Pick a format:
<ul><li><b>SRT</b> / <b>WebVTT</b> — subtitles for video players and YouTube.</li>
<li><b>TXT</b> — plain text. <b>DOCX</b> — Word, with a colour per speaker. <b>PDF</b> — with Assamese/Bengali/Hindi fonts embedded so it prints correctly anywhere.</li>
<li><b>JSON</b> — full data including word timings. <b>CSV</b> — opens in Excel.</li>
<li><b>Shareable HTML page</b> — one file with the audio built in; anyone can click a line to hear it.</li>
<li><b>Video with burned-in subtitles</b> — only for video projects; the subtitled MP4 downloads when ready.</li></ul></li></ol>
<p>Files go to your browser's Downloads folder.</p>""")

sec("live", "Live microphone transcription", """
<ol><li>Open the <b>Live</b> tab. Choose the language (Automatic works too) and engine, and optionally a name.</li>
<li>Click <b>● Start</b> and allow microphone access in the browser when asked.</li>
<li>Speak normally. Grey italic text is a quick preview; each finished sentence appears in the list with its time.</li>
<li>Click <b>■ Stop</b>. The recording and transcript are saved as a project; click <b>Open in editor</b> to correct and export it.</li></ol>
<p>A GPU makes live mode much more responsive. On CPU, use a smaller Whisper pack for live work.</p>""")

sec("projects", "Projects and search", """
<ul><li>The <b>Projects</b> tab lists every transcript with its length, language and tags.</li>
<li>The search box looks through project names, tags <b>and the text of every transcript</b>. Click a result to open it at that moment in the audio.</li>
<li>Click ✕ on a project card to delete the project and its audio permanently.</li></ul>""")

sec("settings", "Settings", """
<ul><li><b>Processor</b>: Automatic uses the NVIDIA GPU when the GPU runtime pack is installed, otherwise the CPU.</li>
<li><b>Precision</b>: float16 for GPUs; int8+float16 uses less GPU memory; int8 is the fast CPU choice.</li>
<li><b>Beam size</b>: higher is slightly more accurate but slower (5 is a good default).</li>
<li><b>Skip silence</b>: voice activity detection removes silent parts before transcribing.</li>
<li><b>Hallucination guard</b>: removes invented lines such as "Thank you for watching" and endless repeats in silent or noisy passages.</li>
<li><b>Default language/engine</b> and the default processing options pre-fill the Transcribe and Live tabs.</li>
<li>Click <b>Save settings</b>. The folder where projects and packs are stored is shown at the bottom.</li></ul>""")

sec("gpu", "Using your NVIDIA graphics card", """
<ol><li>Get the <b>NVIDIA GPU runtime</b> pack on the Model packs tab and keep your NVIDIA driver up to date.</li>
<li>In <b>Settings</b>, set Processor to Automatic or NVIDIA GPU, and Precision to Automatic.</li>
<li>The <b>Model packs</b> tab shows which processor is in use.</li>
<li>With 8 GB of GPU memory, Whisper large-v3-turbo runs comfortably in float16. If memory runs short, choose int8+float16; jobs also fall back to CPU automatically.</li></ol>""")

sec("theme", "Dark and light theme", """<p>Click the round half-filled button in the top bar to switch between dark and light. Your choice is remembered.</p>""")

sec("keys", "Keyboard shortcuts", """
<ul><li><kbd>Ctrl</kbd>+<kbd>Space</kbd> play/pause · <kbd>Alt</kbd>+<kbd>←</kbd>/<kbd>→</kbd> back/forward 5 s</li>
<li><kbd>Alt</kbd>+<kbd>↑</kbd>/<kbd>↓</kbd> previous/next segment · <kbd>Alt</kbd>+<kbd>[</kbd>/<kbd>]</kbd> slower/faster</li>
<li><kbd>Ctrl</kbd>+<kbd>S</kbd> save · <kbd>Ctrl</kbd>+<kbd>Enter</kbd> split at cursor · <kbd>F1</kbd> this guide · <kbd>Esc</kbd> close dialogs</li></ul>""")

sec("privacy", "Offline use and privacy", """
<ul><li>Everything runs on this PC. Audio, transcripts and models never leave it.</li>
<li>The app blocks its own outbound internet connections and has no telemetry, update checks or sign-in. The only exception is <b>Download and install</b> on the Model packs tab, which contacts Hugging Face, GitHub, PyPI and AI4Bharat to fetch the packs you ticked.</li>
<li>The web page is served only to this PC (address 127.0.0.1) and cannot be opened from other computers.</li>
<li>Projects are stored in <code>%LOCALAPPDATA%\\VU3INI Transcribe Studio</code>.</li></ul>""")

sec("trouble", "Troubleshooting", """
<ul><li><b>"No speech recognition model is installed"</b> — get the Whisper large-v3-turbo pack on the Model packs tab.</li>
<li><b>A pack download fails with "No internet connection"</b> — check the connection and try again; for "gated" errors, paste a Hugging Face token.</li>
<li><b>Transcription is slow</b> — install the NVIDIA GPU runtime pack, or use int8 precision on CPU; close other heavy programs.</li>
<li><b>GPU not detected</b> — update the NVIDIA driver, make sure the GPU runtime pack is installed, then restart the app.</li>
<li><b>Wrong language detected</b> — choose the language yourself instead of Automatic.</li>
<li><b>Repeated or invented lines</b> — keep Hallucination guard and Skip silence on.</li>
<li><b>The browser tab was closed</b> — use the tray icon → Open.</li>
<li>Logs are in <code>%LOCALAPPDATA%\\VU3INI Transcribe Studio\\logs</code>.</li></ul>""")

sec("about", "About", """<p>Help → <b>About</b> shows the version, the author (Sasanka Boruah -VU3INI, hamvu3ini@gmail.com), the open-source projects this app builds on, and every bundled component with its licence.</p>""")

out = pathlib.Path(__file__).resolve().parent.parent / "app" / "web" / "help.json"
out.write_text(json.dumps(H, ensure_ascii=False, indent=1), encoding="utf-8")
print("wrote", out, len(H), "sections")
