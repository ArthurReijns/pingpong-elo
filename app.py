import streamlit as st
import pandas as pd
import math
import gspread
from google.oauth2.service_account import Credentials
import datetime
import time
from itertools import combinations
 
# =========================
# CONFIG
# =========================
K = 32
START_ELO = 1000
 
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
 
client = gspread.authorize(creds)
spreadsheet = client.open(SHEET_NAME)
sheet = spreadsheet.worksheet("PingPongELOKARMA_matches")
 
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
    "datum":          "Date"
}
 
LEADERBOARD_COL_RENAME = {
    "speler":       "Player",
    "elo":          "ELO Rating",
    "highest_elo":  "Highest ELO",
    "matches":      "Matches Played",
    "wins":         "Matches Won",
    "win %":        "Win %",
    "biggest_win":  "Biggest Win (pts)",
    "streak":       "Current Streak 🔥"
}
 
MATCHMAKING_COL_RENAME = {
    "A":   "Player 1",
    "B":   "Player 2",
    "gap": "ELO Gap"
}
 
def display_matches(df):
    return df.rename(columns=MATCH_COL_RENAME)
 
# =========================
# USERS / LOGIN
# =========================
def load_users():
    users_df = pd.DataFrame(sheet.spreadsheet.worksheet("USERS").get_all_records())
    users_df["name"] = users_df["name"].astype(str).str.strip()
    users_df["pin"]  = users_df["pin"].astype(str).str.strip()
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
            st.session_state.user = name
            st.rerun()
        else:
            st.error("❌ Wrong name or PIN")
    st.stop()
 
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
    return 1 / (1 + 10 ** ((b - a) / 400))
 
def valid_score(s1, s2):
    high = max(s1, s2)
    low  = min(s1, s2)
    return (high == 11 and low <= 9) or (high > 11 and high - low == 2)
 
def user_matches(df):
    return df[df["created_by"] == st.session_state.user]
 
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
    except:
        return pd.DataFrame(columns=cols)
 
def save_data(df):
    df = df.fillna("")
    sheet.clear()
    sheet.update([df.columns.tolist()] + df.astype(str).values.tolist())
 
# =========================
# ELO ENGINE
# =========================
def compute_elo(df):
    if df.empty:
        return (
            pd.DataFrame(columns=["speler","elo","matches","wins","winrate"]),
            pd.DataFrame(),
            pd.DataFrame()
        )
 
    df = df.sort_values("wedstrijdId")
    elo     = {}
    stats   = {}
    history = []
    form_log= []
 
    for _, r in df.iterrows():
        t1 = get_players(r, "Team1")
        t2 = get_players(r, "Team2")
        if not t1 or not t2:
            continue
 
        try:
            s1 = int(r["team1_punten"])
            s2 = int(r["team2_punten"])
        except:
            continue
 
        for p in t1 + t2:
            if p not in elo:
                elo[p]   = START_ELO
                stats[p] = {"matches": 0, "wins": 0}
 
        e1 = sum(elo[p] for p in t1) / len(t1)
        e2 = sum(elo[p] for p in t2) / len(t2)
 
        res1 = 1 if s1 > s2 else 0
        res2 = 1 - res1
 
        for p in t1:
            form_log.append((p, res1))
        for p in t2:
            form_log.append((p, res2))
 
        diff = abs(s1 - s2)
        mult = math.log(diff + 1)
        d1   = K * mult * (res1 - expected(e1, e2))
 
        for p in t1:
            elo[p]             += d1
            stats[p]["matches"] += 1
            stats[p]["wins"]    += res1
        for p in t2:
            elo[p]             -= d1
            stats[p]["matches"] += 1
            stats[p]["wins"]    += res2
 
        for p in elo:
            history.append({
                "wedstrijdId": r["wedstrijdId"],
                "datum":       r["datum"],
                "speler":      p,
                "elo":         elo[p]
            })
 
    hist_df = pd.DataFrame(history)
    form_df = pd.DataFrame(form_log, columns=["speler","result"])
 
    current = []
    for p in elo:
        s  = stats[p]
        wr = s["wins"] / s["matches"] if s["matches"] else 0
        current.append({"speler": p, "elo": elo[p],
                        "matches": s["matches"], "wins": s["wins"], "winrate": wr})
 
    return pd.DataFrame(current), hist_df, form_df
 
# =========================
# EXTRA STAT HELPERS
# =========================
def compute_streaks(form_df):
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
    if hist_df.empty:
        return {}
    return hist_df.groupby("speler")["elo"].max().to_dict()
 
