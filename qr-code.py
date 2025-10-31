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
SECURITY_FILE = "security_accounts.json"
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

def hash_password(password: str):
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(stored_hash: str, plain_password: str):
    return stored_hash == hash_password(plain_password)

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
        # handle forms like "1h", "1 h", "1hr", "1 hr", "1.5h"
        if "hour" in s or "hr" in s or (s.endswith("h") and len(s) > 1):
            # extract leading numeric token
            num_token = s.split()[0].replace("h", "").replace("hr", "")
            num = float(num_token)
            return timedelta(hours=num)
        # minutes: "30min", "30 mins", "30 m"
        if "min" in s or (s.endswith("m") and len(s) > 1):
            num_token = s.split()[0].replace("min", "").replace("m", "")
            num = float(num_token)
            return timedelta(minutes=num)
        if ":" in s:  # 1:30 -> 1 hour 30 mins
            h, m = s.split(":")
            return timedelta(hours=int(h), minutes=int(m))
    except Exception:
        pass
    # fallback default
    return timedelta(minutes=30)

# ---------------------------
# Security accounts helpers
# ---------------------------
def ensure_security_file():
    if not os.path.exists(SECURITY_FILE):
        save_json(SECURITY_FILE, [])

def load_security_accounts():
    ensure_security_file()
    return load_json(SECURITY_FILE)  # list of dicts [{"username":..., "password":...}, ...]

def save_security_accounts(accounts):
    save_json(SECURITY_FILE, accounts)

def add_security_account(username, password_plain):
    accounts = load_security_accounts()
    if any(a["username"] == username for a in accounts):
        return False
    accounts.append({"username": username, "password": hash_password(password_plain)})
    save_security_accounts(accounts)
    return True

