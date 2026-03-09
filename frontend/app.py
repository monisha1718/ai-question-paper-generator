"""
Streamlit Chat Interface for the AI Question Paper Generation System.

Run with:  streamlit run frontend/app.py
"""

import io
import requests
import streamlit as st

# ── Configuration ───────────────────────────────────────────────────────

API_BASE = "http://127.0.0.1:8001/api"

# ── Page config ─────────────────────────────────────────────────────────

st.set_page_config(page_title="Question Paper AI", page_icon="📝", layout="wide")


# ── Session state defaults ──────────────────────────────────────────────

def _init_state():
    defaults = {
        "token": None,
        "user": None,
        "messages": [],
        "step": "greet",        # chatbot flow state
        "subject": None,
        "unit_or_topic": None,
        "exam_type": None,
        "marks_distribution": None,
        "last_paper": None,     # last generated paper text
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init_state()


# ── Helper: API call with auth ──────────────────────────────────────────

def _headers():
    return {"Authorization": f"Bearer {st.session_state.token}"}


def _api_get(path, params=None):
    return requests.get(f"{API_BASE}{path}", headers=_headers(), params=params)


def _api_post(path, **kwargs):
    return requests.post(f"{API_BASE}{path}", headers=_headers(), **kwargs)


# ── Helper: add a message to chat ──────────────────────────────────────

def _bot(msg):
    st.session_state.messages.append({"role": "assistant", "content": msg})


def _user_msg(msg):
    st.session_state.messages.append({"role": "user", "content": msg})


# ── Login / Register sidebar ───────────────────────────────────────────

def _login_ui():
    st.sidebar.title("Faculty Login")
    tab_login, tab_register = st.sidebar.tabs(["Login", "Register"])

    with tab_login:
        username = st.text_input("Username", key="login_user")
        password = st.text_input("Password", type="password", key="login_pass")
        if st.button("Login", key="btn_login"):
            resp = requests.post(f"{API_BASE}/login", json={"username": username, "password": password})
            if resp.status_code == 200:
                data = resp.json()
                st.session_state.token = data["access_token"]
                st.session_state.user = data["user"]
                st.session_state.messages = []
                st.session_state.step = "greet"
                st.rerun()
            else:
                st.error("Invalid credentials. Please try again.")

    with tab_register:
        reg_name = st.text_input("Full Name", key="reg_name")
        reg_user = st.text_input("Username", key="reg_user")
        reg_pass = st.text_input("Password", type="password", key="reg_pass")
        reg_dept = st.text_input("Department", key="reg_dept")
        reg_subj = st.text_input("Assigned Subject", key="reg_subj")
        reg_role = st.selectbox("Role", ["HOD", "Professor", "Associate Professor", "Assistant Professor"], key="reg_role")
        if st.button("Register", key="btn_register"):
            resp = requests.post(f"{API_BASE}/register", json={
                "username": reg_user,
                "password": reg_pass,
                "name": reg_name,
                "department": reg_dept,
                "assigned_subject": reg_subj,
                "role": reg_role,
            })
            if resp.status_code == 201:
                st.success("Registration successful! You can now log in.")
            else:
                st.error(resp.json().get("detail", "Registration failed."))


# ── Main chat area ──────────────────────────────────────────────────────

def _display_chat():
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])


