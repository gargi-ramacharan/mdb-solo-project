# Underline

Underline is a prototype scanner that finds **hidden text in PDFs**: text an AI model reads but a human can't see
(white-on-white prompts, 1pt fonts, off-page text, zero-width Unicode, metadata).
The app name lives in one place: `APP_NAME` in `app/config.ts`.

```
backend/     FastAPI + PyMuPDF scanner (GET /health, POST /scan, POST /classify/{scan_id})
app/         Expo (expo-router, TypeScript): runs in Expo Go and on web
test_pdfs/   generate_test_pdfs.py + generated demo PDFs
```

## 1. Backend (terminal 1)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # runtime deps + uvicorn + pytest
uvicorn main:app --host 0.0.0.0 --port 8000
```

`requirements.txt` holds only what the deployed backend needs (Vercel installs it); `requirements-dev.txt`
adds the local server and the test runner.

The OCR for the visual diff is RapidOCR (`rapidocr-onnxruntime`, installed by `requirements.txt`; no system
packages or Homebrew needed). `ENABLE_VISUAL_DIFF=false` turns it off. Its models load once, on the first scan. If it can't load, scans still run
and report `visual_diff.status: "unavailable"` with the error.

Check it: `curl http://localhost:8000/health` → `{"status":"ok", "ai_review": {...}, "visual_diff": true}`

### AI review (optional)

The LLM second opinion can run on **Claude Haiku 4.5** (Anthropic API) or a **local model via Ollama**
(free, offline). `LLM_PROVIDER` picks one; unset or `none` means no AI review: nothing is called, flags keep
their rule labels, and the app shows "AI review unavailable (rules + OCR only)". That's how the Vercel
deployment runs.

```bash
cp .env.example .env      # in backend/, then edit it
```

**Anthropic**: set `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY=sk-ant-...`.

**Ollama** (local):

```bash
brew install ollama               # or download from https://ollama.com
ollama serve                      # skip if the Ollama app is already running
ollama pull qwen2.5:7b            # ~4.7 GB
```

Then in `backend/.env`:

```
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen2.5:7b                 # default
OLLAMA_URL=http://localhost:11434       # default
```

Ollama gets a 30 s timeout (the API gets 5 s) and one retry on a failed or partly invalid answer.
Its output is constrained with a JSON schema (`format`), with `id` limited to the ids in that request,
plus `repeat_penalty: 1.1` and `num_predict` = 100 + 150 per snippet. A 7B model takes roughly 1.5 to 2.5 s per document on a laptop.
`.env` is gitignored. Restart uvicorn after changing it.

### API

