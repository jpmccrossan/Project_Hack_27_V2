import sys
import time
import subprocess
import streamlit as st
from pathlib import Path

_ROOT = str(Path(__file__).parent.parent)
for _p in [_ROOT, str(Path(__file__).parent.parent / "LLM")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from utils.shared import BLUE, BLUE_DIM, BLUE_DARK, GOLD, BG, CARD_BG, inject_theme

import re

from ollama_client import is_ollama_running, list_models, chat_stream, chat_complete
from db_context import (
    build_full_system_prompt, get_all_table_names, get_row_count, DB_PATH, _q, execute_sql
)

_SQL_RE = re.compile(r"```sql\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
_MAX_ROUNDS = 5  # max SQL execution rounds before forcing a final answer


def _extract_sql(text):
    return [s.strip() for s in _SQL_RE.findall(text) if s.strip()]


def _stream_to(ph, model, messages, suffix="▌"):
    """Stream a chat response into a Streamlit placeholder. Returns full text."""
    full = ""
    for chunk in chat_stream(model, messages):
        full += chunk
        ph.markdown(full + suffix)
    ph.markdown(full)
    return full

st.set_page_config(page_title="LLM Data Chat", page_icon="💬", layout="wide")

inject_theme("""
    [data-testid="stChatMessage"] {
        background-color: #0C1629 !important; border: 1px solid #0D2040;
        border-radius: 8px; margin-bottom: 8px;
    }
    [data-testid="stChatMessage"] p  { color: #D0E8FF !important; line-height:1.65; }
    [data-testid="stChatMessage"] li { color: #D0E8FF !important; }
    [data-testid="stChatMessage"] code {
        background: #060918 !important; color: #60E4B8 !important; padding: 1px 5px; border-radius:3px;
    }
    [data-testid="stChatMessage"] pre {
        background: #060918 !important; border:1px solid #0D2040 !important; border-radius:6px; padding:10px;
    }
    [data-testid="stChatMessage"] table { border-collapse:collapse; width:100%; margin:8px 0; }
    [data-testid="stChatMessage"] th { background:#0D2040; color:#4FC3F7; padding:6px 12px; text-align:left; }
    [data-testid="stChatMessage"] td { padding:5px 12px; border-bottom:1px solid #0D2040; color:#D0E8FF; }
    [data-testid="stChatMessage"] h2 { font-size:1.1rem !important; margin-top:16px; }
    [data-testid="stChatMessage"] h3 { font-size:0.95rem !important; }
    div[data-testid="stChatInput"] textarea {
        background:#0C1629 !important; color:#4FC3F7 !important; border-color:#0D2040 !important;
    }
    .stButton button { background:#0C1629; border:1px solid #0D2040; color:#4FC3F7; border-radius:6px; font-size:0.82rem; }
    .stButton button:hover { border-color:#4FC3F7; color:#FFFFFF; background:#0D2040; }
""")

# ── DB check ──────────────────────────────────────────────────────────────────
if not DB_PATH.exists():
    st.error("Database not found. Run: python API_Connection_Files/run_all.py")
    st.stop()

# ── Auto-start Ollama if not running ─────────────────────────────────────────
def _try_start_ollama():
    """Attempt to launch `ollama serve` as a background process."""
    try:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        # Give it a moment to bind the port
        for _ in range(8):
            time.sleep(0.5)
            if is_ollama_running():
                return True
    except FileNotFoundError:
        pass  # ollama not installed
    except Exception:
        pass
    return is_ollama_running()


if not is_ollama_running():
    with st.spinner("Starting Ollama…"):
        _try_start_ollama()

_ollama_ok = is_ollama_running()
_models    = list_models() if _ollama_ok else []

# ── Sidebar ───────────────────────────────────────────────────────────────────
if _ollama_ok:
    st.sidebar.success("Ollama running")
else:
    st.sidebar.error("Ollama not detected")
    st.sidebar.markdown(
        "<div style='font-size:0.75rem;color:{d};'>"
        "Install: <a href='https://ollama.com' style='color:{b};'>ollama.com</a><br>"
        "Then: <code style='color:#60E4B8;'>ollama serve</code><br>"
        "Pull model: <code style='color:#60E4B8;'>ollama pull llama3.2</code>"
        "</div>".format(d=BLUE_DIM, b=BLUE),
        unsafe_allow_html=True,
    )

# Model picker
st.sidebar.markdown("**Model**")
if _models:
    _model = st.sidebar.selectbox("Model", _models, label_visibility="collapsed")
else:
    _model = st.sidebar.text_input(
        "Model name", value="llama3.2", label_visibility="collapsed",
        help="Type the model name. Pull it first: ollama pull <name>",
    )
    if _ollama_ok and not _models:
        st.sidebar.caption("No models found. Run: `ollama pull llama3.2`")

st.sidebar.markdown("---")

# Controls
if st.sidebar.button("🗑  Clear Chat", use_container_width=True):
    st.session_state.llm_messages = []
    st.rerun()

if st.sidebar.button("🔄  Reload DB Context", use_container_width=True,
                     help="Re-reads the database — picks up new tables and fresh prices"):
    for k in ("llm_system_prompt", "llm_context_loaded_at", "llm_tables",
              "llm_context_db_ts", "llm_prompt_len"):
        st.session_state.pop(k, None)
    st.session_state.llm_rebuilding = True
    st.rerun()

# Export chat
if st.session_state.get("llm_messages"):
    md_lines = []
    for m in st.session_state.llm_messages:
        role = "**You**" if m["role"] == "user" else "**Assistant**"
        md_lines.append("{}\n\n{}\n\n---\n".format(role, m["content"]))
    md_export = "\n".join(md_lines)
    st.sidebar.download_button(
        "⬇  Export Chat (md)", data=md_export,
        file_name="llm_chat_export.md", mime="text/markdown",
        use_container_width=True,
    )

st.sidebar.markdown("---")

# Context info
if "llm_tables" in st.session_state:
    st.sidebar.markdown(
        "<div style='font-size:0.68rem;color:{d};'>"
        "<b style='color:{b};'>Context loaded</b><br>"
        "Tables: {t}<br>"
        "Prompt: {p:,} chars<br>"
        "Loaded: {ts}</div>".format(
            d=BLUE_DIM, b=BLUE,
            t=st.session_state.llm_tables,
            p=st.session_state.get("llm_prompt_len", 0),
            ts=st.session_state.get("llm_context_loaded_at", "—"),
        ),
        unsafe_allow_html=True,
    )

st.sidebar.markdown(
    "<div style='font-size:0.65rem;color:#333355;margin-top:8px;'>"
    "All inference is local via Ollama.<br>No data leaves your machine.<br><br>"
    "<b>To remove this feature:</b><br>"
    "Delete <code>pages/3_💬_LLM_Data_Chat.py</code><br>"
    "and the <code>LLM/</code> folder."
    "</div>",
    unsafe_allow_html=True,
)

# ── Page header ───────────────────────────────────────────────────────────────
st.markdown(
    "<div style='background:linear-gradient(135deg,#06091A 0%,#0C1629 60%,#00205B 100%);"
    "border:1px solid {bk};border-radius:10px;padding:22px 32px;margin-bottom:20px;'>"
    "<div style='font-size:0.7rem;color:{d};letter-spacing:0.2em;"
    "text-transform:uppercase;margin-bottom:2px;'>Local AI · Ollama · Project Hack 27</div>"
    "<div style='font-size:1.85rem;font-weight:700;color:{b};letter-spacing:0.04em;'>"
    "💬 LLM Data Chat</div>"
    "<div style='color:{d};font-size:0.88rem;margin-top:4px;'>"
    "Ask questions about jet engine costs, risks, and trends. "
    "The AI has live access to all database tables and auto-picks up new ones on context reload.</div>"
    "</div>".format(bk=BLUE_DARK, d=BLUE_DIM, b=BLUE),
    unsafe_allow_html=True,
)

# ── Build / cache system prompt ───────────────────────────────────────────────
if "llm_system_prompt" not in st.session_state:
    _rebuilding = st.session_state.pop("llm_rebuilding", False)

    # Prominent loading banner at top of content area
    _load_banner = st.empty()
    _load_banner.markdown(
        "<div style='background:{c};border:1px solid {g};border-radius:10px;"
        "padding:18px 28px;margin-bottom:16px;display:flex;align-items:center;gap:14px;'>"
        "<div style='font-size:1.5rem;'>⬡</div>"
        "<div>"
        "<div style='font-size:0.75rem;color:{g};text-transform:uppercase;"
        "letter-spacing:0.15em;margin-bottom:2px;'>{action}</div>"
        "<div style='font-size:1rem;font-weight:600;color:#FFFFFF;'>"
        "Reading database and building AI context…</div>"
        "<div style='font-size:0.78rem;color:{d};margin-top:3px;'>"
        "Querying all {n} tables · computing JIC risk levels · injecting live prices</div>"
        "</div>"
        "</div>".format(
            c=CARD_BG, g=GOLD, d=BLUE_DIM,
            action="Reloading" if _rebuilding else "Loading",
            n=len(get_all_table_names()),
        ),
        unsafe_allow_html=True,
    )

    with st.spinner(""):
        try:
            tables    = get_all_table_names()
            prompt    = build_full_system_prompt()
            loaded_at = time.strftime("%H:%M:%S")

            st.session_state.llm_system_prompt     = prompt
            st.session_state.llm_tables            = len(tables)
            st.session_state.llm_prompt_len        = len(prompt)
            st.session_state.llm_context_loaded_at = loaded_at
            try:
                ts_row = _q("SELECT MAX(fetched_at) AS ts FROM price_snapshots")
                st.session_state.llm_context_db_ts = ts_row["ts"].iloc[0] or ""
            except Exception:
                st.session_state.llm_context_db_ts = ""
        except Exception as e:
            st.error("Failed to build database context: {}".format(e))
            st.stop()

    _load_banner.empty()  # dismiss banner once done

# ── Stale context warning ─────────────────────────────────────────────────────
try:
    _current_db_ts = _q("SELECT MAX(fetched_at) AS ts FROM price_snapshots")["ts"].iloc[0] or ""
    if (st.session_state.get("llm_context_db_ts", "") and
            _current_db_ts != st.session_state.llm_context_db_ts):
        st.warning(
            "⚠ The market data has been refreshed since this AI context was built "
            "(context: {} · database: {}). "
            "Click **🔄 Reload DB Context** in the sidebar so the AI uses the latest prices.".format(
                st.session_state.get("llm_context_loaded_at", "?"),
                _current_db_ts[11:19] if len(_current_db_ts) > 10 else _current_db_ts,
            ),
            icon=None,
        )
except Exception:
    pass

# ── Chat state ────────────────────────────────────────────────────────────────
if "llm_messages" not in st.session_state:
    st.session_state.llm_messages = []

# ── Suggested prompts (empty chat only) ───────────────────────────────────────
SUGGESTIONS = [
    ("🔴  Full Risk Report",
     "Generate a comprehensive cost risk report for all jet engine components, "
     "ranked by exposure. Include current prices, 1-year trends, JIC risk levels, "
     "and procurement recommendations."),
    ("📊  Executive Summary",
     "Write an executive summary of current jet engine manufacturing cost exposure "
     "suitable for a Rolls-Royce leadership briefing. Cover metals, energy, FX, and macro risks."),
    ("⬡  Metals Analysis",
     "Analyse all tracked metals: current GBP price, 1-year price change, JIC risk level, "
     "and the specific jet engine components affected by each metal's movement."),
    ("⚡  Energy Impact",
     "How are current energy commodity prices affecting jet engine manufacturing costs? "
     "Cover all tracked energy futures and trace through to component cost impact."),
    ("💱  FX Risk Briefing",
     "Assess our GBP foreign exchange exposure across all tracked currency pairs. "
     "Which procurement currencies pose the highest risk to our cost base right now?"),
    ("📈  Top 3 Actions",
     "What are the top 3 specific commodity risks Rolls-Royce should act on this quarter? "
     "Give concrete recommendations with supporting data."),
    ("🔩  Highest Risk Component",
     "Which single jet engine component has the highest material cost risk right now? "
     "Give a detailed breakdown of each material, its price trend, and the aggregate risk score."),
    ("📋  Contract Strategy",
     "Based on current price trends, which materials should we consider locking into "
     "fixed-price contracts, and which should remain spot-priced? Justify with data."),
]

if not st.session_state.llm_messages:
    st.markdown(
        "<div style='color:{d};font-size:0.7rem;text-transform:uppercase;"
        "letter-spacing:0.15em;margin-bottom:10px;'>Quick start — click to send</div>".format(d=BLUE_DIM),
        unsafe_allow_html=True,
    )
    col_a, col_b = st.columns(2)
    for i, (label, prompt_text) in enumerate(SUGGESTIONS):
        col = col_a if i % 2 == 0 else col_b
        if col.button(label, key="sug_{}".format(i), use_container_width=True, help=prompt_text):
            st.session_state.llm_messages.append({"role": "user", "content": prompt_text})
            st.rerun()
    st.markdown("<div style='margin-top:4px'></div>", unsafe_allow_html=True)

# ── Render chat history ────────────────────────────────────────────────────────
for msg in st.session_state.llm_messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ── Input + inference ─────────────────────────────────────────────────────────
# _pending = True when the last message is from the user (no assistant reply yet).
# Covers: suggestion button click → rerun, OR normal chat input on same render.
_pending = (
    bool(st.session_state.llm_messages)
    and st.session_state.llm_messages[-1]["role"] == "user"
)

_THINKING_HTML = (
    "<div style='color:{d};font-size:0.85rem;'>"
    "<span style='animation:pulse 1s infinite;'>⬡</span>&nbsp;&nbsp;Thinking…</div>"
    "<style>@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:0.25}}}}</style>"
).format(d=BLUE_DIM)

if not _ollama_ok:
    st.warning(
        "Ollama is not running — attempted auto-start but it is not installed or failed.  \n"
        "Install from **ollama.com**, then run `ollama serve` in a terminal."
    )
else:
    user_input = st.chat_input(
        "Ask about costs, risks, trends — or request a full report…",
        disabled=_pending,
    )

    if user_input:
        st.session_state.llm_messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)
        _pending = True

    if _pending:
        _sys = {"role": "system", "content": st.session_state.llm_system_prompt}
        _conv = [{"role": m["role"], "content": m["content"]}
                 for m in st.session_state.llm_messages]
        _msgs = [_sys] + _conv

        with st.chat_message("assistant"):
            _thinking = st.empty()
            _thinking.markdown(_THINKING_HTML, unsafe_allow_html=True)

            # ── Agentic SQL loop ────────────────────────────────────────────────
            # Round 1: always stream so user sees the model thinking / writing SQL.
            # If response contains SQL blocks, execute them, inject results, repeat.
            # Each subsequent round is also streamed. Loop until no SQL or max rounds.

            _ans_ph = st.empty()
            _round_text = _stream_to(_ans_ph, _model, _msgs)
            _thinking.empty()

            _msgs = _msgs + [{"role": "assistant", "content": _round_text}]
            _final = _round_text

            for _rnd in range(_MAX_ROUNDS - 1):
                _sqls = _extract_sql(_final)
                if not _sqls:
                    break  # no SQL in last response — we're done

                # Execute every SQL block, show results
                _result_parts = []
                with st.expander(
                    "📊 {} quer{} executed".format(len(_sqls), "y" if len(_sqls) == 1 else "ies"),
                    expanded=True,
                ):
                    for _sql in _sqls:
                        st.code(_sql, language="sql")
                        _res = execute_sql(_sql)
                        _display = _res[:1200] + "\n…[truncated]" if len(_res) > 1200 else _res
                        st.code(_display, language="text")
                        _result_parts.append("Query:\n{}\n\nResult:\n{}".format(_sql, _res))

                _result_content = "\n\n---\n\n".join(_result_parts)
                _msgs = _msgs + [{
                    "role": "user",
                    "content": (
                        "Query results:\n\n{}\n\n"
                        "Using these results, answer the original question directly. "
                        "If you need more data write another SQL query. "
                        "Otherwise give your final answer now."
                    ).format(_result_content),
                }]

                _next_ph = st.empty()
                _next_ph.markdown(
                    "<div style='color:{d};font-size:0.8rem;margin-top:4px;'>"
                    "⬡ Reasoning over results…</div>".format(d=BLUE_DIM),
                    unsafe_allow_html=True,
                )
                _next_text = _stream_to(_next_ph, _model, _msgs)
                _msgs = _msgs + [{"role": "assistant", "content": _next_text}]
                _final = _next_text

            # Only the last assistant text is saved as the visible reply
            st.session_state.llm_messages.append(
                {"role": "assistant", "content": _final}
            )