def compute_biggest_win(df):
    biggest = {}
    for _, r in df.iterrows():
        t1 = get_players(r, "Team1")
        t2 = get_players(r, "Team2")
        if not t1 or not t2:
            continue
        try:
            s1, s2 = int(r["team1_punten"]), int(r["team2_punten"])
        except:
            continue
        diff    = abs(s1 - s2)
        winners = t1 if s1 > s2 else t2
        for p in winners:
            if p not in biggest or diff > biggest[p]:
                biggest[p] = diff
    return biggest
 
# =========================
# LOAD & ENRICH
# =========================
df = load_data()
current_df, hist_df, form_df = compute_elo(df)
 
streaks          = compute_streaks(form_df)
highest_elo_dict = compute_highest_elo(hist_df)
biggest_win_dict = compute_biggest_win(df)
 
if not current_df.empty:
    current_df["streak"]      = current_df["speler"].map(lambda p: streaks.get(p, 0))
    current_df["highest_elo"] = current_df["speler"].map(
        lambda p: highest_elo_dict.get(p,
            float(current_df.loc[current_df["speler"] == p, "elo"].iloc[0])
            if not current_df[current_df["speler"] == p].empty else 0
        )
    )
    current_df["biggest_win"] = current_df["speler"].map(lambda p: biggest_win_dict.get(p, 0))
 
# Player list from USERS sheet (always up to date)
players_list = sorted(users_df["name"].tolist())
 
def get_elo(player):
    row = current_df[current_df["speler"] == player]
    return START_ELO if row.empty else float(row["elo"].iloc[0])
 
# =========================
# BUILD TABS
# =========================
st.title("🏓🔥 KARMA Ping Pong Leaderboard 🏓🔥")
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
]
if is_arthur:
    tab_labels.append("⚙️ Manage Players")
 
tabs = st.tabs(tab_labels)
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = tabs[:8]
tab_admin = tabs[8] if is_arthur else None
 
# =========================
# TAB 1 — MATCHES
# =========================
with tab1:
    # ---- Add Match ----
    st.subheader("➕ Add Match")
 
    col1, col2 = st.columns(2)
 
    t1_p1_sel = col1.selectbox("Team 1 — Player 1",          [""] + players_list, key="t1p1")
    t1_p2_sel = col1.selectbox("Team 1 — Player 2 (optional)",[""] + players_list, key="t1p2")
    s1        = col1.number_input("Points Team 1", 0, 30, 11)
 
    t2_p1_sel = col2.selectbox("Team 2 — Player 1",          [""] + players_list, key="t2p1")
    t2_p2_sel = col2.selectbox("Team 2 — Player 2 (optional)",[""] + players_list, key="t2p2")
    s2        = col2.number_input("Points Team 2", 0, 30, 11)
 
    # No future dates allowed
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
            new_id = 1 if df.empty else int(df["wedstrijdId"].max()) + 1
            new = pd.DataFrame([{
                "wedstrijdId":    new_id,
                "created_by":     st.session_state.user,
                "Team1_player1":  t1_p1_val,
                "Team1_player2":  t1_p2_val or "",
                "Team2_player1":  t2_p1_val,
                "Team2_player2":  t2_p2_val or "",
                "team1_punten":   s1,
                "team2_punten":   s2,
                "datum":          str(date)
            }])
            df = pd.concat([df, new], ignore_index=True)
            save_data(df)
            st.success(f"✅ Match #{new_id} added successfully!")
            st.cache_data.clear()
            time.sleep(0.5)
            st.rerun()
 
    st.divider()
 
    # ---- All Matches ----
    st.subheader("📋 All Matches")
    st.dataframe(
        display_matches(df.sort_values("wedstrijdId", ascending=False)),
        use_container_width=True,
        hide_index=True
    )
 
    st.divider()
 
    # ---- Delete Match ----
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
            st.session_state.confirm_delete  = False
            st.session_state.last_delete_id  = del_id
 
        confirm = st.checkbox("I confirm I want to delete this match", key="confirm_delete")
 
        if st.button("Delete ❌"):
            if confirm:
                df = df[df["wedstrijdId"] != del_id]
                save_data(df)
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
 
        lb_display = (
            lb.sort_values("elo", ascending=False)
            [[
                "speler", "elo", "highest_elo",
                "matches", "wins", "win %",
                "biggest_win", "streak"
            ]]
            .rename(columns=LEADERBOARD_COL_RENAME)
        )
        st.dataframe(lb_display, hide_index=True, use_container_width=True)
    else:
        st.info("No data yet.")
 
