# How to Run The Assumptionisator

## Quickest way (one command)

```bash
cd <project-folder>    # wherever you cloned or downloaded the repo
python start.py
```

`start.py` automatically:
- Uses the project venv if one exists, otherwise system Python
- Installs any missing dependencies from `requirements.txt`
- Takes a backup of the database before starting
- Launches Streamlit at **http://localhost:8501**
- Refreshes live commodity prices every 15 minutes in the background

---

## Options

```bash
python start.py --no-refresh          # disable background price fetching
python start.py --interval 300        # refresh every 5 minutes instead
```

---

## Manual steps (if start.py doesn't work)

```bash
# 1. Go to the project folder (wherever you cloned it)
cd <project-folder>

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # Mac/Linux
# venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Fetch live market data (first time, ~60s)
python API_Connection_Files/run_all.py

# 5. Launch the app
streamlit run app.py
```

Then open **http://localhost:8501** in your browser.

---

## Refresh market data manually

Click **"🔄 Refresh market data"** in the Market Cost Dashboard sidebar, or run:

```bash
python API_Connection_Files/run_all.py      # full fetch including history (~60s)
python API_Connection_Files/fetch_live.py   # snapshot only, fast (~15s)
```

---

## Database backup

```bash
python backup.py
```

Exports all tables to `Data/backups/<timestamp>/`. Keeps the 10 most recent backups automatically. Also runs on every `python start.py`.

---

## AI Chat (Ollama)

The AI Chat page requires Ollama running locally:

```bash
# Install from https://ollama.com — then:
ollama serve            # start the server (separate terminal)
ollama pull gemma2      # download a model (first time only, ~5GB)
```

---

## Common errors

| Error | Fix |
|-------|-----|
| `StreamlitPageNotFoundError` | Run `python start.py` instead of `streamlit run app.py` from the wrong directory. |
| `ModuleNotFoundError` | Activate the venv, then `pip install -r requirements.txt`. |
| Ollama not detected | Run `ollama serve` in a separate terminal. |
| Database offline | Run `python API_Connection_Files/run_all.py` first. |