# ---------------------------
# Registration Page (homeowner)
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
# Login Page (homeowner)
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
# QR Generator Page (homeowner)
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

        data = {
            "visitor": {
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
        }
        save_json(DB_FILE, data)

        st.success(f"✅ Share this link with the visitor:\n{scan_link}")
        st.info(f"QR valid until **{expiry_time.strftime('%H:%M:%S')}** today")

# ---------------------------
# Security login (for security guards)
# ---------------------------
def security_login_widget():
    st.subheader("Security Login")
    st.info("Only authorized security personnel can confirm entries.")

    accounts = load_security_accounts()
    username = st.text_input("Username", key="sec_user")
    password = st.text_input("Password", type="password", key="sec_pass")

    if st.button("Login as Security"):
        user = next((a for a in accounts if a["username"] == username), None)
        if user and verify_password(user["password"], password):
            st.session_state["security_logged_in"] = True
            st.session_state["security_user"] = username
            st.success("✅ Security login successful.")
            st.rerun()
        else:
            st.error("Invalid security credentials.")

# ---------------------------
# Visitor Page (with AI ID verification & confidence check)
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

    # ID upload + AI verification (confidence threshold: 70%)
    if not visitor.get("id_uploaded"):
        st.subheader("📸 Upload Your ID")
        uploaded_id = st.file_uploader("Upload your ID (Image Only)", type=["jpg", "jpeg", "png"])

        if uploaded_id:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                tmp.write(uploaded_id.getvalue())
                tmp_path = tmp.name

            # Load model and run inference
            try:
                model = YOLO(MODEL_PATH)
                results = model.predict(tmp_path, conf=0.25, verbose=False)  # low conf to get boxes
            except Exception as e:
                os.remove(tmp_path)
                st.error(f"Model error: {e}")
                return

            # Check boxes for 'id' label and confidence >= 70%
            found_valid_id = False
            if len(results) > 0 and hasattr(results[0], "boxes"):
                boxes = results[0].boxes
                for box in boxes:
                    cls = int(box.cls)
                    label = model.names[cls].lower()
                    conf = float(box.conf) * 100.0  # convert to percent
                    # Accept if label mentions "id" and conf >= 70
                    if "id" in label and conf >= 70.0:
                        found_valid_id = True
                        break

            os.remove(tmp_path)

            if found_valid_id:
                visitor["id_uploaded"] = True
                visitor["id_filename"] = uploaded_id.name
                data["visitor"] = visitor
                save_json(DB_FILE, data)
                st.success("✅ Valid ID detected and approved (confidence >= 70%).")
                st.rerun()
            else:
                st.error("❌ No valid ID detected with sufficient confidence (>=70%). Please try again with a clear photo of the ID.")
                return
        else:
            st.warning("⚠ Please upload your ID to proceed.")
            return

    # Show QR for Security (security will need to login to confirm)
    st.subheader("QR Code for Gate Entry")
    scan_link = f"{st.session_state.get('public_url', '')}/?page=Security&token={token}"
    qr_bytes = generate_qr(scan_link)
    st.image(qr_bytes, caption="QR Code for Security to Scan")

    # Show countdown if already scanned
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
# Security Page (requires security login)
# ---------------------------
def page_security():
    from streamlit_autorefresh import st_autorefresh
    st.title("🛡 Security Dashboard")

    # if not logged in as security, show login widget and stop
    if not st.session_state.get("security_logged_in", False):
        security_login_widget()
        st.stop()

    # At this point security is logged in
    query_params = st.query_params
    token = query_params.get("token", None)

    data = load_json(DB_FILE)
    visitor = data.get("visitor")

    # If no visitor loaded or token mismatch -> but still allow scanning by scanning QR with token
    if token:
        # route with token: check and ensure visitor matches
        if not visitor or visitor.get("token") != token:
            st.error("❌ Scanned QR not valid or not recognized.")
            return

    if not visitor:
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

    # Confirm entry only if security logged in:
    if not visitor.get("scan_time"):
        if st.button("✅ Confirm Entry (Security)"):
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

    # Allow security to logout
    if st.sidebar.button("🔒 Security Logout"):
        st.session_state.pop("security_logged_in", None)
        st.session_state.pop("security_user", None)
        st.success("Security logged out.")
        st.rerun()

# ---------------------------
# Admin Page
# ---------------------------
def page_admin():
    st.title("🧑‍💼 Admin Dashboard - Approve New Accounts & Manage Security")

    pending = load_json(PENDING_FILE)
    users = load_json(USERS_FILE)

    # Pending homeowners table
    st.subheader("Pending Homeowner Registrations")
    if not pending:
        st.info("No pending registration requests.")
    else:
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
                if st.button("✅ Approve homeowner"):
                    users[selected_email] = {"phone": info["phone"], "password": info["password"]}
                    save_json(USERS_FILE, users)
                    del pending[selected_email]
                    save_json(PENDING_FILE, pending)
                    st.success(f"Approved {selected_email}")
                    st.rerun()
            with col2:
                if st.button("❌ Reject homeowner"):
                    del pending[selected_email]
                    save_json(PENDING_FILE, pending)
                    st.warning(f"Rejected {selected_email}")
                    st.rerun()

    st.markdown("---")
    # Manage security accounts
    st.subheader("Security Accounts (create / list)")
    accounts = load_security_accounts()
    if accounts:
        df_sec = pd.DataFrame([{"Username": a["username"]} for a in accounts])
        st.table(df_sec)
    else:
        st.info("No security accounts yet.")

    st.write("Create new security account:")
    new_sec_user = st.text_input("Security username", key="new_sec_user")
    new_sec_pass = st.text_input("Security password", type="password", key="new_sec_pass")
    if st.button("Create Security Account"):
        if not new_sec_user or not new_sec_pass:
            st.error("Please provide username and password.")
        else:
            created = add_security_account(new_sec_user, new_sec_pass)
            if created:
                st.success(f"Security user '{new_sec_user}' created.")
                st.rerun()
            else:
                st.warning("Username already exists.")

# ---------------------------
# Main App
# ---------------------------
def main(public_url):
    # read & normalize page query param
    raw_page = st.query_params.get("page")
    page_param = None
    if isinstance(raw_page, list) and raw_page:
        page_param = raw_page[0]
    elif isinstance(raw_page, str):
        page_param = raw_page

    page_clean = page_param.lower() if page_param else None

    # direct routes
    if page_clean == "visitor":
        page_visitor()
        return
    if page_clean == "security":
        page_security()
        return
    if page_clean == "admin":
        page_admin()
        return

    # if homeowner not logged in, show login/register
    if not st.session_state.get("logged_in", False):
        if st.session_state.get("show_login", True):
            page_login()
        else:
            page_register()
        return

    # Logged-in homeowner UI
    PAGES = {"Generator": lambda: page_generator(public_url)}
    page = st.sidebar.radio("Navigate", list(PAGES.keys()), index=0)

    # Logout button for homeowners
    st.sidebar.divider()
    if st.sidebar.button("🚪 Logout"):
        # clear homeowner session keys but keep security login separate
        keys_to_keep = [k for k in st.session_state.keys() if k.startswith("security")]
        all_keys = list(st.session_state.keys())
        for k in all_keys:
            if not k.startswith("security"):
                st.session_state.pop(k, None)
        # re-add any security keys if they existed
        for k in keys_to_keep:
            pass
        st.success("Logged out successfully.")
        st.rerun()

    PAGES[page]()

# ---------------------------
# Run App
# ---------------------------
if __name__ == "__main__":
    # ensure security file exists
    ensure_security_file()

    st.session_state.setdefault(
        "public_url", "https://app-qrcode-kbtgae6rj8r2qrdxprggcm.streamlit.app/"
    )
    main(st.session_state["public_url"])