# =========================
# TAB 3 — STATS
# =========================
with tab3:
    st.subheader("📊 Global Stats")
 
    if not current_df.empty:
        col1, col2, col3 = st.columns(3)
        col1.metric("Players",  len(current_df))
        col2.metric("Matches",  len(df))
        col3.metric("Avg ELO",  int(current_df["elo"].mean()))
 
        top_wins    = current_df.sort_values("wins",        ascending=False).iloc[0]
        top_elo     = current_df.sort_values("elo",         ascending=False).iloc[0]
        top_highest = current_df.sort_values("highest_elo", ascending=False).iloc[0]
        top_matches = current_df.sort_values("matches",     ascending=False).iloc[0]
 
        st.markdown(f"## 🏅 Most Wins: **{top_wins['speler']}** ({top_wins['wins']} wins)")
        st.markdown(f"## 🔥 Highest Current ELO: **{top_elo['speler']}** ({int(top_elo['elo'])})")
        st.markdown(f"## 👑 Highest Ever ELO:    **{top_highest['speler']}** ({int(top_highest['highest_elo'])})")
        st.markdown(f"## 🎯 Most Matches Played: **{top_matches['speler']}** ({top_matches['matches']} matches)")
 
        # Biggest score difference
        if not df.empty:
            df_copy = df.copy()
            df_copy["diff"] = (
                df_copy["team1_punten"].astype(float) - df_copy["team2_punten"].astype(float)
            ).abs()
            bm = df_copy.sort_values("diff", ascending=False).iloc[0]
            t1_str = " & ".join(filter(lambda x: x and x.lower() != "nan",
                                       [str(bm["Team1_player1"]), str(bm["Team1_player2"])]))
            t2_str = " & ".join(filter(lambda x: x and x.lower() != "nan",
                                       [str(bm["Team2_player1"]), str(bm["Team2_player2"])]))
            st.markdown(f"# 💥 Biggest Score Gap:  **{t1_str}** vs **{t2_str}** "
                     f"({int(bm['team1_punten'])}–{int(bm['team2_punten'])})")
 
        # Biggest upset (lowest pre-match win probability for the winner)
        if not df.empty:
            upset_data  = []
            elo_running = {}
            for _, r in df.sort_values("wedstrijdId").iterrows():
                t1_players = get_players(r, "Team1")
                t2_players = get_players(r, "Team2")
                if not t1_players or not t2_players:
                    continue
                try:
                    s1_r, s2_r = int(r["team1_punten"]), int(r["team2_punten"])
                except:
                    continue
 
                for p in t1_players + t2_players:
                    if p not in elo_running:
                        elo_running[p] = START_ELO
 
                e1_r = sum(elo_running[p] for p in t1_players) / len(t1_players)
                e2_r = sum(elo_running[p] for p in t2_players) / len(t2_players)
                prob_t1 = expected(e1_r, e2_r)
                t1_won  = s1_r > s2_r
 
                if t1_won and prob_t1 < 0.5:
                    upset_data.append({
                        "match_id": r["wedstrijdId"],
                        "winner":   " & ".join(t1_players),
                        "loser":    " & ".join(t2_players),
                        "win_prob": prob_t1,
                        "score":    f"{s1_r}–{s2_r}"
                    })
                elif not t1_won and prob_t1 > 0.5:
                    upset_data.append({
                        "match_id": r["wedstrijdId"],
                        "winner":   " & ".join(t2_players),
                        "loser":    " & ".join(t1_players),
                        "win_prob": 1 - prob_t1,
                        "score":    f"{s1_r}–{s2_r}"
                    })
 
                # Update running ELO
                res1_r = 1 if t1_won else 0
                diff_r = abs(s1_r - s2_r)
                mult_r = math.log(diff_r + 1)
                d1_r   = K * mult_r * (res1_r - expected(e1_r, e2_r))
                for p in t1_players:
                    elo_running[p] += d1_r
                for p in t2_players:
                    elo_running[p] -= d1_r
 
            if upset_data:
                bu = min(upset_data, key=lambda x: x["win_prob"])
                st.markdown(f"## 😱 Biggest Upset: **{bu['winner']}** beat **{bu['loser']}** "
                         f"with only **{bu['win_prob']*100:.1f}%** win chance "
                         f"(Match #{bu['match_id']}, {bu['score']})")
 
        st.subheader("📈 ELO progress per match")
        if not hist_df.empty:
            st.line_chart(hist_df.pivot_table(
                index="wedstrijdId", columns="speler", values="elo"))
 
        st.subheader("📅 ELO progress per date")
        if not hist_df.empty:
            latest = (hist_df.sort_values("wedstrijdId")
                      .groupby(["datum","speler"]).last().reset_index())
            st.line_chart(latest.pivot(index="datum", columns="speler", values="elo"))
    else:
        st.info("No data yet.")
 
