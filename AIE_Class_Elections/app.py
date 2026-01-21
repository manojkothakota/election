import streamlit as st
import sqlite3
import os
import json
from datetime import datetime
import time

# ================= CONFIG =================
STUDENT_PASSWORD = "AIE"
ADMIN_PASSWORD = "9182356716"

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


def reset_database():
    """DANGER: Completely resets the election database - only for admin"""
    conn = get_conn()
    cur = conn.cursor()
    
    # Clear all election data but keep admin logs for audit trail
    cur.execute("DELETE FROM votes")
    cur.execute("DELETE FROM students")
    cur.execute("DELETE FROM candidates")
    cur.execute("UPDATE control SET published = 0, published_at = NULL, publish_admin = NULL WHERE id = 1")
    
    # Reset autoincrement counters (optional but good for clean state)
    cur.execute("DELETE FROM sqlite_sequence WHERE name IN ('votes', 'students', 'candidates')")
    
    conn.commit()
    conn.close()
    
    log_admin_action("RESET_DATABASE", {"timestamp": datetime.now().isoformat()})
    return True


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
    .reset-section {
        background-color: #fff3e0;
        padding: 20px;
        border-radius: 10px;
        border: 2px solid #ff9800;
        margin: 20px 0;
    }
</style>
""", unsafe_allow_html=True)

st.title("🗳️ AIE Class Elections 2026")

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
if 'show_reset_database' not in st.session_state:
    st.session_state.show_reset_database = False


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
    # ---------------- ADMIN LOGIN ----------------
    if not st.session_state.admin_authenticated:
        st.subheader("🔐 Admin Login")
        ap = st.text_input("Admin Password", type="password")

        if st.button("Login"):
            if ap == ADMIN_PASSWORD:
                st.session_state.admin_authenticated = True
                st.rerun()
            else:
                st.error("Invalid admin password")
        return

    # ---------------- ADMIN MENU ----------------
    st.sidebar.markdown("### 🔧 Admin Controls")
    admin_menu = st.sidebar.selectbox(
        "Admin Menu",
        [
            "Dashboard",
            "Add Candidates",
            "View Candidates",
            "Vote Counts",
            "Publish Results",
            "Reset Election",
            "Reset Database",  # NEW OPTION ADDED HERE
        ],
    )

    st.subheader("👨‍💼 Admin Panel")

    # ---------------- DASHBOARD ----------------
    if admin_menu == "Dashboard":
        stats = get_voting_stats()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Eligible", stats["total_eligible"]+1)
        c2.metric("Voted", stats["voted"])
        c3.metric("Pending", stats["pending"])
        c4.metric("Turnout", f"{stats['turnout_percentage']:.1f}%")

        progress = (
            stats["voted"] / stats["total_eligible"]
            if stats["total_eligible"] > 0
            else 0
        )
        st.progress(progress)

    # ---------------- ADD CANDIDATES ----------------
    elif admin_menu == "Add Candidates":
        st.subheader("➕ Add Candidate")

        cat = st.selectbox("Category", CATEGORIES)
        name = st.text_input("Candidate Name")

        if st.button("Add"):
            if not name.strip():
                st.warning("Name cannot be empty")
            elif add_candidate(name.strip(), cat):
                st.success("Candidate added successfully")
                st.rerun()
            else:
                st.error("Candidate already exists in this category")

    # ---------------- VIEW CANDIDATES ----------------
    elif admin_menu == "View Candidates":
        st.subheader("📋 Candidates List")
        candidates = get_all_candidates()

        if not candidates:
            st.info("No candidates added yet")
        else:
            vote_map = get_candidate_vote_counts()
            for cat in CATEGORIES:
                st.markdown(f"### {cat}")
                for _, ccat, cname, _ in candidates:
                    if ccat == cat:
                        count = vote_map.get(f"{ccat}|{cname}", 0)
                        st.write(f"- {cname} (Votes: {count})")

    # ---------------- VOTE COUNTS (NO NAMES) ----------------
    elif admin_menu == "Vote Counts":
        st.subheader("📊 Vote Counts (Anonymous)")

        counts = get_vote_counts()
        if not counts:
            st.info("No votes cast yet")
        else:
            for cat in CATEGORIES:
                st.markdown(f"### {cat}")
                cat_votes = [c for c in counts if c[0] == cat]
                total = sum(c[2] for c in cat_votes)

                st.write(f"Total votes: {total}")
                for i, (_, _, v) in enumerate(cat_votes, 1):
                    percent = (v / total * 100) if total else 0
                    st.write(f"Candidate {i}: {v} votes ({percent:.1f}%)")
                    st.progress(percent / 100)

    # ---------------- PUBLISH RESULTS ----------------
    elif admin_menu == "Publish Results":
        if not results_published():
            if st.button("📢 Publish Results"):
                publish_results()
                st.success("Results published successfully")
                st.balloons()
                st.rerun()

        if results_published():
            st.subheader("🏆 Winners")
            winners_data, winner_votes = winners()

            if not winners_data:
                st.info("No winners yet")
            else:
                for cat, names in winners_data.items():
                    if len(names) == 1:
                        st.markdown(f'<div class="winner-card"><h3>{cat}</h3><h2>🏆 {names[0]} 🏆</h2><p>Votes: {winner_votes[cat]}</p></div>', unsafe_allow_html=True)
                    else:
                        st.warning(f"{cat} Tie: {', '.join(names)}")

    # ---------------- RESET ELECTION ----------------
    elif admin_menu == "Reset Election":
        st.error("⚠️ Reset Election - This will delete ALL election data but keep the database structure")
        
        st.markdown('<div class="reset-section">', unsafe_allow_html=True)
        st.markdown("### What will be deleted:")
        st.markdown("- ✅ All student votes")
        st.markdown("- ✅ All candidate records")
        st.markdown("- ✅ All student voting records")
        st.markdown("- ✅ Election published status")
        
        st.markdown("### What will be kept:")
        st.markdown("- ✅ Database structure")
        st.markdown("- ✅ Admin logs (for audit trail)")
        st.markdown("</div>", unsafe_allow_html=True)
        
        confirm1 = st.checkbox("I understand this will delete ALL voting data")
        confirm2 = st.checkbox("I confirm I want to reset the election")
        
        if confirm1 and confirm2:
            if st.button("🗑️ RESET ELECTION", type="primary"):
                reset_election()
                st.success("✅ Election has been reset successfully!")
                st.info("You can now add new candidates and start fresh voting.")
                st.balloons()
                time.sleep(2)
                st.rerun()

    # ---------------- RESET DATABASE ----------------
    elif admin_menu == "Reset Database":  # NEW SECTION ADDED
        st.markdown("""
        <div style='background-color: #ffebee; padding: 20px; border-radius: 10px; border: 3px solid #f44336; margin: 20px 0;'>
            <h2 style='color: #d32f2f;'>⚠️ DANGER ZONE - COMPLETE DATABASE RESET</h2>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown('<div class="reset-section">', unsafe_allow_html=True)
        st.markdown("### ⚠️ WARNING: This action is EXTREMELY DESTRUCTIVE!")
        
        st.markdown("### What will happen:")
        st.markdown("1. ❌ **ALL election data will be deleted**")
        st.markdown("2. ❌ All candidate names will be removed")
        st.markdown("3. ❌ All student votes will be erased")
        st.markdown("4. ❌ All student voting records will be cleared")
        st.markdown("5. ❌ Election results will be unpublished")
        st.markdown("6. ✅ Database structure will remain intact")
        st.markdown("7. ✅ Admin logs will be kept for audit trail")
        
        st.markdown("### When to use this:")
        st.markdown("- For a completely fresh start")
        st.markdown("- If you want to change ALL candidate names")
        st.markdown("- After election is complete and you want to prepare for next election")
        st.markdown("</div>", unsafe_allow_html=True)
        
        # Add extra confirmation steps
        st.markdown("---")
        st.markdown("### 🔐 Confirmation Steps")
        
        col1, col2 = st.columns(2)
        with col1:
            confirm_reset = st.checkbox("I understand this will delete ALL data")
            confirm_irreversible = st.checkbox("I understand this action is irreversible")
        with col2:
            confirm_admin = st.checkbox("I am an authorized administrator")
            confirm_backup = st.checkbox("I have backed up any important data")
        
        # Final confirmation with password
        if confirm_reset and confirm_irreversible and confirm_admin and confirm_backup:
            st.markdown("### 🚨 Final Confirmation")
            reset_password = st.text_input("Enter admin password to proceed:", type="password")
            
            if st.button("🔥 NUKE DATABASE & START FRESH", type="primary"):
                if reset_password == ADMIN_PASSWORD:
                    try:
                        reset_database()
                        st.success("✅ Database reset completed successfully!")
                        st.balloons()
                        st.info("The database is now completely empty. You can add new candidates and start fresh.")
                        time.sleep(3)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error resetting database: {str(e)}")
                else:
                    st.error("❌ Incorrect password. Database reset aborted.")
        else:
            st.warning("Please check all confirmation boxes to proceed.")

    # ---------------- LOGOUT ----------------
    st.sidebar.markdown("---")
    if st.sidebar.button("🚪 Logout Admin"):
        st.session_state.admin_authenticated = False
        st.rerun()


# ================= MAIN APP =================
def main():
    # Sidebar navigation
    st.sidebar.title("Navigation")
    app_mode = st.sidebar.radio(
        "Select Mode",
        ["Student Voting", "Admin Panel"]
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown("### ℹ️ About")
    st.sidebar.info(
        "AIE Class Elections 2024\n\n"
        "• Each student votes once\n"
        "• 4 categories\n"
        "• Admin manages candidates\n"
        "• Results published by admin"
    )

    # Render based on mode
    if app_mode == "Student Voting":
        render_voting_page()
    elif app_mode == "Admin Panel":
        render_admin_panel()


if __name__ == "__main__":
    main()


