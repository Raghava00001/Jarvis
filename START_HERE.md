# 🎯 START HERE — JARVIS Quick Setup

## 1. Install
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```
Optional features (face, emotion, OCR, calendar, Spotify): `pip install -r requirements-optional.txt`

## 2. Configure
```powershell
copy .env.example .env
```
Set `GEMINI_API_KEY` in `.env` (get one at https://aistudio.google.com/apikey).

Optional: `copy user_profile.example.json user_profile.json` and set your name.

## 3. Run
```powershell
start_jarvis.bat
```
The HUD opens at **http://localhost:8080**. You can also run `python jarvis/gui/websocket_server.py`.

## First commands to try
1. "What time is it?"
2. "Open calculator"
3. "Tell me the news"
4. "Switch to Friday"
5. "Restart the computer", then "cancel" to see the confirmation step

## Verify
```powershell
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```
All 201 tests should pass.

See `README.md` for the full documentation and the Security section.
