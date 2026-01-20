import streamlit as st
import sqlite3
import os
import json
from datetime import datetime
import time

# ================= CONFIG =================
STUDENT_PASSWORD = "AIE_ELECTIONS"
ADMIN_PASSWORD = "admin@aie"

CATEGORIES = [
    "Hostler Boy",
    "Dayscholar Boy",
    "Hostler Girl",
    "Dayscholar Girl"
]

DB_PATH = "database/election.db"


# ================= DATABASE UTIL =================
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # Create tables with proper schema
    cur.execute("""
    CREATE TABLE IF NOT EXISTS students (
        student_id TEXT PRIMARY KEY,
        has_voted INTEGER DEFAULT 0,
        vote_timestamp TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(name, category)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT,
        category TEXT NOT NULL,
        candidate TEXT NOT NULL,
        voted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS control (
        id INTEGER PRIMARY KEY,
        published INTEGER DEFAULT 0,
        published_at TEXT,
        publish_admin TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS admin_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_user TEXT,
        action TEXT,
        details TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Initialize control table if empty
    cur.execute("SELECT COUNT(*) FROM control")
    if cur.fetchone()[0] == 0:
        cur.execute("INSERT INTO control (id, published) VALUES (1, 0)")

    conn.commit()
    conn.close()


os.makedirs("database", exist_ok=True)
init_db()


# ================= LOGGING =================
def log_admin_action(action, details=""):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO admin_logs (admin_user, action, details)
        VALUES (?, ?, ?)
    """, ("Admin", action, json.dumps(details)))
    conn.commit()
    conn.close()


# ================= FUNCTIONS =================
def valid_student_id(sid):
    sid = sid.strip().upper()
    return sid.startswith("AIE24") and sid[-3:].isdigit() and 201 <= int(sid[-3:]) <= 261


def add_candidate(name, category):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO candidates (name, category) VALUES (?, ?)",
                    (name.strip(), category))
        conn.commit()
        log_admin_action("ADD_CANDIDATE", {"name": name, "category": category})
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def delete_candidate(name, category):
    conn = get_conn()
    cur = conn.cursor()
    try:
        # Check if candidate has received votes
        cur.execute("SELECT COUNT(*) FROM votes WHERE candidate = ? AND category = ?", (name, category))
        vote_count = cur.fetchone()[0]

        if vote_count > 0:
            conn.close()
            return False, f"Cannot delete '{name}' from {category} as they have received {vote_count} vote(s)."

        # Delete the candidate
        cur.execute("DELETE FROM candidates WHERE name = ? AND category = ?", (name, category))
        affected_rows = cur.rowcount

        if affected_rows > 0:
            conn.commit()
            log_admin_action("DELETE_CANDIDATE", {"name": name, "category": category})
            return True, f"Candidate '{name}' deleted from {category}."
        else:
            return False, "Candidate not found."
    except Exception as e:
        return False, f"Error deleting candidate: {str(e)}"
    finally:
        conn.close()


def get_candidates(category):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT name FROM candidates WHERE category=? ORDER BY name", (category,))
    data = [r[0] for r in cur.fetchall()]
    conn.close()
    return data


