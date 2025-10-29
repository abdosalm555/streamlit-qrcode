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
import re

# =====================
# LOAD AI MODEL
# =====================
MODEL_PATH = "best.pt"
try:
    model = YOLO(MODEL_PATH)
except Exception as e:
    model = None
    st.warning(f"⚠️ Model not loaded: {e}")

# =====================
# FILE PATHS
# =====================
DATA_FILE = "credentials.json"
PENDING_FILE = "pending_requests.json"

# =====================
# HELPER FUNCTIONS
# =====================
def load_data(file):
    if os.path.exists(file):
        with open(file, "r") as f:
            return json.load(f)
    return {}

def save_data(file, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=4)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def authenticate(username, password):
    users = load_data(DATA_FILE)
    if username in users and users[username]["password"] == hash_password(password):
        return True, users[username]["role"]
    return False, None

def convert_time_to_minutes(time_str):
    time_str = time_str.lower().strip()
    try:
        # match patterns like "1 h", "1 hr", "2 hours", "30 mins"
        if "hour" in time_str or "hr" in time_str or "h" in time_str:
            hours = re.findall(r"\d+", time_str)
            return int(hours[0]) * 60 if hours else 60
        elif "min" in time_str or "m" in time_str:
            mins = re.findall(r"\d+", time_str)
            return int(mins[0]) if mins else 30
        else:
            return int(time_str)
    except:
        return 30  # default 30 minutes

# =====================
# QR CODE GENERATOR
# =====================
def generate_qr(data):
    qr = qrcode.make(data)
    buffer = BytesIO()
    qr.save(buffer, format="PNG")
    return buffer.getvalue()

# =====================
# AI VALIDATION FUNCTION
# =====================
def is_valid_id(image_bytes):
    if model is None:
        st.error("AI model not loaded.")
        return False

    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as temp_file:
        temp_file.write(image_bytes)
        temp_path = temp_file.name

    results = model(temp_path)
    for r in results:
        if len(r.boxes) > 0:
            conf = float(r.boxes.conf.max().item())
            if conf >= 0.7:
                return True
    return False

# =====================
# STREAMLIT APP
# =====================
st.set_page_config(page_title="QR Access System", layout="centered")

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "role" not in st.session_state:
    st.session_state.role = None
if "username" not in st.session_state:
    st.session_state.username = None
if "countdown" not in st.session_state:
    st.session_state.countdown = None

# =====================
# PAGES
# =====================
def page_register():
    st.title("🏠 Homeowner Registration")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Submit Registration Request"):
        requests = load_data(PENDING_FILE)
        requests[username] = {"password": hash_password(password)}
        save_data(PENDING_FILE, requests)
        st.success("✅ Registration request submitted for admin approval.")

def page_login():
    st.title("🔐 Login Page")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        success, role = authenticate(username, password)
        if success:
            st.session_state.logged_in = True
            st.session_state.role = role
            st.session_state.username = username
            st.experimental_rerun()
        else:
            st.error("❌ Invalid credentials or unapproved account.")

def page_admin():
    st.title("👨‍💼 Admin Dashboard")
    pending = load_data(PENDING_FILE)
    users = load_data(DATA_FILE)

    if pending:
        st.subheader("Pending Approvals")
        for username, info in pending.items():
            col1, col2 = st.columns([2, 1])
            col1.write(f"**{username}**")
            if col2.button("✅ Approve", key=username):
                users[username] = {"password": info["password"], "role": "homeowner"}
                del pending[username]
                save_data(DATA_FILE, users)
                save_data(PENDING_FILE, pending)
                st.success(f"{username} approved!")
                st.experimental_rerun()
    else:
        st.info("No pending registration requests.")

def page_generator():
    st.title("🏠 Homeowner QR Generator")

    visitor_name = st.text_input("Visitor Name")
    visit_time = st.text_input("Visit Duration (e.g. '1 hour', '30 mins', '2h')", "30 mins")

    if st.button("Generate QR Code"):
        minutes = convert_time_to_minutes(visit_time)
        expire_time = datetime.now() + timedelta(minutes=minutes)

        qr_payload = {
            "visitor": visitor_name,
            "expire_at": expire_time.isoformat()
        }
        qr_data = json.dumps(qr_payload)
        qr_img = generate_qr(qr_data)

        st.image(qr_img, caption="Visitor QR Code")
        qr_url = f"{st.get_option('server.baseUrlPath')}?page=visitor"
        st.write(f"Share this visitor page: {qr_url}")

def page_security():
    st.title("🛡️ Security Checkpoint")
    st.info("Scan visitor QR code below.")
    uploaded_file = st.file_uploader("Upload QR Code Image", type=["png", "jpg", "jpeg"])

    if uploaded_file:
        image = np.array(bytearray(uploaded_file.read()), dtype=np.uint8)
        image = cv2.imdecode(image, cv2.IMREAD_COLOR)

        try:
            import pyzbar.pyzbar as pyzbar
            decoded = pyzbar.decode(image)
            if decoded:
                qr_data = json.loads(decoded[0].data.decode("utf-8"))
                expire_time = datetime.fromisoformat(qr_data["expire_at"])
                if datetime.now() < expire_time:
                    st.success(f"✅ Access granted to {qr_data['visitor']}")
                    st.session_state.countdown = (expire_time - datetime.now()).seconds
                else:
                    st.error("❌ QR code expired.")
            else:
                st.error("No QR code detected.")
        except Exception as e:
            st.error(f"Error decoding QR: {e}")

def page_visitor():
    st.title("🎫 Visitor Verification")

    uploaded_id = st.file_uploader("Upload your ID for verification", type=["jpg", "jpeg", "png"])
    if uploaded_id:
        st.image(uploaded_id, caption="Uploaded ID")
        with st.spinner("🔍 Verifying ID..."):
            if is_valid_id(uploaded_id.read()):
                st.success("✅ ID Verified Successfully!")
                st.info("Wait for the security to scan your QR code for entry.")
            else:
                st.error("❌ Invalid ID. Please upload a valid ID image.")

# =====================
# NAVIGATION
# =====================
if not st.session_state.logged_in:
    menu = st.sidebar.radio("Menu", ["Login", "Register", "Visitor"])
    if menu == "Login":
        page_login()
    elif menu == "Register":
        page_register()
    else:
        page_visitor()
else:
    if st.session_state.role == "admin":
        page_admin()
    elif st.session_state.role == "homeowner":
        page_generator()
    elif st.session_state.role == "security":
        page_security()

    st.sidebar.button("Logout", on_click=lambda: st.session_state.update({"logged_in": False, "role": None}))