def _handle_chatbot_flow(user_input: str):
    """
    State-machine driven chatbot flow:
      greet → ask_subject → ask_unit → ask_exam_type → ask_marks →
      ask_upload → confirm → generate → done
    """
    step = st.session_state.step
    user = st.session_state.user

    # ─── Regenerate shortcut (works in any state after first generation) ──
    if "regenerate" in user_input.lower() and st.session_state.last_paper:
        _bot("Regenerating your question paper with different questions...")
        resp = _api_post("/generate", params={
            "subject": st.session_state.subject,
            "unit_or_topic": st.session_state.unit_or_topic,
            "exam_type": st.session_state.exam_type,
            "marks_distribution": st.session_state.marks_distribution or "",
            "regenerate": True,
        })
        if resp.status_code == 200:
            paper = resp.json()["question_paper"]
            st.session_state.last_paper = paper
            _bot(paper)
            _bot("You can type **'Regenerate question paper'** to get a new set, "
                 "or use the download buttons in the sidebar.")
        else:
            _bot(f"Error: {resp.json().get('detail', 'Generation failed.')}")
        return

    # ─── Normal flow ─────────────────────────────────────────────────────
    if step == "greet":
        _bot(f"Hello, {user['name']}! Welcome to the AI Question Paper Generator.\n\n"
             f"Your role: **{user['role']}** | Department: **{user['department']}**\n\n"
             f"Let's create a question paper. Please tell me the **Subject Name**.")
        st.session_state.step = "ask_subject"

    elif step == "ask_subject":
        # HOD can choose any subject; others are locked to their assignment
        if user["role"] != "HOD":
            allowed = user["assigned_subject"]
            if user_input.strip().lower() != allowed.lower():
                _bot(f"You are assigned to **{allowed}**. I'll use that subject.")
                st.session_state.subject = allowed
            else:
                st.session_state.subject = user_input.strip()
        else:
            st.session_state.subject = user_input.strip()
        _bot(f"Subject set to **{st.session_state.subject}**.\n\n"
             "Now, please enter the **Unit or Topic** you want the questions from.")
        st.session_state.step = "ask_unit"

    elif step == "ask_unit":
        st.session_state.unit_or_topic = user_input.strip()
        _bot(f"Unit/Topic: **{st.session_state.unit_or_topic}**.\n\n"
             "What is the **Exam Type**? (Internal / Semester)")
        st.session_state.step = "ask_exam_type"

    elif step == "ask_exam_type":
        exam = user_input.strip()
        if exam.lower() not in ("internal", "semester"):
            _bot("Please type **Internal** or **Semester**.")
            return
        st.session_state.exam_type = exam.title()
        _bot(f"Exam Type: **{st.session_state.exam_type}**.\n\n"
             "Any specific **marks distribution** instructions? "
             "(Type 'no' to use the default: Part A-2 marks, Part B-5 marks, Part C-10 marks)")
        st.session_state.step = "ask_marks"

    elif step == "ask_marks":
        if user_input.strip().lower() in ("no", "none", "default", "n/a"):
            st.session_state.marks_distribution = None
        else:
            st.session_state.marks_distribution = user_input.strip()
        _bot("Great! Now please **upload your PDF study material** using the uploader in the sidebar.\n\n"
             "If you have already uploaded material for this subject, type **'skip'** to proceed directly.")
        st.session_state.step = "ask_upload"

    elif step == "ask_upload":
        if user_input.strip().lower() in ("skip", "done"):
            _bot("Proceeding with uploaded material.\n\n"
                 "Ready to generate the question paper? Type **'yes'** to proceed.")
            st.session_state.step = "confirm"
        else:
            _bot("Please use the **PDF uploader** in the sidebar to upload your file, "
                 "then type **'done'** when finished, or **'skip'** if material is already uploaded.")

    elif step == "confirm":
        if user_input.strip().lower() in ("yes", "y", "ok", "proceed", "generate"):
            _bot("Generating your question paper... This may take a moment.")
            resp = _api_post("/generate", params={
                "subject": st.session_state.subject,
                "unit_or_topic": st.session_state.unit_or_topic,
                "exam_type": st.session_state.exam_type,
                "marks_distribution": st.session_state.marks_distribution or "",
                "regenerate": False,
            })
            if resp.status_code == 200:
                paper = resp.json()["question_paper"]
                st.session_state.last_paper = paper
                _bot(paper)
                _bot("Question paper generated!\n\n"
                     "- Type **'Regenerate question paper'** to get a new version.\n"
                     "- Use the **Download** buttons in the sidebar to save as PDF or DOCX.\n"
                     "- Type **'new'** to start a fresh question paper.")
                st.session_state.step = "done"
            else:
                detail = resp.json().get("detail", "Generation failed.")
                _bot(f"Error: {detail}")
        else:
            _bot("Type **'yes'** to generate the question paper, or update details above.")

    elif step == "done":
        if user_input.strip().lower() in ("new", "restart", "start over"):
            st.session_state.step = "greet"
            st.session_state.last_paper = None
            _bot("Starting fresh! Let's create a new question paper.\n\n"
                 "Please tell me the **Subject Name**.")
            st.session_state.step = "ask_subject"
        else:
            # Pass-through to RAG chat for general queries
            resp = _api_post("/chat", json={"message": user_input})
            if resp.status_code == 200:
                _bot(resp.json()["reply"])
            else:
                _bot("Sorry, I couldn't process that. Try again or type **'new'** to start over.")


