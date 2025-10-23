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
import re  # <-- added for improved time parsing

# ---------------------------
# File paths
# ---------------------------
USERS_FILE = "users.json"
PENDING_FILE = "pending_users.json"
DB_FILE = "scans.json"
MODEL_PATH = "best.pt"  # <-- Your AI model file


# ---------------------------
# Helpers
# ---------------------------
def load_json(file_path):
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            return json.load(f)
    return {}


def save_json(file_path, data):
    with open(file_path, "w") as f:
        json.dump(data, f, indent=4)


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def generate_qr(data: str):
    qr = qrcode.QRCode(version=1, box_size=8, border=4)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_end_of_day():
    now = datetime.now()
    return datetime(now.year, now.month, now.day, 23, 59, 59)


# ✅ Improved function to handle flexible time input formats
def parse_estimated_time(time_str):
    time_str = time_str.lower().strip()

    # Handle hours (hour, hr, hrs, h)
    if any(x in time_str for x in ["hour", "hr", "hrs", "h"]):
        match = re.search(r"(\d+)", time_str)
        if match:
            hours = int(match.group(1))
            return timedelta(hours=hours)

    # Handle minutes (minute, min, mins, m)
    if any(x in time_str for x in ["minute", "min", "mins", "m"]):
        match = re.search(r"(\d+)", time_str)
        if match:
            minutes = int(match.group(1))
            return timedelta(minutes=minutes)

    # Default if unrecognized
    return timedelta(minutes=30)


# ---------------------------
# Registration Page
# ---------------------------
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


# ---------------------------
# Login Page
# ---------------------------
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


# ---------------------------
# QR Generator Page
# ---------------------------
def page_generator(public_url):
    st.title("🔑 QR Code Generator")

    visitor_name = st.text_input("Visitor Name")
    homeowner_name = st.text_input("Name of Home Owner")
    block_number = st.text_input("Block Number")
    purpose = st.text_area("Purpose of Visit")
    estimated_time = st.text_input("Estimated Time of Stay (e.g., 1 hour, 30 mins)")

    if st.button("Generate QR Link"):
        token = base64.urlsafe_b64encode(os.urandom(6)).decode("utf-8")
        scan_link = f"{public_url}/?page=Visitor&token={token}"

        expiry_time = get_end_of_day()

        data = {
            "visitor": {
                "token": token,
                "visitor_name": visitor_name,
                "homeowner_name": homeowner_name,
                "block_number": block_number,
                "purpose": purpose,
                "estimated_time": estimated_time,
                "scan_time": None,
                "expiry_time": expiry_time.isoformat(),
                "id_uploaded": False,
            }
        }
        save_json(DB_FILE, data)

        st.success(f"✅ Share this link with the visitor:\n{scan_link}")
        st.info(f"QR valid until **{expiry_time.strftime('%H:%M:%S')}** today")


# ---------------------------
# Visitor Page
# ---------------------------
def page_visitor():
    from streamlit_autorefresh import st_autorefresh
    st.title("🙋 Visitor Check-In")

    query_params = st.query_params
    token = query_params.get("token", None)

    if not token:
        st.error("❌ Invalid or missing QR token")
        return

    data = load_json(DB_FILE)
    visitor = data.get("visitor", {})

    if not visitor or visitor.get("token") != token:
        st.error("❌ QR Code not recognized")
        return

    expiry_time = datetime.fromisoformat(visitor["expiry_time"])
    if datetime.now() > expiry_time:
        st.error("⏱ QR Expired (End of Day)")
        return

    if not visitor.get("id_uploaded"):
        st.subheader("📸 Upload Your ID")
        uploaded_id = st.file_uploader("Upload your ID (Image Only)", type=["jpg", "jpeg", "png"])

        if uploaded_id:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                tmp.write(uploaded_id.getvalue())
                tmp_path = tmp.name

            model = YOLO(MODEL_PATH)
            results = model.predict(tmp_path, conf=0.5, verbose=False)
            detected_labels = [model.names[int(box.cls)] for box in results[0].boxes]

            if "ID" in detected_labels or "id" in detected_labels:
                visitor["id_uploaded"] = True
                visitor["id_filename"] = uploaded_id.name
                data["visitor"] = visitor
                save_json(DB_FILE, data)
                st.success("✅ Valid ID detected and approved.")
                os.remove(tmp_path)
                st.rerun()
            else:
                st.error("❌ Not a valid ID card. Please try again with a clear image.")
                os.remove(tmp_path)
                return
        else:
            st.warning("⚠ Please upload your ID to proceed.")
            return

    st.subheader("QR Code for Gate Entry")
    scan_link = f"{st.session_state.get('public_url', '')}/?page=Security&token={token}"
    qr_bytes = generate_qr(scan_link)
    st.image(qr_bytes, caption="QR Code for Security to Scan")

    if visitor.get("scan_time"):
        st.subheader("⏳ Time Remaining")
        scanned_at = datetime.fromisoformat(visitor["scan_time"])
        estimated_duration = parse_estimated_time(visitor["estimated_time"])
        end_time = scanned_at + estimated_duration
        remaining = end_time - datetime.now()
        if remaining.total_seconds() > 0:
            st.success(f"Time Left: {str(remaining).split('.')[0]}")
        else:
            st.error("⏱ Visitor's estimated time has expired.")
        st_autorefresh(interval=1000, key="visitor_refresh")
    else:
        st.info("⌛ Waiting for Security to confirm your entry.")


