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
import numpy as np

# ---------------- FILE PATHS ----------------
USERS_FILE = "users.json"
PENDING_FILE = "pending_users.json"
SESSIONS_FILE = "active_visits.json"
MODEL_PATH = "best.pt"

SECRET_KEY = "secure_key_123"
SECURITY_CREDENTIALS = {"security": "1234"}
ADMIN_PASSWORD = "admin123"

# ---------------- HELPERS ----------------
def load_json(file_path):
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            return json.load(f)
    return {}

def save_json(file_path, data):
    with open(file_path, "w") as f:
        json.dump(data, f, indent=4)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def create_hash(visitor_id, expiry_time):
    """Generate secure auth token for visitor."""
    data = f"{visitor_id}{expiry_time}{SECRET_KEY}"
    return hashlib.sha256(data.encode()).hexdigest()[:10]

def parse_time_input(time_str):
    """Parse user input like '1h', '1 hour', '30 mins'."""
    time_str = time_str.lower().replace(" ", "")
    if "h" in time_str:
        hours = float(time_str.replace("hours", "").replace("hour", "").replace("h", ""))
        return timedelta(hours=hours)
    elif "m" in time_str:
        mins = float(time_str.replace("minutes", "").replace("minute", "").replace("mins", "").replace("min", "").replace("m", ""))
        return timedelta(minutes=mins)
    else:
        return timedelta(minutes=30)

def generate_qr(data):
    qr = qrcode.QRCode(version=1, box_size=8, border=4)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def verify_token(visitor_id, auth, sessions):
    """Ensure the visitor link is valid and not expired."""
    if visitor_id not in sessions:
        return False, "Invalid visitor ID"
    record = sessions[visitor_id]
    if record["auth"] != auth:
        return False, "Invalid token"
    expiry = datetime.fromisoformat(record["expiry"])
    if datetime.now() > expiry:
        return False, "QR code expired"
    return True, "Valid"

# ---------------- PAGES ----------------

def page_register():
    st.title("🏠 Homeowner Registration")

    pending = load_json(PENDING_FILE)
    users = load_json(USERS_FILE)

    email = st.text_input("Email (used as username)")
    phone = st.text_input("Phone Number")
    password = st.text_input("Password", type="password")
    confirm = st.text_input("Confirm Password", type="password")

    if st.button("Submit Registration Request"):
        if not email or not password or not phone:
            st.error("Please fill all fields.")
        elif password != confirm:
            st.error("Passwords do not match.")
        elif email in users:
            st.warning("This email is already approved.")
        elif email in pending:
            st.warning("This email is already awaiting admin approval.")
        else:
            pending[email] = {
                "phone": phone,
                "password": hash_password(password),
                "submitted_at": datetime.now().isoformat(),
            }
            save_json(PENDING_FILE, pending)
            st.success("✅ Registration request sent for admin approval.")
            st.info("Please wait until your account is approved.")
            st.session_state["show_login"] = True
            st.rerun()

def page_login():
    st.title("🔐 Homeowner Login")

    users = load_json(USERS_FILE)

    email = st.text_input("Email")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        if email not in users:
            st.error("Email not registered or not yet approved.")
        elif users[email]["password"] != hash_password(password):
            st.error("Incorrect password.")
        else:
            st.session_state["logged_in"] = True
            st.session_state["email"] = email
            st.success("✅ Login successful!")
            st.rerun()

    st.info("Don't have an account?")
    if st.button("Register Here"):
        st.session_state["show_login"] = False
        st.rerun()