def get_all_candidates():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, category, name, added_at 
        FROM candidates 
        ORDER BY category, name
    """)
    data = cur.fetchall()
    conn.close()
    return data


def get_candidate_vote_counts():
    """Get vote counts for each candidate"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT candidate, category, COUNT(*) as vote_count
        FROM votes
        GROUP BY candidate, category
    """)
    data = {f"{row[1]}|{row[0]}": row[2] for row in cur.fetchall()}
    conn.close()
    return data


def submit_votes(sid, selections):
    conn = get_conn()
    cur = conn.cursor()
    timestamp = datetime.now().isoformat()

    # First check if student has already voted
    cur.execute("SELECT has_voted FROM students WHERE student_id=?", (sid,))
    row = cur.fetchone()

    if row and row[0] == 1:
        conn.close()
        return False, "You have already voted!"

    try:
        # Insert votes
        for cat, cand in selections.items():
            cur.execute("""
                INSERT INTO votes (student_id, category, candidate, voted_at)
                VALUES (?, ?, ?, ?)
            """, (sid, cat, cand, timestamp))

        # Mark student as voted
        cur.execute("""
            INSERT OR REPLACE INTO students (student_id, has_voted, vote_timestamp)
            VALUES (?, 1, ?)
        """, (sid, timestamp))

        conn.commit()
        return True, "Vote submitted successfully!"
    except Exception as e:
        conn.rollback()
        return False, f"Error submitting vote: {str(e)}"
    finally:
        conn.close()


def already_voted(sid):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT has_voted FROM students WHERE student_id=?", (sid,))
    row = cur.fetchone()
    conn.close()
    return row and row[0] == 1


def get_voting_stats():
    conn = get_conn()
    cur = conn.cursor()

    # Total eligible students (assuming 60 students from 201-261)
    total_eligible = 60

    # Students who have voted
    cur.execute("SELECT COUNT(*) FROM students WHERE has_voted = 1")
    voted = cur.fetchone()[0]

    # Votes per category
    cur.execute("SELECT category, COUNT(*) FROM votes GROUP BY category")
    category_counts = dict(cur.fetchall())

    conn.close()

    return {
        "total_eligible": total_eligible,
        "voted": voted,
        "pending": total_eligible - voted,
        "turnout_percentage": (voted / total_eligible * 100) if total_eligible > 0 else 0,
        "category_counts": category_counts
    }


def get_vote_counts():  # Renamed from vote_counts to avoid conflict
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT category, candidate, COUNT(*) as votes
        FROM votes
        GROUP BY category, candidate
        ORDER BY category, votes DESC
    """)
    data = cur.fetchall()
    conn.close()
    return data


def publish_results(admin_user="Admin"):
    conn = get_conn()
    cur = conn.cursor()
    publish_time = datetime.now().isoformat()

    # Ensure there's a row in control table
    cur.execute("SELECT COUNT(*) FROM control WHERE id = 1")
    if cur.fetchone()[0] == 0:
        cur.execute("INSERT INTO control (id, published) VALUES (1, 0)")

    cur.execute("""
        UPDATE control 
        SET published = 1, published_at = ?, publish_admin = ?
        WHERE id = 1
    """, (publish_time, admin_user))

    conn.commit()
    conn.close()

    log_admin_action("PUBLISH_RESULTS", {"timestamp": publish_time})
    return True


def results_published():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT published FROM control WHERE id = 1")
    row = cur.fetchone()
    conn.close()
    return row and row[0] == 1


def get_publish_status():
    """Get detailed publish status"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT published, published_at, publish_admin FROM control WHERE id = 1")
    row = cur.fetchone()
    conn.close()
    if row:
        return {
            "published": row[0] == 1,
            "published_at": row[1],
            "publish_admin": row[2]
        }
    return {"published": False, "published_at": None, "publish_admin": None}


def winners():
    conn = get_conn()
    cur = conn.cursor()
    result = {}
    winner_votes = {}  # Renamed from vote_counts to avoid conflict

    for cat in CATEGORIES:
        cur.execute("""
            SELECT candidate, COUNT(*) as votes 
            FROM votes 
            WHERE category = ?
            GROUP BY candidate 
            ORDER BY votes DESC
        """, (cat,))

        candidates = cur.fetchall()
        if candidates:
            max_votes = candidates[0][1]
            # Check for ties
            winners_list = [cand[0] for cand in candidates if cand[1] == max_votes]
            result[cat] = winners_list
            winner_votes[cat] = max_votes

    conn.close()
    return result, winner_votes  # Changed variable name here


def reset_election():
    """DANGER: Completely resets the election - only for admin"""
    conn = get_conn()
    cur = conn.cursor()

    # Clear all data except admin logs
    cur.execute("DELETE FROM votes")
    cur.execute("DELETE FROM students")
    cur.execute("DELETE FROM candidates")
    cur.execute("UPDATE control SET published = 0, published_at = NULL, publish_admin = NULL WHERE id = 1")

    conn.commit()
    conn.close()

    log_admin_action("RESET_ELECTION", {"timestamp": datetime.now().isoformat()})


# ================= UI =================
st.set_page_config(
    page_title="AIE Elections",
    page_icon="🗳️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .stApp {
        max-width: 1200px;
        margin: 0 auto;
    }
    .voting-card {
        padding: 20px;
        border-radius: 10px;
        background-color: #f0f2f6;
        margin: 10px 0;
        border-left: 5px solid #4CAF50;
    }
    .winner-card {
        padding: 25px;
        border-radius: 15px;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        text-align: center;
        margin: 15px 0;
        animation: pulse 2s infinite;
    }
    @keyframes pulse {
        0% { transform: scale(1); }
        50% { transform: scale(1.02); }
        100% { transform: scale(1); }
    }
    .confetti {
        position: fixed;
        width: 10px;
        height: 10px;
        animation: confetti-fall 3s linear infinite;
        z-index: 1000;
    }
    .stats-card {
        background: white;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        margin: 10px 0;
    }
    .vote-review {
        background-color: #e8f5e9;
        padding: 15px;
        border-radius: 10px;
        border-left: 5px solid #4caf50;
        margin: 10px 0;
    }
    .delete-warning {
        background-color: #ffebee;
        padding: 15px;
        border-radius: 10px;
        border-left: 5px solid #f44336;
        margin: 10px 0;
    }
</style>
""", unsafe_allow_html=True)

