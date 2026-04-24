import streamlit as st
import pandas as pd
import math
import gspread
from google.oauth2.service_account import Credentials
import datetime
import time
from itertools import combinations

# =========================
# CONFIG (defaults — overridable via Settings tab)
# =========================
DEFAULT_K          = 32
DEFAULT_START_ELO  = 1000
DEFAULT_SCALE      = 400   # ELO scale factor (400 is standard)
DEFAULT_WEIGHT_1v1 = 1.0
DEFAULT_WEIGHT_2v2 = 0.5

st.set_page_config(page_title="🏓 Ping Pong ELO Arena", layout="wide")

SHEET_NAME = "PingPongELOKARMA_matches"

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds = Credentials.from_service_account_info(
    dict(st.secrets["google"]["service_account"]),
    scopes=scope
)

client      = gspread.authorize(creds)
spreadsheet = client.open(SHEET_NAME)
sheet       = spreadsheet.worksheet("PingPongELOKARMA_matches")

# =========================
# LOAD ELO SETTINGS
# =========================
@st.cache_data(ttl=60)
def load_settings():
    try:
        ws = spreadsheet.worksheet("SETTINGS")
        rows = ws.get_all_records()
        d = {r["key"]: r["value"] for r in rows if "key" in r and "value" in r}

        return {
            "K":         float(d.get("K", DEFAULT_K)),
            "START_ELO": float(d.get("START_ELO", DEFAULT_START_ELO)),
            "SCALE":     float(d.get("SCALE", DEFAULT_SCALE)),
            "W_1V1":     float(d.get("W_1V1", DEFAULT_WEIGHT_1v1)),
            "W_2V2":     float(d.get("W_2V2", DEFAULT_WEIGHT_2v2)),
        }

    except Exception:
        return {
            "K": DEFAULT_K,
            "START_ELO": DEFAULT_START_ELO,
            "SCALE": DEFAULT_SCALE,
            "W_1V1": DEFAULT_WEIGHT_1v1,
            "W_2V2": DEFAULT_WEIGHT_2v2,
        }

def save_settings(k, start_elo, scale, w_1v1, w_2v2):
    try:
        try:
            ws = spreadsheet.worksheet("SETTINGS")
        except Exception:
            ws = spreadsheet.add_worksheet("SETTINGS", rows=20, cols=3)

        ws.clear()

        ws.update([
            ["key", "value", "description"],
            ["K",         str(k),        "K-factor"],
            ["START_ELO", str(start_elo),"Start ELO"],
            ["SCALE",     str(scale),    "Scaling factor"],
            ["W_1V1",     str(w_1v1),    "Overall weight for 1v1 matches"],
            ["W_2V2",     str(w_2v2),    "Overall weight for 2v2 matches"],
        ])

        st.cache_data.clear()

    except Exception as e:
        st.error(f"Kon instellingen niet opslaan: {e}")

settings  = load_settings()

K         = settings["K"]
START_ELO = settings["START_ELO"]
SCALE     = settings["SCALE"]

W_1V1     = settings["W_1V1"]
W_2V2     = settings["W_2V2"]

# =========================
# COLUMN RENAME MAPS
# =========================
MATCH_COL_RENAME = {
    "wedstrijdId":    "Match ID",
    "created_by":     "Added by",
    "Team1_player1":  "Team 1 Player 1",
    "Team1_player2":  "Team 1 Player 2",
    "Team2_player1":  "Team 2 Player 1",
    "Team2_player2":  "Team 2 Player 2",
    "team1_punten":   "Points Team 1",
    "team2_punten":   "Points Team 2",
    "datum":          "Date",
    "match_type":     "Type"
}

LEADERBOARD_COL_RENAME = {
    "speler":          "Player",
    "elo":             "ELO (Overall)",
    "elo_1v1":         "ELO (1v1)",
    "elo_2v2":         "ELO (2v2)",
    "highest_elo":     "Highest ELO",
    "matches":         "Matches",
    "wins":            "Wins",
    "win %":           "Win %",
    "matches_1v1":     "Matches (1v1)",
    "wins_1v1":        "Wins (1v1)",
    "win%_1v1":        "Win % (1v1)",
    "matches_2v2":     "Matches (2v2)",
    "wins_2v2":        "Wins (2v2)",
    "win%_2v2":        "Win % (2v2)",
    "biggest_win":     "Biggest Win (pts)",
    "streak":          "Streak 🔥"
}

def display_matches(df):
    return df.rename(columns=MATCH_COL_RENAME)

# =========================
# USERS / LOGIN
# =========================
def load_users():
    users_df = pd.DataFrame(spreadsheet.worksheet("USERS").get_all_records())
    users_df["name"]  = users_df["name"].astype(str).str.strip()
    users_df["pin"]   = users_df["pin"].astype(str).str.strip()
    if "group" not in users_df.columns:
        users_df["group"] = "default"
    users_df["group"] = users_df["group"].astype(str).str.strip()
    return users_df

users_df = load_users()

if "user" not in st.session_state:
    st.session_state.user = None

if st.session_state.user is None:
    st.title("🔐 Login")
    name = st.text_input("Name")
    pin  = st.text_input("PIN", type="password")

    if st.button("Login"):
        match = users_df[
            (users_df["name"] == name) &
            (users_df["pin"]  == pin)
        ]
        if not match.empty:
            st.session_state.user  = name
            st.session_state.group = match.iloc[0]["group"]
            st.rerun()
        else:
            st.error("❌ Wrong name or PIN")
    st.stop()

# Make sure group is set (for existing sessions after code update)
if "group" not in st.session_state:
    row = users_df[users_df["name"] == st.session_state.user]
    st.session_state.group = row.iloc[0]["group"] if not row.empty else "default"

current_group = st.session_state.group

# Welcome banner
st.markdown(f"👋 **Welcome, {st.session_state.user}!**")

# =========================
# HELPERS
# =========================
def clean_name(name):
    if pd.isna(name) or name is None or name == "":
        return None
    name = str(name).strip()
    return name[:1].upper() + name[1:].lower()

def get_players(row, prefix):
    players = []
    for key in [f"{prefix}_player1", f"{prefix}_player2"]:
        val = row.get(key)
        if val is None:
            continue
        val = str(val).strip()
        if val == "" or val.lower() == "nan":
            continue
        players.append(val)
    return players

def expected(a, b):
    return 1 / (1 + 10 ** ((b - a) / SCALE))

def valid_score(s1, s2):
    high = max(s1, s2)
    low  = min(s1, s2)
    return (high == 11 and low <= 9) or (high > 11 and high - low == 2)

def user_matches(df):
    return df[df["created_by"] == st.session_state.user]

def is_1v1(row):
    t1 = get_players(row, "Team1")
    t2 = get_players(row, "Team2")
    return len(t1) == 1 and len(t2) == 1

def is_2v2(row):
    t1 = get_players(row, "Team1")
    t2 = get_players(row, "Team2")
    return len(t1) == 2 and len(t2) == 2

# =========================
# DATA LOADING / SAVING
# =========================
@st.cache_data(ttl=5)
def load_data():
    cols = [
        "wedstrijdId", "created_by",
        "Team1_player1", "Team1_player2",
        "Team2_player1", "Team2_player2",
        "team1_punten", "team2_punten", "datum"
    ]
    try:
        df = pd.DataFrame(sheet.get_all_records())
        for c in cols:
            if c not in df.columns:
                df[c] = None
        return df[cols]
    except Exception:
        return pd.DataFrame(columns=cols)

def save_data(df):
    df = df.fillna("")
    sheet.clear()
    sheet.update([df.columns.tolist()] + df.astype(str).values.tolist())

# =========================
# GROUP FILTER
# =========================
def filter_by_group(df, users_df, group):
    """Keep only matches where ALL players belong to the same group."""
    group_players = set(users_df[users_df["group"] == group]["name"].tolist())
    if not group_players:
        return df
    def all_in_group(row):
        players = get_players(row, "Team1") + get_players(row, "Team2")
        return all(p in group_players for p in players) if players else False
    return df[df.apply(all_in_group, axis=1)].reset_index(drop=True)