def page_generator(public_url):
    if not st.session_state.get("logged_in"):
        st.warning("Please login first.")
        return

    st.title("🔑 Generate Visitor QR Code")

    visitor_name = st.text_input("Visitor Name")
    visit_duration = st.text_input("Visit Duration (e.g., 1h, 30 mins)", value="30 mins")

    if st.button("Generate QR"):
        delta = parse_time_input(visit_duration)
        expiry_time = datetime.now() + delta
        visitor_id = hashlib.sha1(visitor_name.encode()).hexdigest()[:8]
        auth_token = create_hash(visitor_id, expiry_time)

        sessions = load_json(SESSIONS_FILE)
        sessions[visitor_id] = {
            "auth": auth_token,
            "expiry": expiry_time.isoformat(),
            "visitor_name": visitor_name,
            "created_by": st.session_state["email"]
        }
        save_json(SESSIONS_FILE, sessions)

        qr_url = f"{public_url}?page=Visitor&id={visitor_id}&auth={auth_token}"
        qr_bytes = generate_qr(qr_url)
        st.image(qr_bytes, caption="Visitor QR Code")
        st.success(f"QR valid until {expiry_time.strftime('%Y-%m-%d %H:%M:%S')}")
        st.write("🔗 Visitor URL:", qr_url)

def page_visitor():
    st.title("🙋 Visitor Entry")
    query_params = st.query_params
    visitor_id = query_params.get("id", [None])[0]
    auth = query_params.get("auth", [None])[0]

    sessions = load_json(SESSIONS_FILE)
    valid, msg = verify_token(visitor_id, auth, sessions)
    if not valid:
        st.error(f"🚫 Access Denied: {msg}")
        st.stop()

    st.success(f"Welcome {sessions[visitor_id]['visitor_name']}! Upload your ID.")
    uploaded_id = st.file_uploader("Upload ID card", type=["jpg", "png", "jpeg"])

    if uploaded_id:
        st.info("🧠 Verifying ID using AI model...")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            tmp.write(uploaded_id.read())
            tmp_path = tmp.name

        model = YOLO(MODEL_PATH)
        results = model.predict(tmp_path)
        detected = any("id" in res.names.values() for res in results)

        if detected:
            st.success("✅ Valid ID detected. Access granted!")
            os.remove(tmp_path)
        else:
            st.error("❌ Invalid ID. Access denied.")
            os.remove(tmp_path)

def page_security_login():
    st.title("🛡 Security Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        if username in SECURITY_CREDENTIALS and SECURITY_CREDENTIALS[username] == password:
            st.session_state["security_logged_in"] = True
            st.success("✅ Login successful!")
            st.rerun()
        else:
            st.error("❌ Invalid credentials")

def page_security():
    if not st.session_state.get("security_logged_in"):
        st.warning("You must be logged in as Security.")
        return

    st.title("🧾 Security Dashboard")

    sessions = load_json(SESSIONS_FILE)
    if not sessions:
        st.info("No active visitor sessions.")
        return

    for vid, data in sessions.items():
        exp = datetime.fromisoformat(data["expiry"]).strftime("%H:%M:%S")
        st.write(f"**Visitor:** {data['visitor_name']} | **Expires:** {exp} | **Auth:** {data['auth']}")

def page_admin():
    st.title("👑 Admin Dashboard")

    password = st.text_input("Enter Admin Password", type="password")
    if password != ADMIN_PASSWORD:
        st.warning("Enter correct admin password.")
        return

    pending = load_json(PENDING_FILE)
    users = load_json(USERS_FILE)

    if not pending:
        st.info("No pending requests.")
        return

    for email, info in pending.items():
        st.write(f"📧 {email} | 📞 {info['phone']} | Submitted: {info['submitted_at']}")
        cols = st.columns(2)
        with cols[0]:
            if st.button(f"Approve {email}"):
                users[email] = {"phone": info["phone"], "password": info["password"]}
                save_json(USERS_FILE, users)
                del pending[email]
                save_json(PENDING_FILE, pending)
                st.success(f"✅ Approved {email}")
                st.rerun()
        with cols[1]:
            if st.button(f"Reject {email}"):
                del pending[email]
                save_json(PENDING_FILE, pending)
                st.warning(f"❌ Rejected {email}")
                st.rerun()

# ---------------- MAIN APP ----------------
def main(public_url):
    page = st.sidebar.radio(
        "Navigation",
        ["Login", "Register", "QR Generator", "Visitor", "Security Login", "Security", "Admin"]
    )

    if page == "Login":
        page_login()
    elif page == "Register":
        page_register()
    elif page == "QR Generator":
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
    public_url = "https://app-qrcode-kbtgae6rj8r2qrdxprggcm.streamlit.app/"
    main(public_url)