st.title("🗳️ AIE Class Elections 2024")

# ================= SESSION STATE =================
if 'voting_complete' not in st.session_state:
    st.session_state.voting_complete = False
if 'admin_authenticated' not in st.session_state:
    st.session_state.admin_authenticated = False
if 'verified' not in st.session_state:
    st.session_state.verified = False
if 'student_id' not in st.session_state:
    st.session_state.student_id = ""
if 'reviewing_votes' not in st.session_state:
    st.session_state.reviewing_votes = False
if 'selections' not in st.session_state:
    st.session_state.selections = {}
if 'show_publish_confirmation' not in st.session_state:
    st.session_state.show_publish_confirmation = False
if 'show_reset' not in st.session_state:
    st.session_state.show_reset = False


# ================= STUDENT VOTING =================
def render_voting_page():
    if st.session_state.voting_complete:
        # Show only thank you message - no sidebar, no menu
        st.markdown("""
        <div style='text-align: center; padding: 100px 20px;'>
            <h1 style='color: #4CAF50; font-size: 60px;'>✅</h1>
            <h2>Thank You for Voting!</h2>
            <p style='font-size: 18px;'>Your vote has been successfully submitted.</p>
            <p style='color: #666; font-size: 0.9em;'>Election results will be announced soon.</p>
        </div>
        """, unsafe_allow_html=True)

        # Add celebratory emojis
        cols = st.columns(5)
        celebratory_emojis = ["🎉", "✨", "⭐", "🏆", "👏"]
        for col, emoji in zip(cols, celebratory_emojis):
            col.markdown(f"<h2 style='text-align: center;'>{emoji}</h2>", unsafe_allow_html=True)

        st.stop()

    # Show voting interface
    st.subheader("Student Voting Portal")

    # If not verified, show login form
    if not st.session_state.get('verified', False):
        with st.form("login_form"):
            col1, col2 = st.columns(2)

            with col1:
                sid = st.text_input("Student ID", placeholder="AIE24XXX", key="login_sid")
            with col2:
                pwd = st.text_input("Password", type="password", key="login_pwd")

            submitted = st.form_submit_button("Verify & Proceed", use_container_width=True)

            if submitted:
                if not sid or not pwd:
                    st.error("Please enter both Student ID and Password")
                    st.stop()

                if pwd != STUDENT_PASSWORD:
                    st.error("Invalid password")
                    st.stop()

                if not valid_student_id(sid):
                    st.error("Invalid Student ID format. Expected: AIE24201 to AIE24261")
                    st.stop()

                if already_voted(sid):
                    st.error("❌ You have already voted. Each student can vote only once.")
                    st.stop()

                st.session_state.student_id = sid
                st.session_state.verified = True
                st.rerun()
    else:
        # Show voting form if verified
        st.markdown("---")
        st.subheader(f"🗳️ Cast Your Votes - {st.session_state.student_id}")
        st.info("Please select one candidate for each category. All fields are required.")

        # Check if reviewing votes
        if st.session_state.get('reviewing_votes', False):
            st.markdown("### Review Your Votes")
            st.markdown('<div class="vote-review">', unsafe_allow_html=True)
            for cat, cand in st.session_state.selections.items():
                st.write(f"**{cat}:** {cand}")
            st.markdown('</div>', unsafe_allow_html=True)

            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ Confirm & Submit", type="primary", use_container_width=True):
                    success, message = submit_votes(st.session_state.student_id, st.session_state.selections)
                    if success:
                        st.session_state.voting_complete = True
                        st.success(message)
                        time.sleep(2)
                        st.rerun()
                    else:
                        st.error(message)
            with col2:
                if st.button("✏️ Edit Votes", use_container_width=True):
                    st.session_state.reviewing_votes = False
                    st.rerun()
        else:
            # Main voting form
            all_selected = True
            selections = {}

            for cat in CATEGORIES:
                candidates = get_candidates(cat)
                if not candidates:
                    st.error(f"No candidates available for {cat}")
                    st.warning(f"Please contact admin to add candidates for {cat}")
                    all_selected = False
                    continue

                options = ["-- Select Candidate --"] + candidates
                choice = st.selectbox(
                    f"**{cat}**",
                    options,
                    key=f"vote_{cat}",
                    help=f"Select your preferred candidate for {cat}"
                )

                if choice == "-- Select Candidate --":
                    all_selected = False
                else:
                    selections[cat] = choice

            st.session_state.selections = selections

            if all_selected and len(selections) == len(CATEGORIES):
                col1, col2, col3 = st.columns([1, 2, 1])
                with col2:
                    if st.button("📋 Review & Submit", type="primary", use_container_width=True):
                        st.session_state.reviewing_votes = True
                        st.rerun()
            else:
                st.warning("⚠️ Please select a candidate for all categories before submitting.")

            # Back to login button
            if st.button("← Back to Login"):
                st.session_state.verified = False
                st.session_state.student_id = ""
                st.rerun()