# =========================
# TAB 4 — PLAYER
# =========================
with tab4:
    st.subheader("👤 Player Overview")
 
    if not current_df.empty:
        player      = st.selectbox("Select player", sorted(current_df["speler"].tolist()))
        p           = current_df[current_df["speler"] == player].iloc[0]
        player_hist = hist_df[hist_df["speler"] == player] if not hist_df.empty else pd.DataFrame()
        highest_elo = player_hist["elo"].max() if not player_hist.empty else p["elo"]
 
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Current ELO", int(p["elo"]))
        col2.metric("Highest ELO", int(highest_elo))
        col3.metric("Matches",     p["matches"])
        col4.metric("Win %",       f"{p['winrate']*100:.1f}%")
 
        st.subheader("🔥 Form (last 10 matches)")
        f = form_df[form_df["speler"] == player].tail(10) if not form_df.empty else pd.DataFrame()
        form_icons = "".join(["🟢" if x == 1 else "🔴" for x in f["result"]]) if not f.empty else "–"
        st.write(form_icons)
 
        # Current win streak
        player_results  = form_df[form_df["speler"] == player]["result"].tolist() if not form_df.empty else []
        current_streak  = 0
        for res in reversed(player_results):
            if res == 1:
                current_streak += 1
            else:
                break
        st.markdown(f"## 🔥 Current Win Streak: **{current_streak}**")
 
        # Head-to-head stats
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
            except:
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
 
        col1, col2 = st.columns(2)
        with col1:
            if opponents_count:
                mpa = max(opponents_count, key=opponents_count.get)
                st.markdown(f"## 🎯 Most played against: **{mpa}** ({opponents_count[mpa]}×)")
            if partners_count:
                mp = max(partners_count, key=partners_count.get)
                st.markdown(f"## 🤝 Favourite 2v2 partner: **{mp}** ({partners_count[mp]}×)")
        with col2:
            if beaten_count:
                mb = max(beaten_count, key=beaten_count.get)
                st.markdown(f"## 😤 Most beaten: **{mb}** ({beaten_count[mb]}×)")
            if lost_to_count:
                ml = max(lost_to_count, key=lost_to_count.get)
                st.markdown(f"## 😰 Lost to most: **{ml}** ({lost_to_count[ml]}×)")
 
        st.subheader("📈 ELO evolution per match")
        if not player_hist.empty:
            st.line_chart(player_hist.set_index("wedstrijdId")["elo"])
 
        st.subheader("📅 ELO evolution per date")
        if not player_hist.empty:
            latest = (player_hist.sort_values("wedstrijdId")
                      .groupby(["datum","speler"]).last().reset_index())
            st.line_chart(latest.pivot(index="datum", columns="speler", values="elo"))
    else:
        st.info("No data yet.")
 
# =========================
# TAB 5 — 1v1 MATCHMAKING
# =========================
with tab5:
    st.subheader("🧠 1v1 Matchmaking — Closest ELO Pairs")
 
    if not current_df.empty:
        sorted_players = current_df.sort_values("elo")
        suggestions    = []
 
        for i in range(len(sorted_players) - 1):
            low  = sorted_players.iloc[i]
            high = sorted_players.iloc[i + 1]
            suggestions.append({
                "Player 1": low["speler"],
                "Player 2": high["speler"],
                "ELO Gap":  int(high["elo"] - low["elo"])
            })
 
        st.dataframe(pd.DataFrame(suggestions), hide_index=True, use_container_width=True)
    else:
        st.info("No data yet.")
 
# =========================
# TAB 6 — 2v2 MATCHMAKING
# =========================
with tab6:
    st.subheader("👥 2v2 Matchmaking — Balanced Teams")
    st.write("Showing all combinations where Team 1 has a **40–60% win chance** (sorted by balance)")
 
    if not current_df.empty and len(current_df) >= 4:
        all_players = current_df["speler"].tolist()
        combos      = []
        seen        = set()
 
        for team1 in combinations(all_players, 2):
            remaining = [p for p in all_players if p not in team1]
            for team2 in combinations(remaining, 2):
                key = frozenset([frozenset(team1), frozenset(team2)])
                if key in seen:
                    continue
                seen.add(key)
 
                e1   = (get_elo(team1[0]) + get_elo(team1[1])) / 2
                e2   = (get_elo(team2[0]) + get_elo(team2[1])) / 2
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
            combos_df = pd.DataFrame(combos).sort_values("Team 1 Win %")
            st.dataframe(combos_df, hide_index=True, use_container_width=True)
        else:
            st.info("No balanced 2v2 combinations found with current ELO ratings.")
    else:
        st.info("Need at least 4 players with matches to suggest 2v2 matchups.")
 