# =========================
# ELO ENGINE (FINAL VERSION)
# =========================
def compute_elo(df):

    if df.empty:
        empty_cur = pd.DataFrame(columns=[
            "speler","elo","elo_1v1","elo_2v2",
            "matches","wins","matches_1v1","wins_1v1",
            "matches_2v2","wins_2v2","winrate"
        ])
        return empty_cur, pd.DataFrame(), pd.DataFrame()

    df = df.sort_values("wedstrijdId")

    # -------------------------
    # STATE
    # -------------------------
    elo = {}
    elo_1v1 = {}
    elo_2v2 = {}
    stats = {}

    history = []
    form_log = []

    # -------------------------
    # LOOP MATCHES
    # -------------------------
    for _, r in df.iterrows():

        t1 = get_players(r, "Team1")
        t2 = get_players(r, "Team2")

        if not t1 or not t2:
            continue

        try:
            s1 = float(r["team1_punten"])
            s2 = float(r["team2_punten"])
        except:
            continue

        mtype = "1v1" if (len(t1) == 1 and len(t2) == 1) else "2v2"

        # -------------------------
        # INIT PLAYERS
        # -------------------------
        for p in t1 + t2:
            if p not in elo:
                elo[p] = START_ELO
                elo_1v1[p] = START_ELO
                elo_2v2[p] = START_ELO
                stats[p] = {
                    "matches": 0, "wins": 0,
                    "matches_1v1": 0, "wins_1v1": 0,
                    "matches_2v2": 0, "wins_2v2": 0
                }

        res1 = 1 if s1 > s2 else 0
        res2 = 1 - res1

        # -------------------------
        # FORM TRACKING
        # -------------------------
        for p in t1:
            form_log.append((p, res1, mtype))
        for p in t2:
            form_log.append((p, res2, mtype))

        diff = abs(s1 - s2)
        mult = max(1.0, math.log(diff + 1))

        # =====================================================
        # 🟦 1V1 MATCH
        # =====================================================
        if mtype == "1v1":

            e1 = elo_1v1[t1[0]]
            e2 = elo_1v1[t2[0]]

            expected1 = 1 / (1 + 10 ** ((e2 - e1) / SCALE))
            d = K * mult * (res1 - expected1)

            # update 1v1 + overall
            for p in t1:
                elo_1v1[p] += d
                elo[p] += W_1V1 * d

                stats[p]["matches"] += 1
                stats[p]["wins"] += res1
                stats[p]["matches_1v1"] += 1
                stats[p]["wins_1v1"] += res1

            for p in t2:
                elo_1v1[p] -= d
                elo[p] -= W_1V1 * d

                stats[p]["matches"] += 1
                stats[p]["wins"] += res2
                stats[p]["matches_1v1"] += 1
                stats[p]["wins_1v1"] += res2

        # =====================================================
        # 🟩 2V2 MATCH
        # =====================================================
        else:

            e1 = sum(elo_2v2[p] for p in t1) / len(t1)
            e2 = sum(elo_2v2[p] for p in t2) / len(t2)

            expected1 = 1 / (1 + 10 ** ((e2 - e1) / SCALE))
            d = K * mult * (res1 - expected1)

            # update 2v2 + overall
            for p in t1:
                elo_2v2[p] += d
                elo[p] += W_2V2 * d

                stats[p]["matches"] += 1
                stats[p]["wins"] += res1
                stats[p]["matches_2v2"] += 1
                stats[p]["wins_2v2"] += res1

            for p in t2:
                elo_2v2[p] -= d
                elo[p] -= W_2V2 * d

                stats[p]["matches"] += 1
                stats[p]["wins"] += res2
                stats[p]["matches_2v2"] += 1
                stats[p]["wins_2v2"] += res2

        # -------------------------
        # HISTORY (after update)
        # -------------------------
        for p in elo:
            history.append({
                "wedstrijdId": r["wedstrijdId"],
                "datum": r["datum"],
                "speler": p,
                "elo": elo[p],
                "elo_1v1": elo_1v1[p],
                "elo_2v2": elo_2v2[p],
                "match_type": mtype
            })

    # =========================
    # OUTPUT TABLES
    # =========================
    hist_df = pd.DataFrame(history)
    hist_df["datum"] = pd.to_datetime(hist_df["datum"])

    form_df = pd.DataFrame(form_log, columns=["speler", "result", "match_type"])

    current = []
    for p in elo:
        s = stats[p]
        wr1 = s["wins_1v1"] / s["matches_1v1"] if s["matches_1v1"] else None
        wr2 = s["wins_2v2"] / s["matches_2v2"] if s["matches_2v2"] else None
        current.append({
            "speler": p,
            "elo": elo[p],
            "elo_1v1": elo_1v1[p],
            "elo_2v2": elo_2v2[p],

            "matches": s["matches"],
            "wins": s["wins"],
            "winrate": s["wins"] / s["matches"] if s["matches"] else 0,

            "matches_1v1": s["matches_1v1"],
            "wins_1v1": s["wins_1v1"],
            "winrate_1v1":  wr1,

            "matches_2v2": s["matches_2v2"],
            "wins_2v2": s["wins_2v2"],
            "winrate_2v2":  wr2,
        })

    return pd.DataFrame(current), hist_df, form_df

# =========================
# ELO ENGINE  (overall + 1v1 + 2v2)
# =========================
def compute_elo(df):
    """Returns (current_df, hist_df, form_df) with overall, 1v1 and 2v2 ELO."""
    if df.empty:
        empty_cur = pd.DataFrame(columns=[
            "speler","elo","elo_1v1","elo_2v2",
            "matches","wins","matches_1v1","wins_1v1","matches_2v2","wins_2v2","winrate"
        ])
        return empty_cur, pd.DataFrame(), pd.DataFrame()

    df = df.sort_values("wedstrijdId")

    elo      = {}   # overall
    elo_1v1  = {}
    elo_2v2  = {}
    stats    = {}
    history  = []
    form_log = []

    for _, r in df.iterrows():
        t1 = get_players(r, "Team1")
        t2 = get_players(r, "Team2")
        if not t1 or not t2:
            continue
        try:
            s1 = int(r["team1_punten"])
            s2 = int(r["team2_punten"])
        except Exception:
            continue

        mtype = "1v1" if (len(t1) == 1 and len(t2) == 1) else "2v2"

        for p in t1 + t2:
            if p not in elo:
                elo[p]     = START_ELO
                elo_1v1[p] = None
                elo_2v2[p] = None
                stats[p]   = {
                    "matches": 0, "wins": 0,
                    "matches_1v1": 0, "wins_1v1": 0,
                    "matches_2v2": 0, "wins_2v2": 0
                }

        e1_ov = sum(elo[p] for p in t1) / len(t1)
        e2_ov = sum(elo[p] for p in t2) / len(t2)
        res1  = 1 if s1 > s2 else 0
        res2  = 1 - res1

        for p in t1:
            form_log.append((p, res1, mtype))
        for p in t2:
            form_log.append((p, res2, mtype))

        diff = abs(s1 - s2)
        mult = math.log(diff + 1)
        d_ov = K * mult * (res1 - expected(e1_ov, e2_ov))

        # --- update overall ELO ---
        for p in t1:
            elo[p]             += d_ov
            stats[p]["matches"] += 1
            stats[p]["wins"]    += res1
        for p in t2:
            elo[p]             -= d_ov
            stats[p]["matches"] += 1
            stats[p]["wins"]    += res2

        # --- update 1v1 or 2v2 ELO ---
        if mtype == "1v1":
            for p in t1 + t2:
                if elo_1v1[p] is None:
                    elo_1v1[p] = START_ELO
            e1_s = sum(elo_1v1[p] for p in t1) / len(t1)
            e2_s = sum(elo_1v1[p] for p in t2) / len(t2)
            d_s  = K * mult * (res1 - expected(e1_s, e2_s))
            for p in t1:
                elo_1v1[p]              += d_s
                stats[p]["matches_1v1"] += 1
                stats[p]["wins_1v1"]    += res1
            for p in t2:
                elo_1v1[p]              -= d_s
                stats[p]["matches_1v1"] += 1
                stats[p]["wins_1v1"]    += res2
        else:
            for p in t1 + t2:
                if elo_2v2[p] is None:
                    elo_2v2[p] = START_ELO
            e1_s = sum(elo_2v2[p] for p in t1) / len(t1)
            e2_s = sum(elo_2v2[p] for p in t2) / len(t2)
            d_s  = K * mult * (res1 - expected(e1_s, e2_s))
            for p in t1:
                elo_2v2[p]              += d_s
                stats[p]["matches_2v2"] += 1
                stats[p]["wins_2v2"]    += res1
            for p in t2:
                elo_2v2[p]              -= d_s
                stats[p]["matches_2v2"] += 1
                stats[p]["wins_2v2"]    += res2

        for p in elo:
            history.append({
                "wedstrijdId": r["wedstrijdId"],
                "datum":       r["datum"],
                "speler":      p,
                "elo":         elo[p],
                "elo_1v1":     elo_1v1[p],
                "elo_2v2":     elo_2v2[p],
                "match_type":  mtype
            })

    hist_df = pd.DataFrame(history)
    hist_df["datum"] = pd.to_datetime(hist_df["datum"])
    form_df = pd.DataFrame(form_log, columns=["speler", "result", "match_type"])

    current = []
    for p in elo:
        s  = stats[p]
        wr = s["wins"] / s["matches"] if s["matches"] else 0
        wr1 = s["wins_1v1"] / s["matches_1v1"] if s["matches_1v1"] else None
        wr2 = s["wins_2v2"] / s["matches_2v2"] if s["matches_2v2"] else None
        current.append({
            "speler":       p,
            "elo":          elo[p],
            "elo_1v1":      elo_1v1[p],
            "elo_2v2":      elo_2v2[p],
            "matches":      s["matches"],
            "wins":         s["wins"],
            "winrate":      wr,
            "matches_1v1":  s["matches_1v1"],
            "wins_1v1":     s["wins_1v1"],
            "winrate_1v1":  wr1,
            "matches_2v2":  s["matches_2v2"],
            "wins_2v2":     s["wins_2v2"],
            "winrate_2v2":  wr2,
        })

    return pd.DataFrame(current), hist_df, form_df

