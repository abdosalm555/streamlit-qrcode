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

# -------------------- FILES --------------------
DATA_FILE = "data.json"
PENDING_FILE = "pending_users.json"

# Load YOLO model for ID verification
model = YOLO("best.pt")

# -------------------- FUNCTIONS --------------------
def load_data(file):
    if not os.path.exists(file):
        return {}
    with open(file, "r") as f:
        return json.load(f)

def save_data(data, file):
    with open(file, "w") as f:
        json.dump(data, f, indent=4)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def verify_id(image_file, confidence_threshold=0.7):
    """Verify if uploaded ID image is valid using YOLO model."""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            tmp.write(image_file.read())
            tmp_path = tmp.name

        results = model.predict(tmp_path, conf=0.25, verbose=False)

        # Check if any detection has confidence >= threshold
        for result in results:
            for box in result.boxes:
                if box.conf[0] >= confidence_threshold:
                    return True
        return False
    except Exception as e:
        print("Error verifying ID:", e)
        return False

def generate_qr(data):
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf)
    return buf.getvalue()

def parse_time_input(time_str):
    time_str = time_str.lower().strip()
    if "hour" in time_str or "hr" in time_str or "h" in time_str:
        num = [int(s) for s in time_str.split() if s.isdigit()]
        return timedelta(hours=num[0] if num else 1)
    elif "min" in time_str:
        num = [int(s) for s in time_str.split() if s.isdigit()]
        return timedelta(minutes=num[0] if num else 30)
    else:
        return timedelta(minutes=30)

# -------------------- PAGES --------------------
def page_register():
    st.title("🏠 Register as Homeowner")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Register"):
        if username and password:
            pending = load_data(PENDING_FILE)
            if username in pending:
                st.warning("This username is already pending approval.")
            else:
                pending[username] = hash_password(password)
                save_data(pending, PENDING_FILE)
                st.success("✅ Registration request sent! Wait for admin approval.")
        else:
            st.error("Please fill all fields.")

def page_admin():
    st.title("👩‍💼 Admin Approval Page")
    pending = load_data(PENDING_FILE)
    approved = load_data(DATA_FILE)

    if not pending:
        st.info("No pending registration requests.")
        return

    st.subheader("Pending Accounts:")
    for user, pwd in pending.items():
        col1, col2 = st.columns([3, 1])
        col1.write(f"👤 **{user}**")
        if col2.button("Approve", key=user):
            approved[user] = pwd
            save_data(approved, DATA_FILE)
            del pending[user]
            save_data(pending, PENDING_FILE)
            st.success(f"✅ {user} approved!")

def page_login():
    st.title("🔐 Homeowner Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        data = load_data(DATA_FILE)
        if username in data and data[username] == hash_password(password):
            st.session_state["logged_in"] = True
            st.session_state["username"] = username
            st.success("✅ Login successful!")
        else:
            st.error("❌ Invalid username or password.")

def page_homeowner():
    st.title("🏡 Generate Visitor QR Code")

    if "logged_in" not in st.session_state or not st.session_state["logged_in"]:
        st.warning("Please log in first.")
        return

    visitor_name = st.text_input("Visitor Name")
    duration_input = st.text_input("Access Duration (e.g. '1 hour', '30 mins')")
    generate_btn = st.button("Generate QR")

    if generate_btn and visitor_name:
        duration = parse_time_input(duration_input)
        expiry = datetime.now() + duration

        payload = {
            "visitor": visitor_name,
            "expires_at": expiry.strftime("%Y-%m-%d %H:%M:%S")
        }

        qr_data = json.dumps(payload)
        qr_img = generate_qr(qr_data)

        st.image(qr_img, caption=f"QR for {visitor_name}", use_column_width=False)
        st.success(f"QR valid until {expiry.strftime('%H:%M:%S')}")

def page_visitor():
    st.title("🎫 Visitor Verification")

    uploaded_file = st.file_uploader("Upload your ID card", type=["jpg", "jpeg", "png"])
    if uploaded_file is not None:
        st.image(uploaded_file, caption="Uploaded ID", use_column_width=True)

        with st.spinner("Verifying ID..."):
            valid_id = verify_id(uploaded_file, confidence_threshold=0.7)

        if valid_id:
            st.success("✅ ID Verified Successfully!")
            qr = qrcode.make("Visitor verified successfully")
            buf = BytesIO()
            qr.save(buf)
            st.image(buf.getvalue(), caption="Your Access QR Code")
        else:
            st.error("❌ Invalid ID detected. Please upload a valid government-issued ID.")

def page_security():
    st.title("🛡️ Security Verification")
    uploaded_file = st.file_uploader("Scan Visitor QR", type=["png", "jpg", "jpeg"])
    if uploaded_file is not None:
        img = cv2.imdecode(np.frombuffer(uploaded_file.read(), np.uint8), cv2.IMREAD_COLOR)
        from pyzbar.pyzbar import decode
        decoded = decode(img)
        if decoded:
            data = json.loads(decoded[0].data.decode())
            exp = datetime.strptime(data["expires_at"], "%Y-%m-%d %H:%M:%S")
            if datetime.now() < exp:
                st.success(f"✅ Access granted for {data['visitor']}")
            else:
                st.error("❌ QR code expired!")
        else:
            st.error("❌ Invalid QR code!")

# -------------------- MAIN --------------------
st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to", ["Register", "Admin", "Login", "Homeowner", "Visitor", "Security"])

if page == "Register":
    page_register()
elif page == "Admin":
    page_admin()
elif page == "Login":
    page_login()
elif page == "Homeowner":
    page_homeowner()
elif page == "Visitor":
    page_visitor()
elif page == "Security":
    page_security()