# =========================
# TAB 7 — 1v1 WIN PROBABILITY
# =========================
with tab7:
    st.subheader("🎯 1v1 Win Probability")
 
    if not current_df.empty:
        players_sorted = sorted(current_df["speler"].tolist())
 
        col1, col2 = st.columns(2)
        a = col1.selectbox("Player A", players_sorted, key="wp1_a")
        b = col2.selectbox("Player B", players_sorted, key="wp1_b")
 
        prob = expected(get_elo(a), get_elo(b))
 
        col1.metric(f"🏓 {a}", f"{prob*100:.1f}%")
        col2.metric(f"🏓 {b}", f"{(1-prob)*100:.1f}%")
    else:
        st.info("No data yet.")
 
# =========================
# TAB 8 — 2v2 WIN PROBABILITY
# =========================
with tab8:
    st.subheader("🎯 2v2 Win Probability")
 
    if not current_df.empty:
        players_sorted = sorted(current_df["speler"].tolist())
 
        col1, col2 = st.columns(2)
        col1.markdown("**🟦 Team 1**")
        col2.markdown("**🟥 Team 2**")
 
        t1a = col1.selectbox("Team 1 — Player 1", players_sorted, key="2v2_t1a")
        t1b = col1.selectbox("Team 1 — Player 2", players_sorted, key="2v2_t1b")
        t2a = col2.selectbox("Team 2 — Player 1", players_sorted, key="2v2_t2a")
        t2b = col2.selectbox("Team 2 — Player 2", players_sorted, key="2v2_t2b")
 
        e1   = (get_elo(t1a) + get_elo(t1b)) / 2
        e2   = (get_elo(t2a) + get_elo(t2b)) / 2
        prob = expected(e1, e2)
 
        col1.metric(f"🟦 {t1a} & {t1b}", f"{prob*100:.1f}%")
        col2.metric(f"🟥 {t2a} & {t2b}", f"{(1-prob)*100:.1f}%")
    else:
        st.info("No data yet.")
 
# =========================
# ADMIN TAB — MANAGE PLAYERS (Arthur only)
# =========================
if is_arthur and tab_admin is not None:
    with tab_admin:
        st.subheader("⚙️ Player Management")
        st.info("Only visible to Arthur.")
 
        def load_users_ws():
            ws       = sheet.spreadsheet.worksheet("USERS")
            users_df = pd.DataFrame(ws.get_all_records())
            users_df["name"] = users_df["name"].astype(str).str.strip()
            users_df["pin"]  = users_df["pin"].astype(str).str.strip()
            return users_df, ws
 
        admin_users_df, users_ws = load_users_ws()
 
        st.write("**Current players:**")
        st.dataframe(admin_users_df[["name", "pin"]], use_container_width=True, hide_index=True) 
     
        st.divider()
        st.subheader("➕ Add New Player")
        new_name = st.text_input("Player Name",  key="admin_new_name")
        new_pin  = st.text_input("PIN",          key="admin_new_pin", type="password")
 
        if st.button("Add Player ✅"):
            if not new_name.strip() or not new_pin.strip():
                st.error("Name and PIN are required.")
            elif new_name.strip() in admin_users_df["name"].tolist():
                st.error(f"Player '{new_name}' already exists.")
            else:
                new_row        = pd.DataFrame([{"name": new_name.strip(), "pin": new_pin.strip()}])
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
        
        confirm_remove_player = st.checkbox(
            f"I confirm I want to permanently remove **{del_player}**",
            key="confirm_remove_player"
        )
        
        if st.button("Remove Player ❌"):
            if confirm_remove_player:
                admin_users_df = admin_users_df[admin_users_df["name"] != del_player]
                users_ws.clear()
                users_ws.update([admin_users_df.columns.tolist()] +
                                admin_users_df.astype(str).values.tolist())
                st.success(f"Player **{del_player}** removed.")
                st.rerun()
            else:
                st.error("Please confirm deletion first ⚠️")
