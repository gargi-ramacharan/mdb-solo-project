# mdb-solo-project

Prototype scanner that finds **hidden text in PDFs**: text an AI model reads but a human can't see
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
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

Check it: `curl http://localhost:8000/health` → `{"status":"ok"}`

### AI review (optional)

The LLM second opinion can run on **Claude Haiku 4.5** (Anthropic API) or a **local model via Ollama**
(free, offline). Without either, everything still works and flags are labeled rule-based only
("AI review unavailable").

```bash
cp .env.example .env      # in backend/, then edit it
```

**Anthropic** (default): set `ANTHROPIC_API_KEY=sk-ant-...` (and `LLM_PROVIDER=anthropic`, or leave it unset).

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

- `POST /scan` (multipart `file`): returns rule-based results immediately, plus `scan_id` and
  `timings_ms: {parse, detect, rule_classify, total}`.
- `POST /classify/{scan_id}`: runs the AI review on that scan and returns updated `flags` (each with
  `rule_label`, `llm_label`, `final_label`, `llm_reason`, `llm_status`), the updated `risk`, and
  `timings_ms: {llm, cache_hits, llm_calls, retries, llm_error, provider}`. Scans are kept in memory (last 200).

The app shows the report as soon as `/scan` returns, then calls `/classify` in the background and
updates the badges and the risk banner when the AI review comes back.

### Tests and benchmark

```bash
cd backend
.venv/bin/python -m pytest tests -q             # LLM is mocked; no key or network needed
.venv/bin/python benchmark.py                   # every PDF in ../test_pdfs, provider from LLM_PROVIDER
.venv/bin/python benchmark.py --provider ollama # or --provider anthropic
.venv/bin/python benchmark.py --mock-llm        # fake LLM with 600 ms latency (no credits used)
.venv/bin/python benchmark.py path/to/folder    # any folder of PDFs
```

The benchmark prints a per-file table (parse/detect/LLM/total ms, cache hits, final risk) with averages,
writes `benchmark_results.csv`, then reruns everything to show the cache-hit speedup.

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
