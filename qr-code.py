import streamlit as st
import qrcode
import json
import os
import hashlib
from datetime import datetime, timedelta
from io import BytesIO
import base64
from ultralytics import YOLO
import tempfile
import cv2
import numpy as np

# ---------------- SECURITY AND AUTH ----------------

SECURITY_CREDENTIALS = {"security": "1234"}
ADMIN_PASSWORD = "admin123"
SESSION_FILE = "active_visits.json"
SECRET_KEY = "secure_key_123"

# ---------------- HELPER FUNCTIONS ----------------

def load_sessions():
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, "r") as f:
            return json.load(f)
    return {}

def save_sessions(data):
    with open(SESSION_FILE, "w") as f:
        json.dump(data, f, indent=4)

def create_hash(visitor_id, expiry_time):
    """Generate a secure hash token."""
    data = f"{visitor_id}{expiry_time}{SECRET_KEY}"
    return hashlib.sha256(data.encode()).hexdigest()[:10]

def parse_time_input(time_str):
    """Parse strings like '1h', '30 mins', '2 hours' into timedelta."""
    time_str = time_str.lower().replace(" ", "")
    if "h" in time_str:
        hours = float(time_str.replace("hours", "").replace("hour", "").replace("h", ""))
        return timedelta(hours=hours)
    elif "m" in time_str:
        mins = float(time_str.replace("minutes", "").replace("minute", "").replace("mins", "").replace("min", "").replace("m", ""))
        return timedelta(minutes=mins)
    else:
        return timedelta(minutes=30)  # default 30 min

def verify_token(visitor_id, auth, sessions):
    """Validate visitor token."""
    if visitor_id not in sessions:
        return False, "Invalid visitor ID"
    record = sessions[visitor_id]
    if record["auth"] != auth:
        return False, "Invalid token"
    expiry = datetime.fromisoformat(record["expiry"])
    if datetime.now() > expiry:
        return False, "QR code expired"
    return True, "Valid"

# ---------------- PAGE FUNCTIONS ----------------

def page_login():
    st.title("🏠 Homeowner Login")
    if "homeowner_logged_in" not in st.session_state:
        st.session_state.homeowner_logged_in = False

    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        if username == "homeowner" and password == "1234":
            st.session_state.homeowner_logged_in = True
            st.success("✅ Login successful!")
        else:
            st.error("Invalid credentials")

def page_generator(public_url):
    if not st.session_state.get("homeowner_logged_in"):
        st.warning("Please log in first.")
        return

    st.title("🔑 Generate Visitor QR Code")

    visitor_name = st.text_input("Visitor Name")
    visit_duration = st.text_input("Visit Duration (e.g., '1h', '30 mins')", value="30 mins")

    if st.button("Generate QR Code"):
        delta = parse_time_input(visit_duration)
        expiry_time = datetime.now() + delta
        visitor_id = hashlib.sha1(visitor_name.encode()).hexdigest()[:8]
        auth_token = create_hash(visitor_id, expiry_time)

        # Save session
        sessions = load_sessions()
        sessions[visitor_id] = {
            "auth": auth_token,
            "expiry": expiry_time.isoformat(),
            "visitor_name": visitor_name
        }
        save_sessions(sessions)

        # Generate visitor URL
        qr_url = f"{public_url}?page=visitor&id={visitor_id}&auth={auth_token}"
        qr = qrcode.make(qr_url)
        buf = BytesIO()
        qr.save(buf, format="PNG")
        qr_b64 = base64.b64encode(buf.getvalue()).decode()

        st.image(f"data:image/png;base64,{qr_b64}", caption="Visitor QR Code", use_column_width=True)
        st.write("🔗 Visitor Link:", qr_url)
        st.success(f"QR code valid until: {expiry_time.strftime('%Y-%m-%d %H:%M:%S')}")

def page_visitor():
    st.title("🙋 Visitor Entry")
    query_params = st.query_params
    visitor_id = query_params.get("id", [None])[0]
    auth = query_params.get("auth", [None])[0]

    sessions = load_sessions()
    valid, msg = verify_token(visitor_id, auth, sessions)
    if not valid:
        st.error(f"🚫 Access Denied: {msg}")
        st.stop()

    st.success(f"Welcome {sessions[visitor_id]['visitor_name']}! Please upload your ID to continue.")
    uploaded_id = st.file_uploader("Upload your ID card", type=["jpg", "png", "jpeg"])

    if uploaded_id:
        # Placeholder for AI model detection
        st.info("Checking ID validity using AI model...")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as temp_file:
            temp_file.write(uploaded_id.read())
            temp_path = temp_file.name

        # Example AI model call (replace this with your actual model)
        model = YOLO("best.pt")
        results = model.predict(temp_path)
        detected = any("id" in res.names.values() for res in results)

        if detected:
            st.success("✅ Valid ID detected!")
            st.balloons()
        else:
            st.error("❌ Invalid ID. Access denied.")
            st.stop()

def page_security():
    if "security_logged_in" not in st.session_state or not st.session_state["security_logged_in"]:
        st.warning("🚫 You must be logged in as Security to access this page.")
        st.stop()

    st.title("🛡️ Security Control Panel")
    st.info("Scan visitor QR code or monitor countdowns here.")
    st.write("Authorized Security Access Granted ✅")

def page_security_login():
    st.title("🔐 Security Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        if username in SECURITY_CREDENTIALS and SECURITY_CREDENTIALS[username] == password:
            st.session_state["security_logged_in"] = True
            st.success("✅ Login successful!")
            st.switch_page("Security")
        else:
            st.error("❌ Invalid credentials")

def page_admin():
    st.title("👑 Admin Dashboard")
    password = st.text_input("Enter Admin Password", type="password")
    if password != ADMIN_PASSWORD:
        st.warning("🔒 Enter correct password to view pending accounts.")
        return

    st.success("✅ Admin Access Granted")
    st.write("### Active Visit Sessions")
    sessions = load_sessions()
    if not sessions:
        st.info("No active sessions.")
    else:
        for vid, info in sessions.items():
            exp_time = datetime.fromisoformat(info["expiry"]).strftime("%Y-%m-%d %H:%M:%S")
            st.markdown(f"**Visitor:** {info['visitor_name']} | **Expires:** {exp_time} | **Auth:** `{info['auth']}`")

# ---------------- MAIN APP ----------------

def main(public_url):
    st.sidebar.title("Navigation")
    page = st.sidebar.radio("Go to", ["Login", "Generator", "Visitor", "Security Login", "Security", "Admin"])

    if page == "Login":
        page_login()
    elif page == "Generator":
        page_generator(public_url)
    elif page == "Visitor":
        page_visitor()
    elif page == "Security Login":
        page_security_login()
    elif page == "Security":
        page_security()
    elif page == "Admin":
        page_admin()

if __name__ == "__main__":
    # Public URL for your Streamlit Cloud deployment
    public_url = "https://app-qrcode-kbtgae6rj8r2qrdxprggcm.streamlit.app/"
    main(public_url)