# ---------------------------
# Security Page
# ---------------------------
def page_security():
    from streamlit_autorefresh import st_autorefresh
    st.title("🛡 Security Dashboard")

    query_params = st.query_params
    token = query_params.get("token", None)

    data = load_json(DB_FILE)
    visitor = data.get("visitor")

    if not visitor or (token and visitor.get("token") != token):
        st.info("No active visitor records yet.")
        return

    expiry_time = datetime.fromisoformat(visitor["expiry_time"])
    if datetime.now() > expiry_time:
        st.error("⏱ QR Expired (End of Day)")
        return

    st.subheader("Visitor Information")
    st.write(f"**Visitor Name:** {visitor['visitor_name']}")
    st.write(f"**Homeowner Name:** {visitor['homeowner_name']}")
    st.write(f"**Block Number:** {visitor['block_number']}")
    st.write(f"**Purpose:** {visitor['purpose']}")
    st.write(f"**Estimated Time:** {visitor['estimated_time']}")

    if not visitor.get("scan_time"):
        if st.button("✅ Confirm Entry"):
            visitor["scan_time"] = datetime.now().isoformat()
            data["visitor"] = visitor
            save_json(DB_FILE, data)
            st.success("Entry confirmed. Timer started.")
            st.rerun()
    else:
        scanned_at = datetime.fromisoformat(visitor["scan_time"])
        st.write(f"**Scanned At:** {scanned_at.strftime('%H:%M:%S')}")
        estimated_duration = parse_estimated_time(visitor["estimated_time"])
        end_time = scanned_at + estimated_duration
        remaining = end_time - datetime.now()
        if remaining.total_seconds() > 0:
            st.success(f"⏳ Time Left: {str(remaining).split('.')[0]}")
        else:
            st.error("⏱ Visitor's estimated time has expired.")
        st_autorefresh(interval=1000, key="security_refresh")


# ---------------------------
# Admin Page
# ---------------------------
def page_admin():
    st.title("🧑‍💼 Admin Dashboard - Approve New Accounts")

    pending = load_json(PENDING_FILE)
    users = load_json(USERS_FILE)

    if not pending:
        st.info("No pending registration requests.")
        return

    for email, info in pending.items():
        st.write(f"**Email:** {email}")
        st.write(f"**Phone:** {info['phone']}")
        st.write(f"**Submitted:** {info['submitted_at']}")
        cols = st.columns(2)
        with cols[0]:
            if st.button(f"✅ Approve {email}"):
                users[email] = {"phone": info["phone"], "password": info["password"]}
                save_json(USERS_FILE, users)
                del pending[email]
                save_json(PENDING_FILE, pending)
                st.success(f"Approved {email}")
                st.rerun()
        with cols[1]:
            if st.button(f"❌ Reject {email}"):
                del pending[email]
                save_json(PENDING_FILE, pending)
                st.warning(f"Rejected {email}")
                st.rerun()


# ---------------------------
# Main App
# ---------------------------
def main(public_url):
    page_param = st.query_params.get("page")
    if page_param == "Visitor":
        page_visitor()
        return
    if page_param == "Security":
        page_security()
        return
    if page_param == "Admin":
        page_admin()
        return

    if not st.session_state.get("logged_in", False):
        if st.session_state.get("show_login", True):
            page_login()
        else:
            page_register()
        return

    PAGES = {"Generator": lambda: page_generator(public_url)}

    page = st.sidebar.radio("Navigate", list(PAGES.keys()), index=0)
    st.sidebar.divider()
    if st.sidebar.button("🚪 Logout"):
        st.session_state.clear()
        st.success("Logged out successfully.")
        st.rerun()

    PAGES[page]()


# ---------------------------
# Run App
# ---------------------------
if __name__ == "__main__":
    st.session_state.setdefault(
        "public_url", "https://app-qrcode-kbtgae6rj8r2qrdxprggcm.streamlit.app/"
    )
    main(st.session_state["public_url"])
