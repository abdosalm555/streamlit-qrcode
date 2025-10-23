import streamlit as st
import qrcode
import json
import os
import hashlib
from datetime import datetime, timedelta
from io import BytesIO
import base64

# ---------------------------
# File paths
# ---------------------------
USERS_FILE = "users.json"
DB_FILE = "scans.json"

# ---------------------------
# Admin Credentials
# ---------------------------
ADMIN_CREDENTIALS = {"username": "admin", "password": "admin123"}

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
    """Hash password using SHA-256"""
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
    """Parses '1 hour', '30 mins' etc. to timedelta"""
    time_str = time_str.lower()
    if "hour" in time_str:
        num = int(time_str.split()[0])
        return timedelta(hours=num)
    elif "min" in time_str:
        num = int(time_str.split()[0])
        return timedelta(minutes=num)
    return timedelta(minutes=30)

# ---------------------------
# Authentication Pages
# ---------------------------
def page_register():
    st.title("🏠 Homeowner Registration")

    users = load_json(USERS_FILE)

    email = st.text_input("Email (used as username)")
    phone = st.text_input("Phone Number")
    password = st.text_input("Password", type="password")
    confirm = st.text_input("Confirm Password", type="password")

    if st.button("Register"):
        if not email or not password or not phone:
            st.error("Please fill all fields.")
        elif password != confirm:
            st.error("Passwords do not match.")
        elif email in users:
            st.warning("This email is already registered.")
        else:
            users[email] = {
                "phone": phone,
                "password": hash_password(password),
                "approved": False,  # waiting for admin approval
            }
            save_json(USERS_FILE, users)
            st.success("✅ Registration request sent! Wait for admin approval before logging in.")
            st.session_state["show_login"] = True
            st.rerun()

def page_login():
    st.title("🔐 Homeowner Login")

    users = load_json(USERS_FILE)

    email = st.text_input("Email")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        if email not in users:
            st.error("Email not registered.")
        elif users[email]["password"] != hash_password(password):
            st.error("Incorrect password.")
        elif not users[email].get("approved", False):
            st.warning("⏳ Your account is awaiting admin approval.")
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
# Admin Page
# ---------------------------
def page_admin():
    st.title("🧑‍💼 Admin Dashboard")

    admin_user = st.text_input("Admin Username")
    admin_pass = st.text_input("Admin Password", type="password")

    if st.button("Login as Admin"):
        if admin_user == ADMIN_CREDENTIALS["username"] and admin_pass == ADMIN_CREDENTIALS["password"]:
            st.session_state["admin_logged"] = True
            st.success("✅ Admin login successful.")
            st.rerun()
        else:
            st.error("Invalid admin credentials.")

    if st.session_state.get("admin_logged", False):
        users = load_json(USERS_FILE)

        st.subheader("Pending Approval Requests")
        pending = {u: info for u, info in users.items() if not info.get("approved", False)}

        if not pending:
            st.info("No pending approvals.")
        else:
            for email, info in pending.items():
                with st.container():
                    st.write(f"📧 **{email}** | 📞 {info['phone']}")
                    if st.button(f"✅ Approve {email}", key=email):
                        users[email]["approved"] = True
                        save_json(USERS_FILE, users)
                        st.success(f"Approved {email}")
                        st.rerun()

        st.divider()
        if st.button("🚪 Logout Admin"):
            st.session_state["admin_logged"] = False
            st.rerun()

# ---------------------------
# Page 1: QR Generator
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
                "id_uploaded": False
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
            visitor["id_uploaded"] = True
            visitor["id_filename"] = uploaded_id.name
            data["visitor"] = visitor
            save_json(DB_FILE, data)
            st.success("✅ ID uploaded successfully.")
            st.rerun()
        else:
            st.warning("⚠ Please upload your ID to proceed.")
            return

    st.subheader("QR Code for Gate Entry")
    scan_link = f"{st.session_state.get('public_url', '')}/?page=Security&token={token}"
    qr_bytes = generate_qr(scan_link)
    st.image(qr_bytes, caption="QR Code for Security to Scan")

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

# ---------------------------
# Main Navigation
# ---------------------------
def main(public_url):
    page_query = st.query_params.get("page")

    if page_query == "Visitor":
        page_visitor()
        return
    if page_query == "Security":
        page_security()
        return
    if page_query == "Admin":
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
    st.session_state.setdefault("public_url", "https://app-qrcode-kbtgae6rj8r2qrdxprggcm.streamlit.app/")
    main(st.session_state["public_url"])