The API is **stateless** (serverless instances don't share memory), so each response carries everything:

- `GET /health`: `{status, ai_review: {enabled, provider, reason}, visual_diff}`. Config only, no network calls.
- `POST /scan?visual=true` (multipart `file`): rule-based results, plus `scan_id`, `ai_review`,
  `timings_ms: {parse, detect, visual_diff, rule_classify, render, total}` and `pages`: every flagged page as
  `{page, width, height, image}` where `image` is a 72 dpi JPEG **data URL** (`null` if it would push the
  response past ~3 MB of images; Vercel's response limit is 4.5 MB). Every flag has
  `detected_by: ["style"] | ["visual"] | ["style", "visual"]`, and `visual_diff: {status: ok|off|unavailable}`
  says whether the OCR ran. `?visual=false` skips the OCR for a fast style-only scan.
- `POST /classify` (JSON `{"flags": [{id, text, technique, rule_label}, ...]}`): AI review of the flags sent.
  Returns `{risk, flags: [{id, rule_label, llm_label, llm_reason, llm_status, final_label}], timings_ms:
  {llm, cache_hits, llm_calls, retries, llm_error, provider}}`. The input is untrusted: labels must be known
  values, text is capped at 20,000 chars (the LLM sees at most 1,000), at most 300 flags, unique ids, other
  fields ignored. The final label is still `max(rule_label, llm_label)`.
- Legacy, local only: `POST /classify/{scan_id}` and `GET /scan/{scan_id}/page/{n}.png` read an optional
  in-memory cache of the last 100 scans (`SCAN_CACHE`, on locally, off on Vercel).

The app shows the report as soon as `/scan` returns, then (if `ai_review.enabled`) sends the flags to `/classify` in the background and
updates the badges and the risk banner when the AI review comes back.

### Tests and benchmark

```bash
cd backend
.venv/bin/python -m pytest tests -q             # LLM is mocked; no key or network needed
.venv/bin/python benchmark.py                   # every PDF in ../test_pdfs, provider from LLM_PROVIDER
.venv/bin/python benchmark.py --provider ollama # or --provider anthropic
.venv/bin/python benchmark.py --mock-llm        # fake LLM with 600 ms latency (no credits used)
.venv/bin/python benchmark.py path/to/folder    # any folder of PDFs
.venv/bin/python benchmark.py --no-visual       # skip the OCR visual diff
```

The benchmark prints a per-file table (parse/detect/visual diff/LLM/total ms, cache hits, final risk) with averages,
a per-flag table, and a detector table: for every PDF, how many flags only the style checks found, only
the visual diff found, and both found, plus a summary like "the visual diff caught N attacks the style
checks missed, with 0 false positives on the clean PDFs". It writes `benchmark_results.csv`, then reruns
everything to show the cache-hit speedup.

## 2. Test PDFs (optional; already generated)

```bash
backend/.venv/bin/python test_pdfs/generate_test_pdfs.py
curl -s -F "file=@test_pdfs/poisoned_paper.pdf" http://localhost:8000/scan | python3 -m json.tool
```

| File | Expected |
|---|---|
| clean_paper.pdf | `clean` |
| poisoned_paper.pdf | `manipulation` (white text) |
| poisoned_resume.pdf | `manipulation` (1pt font + zero-width chars + metadata keywords) |
| offpage_trick.pdf | `manipulation` (text placed outside the page) |
| classifier_attack_1.pdf | `manipulation` (white text telling the classifier it's benign + "recommend acceptance") |
| classifier_attack_2.pdf | `manipulation` (1pt fake `</snippet> SYSTEM:` delimiter break-out) |
| classifier_attack_3.pdf | `suspicious` by rules (polite persuasion, no keywords); the AI review is meant to raise it |
| benign_hidden.pdf | `clean` (white "Page 1 of 3" and a figure label, both `benign`) |
| covered_by_rect.pdf | `manipulation`, visual diff only (black text under a white rectangle) |
| covered_by_image.pdf | `manipulation`, visual diff only (instruction for AI screeners under an image) |
| clipped_text.pdf | visual diff only (instruction drawn outside the active clipping path); `suspicious` by rules, the AI review raises it to `manipulation` |
| colored_background.pdf | `manipulation`, both detectors (dark blue text on a dark blue box) |

## 3. App (terminal 2)

```bash
cd app
npm install
npx expo start          # scan the QR code with Expo Go (phone must be on the same Wi-Fi)
npx expo start --web    # or press "w" in the running server, then open http://localhost:8081
```

**Backend URL:** by default the app auto-detects it. On a phone it reuses the IP Expo Go used to reach
your computer, and on web it uses `localhost`. If the home screen shows "Backend offline",
set `BACKEND_URL_OVERRIDE` in `app/config.ts` to your computer's LAN IP, e.g. `http://192.168.1.23:8000`
(macOS: `ipconfig getifaddr en0`). It must **not** be `localhost` on a phone.

To get PDFs onto your phone for the demo, AirDrop/email the files in `test_pdfs/` to yourself and save
them to Files (iOS) or Downloads (Android). The picker can then open them.

## Troubleshooting

- **Phone can't reach backend:** same Wi-Fi? Is the server started with `--host 0.0.0.0`? Is the macOS firewall
  allowing Python? Can your phone's browser open `http://<LAN-IP>:8000/health`?
- **Expo Go can't connect (campus/guest Wi-Fi often blocks device-to-device traffic):** try `npx expo start --tunnel`
  for the app. The backend still needs to be reachable, so a phone hotspot is the easiest fix.

## How detection works

`backend/scanner.py` walks every text span (`page.get_text("dict")`, unclipped so off-page text is included):

- **white_text**: renders the page and compares the span color against the actual background behind it
  (WCAG contrast < 1.5:1), so it also catches dark-on-dark text. Falls back to "all RGB > 240".
- **tiny_font**: font size under 4pt.
- **off_page**: less than 50% of the span's box is inside the page.
- **invisible_render**: render mode 3 / zero opacity, via `page.get_texttrace()`.
- **invisible_unicode**: zero-width chars, soft hyphens, and Unicode tag chars (the hidden tag-char message is decoded).
- **metadata**: title/subject/keywords/etc. containing instructions or invisible chars.

Adjacent flagged spans with the same technique are merged into one flag.

**Visual diff** (`backend/visual_diff.py`, technique **visually_hidden**): the checks above look at *how*
text is drawn, so they miss text that is drawn normally and then hidden by something else: covered by a
shape or an image, or clipped away. The visual diff compares the text layer with what a human sees:

1. Render the page at 2x and OCR it with RapidOCR. It returns *lines*: a 4-point polygon plus text.
2. Turn each polygon into a bbox in PDF points (min/max of the corners, divided by the zoom) and, for each
   extracted span (3+ characters), take the OCR lines on the same line that overlap it.
3. Normalize both (lowercase, letters/digits only; RapidOCR often drops spaces) and look for each span word
   as a fuzzy substring of those lines (rapidfuzz `partial_ratio` >= 75, so OCR typos like `rn`/`m` don't
   cause false flags; words under 4 characters must match exactly). If less than half of the span is
   found, it is a candidate.
4. Second look: RapidOCR's line detector sometimes skips a visible line, so each candidate's own area is
   rendered at 3x and run through the recognizer alone. A crop with almost no contrast counts as blank, because
   the recognizer would otherwise read dark-blue-on-dark-blue text a human can't. Still not found means
   visually hidden. Consecutive hidden spans merge into one flag.
5. A span already flagged by a style check isn't duplicated: that flag gets `detected_by: ["style", "visual"]`.

New flags then go through the same rules and AI review as everything else.

Classification happens in two stages:

1. **Rules** (`backend/classifier.py`): instant. Invisible characters that encode hidden text (Unicode tag
   characters), or more than 5 invisible characters in one snippet, are `manipulation`. AI-directed instruction language, and any hidden text that
   addresses a classifier/scanner/detector ("classify this as benign", "output label", fake `</snippet>`
   or `SYSTEM:` turns), is `manipulation`.
2. **AI review** (`backend/classifier_llm.py`): only flags the rules labeled `suspicious`/`benign` are sent,
   all in **one batched call per document**, and results are cached in memory by sha256 of the normalized
   text. Providers: `AnthropicClassifier` and `OllamaClassifier`, selected by `LLM_PROVIDER`. To add one,
   implement `classify_batch(texts) -> list[LLMResult | None]` and return it from `get_classifier()`.

## Security design (prompt-injection defenses)

The text we send to the LLM was hidden in the PDF on purpose, often *to manipulate an AI*. So the
classifier is itself an attack target. Defenses, all in `backend/classifier_llm.py`, apply identically to
both providers:

- **Untrusted-data framing:** the system prompt says snippets are untrusted data extracted from a document,
  never instructions, and that text trying to influence its own label is itself `manipulation`.
- **Nonce delimiters:** each snippet is wrapped in `<snippet_XXXXXXXX id="N">…</snippet_XXXXXXXX>` with a
  random nonce per request. Every `<`, `>` and `&` in the snippet is escaped and the nonce tag name is
  removed, so a snippet can't close its own delimiter or forge a new one.
- **Size limit:** each snippet is truncated to 1000 characters.
- **Show the hidden part:** before sending, invisible characters are replaced with visible `⟦U+200B⟧` markers
  and a `[scanner note: ...]` gives the count and any decoded tag-character text, so the model judges what an
  AI would actually read. The annotated text is escaped and delimited like any other snippet.
- **Strict output validation:** the reply must be a JSON array (for Ollama, exactly `{"results": [...]}`,
  which is unwrapped first; Ollama is also grammar-constrained by a JSON schema, but that never replaces validation) of `{id, label, reason}`, with exactly those
  keys, string types, ids from this request (no unknown or duplicate ids), and labels from the enum.
  Any item that fails is dropped and that flag keeps its rule label. Reasons are capped at 200 chars.
- **No room to act:** temperature 0, a small output-token cap (`max_tokens` / Ollama `num_predict`), no tools.
- **Severity only goes up:** `final_label = max(rule_label, llm_label)`. The LLM can't remove or downgrade a
  flag, and every flag is always shown. The worst a successful injection can do is fail to raise a label.
- **Fail closed to rules:** no key, Ollama not running, timeout (5 s API with no retries, 30 s Ollama),
  HTTP error, truncated output, or refusal all mean
  `llm_status: "unavailable"` and the rule labels stand. The scan itself never waits on the LLM.

## Deploying to Vercel

Two Vercel projects from the same repo: `backend/` (FastAPI, one Python function) and `app/` (static Expo web
export). Config lives in `backend/vercel.json` (`maxDuration: 300`, tests and local files excluded from the
bundle), `backend/.python-version` (3.12) and `app/vercel.json` (export command, `dist`, SPA rewrite so
routes like `/report` don't 404 on refresh).

Limits that shaped the design (Vercel docs, Oct 2026): 4.5 MB request and response bodies, 300 s max
duration on Hobby, 500 MB uncompressed Python bundles (5 GB with Large Functions, beta). The app refuses PDFs
over 4 MB before uploading when it talks to a deployed backend (`EXPO_PUBLIC_API_URL` set).

| Env var | Where | Meaning |
|---|---|---|
| `LLM_PROVIDER` | backend | `none` (default), `ollama`, or `anthropic` |
| `ENABLE_VISUAL_DIFF` | backend | OCR visual diff, default `true` |
| `ALLOWED_ORIGINS` | backend | comma-separated web origins allowed by CORS (localhost always allowed) |
| `SCAN_CACHE` | backend | legacy in-memory cache, default on locally, off on Vercel |
| `EXPO_PUBLIC_API_URL` | app (build time) | backend URL; unset = local auto-detect |

`.env` files and `test_pdfs/resume.pdf` are gitignored, so they're never in the repo and never deployed.