# ── Sidebar actions (upload / download) ─────────────────────────────────

def _sidebar_actions():
    st.sidebar.markdown("---")
    user = st.session_state.user
    st.sidebar.markdown(f"**Logged in as:** {user['name']}")
    st.sidebar.markdown(f"**Role:** {user['role']}")
    st.sidebar.markdown(f"**Subject:** {user['assigned_subject']}")

    if st.sidebar.button("Logout"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.subheader("Upload PDF Material")
    upload_subject = st.sidebar.text_input(
        "Subject for upload",
        value=user["assigned_subject"] if user["role"] != "HOD" else "",
        key="upload_subject",
    )
    uploaded_file = st.sidebar.file_uploader("Choose a PDF", type=["pdf"], key="pdf_uploader")
    if st.sidebar.button("Upload & Process", key="btn_upload"):
        if uploaded_file and upload_subject:
            files = {"file": (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")}
            resp = _api_post(f"/upload-pdf?subject={upload_subject}", files=files)
            if resp.status_code == 200:
                data = resp.json()
                st.sidebar.success(f"Uploaded! {data['chunks_created']} chunks created.")
                _bot(f"PDF '{uploaded_file.name}' processed successfully for subject "
                     f"'{upload_subject}'. {data['chunks_created']} chunks created.\n\n"
                     "You can now type **'done'** to proceed.")
                if st.session_state.step == "ask_upload":
                    st.session_state.step = "confirm"
                    _bot("Ready to generate the question paper? Type **'yes'** to proceed.")
            else:
                st.sidebar.error(resp.json().get("detail", "Upload failed."))
        else:
            st.sidebar.warning("Please provide both subject name and PDF file.")

    # Download buttons
    if st.session_state.last_paper:
        st.sidebar.markdown("---")
        st.sidebar.subheader("Download Question Paper")

        col1, col2 = st.sidebar.columns(2)
        with col1:
            if st.button("Download PDF", key="dl_pdf"):
                resp = _api_post("/download/pdf", json={
                    "paper_text": st.session_state.last_paper,
                    "subject": st.session_state.subject or "General",
                    "unit_or_topic": st.session_state.unit_or_topic or "General",
                    "exam_type": st.session_state.exam_type or "Semester",
                })
                if resp.status_code == 200:
                    st.sidebar.download_button(
                        label="Save PDF",
                        data=resp.content,
                        file_name=f"question_paper_{st.session_state.subject}.pdf",
                        mime="application/pdf",
                        key="save_pdf",
                    )
                else:
                    st.sidebar.error("PDF generation failed.")

        with col2:
            if st.button("Download DOCX", key="dl_docx"):
                resp = _api_post("/download/docx", json={
                    "paper_text": st.session_state.last_paper,
                    "subject": st.session_state.subject or "General",
                    "unit_or_topic": st.session_state.unit_or_topic or "General",
                    "exam_type": st.session_state.exam_type or "Semester",
                })
                if resp.status_code == 200:
                    st.sidebar.download_button(
                        label="Save DOCX",
                        data=resp.content,
                        file_name=f"question_paper_{st.session_state.subject}.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key="save_docx",
                    )
                else:
                    st.sidebar.error("DOCX generation failed.")


# ── Main ────────────────────────────────────────────────────────────────

def main():
    st.title("AI Question Paper Generator")

    if not st.session_state.token:
        _login_ui()
        st.info("Please log in using the sidebar to get started.")
        st.markdown("""
        ### Default Credentials (for testing)
        | Username | Password | Role |
        |----------|----------|------|
        | `hod` | `hod123` | HOD |
        | `prof1` | `prof123` | Professor |
        | `assoc1` | `assoc123` | Associate Professor |
        | `asst1` | `asst123` | Assistant Professor |
        """)
        return

    _sidebar_actions()

    # Auto-greet on first load
    if st.session_state.step == "greet" and not st.session_state.messages:
        _handle_chatbot_flow("")

    _display_chat()

    # Chat input
    user_input = st.chat_input("Type your message...")
    if user_input:
        _user_msg(user_input)
        with st.chat_message("user"):
            st.markdown(user_input)
        _handle_chatbot_flow(user_input)
        st.rerun()


if __name__ == "__main__":
    main()