# ================= ADMIN PANEL =================
def render_admin_panel():
    if not st.session_state.admin_authenticated:
        st.subheader("🔐 Admin Login")
        ap = st.text_input("Admin Password", type="password", key="admin_pw")

        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            if st.button("Login", type="primary", use_container_width=True):
                if ap == ADMIN_PASSWORD:
                    st.session_state.admin_authenticated = True
                    st.rerun()
                else:
                    st.error("Invalid admin password")
        st.stop()

    # Admin is authenticated
    st.sidebar.markdown("### 🔧 Admin Controls")

    admin_menu = st.sidebar.selectbox(
        "Navigation",
        ["Dashboard", "Manage Candidates", "View Votes", "Publish Results", "Admin Logs", "Reset Election"]
    )

    st.subheader("👨‍💼 Admin Panel")

    if admin_menu == "Dashboard":
        st.markdown("### 📊 Election Dashboard")

        stats = get_voting_stats()

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Eligible", stats["total_eligible"])
        with col2:
            st.metric("Votes Cast", stats["voted"])
        with col3:
            st.metric("Pending", stats["pending"])
        with col4:
            st.metric("Turnout", f"{stats['turnout_percentage']:.1f}%")

        # Voting progress
        progress_value = stats['voted'] / stats['total_eligible'] if stats['total_eligible'] > 0 else 0
        st.progress(progress_value)
        st.caption(f"Voting Progress: {stats['voted']}/{stats['total_eligible']} students")

        # Votes by category
        st.markdown("### Votes by Category")
        for cat in CATEGORIES:
            count = stats['category_counts'].get(cat, 0)
            st.write(f"**{cat}:** {count} votes")

    elif admin_menu == "Manage Candidates":
        st.markdown("### 👥 Manage Candidates")

        tab1, tab2, tab3 = st.tabs(["Add Candidate", "View Candidates", "Delete Candidate"])

        with tab1:
            st.markdown("#### Add New Candidate")
            col1, col2 = st.columns(2)

            with col1:
                cat = st.selectbox("Category", CATEGORIES, key="add_cat")
            with col2:
                name = st.text_input("Candidate Full Name", key="candidate_name")

            if st.button("Add Candidate", type="primary", key="add_candidate_btn"):
                if not name.strip():
                    st.warning("Please enter candidate name")
                else:
                    if add_candidate(name.strip(), cat):
                        st.success(f"✅ Candidate '{name}' added to {cat}")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(f"❌ Candidate '{name}' already exists in {cat}")

        with tab2:
            st.markdown("#### Current Candidates")
            try:
                candidates = get_all_candidates()

                if not candidates:
                    st.info("No candidates added yet")
                else:
                    vote_counts_data = get_candidate_vote_counts()
                    for cat in CATEGORIES:
                        cat_candidates = [c for c in candidates if c[1] == cat]
                        if cat_candidates:
                            st.markdown(f"**{cat}**")
                            for cand in cat_candidates:
                                cand_id, cand_cat, cand_name, added_time = cand
                                vote_key = f"{cand_cat}|{cand_name}"
                                vote_count = vote_counts_data.get(vote_key, 0)

                                if added_time:
                                    try:
                                        dt = datetime.fromisoformat(added_time)
                                        formatted_time = dt.strftime("%Y-%m-%d %H:%M")
                                    except:
                                        formatted_time = added_time[:16]
                                else:
                                    formatted_time = "Unknown"

                                st.markdown(f"- **{cand_name}** (Votes: {vote_count}, Added: {formatted_time})")
                            st.markdown("---")
            except Exception as e:
                st.error(f"Error loading candidates: {str(e)}")

        with tab3:
            st.markdown("#### Delete Candidate")
            st.warning("⚠️ You can only delete candidates who have received 0 votes.")

            # Get all candidates for deletion
            candidates = get_all_candidates()
            vote_counts_data = get_candidate_vote_counts()

            if not candidates:
                st.info("No candidates to delete")
            else:
                # Create a list of candidates with their categories
                candidate_options = []
                for cand in candidates:
                    cand_id, cand_cat, cand_name, _ = cand
                    vote_key = f"{cand_cat}|{cand_name}"
                    vote_count = vote_counts_data.get(vote_key, 0)
                    display_text = f"{cand_name} ({cand_cat}) - {vote_count} vote(s)"
                    candidate_options.append((display_text, cand_name, cand_cat, vote_count))

                if candidate_options:
                    # Create dropdown with candidate info
                    selected_option = st.selectbox(
                        "Select candidate to delete:",
                        options=[opt[0] for opt in candidate_options],
                        key="delete_candidate_select"
                    )

                    # Find the selected candidate
                    selected_candidate = None
                    for opt in candidate_options:
                        if opt[0] == selected_option:
                            selected_candidate = opt
                            break

                    if selected_candidate:
                        display_text, cand_name, cand_cat, vote_count = selected_candidate

                        st.markdown(f"**Selected:** {cand_name} from {cand_cat}")
                        st.markdown(f"**Current Votes:** {vote_count}")

                        if vote_count > 0:
                            st.error(f"❌ Cannot delete {cand_name} as they have {vote_count} vote(s).")
                        else:
                            if st.button("🗑️ Delete Candidate", type="secondary", key="delete_btn"):
                                success, message = delete_candidate(cand_name, cand_cat)
                                if success:
                                    st.success(message)
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error(message)
                else:
                    st.info("No candidates available for deletion")

    elif admin_menu == "View Votes":
        st.markdown("### 📈 Vote Counts")

        publish_status = get_publish_status()
        if publish_status["published"]:
            st.success(f"✅ Results published by {publish_status['publish_admin']} at {publish_status['published_at']}")
        else:
            st.info("Results are not published yet - only admin can see vote counts")

        counts = get_vote_counts()  # Changed function call

        if not counts:
            st.info("No votes cast yet")
        else:
            # Display counts without candidate names (as requested)
            for cat in CATEGORIES:
                cat_counts = [c for c in counts if c[0] == cat]
                if cat_counts:
                    st.markdown(f"**{cat}**")
                    total_cat_votes = sum(c[2] for c in cat_counts)
                    st.write(f"Total votes in this category: **{total_cat_votes}**")

                    # Show counts without names
                    for i, (_, candidate, count) in enumerate(cat_counts, 1):
                        percentage = (count / total_cat_votes * 100) if total_cat_votes > 0 else 0
                        st.write(f"Candidate #{i}: {count} votes ({percentage:.1f}%)")
                        st.progress(percentage / 100)

                    st.markdown("---")

    elif admin_menu == "Publish Results":
        st.markdown("### 🏆 Publish Election Results")

        publish_status = get_publish_status()

        if publish_status["published"]:
            st.success(f"✅ Results have already been published!")
            st.info(f"**Published by:** {publish_status['publish_admin']}")
            st.info(f"**Published at:** {publish_status['published_at']}")

            # Show winners with celebration
            st.balloons()

            winners_data, winner_votes_data = winners()  # Changed variable name

            st.markdown("## 🎉 ELECTION RESULTS 🎉")

            if not winners_data:
                st.info("No votes cast yet - no winners to display")
            else:
                for cat, win_list in winners_data.items():
                    votes = winner_votes_data.get(cat, 0)  # Changed variable name
                    if len(win_list) == 1:
                        st.markdown(f"""
                        <div class='winner-card'>
                            <h2>🏆 {cat} Winner 🏆</h2>
                            <h1>{win_list[0]}</h1>
                            <p>with {votes} votes</p>
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        # Handle tie
                        winners_str = ", ".join(win_list)
                        st.markdown(f"""
                        <div class='winner-card'>
                            <h2>🏆 {cat} Winners (Tie) 🏆</h2>
                            <h3>{winners_str}</h3>
                            <p>each with {votes} votes</p>
                        </div>
                        """, unsafe_allow_html=True)

            # Add sound notification (browser-based)
            st.markdown("""
            <audio autoplay>
                <source src="https://assets.mixkit.co/sfx/preview/mixkit-winning-chimes-2015.mp3" type="audio/mpeg">
            </audio>
            """, unsafe_allow_html=True)

        else:
            st.warning("⚠️ Results are not published yet")

            # Check if there are votes to publish
            counts = get_vote_counts()  # Changed function call
            if not counts:
                st.error("❌ Cannot publish results - no votes have been cast yet!")
                st.info("Wait for students to vote before publishing results.")
            else:
                # Preview winners without publishing
                winners_data, winner_votes_data = winners()  # Changed variable name

                if winners_data:
                    st.markdown("#### Preview of Winners (Will be shown after publishing)")
                    for cat, win_list in winners_data.items():
                        votes = winner_votes_data.get(cat, 0)  # Changed variable name
                        if win_list:
                            st.info(f"**{cat}:** {', '.join(win_list)} - {votes} votes")

                # Publish button with confirmation
                st.markdown("---")
                st.markdown("### Publish Results Now")

                with st.expander("⚠️ Important Information Before Publishing"):
                    st.markdown("""
                    **Once you publish results:**
                    1. Results will be visible to everyone
                    2. Students will see winners on their screens
                    3. This action cannot be undone
                    4. Voting will still be allowed unless you disable it

                    **Ensure:**
                    - All votes have been counted
                    - You have verified the results
                    - You are ready to announce winners
                    """)

                # Multi-step confirmation
                if st.button("🚀 PUBLISH RESULTS NOW", type="primary", use_container_width=True, key="publish_main"):
                    st.session_state.show_publish_confirmation = True

                if st.session_state.get('show_publish_confirmation', False):
                    st.markdown('<div class="delete-warning">', unsafe_allow_html=True)
                    st.markdown("### ❗ FINAL CONFIRMATION REQUIRED ❗")

                    confirm1 = st.checkbox("I confirm that all votes have been counted correctly", key="confirm1")
                    confirm2 = st.checkbox("I understand this action cannot be undone", key="confirm2")
                    confirm3 = st.checkbox("I am authorized to publish election results", key="confirm3")

                    if confirm1 and confirm2 and confirm3:
                        if st.button("✅ CONFIRM AND PUBLISH", type="primary", key="confirm_publish"):
                            try:
                                if publish_results():
                                    st.success("✅ Results published successfully!")
                                    st.balloons()
                                    time.sleep(2)
                                    st.rerun()
                                else:
                                    st.error("Failed to publish results")
                            except Exception as e:
                                st.error(f"Error publishing results: {str(e)}")
                    else:
                        st.info("Please check all confirmation boxes to proceed")
                    st.markdown('</div>', unsafe_allow_html=True)

                    if st.button("Cancel", key="cancel_publish"):
                        st.session_state.show_publish_confirmation = False
                        st.rerun()

    elif admin_menu == "Admin Logs":
        st.markdown("### 📋 Admin Activity Log")

        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM admin_logs ORDER BY timestamp DESC LIMIT 100")
        logs = cur.fetchall()
        conn.close()

        if not logs:
            st.info("No admin activity logged yet")
        else:
            for log in logs:
                with st.expander(f"{log[4]} - {log[2]}"):
                    st.write(f"**Admin:** {log[1]}")
                    st.write(f"**Action:** {log[2]}")
                    if log[3]:
                        try:
                            details = json.loads(log[3])
                            st.write("**Details:**")
                            st.json(details)
                        except:
                            st.write(f"**Details:** {log[3]}")

    elif admin_menu == "Reset Election":
        st.markdown("### ⚠️ DANGER ZONE")
        st.error("This will delete ALL election data! Use with extreme caution.")

        with st.expander("⚠️ Read before proceeding"):
            st.write("""
            This action will:
            1. Delete ALL votes
            2. Delete ALL candidate information
            3. Delete ALL student voting records
            4. Reset published status

            This cannot be undone!
            """)

        if st.button("🚨 SHOW RESET OPTIONS", type="secondary", key="show_reset"):
            st.session_state.show_reset = True

        if st.session_state.get('show_reset', False):
            st.markdown('<div class="delete-warning">', unsafe_allow_html=True)
            st.warning("Are you absolutely sure you want to reset the election?")

            confirm1 = st.checkbox("I understand all votes will be deleted", key="reset_confirm1")
            confirm2 = st.checkbox("I understand all candidate data will be deleted", key="reset_confirm2")
            confirm3 = st.checkbox("I understand student voting records will be deleted", key="reset_confirm3")

            if confirm1 and confirm2 and confirm3:
                if st.button("CONFIRM COMPLETE ELECTION RESET", type="primary", key="confirm_reset"):
                    reset_election()
                    st.success("✅ Election has been reset")
                    st.session_state.show_reset = False
                    time.sleep(2)
                    st.session_state.admin_authenticated = False
                    st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

            if st.button("Cancel Reset", key="cancel_reset"):
                st.session_state.show_reset = False
                st.rerun()

    # Logout button in sidebar
    if st.sidebar.button("🚪 Logout Admin"):
        st.session_state.admin_authenticated = False
        st.rerun()


# ================= MAIN APP FLOW =================
# Sidebar menu - only show if not in voting complete state
if not st.session_state.get('voting_complete', False):
    menu = st.sidebar.selectbox(
        "Navigation",
        ["Student Voting", "Admin Panel"],
        key="main_menu"
    )

    if menu == "Student Voting":
        render_voting_page()
    elif menu == "Admin Panel":
        render_admin_panel()
else:
    # Voting complete - show only thank you page
    render_voting_page()

# ================= FOOTER =================
st.markdown("---")
st.markdown(
    """
    <div style='text-align: center; color: #666; font-size: 0.8em; padding: 20px;'>
        AIE Class Elections 2024 • Secure Voting System • Each Vote Matters
    </div>
    """,
    unsafe_allow_html=True
)

# Database troubleshooting in sidebar (only for admin)
if st.sidebar.button("🔄 Debug Database", key="debug_db"):
    conn = get_conn()
    cur = conn.cursor()

    # Show table info
    st.sidebar.write("### Database Tables")
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cur.fetchall()
    for table in tables:
        st.sidebar.write(f"- {table[0]}")

    # Show control table status
    st.sidebar.write("### Control Table Status")
    try:
        cur.execute("SELECT * FROM control")
        control_data = cur.fetchall()
        st.sidebar.write(control_data)
    except:
        st.sidebar.write("Error reading control table")

    conn.close()