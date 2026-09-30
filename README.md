# mdb-solo-project

Prototype scanner that finds **hidden text in PDFs**: text an AI model reads but a human can't see
(white-on-white prompts, 1pt fonts, off-page text, zero-width Unicode, metadata).
The app name lives in one place: `APP_NAME` in `app/config.ts`.

```
backend/     FastAPI + PyMuPDF scanner (GET /health, POST /scan)
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
Classification is rule-based in `backend/classifier.py`. To swap in an LLM judge, replace
`classify(text, technique) -> (classification, reason)`.
