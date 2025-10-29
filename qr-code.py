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
import pandas as pd

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


def parse_estimated_time(time_str):
    """Smart time parser – handles 1h, 1 hr, 1 hour, 30 mins, etc."""
    s = (time_str or "").lower().strip()
    try:
        # Accept forms like: "1", "1h", "1 h", "1hr", "1 hour", "30m", "30 min", "1:30"
        if ":" in s:
            h, m = s.split(":")
            return timedelta(hours=int(h), minutes=int(m))
        # look for number (possibly float) at start
        import re
        mnum = re.match(r"([0-9]*\.?[0-9]+)", s)
        if mnum:
            num = float(mnum.group(1))
            if "h" in s or "hour" in s or "hr" in s:
                return timedelta(hours=num)
            if "m" in s or "min" in s:
                return timedelta(minutes=num)
            # no unit — assume minutes if large? we'll assume minutes by default
            return timedelta(minutes=num)
    except Exception:
        pass
    return timedelta(minutes=30)  # fallback default

# ---------------------------
# YOLO model loader (cached)
# ---------------------------
@st.cache_resource
def load_model():
    # Will raise if model file missing — let exception show in logs/UI
    return YOLO(MODEL_PATH)

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
            st.session_state["phone"] = users[email]["phone"]
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

    homeowner_email = st.session_state.get("email", "Unknown")
    st.info(f"👤 Logged in as: **{homeowner_email}**")

    visitor_name = st.text_input("Visitor Name")
    block_number = st.text_input("Block Number")
    purpose = st.text_area("Purpose of Visit")
    estimated_time = st.text_input("Estimated Time of Stay (e.g., 1 hour, 30 mins)")

    if st.button("Generate QR Link"):
        token = base64.urlsafe_b64encode(os.urandom(6)).decode("utf-8")
        scan_link = f"{public_url}/?page=Visitor&token={token}"

        expiry_time = get_end_of_day()

        data = load_json(DB_FILE)
        # Save full DB structure to avoid overwriting other keys if they exist
        data["visitor"] = {
            "token": token,
            "visitor_name": visitor_name,
            "homeowner_name": homeowner_email,
            "block_number": block_number,
            "purpose": purpose,
            "estimated_time": estimated_time,
            "scan_time": None,
            "expiry_time": expiry_time.isoformat(),
            "id_uploaded": False,
        }
        save_json(DB_FILE, data)

        st.success(f"✅ Share this link with the visitor:\n{scan_link}")
        st.info(f"QR valid until **{expiry_time.strftime('%H:%M:%S')}** today")


# ---------------------------
# Visitor Page with AI Model Confidence Check
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

    # If ID not uploaded/approved yet -> ask for upload and validate via model
    if not visitor.get("id_uploaded"):
        st.subheader("📸 Upload Your ID")
        uploaded_id = st.file_uploader("Upload your ID (Image Only)", type=["jpg", "jpeg", "png"])

        if uploaded_id:
            st.info("Running AI model for ID validation (requires model to be present)...")
            # Save temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                tmp.write(uploaded_id.getvalue())
                tmp_path = tmp.name

            try:
                # Load cached model
                model = load_model()

                # Run inference (we'll collect confidences of detected boxes)
                # verbose=False to avoid heavy prints
                results = model.predict(tmp_path, conf=0.001, verbose=False)

                # Extract confidences robustly
                conf_scores = []
                if len(results) > 0:
                    r0 = results[0]
                    # r0.boxes.conf may be a tensor or numpy array depending on version
                    try:
                        # prefer .tolist() when available
                        conf_scores = r0.boxes.conf.tolist()
                    except Exception:
                        # fallback: iterate boxes
                        try:
                            conf_scores = [float(b.conf) for b in r0.boxes]
                        except Exception:
                            conf_scores = []

                # Debug: st.write(conf_scores)  # uncomment if you want to see raw confidences

                # Decision: accept if any confidence >= 0.70
                if conf_scores and max(conf_scores) >= 0.70:
                    visitor["id_uploaded"] = True
                    visitor["id_filename"] = uploaded_id.name
                    data["visitor"] = visitor
                    save_json(DB_FILE, data)
                    st.success("✅ Valid ID detected and approved (confidence >= 70%).")
                    # cleanup and rerun to show QR
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
                    st.rerun()
                else:
                    # show most informative message
                    top_conf = max(conf_scores) if conf_scores else None
                    if top_conf is None:
                        st.error("❌ No ID-like object detected. Please upload a clear ID image.")
                    else:
                        st.error(f"❌ Low confidence ({top_conf:.2f}). Not a valid ID image — please try again.")
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
                    return
            except Exception as e:
                st.error(f"AI model error: {e}")
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
                return
        else:
            st.warning("⚠ Please upload your ID to proceed.")
            return

    # If we reach here, ID is approved — show QR for security scanning
    st.subheader("QR Code for Gate Entry")
    scan_link = f"{st.session_state.get('public_url', '')}/?page=Security&token={token}"
    qr_bytes = generate_qr(scan_link)
    st.image(qr_bytes, caption="QR Code for Security to Scan")

    # Countdown display if already scanned by security
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

    # If there's no visitor or token mismatch, show message
    if not visitor or (token and visitor.get("token") != token):
        st.info("No active visitor records yet.")
        return

    # Check end-of-day expiry
    expiry_time = datetime.fromisoformat(visitor["expiry_time"])
    if datetime.now() > expiry_time:
        st.error("⏱ QR Expired (End of Day)")
        return

    # Show visitor info
    st.subheader("Visitor Information")
    st.write(f"**Visitor Name:** {visitor.get('visitor_name','-')}")
    st.write(f"**Homeowner Name:** {visitor.get('homeowner_name','-')}")
    st.write(f"**Block Number:** {visitor.get('block_number','-')}")
    st.write(f"**Purpose:** {visitor.get('purpose','-')}")
    st.write(f"**Estimated Time:** {visitor.get('estimated_time','-')}")

    # Confirm entry -> set scan_time
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

    df = pd.DataFrame([
        {"Email": email, "Phone": info["phone"], "Submitted": info["submitted_at"]}
        for email, info in pending.items()
    ])

    st.dataframe(df, use_container_width=True)

    selected_email = st.selectbox("Select an email to review:", list(pending.keys()))
    if selected_email:
        info = pending[selected_email]
        st.write(f"**Phone:** {info['phone']}")
        st.write(f"**Submitted:** {info['submitted_at']}")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Approve"):
                users[selected_email] = {"phone": info["phone"], "password": info["password"]}
                save_json(USERS_FILE, users)
                del pending[selected_email]
                save_json(PENDING_FILE, pending)
                st.success(f"Approved {selected_email}")
                st.rerun()
        with col2:
            if st.button("❌ Reject"):
                del pending[selected_email]
                save_json(PENDING_FILE, pending)
                st.warning(f"Rejected {selected_email}")
                st.rerun()


# ---------------------------
# Main App
# ---------------------------
def main(public_url):
    raw_page = st.query_params.get("page")
    page_param = None
    if isinstance(raw_page, list) and raw_page:
        page_param = raw_page[0]
    elif isinstance(raw_page, str):
        page_param = raw_page

    page_clean = page_param.lower() if page_param else None

    if page_clean == "visitor":
        page_visitor()
        return
    if page_clean == "security":
        page_security()
        return
    if page_clean == "admin":
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