# =========================
# EXTRA STAT HELPERS
# =========================
def compute_streaks(form_df):
    # ✅ FIX: handle empty dataframe safely
    if form_df is None or form_df.empty or "speler" not in form_df.columns:
        return {}

    streaks = {}
    for player in form_df["speler"].unique():
        results = form_df[form_df["speler"] == player]["result"].tolist()
        streak  = 0
        for r in reversed(results):
            if r == 1:
                streak += 1
            else:
                break
        streaks[player] = streak

    return streaks

def compute_highest_elo(hist_df):
    if hist_df is None or hist_df.empty or "speler" not in hist_df.columns:
        return {}
    return hist_df.groupby("speler")["elo"].max().to_dict()

def compute_biggest_win(df):
    if df is None or df.empty:
        return {}
    biggest = {}
    for _, r in df.iterrows():
        t1 = get_players(r, "Team1")
        t2 = get_players(r, "Team2")
        if not t1 or not t2:
            continue
        try:
            s1, s2 = int(r["team1_punten"]), int(r["team2_punten"])
        except Exception:
            continue
        diff    = abs(s1 - s2)
        winners = t1 if s1 > s2 else t2
        for p in winners:
            if p not in biggest or diff > biggest[p]:
                biggest[p] = diff
    return biggest

# =========================
# FIXED-AXIS CHART HELPER
# =========================
def fixed_line_chart(data: pd.DataFrame, title: str = ""):
    """
    Renders a Plotly line chart with fixed axes (no drag-to-zoom).
    data: DataFrame with index as x-axis and columns as series.
    """
    import plotly.graph_objects as go

    fig = go.Figure()
    for col in data.columns:
        series = data[col].dropna()
        fig.add_trace(go.Scatter(
            x=series.index,
            y=series.values,
            mode="lines+markers",
            name=str(col),
            connectgaps=False
        ))

    all_vals = data.values.flatten()
    all_vals = [v for v in all_vals if not (v != v)]  # remove NaN
    if all_vals:
        y_min = min(all_vals)
        y_max = max(all_vals)
        margin = max((y_max - y_min) * 0.10, 20)
    else:
        y_min, y_max, margin = 800, 1200, 50

    fig.update_layout(
        title=title,
        dragmode=False,
        xaxis=dict(fixedrange=True),
        yaxis=dict(
            fixedrange=True,
            range=[y_min - margin, y_max + margin]
        ),
        height=380,
        margin=dict(l=10, r=10, t=40 if title else 10, b=10),
        legend=dict(orientation="h", y=-0.15)
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

# =========================
# LOAD & ENRICH
# =========================
df_all   = load_data()
df       = filter_by_group(df_all, users_df, current_group)

current_df, hist_df, form_df = compute_elo(df)

streaks_all  = compute_streaks(form_df)

streaks_1v1  = compute_streaks(form_df[form_df["match_type"] == "1v1"]) if "match_type" in form_df.columns else {}
streaks_2v2  = compute_streaks(form_df[form_df["match_type"] == "2v2"]) if "match_type" in form_df.columns else {}

highest_elo_dict = compute_highest_elo(hist_df)
biggest_win_dict = compute_biggest_win(df)

if not current_df.empty:
    current_df["streak"] = current_df["speler"].map(lambda p: streaks_all.get(p, 0))
    current_df["streak_1v1"] = current_df["speler"].map(lambda p: streaks_1v1.get(p, 0))
    current_df["streak_2v2"] = current_df["speler"].map(lambda p: streaks_2v2.get(p, 0))
    current_df["highest_elo"] = current_df["speler"].map(
        lambda p: highest_elo_dict.get(p,
            float(current_df.loc[current_df["speler"] == p, "elo"].iloc[0])
            if not current_df[current_df["speler"] == p].empty else 0
        )
    )
    current_df["biggest_win"] = current_df["speler"].map(lambda p: biggest_win_dict.get(p, 0))

# Player list from USERS sheet (group-filtered, always up to date)
players_list = sorted(
    users_df[users_df["group"] == current_group]["name"].tolist()
)

def get_elo(player, mode="overall"):
    row = current_df[current_df["speler"] == player]
    if row.empty:
        return START_ELO
    if mode == "1v1":
        val = row["elo_1v1"].iloc[0]
        return float(val) if val is not None and str(val) != "None" and not (val != val) else START_ELO
    if mode == "2v2":
        val = row["elo_2v2"].iloc[0]
        return float(val) if val is not None and str(val) != "None" and not (val != val) else START_ELO
    return float(row["elo"].iloc[0])

# =========================
# BUILD TABS
# =========================
st.title("🔥🏓 KARMA Ping Pong Leaderboard 🏓🔥")
st.subheader("Become the KARMA Ping Pong GOAT!")

is_arthur  = st.session_state.user == "Arthur"
tab_labels = [
    "➕ Matches",
    "🏆 Leaderboard",
    "📊 Stats",
    "👤 Players",
    "🧠 1v1 Matchmaking",
    "👥 2v2 Matchmaking",
    "🎯 1v1 Win Probability",
    "🎯 2v2 Win Probability",
    "⚙️ Settings (Admin)",
    "ℹ️ Info & Simulation",
]

if is_arthur:
    tab_labels.append("🔧 Manage Players")

tabs = st.tabs(tab_labels)

tab1  = tabs[0]
tab2  = tabs[1]
tab3  = tabs[2]
tab4  = tabs[3]
tab5  = tabs[4]
tab6  = tabs[5]
tab7  = tabs[6]
tab8  = tabs[7]
tab_set_admin = tabs[8]
tab_info = tabs[9]
tab_admin = tabs[10] if is_arthur else None

# =========================
# TAB 1 — MATCHES
# =========================
with tab1:
    st.subheader("➕ Add Match")

    col1, col2 = st.columns(2)
    
    # --- get current selections (so far) ---
    t1_p1_prev = st.session_state.get("t1p1", "")
    t1_p2_prev = st.session_state.get("t1p2", "")
    t2_p1_prev = st.session_state.get("t2p1", "")
    t2_p2_prev = st.session_state.get("t2p2", "")
    
    def available_players(exclude):
        return [""] + [p for p in players_list if p not in exclude]
    
    # Team 1 Player 1
    t1_p1_sel = col1.selectbox(
        "Team 1 — Player 1",
        available_players(set()),
        key="t1p1"
    )
    
    # Team 1 Player 2 (exclude T1P1)
    t1_p2_sel = col1.selectbox(
        "Team 1 — Player 2 (optional)",
        available_players({t1_p1_sel}),
        key="t1p2"
    )
    
    # Team 2 Player 1 (exclude T1P1 + T1P2)
    t2_p1_sel = col2.selectbox(
        "Team 2 — Player 1",
        available_players({t1_p1_sel, t1_p2_sel}),
        key="t2p1"
    )
    
    # Team 2 Player 2 (exclude all previous)
    t2_p2_sel = col2.selectbox(
        "Team 2 — Player 2 (optional)",
        available_players({t1_p1_sel, t1_p2_sel, t2_p1_sel}),
        key="t2p2"
    )
    
    s1 = col1.number_input("Points Team 1", 0, 30, 11)
    s2 = col2.number_input("Points Team 2", 0, 30, 11)

    date = st.date_input("Match Date", value=datetime.date.today(),
                         max_value=datetime.date.today())

    if st.button("Add match 🚀"):
        t1_p1_val = clean_name(t1_p1_sel) if t1_p1_sel else None
        t1_p2_val = clean_name(t1_p2_sel) if t1_p2_sel else None
        t2_p1_val = clean_name(t2_p1_sel) if t2_p1_sel else None
        t2_p2_val = clean_name(t2_p2_sel) if t2_p2_sel else None

        if not t1_p1_val or not t2_p1_val:
            st.error("❌ At least Player 1 for each team is required")
        elif not valid_score(s1, s2):
            st.error("❌ Invalid score — check ping pong rules (e.g. 11–x or deuce)")
        else:
            new_id = 1 if df_all.empty else int(df_all["wedstrijdId"].max()) + 1
            new = pd.DataFrame([{
                "wedstrijdId":   new_id,
                "created_by":    st.session_state.user,
                "Team1_player1": t1_p1_val,
                "Team1_player2": t1_p2_val or "",
                "Team2_player1": t2_p1_val,
                "Team2_player2": t2_p2_val or "",
                "team1_punten":  s1,
                "team2_punten":  s2,
                "datum":         str(date)
            }])
            df_new = pd.concat([df_all, new], ignore_index=True)
            save_data(df_new)
            st.success(f"✅ Match #{new_id} added successfully!")
            st.cache_data.clear()
            time.sleep(0.5)
            st.rerun()

    st.divider()

    st.subheader("📋 All Matches")
    st.dataframe(
        display_matches(df.sort_values("wedstrijdId", ascending=False)),
        use_container_width=True,
        hide_index=True
    )

    st.divider()

    st.subheader("🗑️ Delete a Match")
    user_df = user_matches(df)

    if user_df.empty:
        st.info("You have no matches to delete.")
    else:
        st.write("Your matches:")
        st.dataframe(display_matches(user_df.sort_values("wedstrijdId", ascending=False)),
                     use_container_width=True, hide_index=True)

        del_id    = st.selectbox("Select Match ID to delete",
                                 user_df.sort_values("wedstrijdId", ascending=False)["wedstrijdId"].tolist())
        match_row = user_df[user_df["wedstrijdId"] == del_id].iloc[0]

        st.warning("⚠️ Match selected for deletion:")
        st.dataframe(display_matches(pd.DataFrame([match_row])),
                     use_container_width=True, hide_index=True)

        if "last_delete_id" not in st.session_state:
            st.session_state.last_delete_id = None
        if st.session_state.last_delete_id != del_id:
            st.session_state.confirm_delete = False
            st.session_state.last_delete_id = del_id

        confirm = st.checkbox("I confirm I want to delete this match", key="confirm_delete")

        if st.button("Delete ❌"):
            if confirm:
                df_new = df_all[df_all["wedstrijdId"] != del_id]
                save_data(df_new)
                st.cache_data.clear()
                st.success(f"Match {del_id} deleted ✅")
                st.rerun()
            else:
                st.error("Please tick the confirmation box first ⚠️")

# =========================
# TAB 2 — LEADERBOARD
# =========================
with tab2:
    st.subheader("🏆 Leaderboard")

    if not current_df.empty:
        lb = current_df.copy()
        lb["elo"]         = lb["elo"].round(0).astype(int)
        lb["highest_elo"] = lb["highest_elo"].round(0).astype(int)
        lb["biggest_win"] = lb["biggest_win"].astype(int)
        lb["win %"]       = (lb["winrate"] * 100).round(1)
        lb["win%_1v1"]    = lb["winrate_1v1"].apply(
            lambda x: f"{x*100:.1f}%" if x is not None and str(x) != "None" and not (x != x) else "–"
        )
        lb["win%_2v2"]    = lb["winrate_2v2"].apply(
            lambda x: f"{x*100:.1f}%" if x is not None and str(x) != "None" and not (x != x) else "–"
        )
        lb["elo_1v1_disp"] = lb["elo_1v1"].apply(
            lambda x: int(round(x)) if x is not None and str(x) != "None" and not (x != x) else "–"
        )
        lb["elo_2v2_disp"] = lb["elo_2v2"].apply(
            lambda x: int(round(x)) if x is not None and str(x) != "None" and not (x != x) else "–"
        )

        view = st.radio("View", ["Overall", "1v1", "2v2"], horizontal=True, key="lb_view")

        if view == "Overall":
            lb_display = (
                lb.sort_values("elo", ascending=False)
                [["speler","elo","highest_elo","matches","wins","win %","biggest_win","streak"]]
                .rename(columns=LEADERBOARD_COL_RENAME)
            )
        elif view == "1v1":
            lb_1 = lb.copy()
        
            # Ensure columns exist BEFORE selecting
            lb_1["elo_1v1_disp"] = lb_1["elo_1v1"].apply(
                lambda x: int(round(x)) if pd.notna(x) else None
            )
            lb_1["win%_1v1"] = lb_1["winrate_1v1"].apply(
                lambda x: f"{x*100:.1f}%" if pd.notna(x) else "–"
            )
        
            lb_1 = lb_1[lb_1["matches_1v1"] > 0].sort_values("elo_1v1", ascending=False)
        
            lb_display = lb_1[["speler","elo_1v1_disp","matches_1v1","wins_1v1","win%_1v1","streak_1v1"]].rename(columns={
                "speler": "Player",
                "elo_1v1_disp": "ELO (1v1)",
                "matches_1v1": "Matches",
                "wins_1v1": "Wins",
                "win%_1v1": "Win %",
                "streak_1v1": "Streak 🔥"
            })
        else:
            lb_2 = lb[lb["matches_2v2"] > 0].sort_values("elo_2v2", ascending=False)
            lb_display = lb_2[["speler","elo_2v2_disp","matches_2v2","wins_2v2","win%_2v2","streak_2v2"]].rename(columns={
                "speler": "Player", "elo_2v2_disp": "ELO (2v2)",
                "matches_2v2": "Matches", "wins_2v2": "Wins",
                "win%_2v2": "Win %", "streak_2v2": "Streak 🔥"
            })

        st.dataframe(
            lb_display,
            hide_index=True,
            use_container_width=True
        )
            
    else:
        st.info("No data yet.")

    st.divider()
    st.subheader("📅 Monthly Ranking")

    if view == "Overall":
        elo_col = "elo"
    elif view == "1v1":
        elo_col = "elo_1v1"
    else:
        elo_col = "elo_2v2"
    
    import calendar
    import datetime as dt
    
    today = dt.date.today()
    year, month = today.year, today.month
    
    month_name = calendar.month_name[month]
    days_in_month = calendar.monthrange(year, month)[1]
    days_left = days_in_month - today.day
    
    st.markdown(f"##### {month_name} {year} — {days_left} days remaining")    
    # -------------------------
    # DATE FILTER
    # -------------------------
    start_month = pd.Timestamp(year=year, month=month, day=1)
    end_month   = pd.Timestamp(today)
    
    df_month = df.copy()
    df_month["datum"] = pd.to_datetime(df_month["datum"])
    
    # -------------------------
    # VIEW FILTER (IMPORTANT FIX)
    # -------------------------
    if view == "1v1":
        df_month = df_month[df_month.apply(lambda r: is_1v1(r), axis=1)]
    elif view == "2v2":
        df_month = df_month[df_month.apply(lambda r: is_2v2(r), axis=1)]
    # Overall = no filter
    
    
    # -------------------------
    # PLAYERS IN THIS VIEW
    # -------------------------
    players = sorted(
        set(df_month["Team1_player1"].dropna().tolist() +
            df_month["Team1_player2"].dropna().tolist() +
            df_month["Team2_player1"].dropna().tolist() +
            df_month["Team2_player2"].dropna().tolist())
    )
    
    rows = []
    
    # -------------------------
    # PROCESS EACH PLAYER
    # -------------------------
    for p in players:
    
        # all matches this month for this player
        player_matches = df_month[
            df_month.apply(lambda r: p in get_players(r, "Team1") + get_players(r, "Team2"), axis=1)
        ]
    
        if player_matches.empty:
            continue
    
        # -------------------------
        # HISTORICAL ELO (CORRECT FIX)
        # -------------------------
        p_hist = hist_df[hist_df["speler"] == p].sort_values("wedstrijdId")
    
        if p_hist.empty:
            continue
    
        p_hist["datum"] = pd.to_datetime(p_hist["datum"], errors="coerce")        
        before_month = p_hist[p_hist["datum"] < pd.Timestamp(start_month)]    
        
        if not before_month.empty:
            start_elo = before_month.iloc[-1][elo_col]
        else:
            start_elo = START_ELO
    
        current_elo = p_hist.iloc[-1][elo_col]
    
        # -------------------------
        # MATCH STATS
        # -------------------------
        wins = 0
        for _, r in player_matches.iterrows():
            t1 = get_players(r, "Team1")
            t2 = get_players(r, "Team2")
    
            try:
                s1, s2 = int(r["team1_punten"]), int(r["team2_punten"])
            except:
                continue
    
            if p in t1 and s1 > s2:
                wins += 1
            elif p in t2 and s2 > s1:
                wins += 1
    
        # -------------------------
        # FINAL STATS
        # -------------------------
        elo_change = current_elo - start_elo
        pct_change = (elo_change / start_elo) * 100 if start_elo else 0
    
        rows.append({
            "Player": p,
            "Start of Month ELO": round(start_elo),
            "Current ELO": round(current_elo),
            "Δ ELO": round(elo_change),
            "%ELO Change": round(pct_change, 1),
            "Matches": len(player_matches),
            "Wins": wins
        })
    
    
    # -------------------------
    # OUTPUT
    # -------------------------
    monthly_df = pd.DataFrame(rows)
    
    if not monthly_df.empty:
        monthly_df = monthly_df.sort_values("Δ ELO", ascending=False)
    
        st.dataframe(
            monthly_df,
            hide_index=True,
            use_container_width=True
        )
    else:
        st.info("No matches this month yet.")

# =========================
# TAB 3 — STATS
# =========================
with tab3:
    st.subheader("📊 Global Stats")

    if not current_df.empty:
        view3 = st.radio("Mode", ["Overall", "1v1", "2v2"], horizontal=True, key="stats_view")

        if view3 == "Overall":
            sub = current_df
            elo_col = "elo"
            matches_col = "matches"
            wins_col = "wins"
        elif view3 == "1v1":
            sub = current_df[current_df["matches_1v1"] > 0].copy()
            sub["elo"] = sub["elo_1v1"]
            elo_col = "elo"
            matches_col = "matches_1v1"
            wins_col = "wins_1v1"
        else:
            sub = current_df[current_df["matches_2v2"] > 0].copy()
            sub["elo"] = sub["elo_2v2"]
            elo_col = "elo"
            matches_col = "matches_2v2"
            wins_col = "wins_2v2"

        df_mode = df if view3 == "Overall" else df[df.apply(
            lambda r: (is_1v1(r) if view3 == "1v1" else is_2v2(r)), axis=1
        )]

        col1, col2, col3 = st.columns(3)
        col1.metric("Players",  len(sub))
        col2.metric("Matches",  len(df_mode))
        col3.metric("Avg ELO",  int(sub[elo_col].mean()) if not sub.empty else "–")

        if not sub.empty:
            top_wins    = sub.sort_values(wins_col,     ascending=False).iloc[0]
            top_elo     = sub.sort_values(elo_col,      ascending=False).iloc[0]
            top_matches = sub.sort_values(matches_col,  ascending=False).iloc[0]

            st.markdown(f"###### 🏅 Most Wins: **{top_wins['speler']}** ({int(top_wins[wins_col])} wins)")
            st.markdown(f"###### 🔥 Highest Current ELO: **{top_elo['speler']}** ({int(top_elo[elo_col])})")
            st.markdown(f"###### 🎯 Most Matches Played: **{top_matches['speler']}** ({int(top_matches[matches_col])} matches)")

        if view3 == "Overall":
            top_highest = current_df.sort_values("highest_elo", ascending=False).iloc[0]
            st.markdown(f"###### 👑 Highest Ever ELO: **{top_highest['speler']}** ({int(top_highest['highest_elo'])})")

        # Biggest score gap
        if not df_mode.empty:
            df_copy = df_mode.copy()
            df_copy["diff"] = (
                df_copy["team1_punten"].astype(float) - df_copy["team2_punten"].astype(float)
            ).abs()
            bm     = df_copy.sort_values("diff", ascending=False).iloc[0]
            t1_str = " & ".join(filter(lambda x: x and x.lower() != "nan",
                                       [str(bm["Team1_player1"]), str(bm["Team1_player2"])]))
            t2_str = " & ".join(filter(lambda x: x and x.lower() != "nan",
                                       [str(bm["Team2_player1"]), str(bm["Team2_player2"])]))
            st.markdown(f"###### 💥 Biggest Score Gap: **{t1_str}** vs **{t2_str}** "
                        f"({int(bm['team1_punten'])}–{int(bm['team2_punten'])})")

        # Biggest upset
        if not df_mode.empty:
            upset_data  = []
            elo_running = {}
            for _, r in df_mode.sort_values("wedstrijdId").iterrows():
                t1_players = get_players(r, "Team1")
                t2_players = get_players(r, "Team2")
                if not t1_players or not t2_players:
                    continue
                try:
                    s1_r, s2_r = int(r["team1_punten"]), int(r["team2_punten"])
                except Exception:
                    continue
                for p in t1_players + t2_players:
                    if p not in elo_running:
                        elo_running[p] = START_ELO
                e1_r    = sum(elo_running[p] for p in t1_players) / len(t1_players)
                e2_r    = sum(elo_running[p] for p in t2_players) / len(t2_players)
                prob_t1 = expected(e1_r, e2_r)
                t1_won  = s1_r > s2_r
                if t1_won and prob_t1 < 0.5:
                    upset_data.append({"match_id": r["wedstrijdId"], "winner": " & ".join(t1_players),
                                       "loser": " & ".join(t2_players), "win_prob": prob_t1,
                                       "score": f"{s1_r}–{s2_r}"})
                elif not t1_won and prob_t1 > 0.5:
                    upset_data.append({"match_id": r["wedstrijdId"], "winner": " & ".join(t2_players),
                                       "loser": " & ".join(t1_players), "win_prob": 1 - prob_t1,
                                       "score": f"{s1_r}–{s2_r}"})
                res1_r  = 1 if t1_won else 0
                diff_r  = abs(s1_r - s2_r)
                mult_r  = math.log(diff_r + 1)
                d1_r    = K * mult_r * (res1_r - expected(e1_r, e2_r))
                for p in t1_players:
                    elo_running[p] += d1_r
                for p in t2_players:
                    elo_running[p] -= d1_r

            if upset_data:
                bu = min(upset_data, key=lambda x: x["win_prob"])
                st.markdown(f"###### 😱 Biggest Upset: **{bu['winner']}** beat **{bu['loser']}** "
                            f"with only **{bu['win_prob']*100:.1f}%** win chance "
                            f"(Match #{bu['match_id']}, {bu['score']})")

        # ---- ELO charts ----
        st.subheader("📈 ELO progress per match")
        if not hist_df.empty:
            all_players   = sorted(hist_df["speler"].unique())
            show_all      = st.checkbox("All players", value=False, key="stats_showall")
            sel_players   = st.multiselect("Select players", all_players, default=all_players, key="stats_sel")
            if show_all:
                sel_players = all_players
            if not sel_players:
                st.warning("Select at least one player.")
            else:
                if view3 == "Overall":
                    elo_pivot_col = "elo"
                elif view3 == "1v1":
                    elo_pivot_col = "elo_1v1"
                else:
                    elo_pivot_col = "elo_2v2"

                fh = hist_df[hist_df["speler"].isin(sel_players)]
                if view3 != "Overall":
                    fh = fh[fh["match_type"] == view3]

                pivot = fh.pivot_table(index="wedstrijdId", columns="speler", values=elo_pivot_col)
                fixed_line_chart(pivot, f"ELO ({view3}) per match")

                st.subheader("📅 ELO progress per date")
                latest = (
                    hist_df[hist_df["speler"].isin(sel_players)]
                    .sort_values("wedstrijdId")
                    .groupby(["datum", "speler"])
                    .last()
                    .reset_index()
                )
                if view3 != "Overall":
                    latest = latest[latest["match_type"] == view3]
                pivot2 = latest.pivot(index="datum", columns="speler", values=elo_pivot_col)
                fixed_line_chart(pivot2, f"ELO ({view3}) per date")
    else:
        st.info("No data yet.")

# =========================
# TAB 4 — PLAYER
# =========================
with tab4:
    st.subheader("👤 Player Overview")

    if not current_df.empty:
        player      = st.selectbox("Select player", sorted(current_df["speler"].tolist()))
        p_row       = current_df[current_df["speler"] == player].iloc[0]
        player_hist = hist_df[hist_df["speler"] == player] if not hist_df.empty else pd.DataFrame()
        highest_elo = player_hist["elo"].max() if not player_hist.empty else p_row["elo"]

        # ---- Key metrics ----
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        col1.metric("ELO (Overall)", int(p_row["elo"]))
        col2.metric("Highest ELO",   int(highest_elo))

        elo1v1_val = p_row["elo_1v1"]
        elo2v2_val = p_row["elo_2v2"]
        col3.metric("ELO (1v1)",  int(round(elo1v1_val)) if elo1v1_val is not None and str(elo1v1_val) != "None" and not (elo1v1_val != elo1v1_val) else "–")
        col4.metric("ELO (2v2)",  int(round(elo2v2_val)) if elo2v2_val is not None and str(elo2v2_val) != "None" and not (elo2v2_val != elo2v2_val) else "–")
        col5.metric("Matches",    p_row["matches"])
        col6.metric("Win %",      f"{p_row['winrate']*100:.1f}%")

        # Sub-stats
        c1, c2 = st.columns(2)
        c1.markdown(f"**1v1:** {int(p_row['matches_1v1'])} matches — {int(p_row['wins_1v1'])} wins — "
                    f"{p_row['winrate_1v1']*100:.1f}% win rate" if p_row['matches_1v1'] > 0 else "**1v1:** No matches")
        c2.markdown(f"**2v2:** {int(p_row['matches_2v2'])} matches — {int(p_row['wins_2v2'])} wins — "
                    f"{p_row['winrate_2v2']*100:.1f}% win rate" if p_row['matches_2v2'] > 0 else "**2v2:** No matches")

        # ---- Form ----
        st.subheader("🔥 Form (last 10 matches)")
        f = form_df[form_df["speler"] == player].tail(10) if not form_df.empty else pd.DataFrame()
        form_icons = "".join(["🟢" if x == 1 else "🔴" for x in f["result"]]) if not f.empty else "–"
        st.write(form_icons)

        player_results = form_df[form_df["speler"] == player]["result"].tolist() if not form_df.empty else []
        current_streak = 0
        for res in reversed(player_results):
            if res == 1:
                current_streak += 1
            else:
                break
        st.markdown(f"###### 🔥 Current Win Streak: **{current_streak}**")

        # ---- Head-to-head ----
        st.subheader("📊 Head-to-Head Stats")
        opponents_count = {}
        partners_count  = {}
        beaten_count    = {}
        lost_to_count   = {}

        for _, row in df.iterrows():
            t1_r = get_players(row, "Team1")
            t2_r = get_players(row, "Team2")
            if not t1_r or not t2_r:
                continue
            try:
                s1_r, s2_r = int(row["team1_punten"]), int(row["team2_punten"])
            except Exception:
                continue

            if player in t1_r:
                my_team, opp_team, won = t1_r, t2_r, s1_r > s2_r
            elif player in t2_r:
                my_team, opp_team, won = t2_r, t1_r, s2_r > s1_r
            else:
                continue

            for partner in my_team:
                if partner != player:
                    partners_count[partner] = partners_count.get(partner, 0) + 1
            for opp in opp_team:
                opponents_count[opp] = opponents_count.get(opp, 0) + 1
                if won:
                    beaten_count[opp]  = beaten_count.get(opp, 0) + 1
                else:
                    lost_to_count[opp] = lost_to_count.get(opp, 0) + 1

        c1, c2 = st.columns(2)
        with c1:
            if opponents_count:
                mpa = max(opponents_count, key=opponents_count.get)
                st.markdown(f"###### 🎯 Most played against: **{mpa}** ({opponents_count[mpa]}×)")
            if partners_count:
                mp = max(partners_count, key=partners_count.get)
                st.markdown(f"###### 🤝 Favourite 2v2 partner: **{mp}** ({partners_count[mp]}×)")
        with c2:
            if beaten_count:
                mb = max(beaten_count, key=beaten_count.get)
                st.markdown(f"###### 😤 Most beaten: **{mb}** ({beaten_count[mb]}×)")
            if lost_to_count:
                ml = max(lost_to_count, key=lost_to_count.get)
                st.markdown(f"###### 😰 Lost to most: **{ml}** ({lost_to_count[ml]}×)")

        # ---- ELO charts (only own matches on x-axis) ----
        if not player_hist.empty:
            # Get match IDs this player actually played in
            own_match_ids = set()
            for _, row in df.iterrows():
                if player in get_players(row, "Team1") + get_players(row, "Team2"):
                    own_match_ids.add(row["wedstrijdId"])

            own_hist = player_hist[player_hist["wedstrijdId"].isin(own_match_ids)].sort_values("wedstrijdId")

            st.subheader("📈 ELO evolution (Overall)")
            ov = own_hist.set_index("wedstrijdId")[["elo"]]
            fixed_line_chart(ov, "Overall ELO per match played")

            has_1v1 = own_hist["elo_1v1"].notna().any()
            has_2v2 = own_hist["elo_2v2"].notna().any()

            if has_1v1:
                st.subheader("📈 ELO evolution (1v1)")
                d1 = own_hist[own_hist["match_type"] == "1v1"].set_index("wedstrijdId")[["elo_1v1"]]
                fixed_line_chart(d1, "1v1 ELO per match played")

            if has_2v2:
                st.subheader("📈 ELO evolution (2v2)")
                d2 = own_hist[own_hist["match_type"] == "2v2"].set_index("wedstrijdId")[["elo_2v2"]]
                fixed_line_chart(d2, "2v2 ELO per match played")

            st.subheader("📅 ELO per date")
            latest = (own_hist.sort_values("wedstrijdId")
                      .groupby("datum").last().reset_index())
            pivot_d = latest.set_index("datum")[["elo"]]
            fixed_line_chart(pivot_d, "Overall ELO per date")

        # ---- Match history table ----
        st.subheader("📋 All matches played")
        played = df[df.apply(
            lambda row: player in get_players(row, "Team1") + get_players(row, "Team2"), axis=1
        )].sort_values("wedstrijdId", ascending=False)
        st.dataframe(display_matches(played), use_container_width=True, hide_index=True)

    else:
        st.info("No data yet.")

# =========================
# TAB 5 — 1v1 MATCHMAKING
# =========================
with tab5:
    st.subheader("🧠 1v1 Matchmaking — Closest ELO Pairs")
    st.caption("Based on 1v1 ELO (or overall ELO if no 1v1 games yet)")

    if not current_df.empty:
        mm1 = current_df.copy()
        mm1["elo_use"] = mm1.apply(
            lambda r: r["elo_1v1"] if r["elo_1v1"] is not None and str(r["elo_1v1"]) != "None"
                       and not (r["elo_1v1"] != r["elo_1v1"]) else r["elo"],
            axis=1
        )
        sorted_players = mm1.sort_values("elo_use", ascending=True)
        suggestions    = []
        for i in range(len(sorted_players) - 1):
            low  = sorted_players.iloc[i]
            high = sorted_players.iloc[i + 1]
            suggestions.append({
                "Player 1":       low["speler"],
                "Player 2":       high["speler"],
                "ELO Gap":        int(high["elo_use"] - low["elo_use"]),
                "Win % Player 1": f"{expected(float(low['elo_use']), float(high['elo_use']))*100:.1f}%",
                "Win % Player 2": f"{expected(float(high['elo_use']), float(low['elo_use']))*100:.1f}%",
            })
        st.dataframe(
            pd.DataFrame(suggestions).sort_values("ELO Gap"),
            hide_index=True,
            use_container_width=True
        )
    else:
        st.info("No data yet.")

# =========================
# TAB 6 — 2v2 MATCHMAKING
# =========================
with tab6:
    st.subheader("👥 2v2 Matchmaking — Balanced Teams")
    st.write("Showing all combinations where Team 1 has a **40–60% win chance** (sorted by balance)")
    st.caption("Based on 2v2 ELO (or overall ELO if no 2v2 games yet)")

    if not current_df.empty and len(current_df) >= 4:
        all_p   = current_df["speler"].tolist()
        combos  = []
        seen    = set()

        for team1 in combinations(all_p, 2):
            remaining = [p for p in all_p if p not in team1]
            for team2 in combinations(remaining, 2):
                key = frozenset([frozenset(team1), frozenset(team2)])
                if key in seen:
                    continue
                seen.add(key)
                e1   = (get_elo(team1[0], "2v2") + get_elo(team1[1], "2v2")) / 2
                e2   = (get_elo(team2[0], "2v2") + get_elo(team2[1], "2v2")) / 2
                prob = expected(e1, e2)
                if 0.40 <= prob <= 0.60:
                    combos.append({
                        "Team 1 Player 1": team1[0],
                        "Team 1 Player 2": team1[1],
                        "Team 2 Player 1": team2[0],
                        "Team 2 Player 2": team2[1],
                        "Team 1 Win %":    round(prob * 100, 1),
                        "Team 2 Win %":    round((1 - prob) * 100, 1),
                    })

        if combos:
            st.dataframe(pd.DataFrame(combos).sort_values("Team 1 Win %"),
                         hide_index=True, use_container_width=True)
        else:
            st.info("No balanced 2v2 combinations found with current ELO ratings.")
    else:
        st.info("Need at least 4 players with matches to suggest 2v2 matchups.")

# =========================
# TAB 7 — 1v1 WIN PROBABILITY
# =========================
with tab7:
    st.subheader("🎯 1v1 Win Probability")
    st.caption("Based on 1v1 ELO (or overall ELO if no 1v1 games yet)")

    if not current_df.empty:
        players_sorted = sorted(current_df["speler"].tolist())

        col1, col2 = st.columns(2)
        
        def available_players(base_list, exclude):
            return [p for p in base_list if p not in exclude]
        
        a = col1.selectbox(
            "Player A",
            available_players(players_sorted, set()),
            key="wp1_a"
        )
        
        b = col2.selectbox(
            "Player B",
            available_players(players_sorted, {a}),
            key="wp1_b"
        )

        elo_a = get_elo(a, "1v1")
        elo_b = get_elo(b, "1v1")
        prob  = expected(elo_a, elo_b)

        col1.metric(f"🏓 {a}", f"{prob*100:.1f}%",
                    delta=f"ELO {int(elo_a)}", delta_color="off")
        col2.metric(f"🏓 {b}", f"{(1-prob)*100:.1f}%",
                    delta=f"ELO {int(elo_b)}", delta_color="off")

        if a != b:
            st.divider()
            st.markdown("#### 💡 What happens to ELO after a match?")
            score_options = ["11-0","11-1","11-2","11-3","11-4","11-5",
                             "11-6","11-7","11-8","11-9","12-10","13-11","14-12","15-13"]

            col1b, col2b = st.columns(2)
            score_a_wins = col1b.selectbox(f"Score if **{a}** wins", score_options,
                                           index=8, key="score_a")
            score_b_wins = col2b.selectbox(f"Score if **{b}** wins", score_options,
                                           index=8, key="score_b")

            def parse_score(s):
                parts = s.split("-")
                return int(parts[0]), int(parts[1])

            def calc_new_elos(winner_elo, loser_elo, w_pts, l_pts):
                diff  = abs(w_pts - l_pts)
                mult  = math.log(diff + 1)
                delta = K * mult * (1 - expected(winner_elo, loser_elo))
                return round(winner_elo + delta), round(loser_elo - delta)

            w1, l1 = parse_score(score_a_wins)
            w2, l2 = parse_score(score_b_wins)

            new_a_if_a_wins, new_b_if_a_wins = calc_new_elos(elo_a, elo_b, w1, l1)
            new_b_if_b_wins, new_a_if_b_wins = calc_new_elos(elo_b, elo_a, w2, l2)

            col1b, col2b = st.columns(2)
            with col1b:
                st.markdown(f"**If {a} wins {score_a_wins}:**")
                st.markdown(f"- {a}: {int(elo_a)} → **{new_a_if_a_wins}** (+{new_a_if_a_wins - int(elo_a)})")
                st.markdown(f"- {b}: {int(elo_b)} → **{new_b_if_a_wins}** ({new_b_if_a_wins - int(elo_b)})")
            with col2b:
                st.markdown(f"**If {b} wins {score_b_wins}:**")
                st.markdown(f"- {b}: {int(elo_b)} → **{new_b_if_b_wins}** (+{new_b_if_b_wins - int(elo_b)})")
                st.markdown(f"- {a}: {int(elo_a)} → **{new_a_if_b_wins}** ({new_a_if_b_wins - int(elo_a)})")

            st.caption("ELO change depends on score margin (bigger win = more ELO) and the gap between players "
                       "(beating a stronger opponent = more ELO than beating a weaker one).")
    else:
        st.info("No data yet.")

# =========================
# TAB 8 — 2v2 WIN PROBABILITY
# =========================
with tab8:
    st.subheader("🎯 2v2 Win Probability")
    st.caption("Based on 2v2 ELO (or overall ELO if no 2v2 games yet)")

    if not current_df.empty:
        players_sorted = sorted(current_df["speler"].tolist())

        def available_players(base_list, exclude):
            return [p for p in base_list if p not in exclude]
        
        col1, col2 = st.columns(2)
        
        col1.markdown("**🟦 Team 1**")
        col2.markdown("**🟥 Team 2**")
        
        t1a = col1.selectbox(
            "Team 1 — Player 1",
            available_players(players_sorted, set()),
            key="2v2_t1a"
        )
        
        t1b = col1.selectbox(
            "Team 1 — Player 2",
            available_players(players_sorted, {t1a}),
            key="2v2_t1b"
        )
        
        t2a = col2.selectbox(
            "Team 2 — Player 1",
            available_players(players_sorted, {t1a, t1b}),
            key="2v2_t2a"
        )
        
        t2b = col2.selectbox(
            "Team 2 — Player 2",
            available_players(players_sorted, {t1a, t1b, t2a}),
            key="2v2_t2b"
        )

        e1   = (get_elo(t1a, "2v2") + get_elo(t1b, "2v2")) / 2
        e2   = (get_elo(t2a, "2v2") + get_elo(t2b, "2v2")) / 2
        prob = expected(e1, e2)

        col1.metric(f"🟦 {t1a} & {t1b}", f"{prob*100:.1f}%",
                    delta=f"Avg ELO {int(e1)}", delta_color="off")
        col2.metric(f"🟥 {t2a} & {t2b}", f"{(1-prob)*100:.1f}%",
                    delta=f"Avg ELO {int(e2)}", delta_color="off")

        players_ok = len({t1a, t1b, t2a, t2b}) == 4
        if players_ok:
            st.divider()
            st.markdown("#### 💡 What happens to ELO after a match?")
            score_options = ["11-0","11-1","11-2","11-3","11-4","11-5",
                             "11-6","11-7","11-8","11-9","12-10","13-11","14-12","15-13"]

            col1c, col2c = st.columns(2)
            score_t1_wins = col1c.selectbox(f"Score if **{t1a} & {t1b}** win", score_options,
                                            index=8, key="score_t1")
            score_t2_wins = col2c.selectbox(f"Score if **{t2a} & {t2b}** win", score_options,
                                            index=8, key="score_t2")

            def calc_new_elos_team(we, le, w_pts, l_pts):
                diff  = abs(w_pts - l_pts)
                mult  = math.log(diff + 1)
                delta = K * mult * (1 - expected(we, le))
                return round(we + delta), round(le - delta)

            def parse_score(s):
                parts = s.split("-")
                return int(parts[0]), int(parts[1])

            w1, l1 = parse_score(score_t1_wins)
            w2, l2 = parse_score(score_t2_wins)

            new_e1_if_t1, new_e2_if_t1 = calc_new_elos_team(e1, e2, w1, l1)
            new_e2_if_t2, new_e1_if_t2 = calc_new_elos_team(e2, e1, w2, l2)

            col1c, col2c = st.columns(2)
            with col1c:
                st.markdown(f"**If {t1a} & {t1b} win {score_t1_wins}:**")
                st.markdown(f"- Team 1 avg ELO: {int(e1)} → **{new_e1_if_t1}** (+{new_e1_if_t1-int(e1)})")
                st.markdown(f"- Team 2 avg ELO: {int(e2)} → **{new_e2_if_t1}** ({new_e2_if_t1-int(e2)})")
            with col2c:
                st.markdown(f"**If {t2a} & {t2b} win {score_t2_wins}:**")
                st.markdown(f"- Team 2 avg ELO: {int(e2)} → **{new_e2_if_t2}** (+{new_e2_if_t2-int(e2)})")
                st.markdown(f"- Team 1 avg ELO: {int(e1)} → **{new_e1_if_t2}** ({new_e1_if_t2-int(e1)})")
            st.caption("ELO is calculated per individual player. Team average is shown here for readability.")
    else:
        st.info("No data yet.")

# =========================
# TAB 9 — SETTINGS
# =========================
with tab_set_admin:
    st.subheader("⚙️ Admin Settings (Arthur only)")

    if not is_arthur:
        st.error("You are not allowed to edit settings.")
        st.stop()

    st.markdown("### 🔧 Adjust parameters")

    col1, col2, col3 = st.columns(3)

    new_k = col1.number_input(
        "K-factor",
        min_value=1.0, max_value=100.0, value=float(K), step=1.0
    )

    new_start = col2.number_input(
        "Starting ELO",
        min_value=100.0, max_value=2000.0, value=float(START_ELO), step=100.0
    )

    new_scale = col3.number_input(
        "Scaling factor",
        min_value=100.0, max_value=1000.0, value=float(SCALE), step=50.0
    )

    st.markdown("### ⚖️ Match type influence on OVERALL ELO")

    col4, col5 = st.columns(2)

    new_w_1v1 = col4.slider(
        "1v1 weight (overall impact)",
        min_value=0.0, max_value=1.0,
        value=float(W_1V1), step=0.05
    )

    new_w_2v2 = col5.slider(
        "2v2 weight (overall impact)",
        min_value=0.0, max_value=1.0,
        value=float(W_2V2), step=0.05
    )

    if st.button("💾 Save settings"):
        save_settings(new_k, new_start, new_scale)
        st.success("Saved!")
        st.cache_data.clear()
        st.rerun()


# =========================
# TAB 10 — INFO
# =========================
with tab_info:
    st.subheader("ℹ️ System Info & ELO Simulation")

    st.markdown("### 📌 Current Parameters")
    st.write(f"**K-factor:** {K}")
    st.write(f"**Starting ELO:** {START_ELO}")
    st.write(f"**Scale:** {SCALE}")

    st.subheader("⚙️ ELO Settings & Explanation")

    st.markdown("""
    ### How does the ELO system work?

    Every player starts with a **starting value** (default 1000). After each match, ELO is recalculated.
    The winner gains points from the loser; the amount depends on three things:

    1. **Expected result** — if you are much stronger than your opponent, the system expects you to win.
       A win then gives fewer ELO points; a loss costs more.
    2. **Score margin** — larger wins (e.g. 11–2) give more ELO than narrow wins (11–9).
       This uses a logarithmic scale so the effect flattens for very large margins.
    3. **K-factor** — determines how fast ELO changes overall.

    **Formula (simplified):**
    ```
    ELO change = K × log(score difference + 1) × (result − expected result)
    ```
    """)

    st.divider()
    st.markdown("### 📊 Simulate ELO change")
    st.caption("Enter two ELO values to see how many points change for a given score.")

    sc1, sc2, sc3 = st.columns(3)
    sim_elo_a = sc1.number_input("Player A ELO", value=1000, step=10, key="sim_a")
    sim_elo_b = sc2.number_input("Player B ELO", value=1000, step=10, key="sim_b")
    sim_score = sc3.selectbox(
        "Score (A wins)",
        ["11-0","11-1","11-2","11-3","11-4","11-5",
         "11-6","11-7","11-8","11-9","12-10","13-11"],
        key="sim_score"
    )

    sim_w, sim_l = int(sim_score.split("-")[0]), int(sim_score.split("-")[1])
    sim_diff  = abs(sim_w - sim_l)
    sim_mult  = math.log(sim_diff + 1)
    sim_exp   = expected(sim_elo_a, sim_elo_b)
    sim_delta = K * sim_mult * (1 - sim_exp)

    st.markdown(f"""
    | | Value |
    |---|---|
    | Expected win chance A | **{sim_exp*100:.1f}%** |
    | Score multiplier (log) | **{sim_mult:.2f}** |
    | ELO change | **+{sim_delta:.1f}** for A / **−{sim_delta:.1f}** for B |
    | New ELO A | **{sim_elo_a + sim_delta:.0f}** |
    | New ELO B | **{sim_elo_b - sim_delta:.0f}** |
    """)

# =========================
# ADMIN TAB — MANAGE PLAYERS (Arthur only)
# =========================
if is_arthur and tab_admin is not None:
    with tab_admin:
        st.subheader("🔧 Player Management")
        st.info("Only visible to Arthur.")

        def load_users_ws():
            ws       = spreadsheet.worksheet("USERS")
            u_df     = pd.DataFrame(ws.get_all_records())
            u_df["name"]  = u_df["name"].astype(str).str.strip()
            u_df["pin"]   = u_df["pin"].astype(str).str.strip()
            if "group" not in u_df.columns:
                u_df["group"] = "default"
            u_df["group"] = u_df["group"].astype(str).str.strip()
            return u_df, ws

        admin_users_df, users_ws = load_users_ws()

        st.write("**Current players:**")
        st.dataframe(admin_users_df[["name","pin","group"]], use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("➕ Add New Player")
        new_name  = st.text_input("Player Name", key="admin_new_name")
        new_pin   = st.text_input("PIN",          key="admin_new_pin",   type="password")
        new_group = st.text_input("Group",        key="admin_new_group", value=current_group)

        if st.button("Add Player ✅"):
            if not new_name.strip() or not new_pin.strip():
                st.error("Name and PIN are required.")
            elif new_name.strip() in admin_users_df["name"].tolist():
                st.error(f"Player '{new_name}' already exists.")
            else:
                new_row        = pd.DataFrame([{"name": new_name.strip(),
                                                "pin":  new_pin.strip(),
                                                "group": new_group.strip() or current_group}])
                admin_users_df = pd.concat([admin_users_df, new_row], ignore_index=True)
                users_ws.clear()
                users_ws.update([admin_users_df.columns.tolist()] +
                                admin_users_df.astype(str).values.tolist())
                st.success(f"Player **{new_name}** added!")
                st.rerun()

        st.divider()
        st.subheader("🗑️ Remove Player")
        del_player = st.selectbox("Select player to remove",
                                  admin_users_df["name"].tolist(), key="admin_del")
        confirm_remove = st.checkbox(f"I confirm I want to permanently remove **{del_player}**",
                                     key="confirm_remove_player")
        if st.button("Remove Player ❌"):
            if confirm_remove:
                admin_users_df = admin_users_df[admin_users_df["name"] != del_player]
                users_ws.clear()
                users_ws.update([admin_users_df.columns.tolist()] +
                                admin_users_df.astype(str).values.tolist())
                st.success(f"Player **{del_player}** removed.")
                st.rerun()
            else:
                st.error("Please confirm deletion first ⚠️")
