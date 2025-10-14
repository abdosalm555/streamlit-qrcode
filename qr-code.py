import streamlit as st
import qrcode
import json
import os
from datetime import datetime, timedelta
from io import BytesIO
import base64

# ---------------------------
# File paths
# ---------------------------
DB_FILE = "scans.json"
USERS_FILE = "users.json"


# ---------------------------
# Helper Functions
# ---------------------------
def load_data(filename):
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return json.load(f)
    return {}


def save_data(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f, indent=4)


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
    return timedelta(minutes=30)  # fallback


# ---------------------------
# Authentication Pages
# ---------------------------
def page_register():
    st.title("🏠 Homeowner Registration")

    users = load_data(USERS_FILE)

    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    phone = st.text_input("Phone Number")

    if st.button("Register"):
        if not email or not password or not phone:
            st.error("Please fill out all fields.")
        elif email in users:
            st.warning("This email is already registered.")
        else:
            users[email] = {"password": password, "phone": phone}
            save_data(USERS_FILE, users)
            st.success("✅ Registration successful! Please log in.")
            st.session_state["page"] = "Login"
            st.rerun()


def page_login():
    st.title("🔐 Homeowner Login")

    users = load_data(USERS_FILE)
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        if email in users and users[email]["password"] == password:
            st.session_state["authenticated"] = True
            st.session_state["user_email"] = email
            st.success("✅ Login successful.")
            st.rerun()
        else:
            st.error("Invalid email or password.")


def page_logout():
    st.session_state["authenticated"] = False
    st.session_state["user_email"] = None
    st.success("🔒 You have been logged out.")
    st.rerun()


# ---------------------------
# Page 1: QR Code Generator (for logged-in homeowners)
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
        save_data(DB_FILE, data)

        st.success(f"✅ Share this link with the visitor:\n{scan_link}")
        st.info(f"QR can be used until **{expiry_time.strftime('%H:%M:%S')}** today")

    st.button("🚪 Logout", on_click=page_logout)


# ---------------------------
# Page 2: Visitor Check-in
# ---------------------------
def page_visitor():
    from streamlit_autorefresh import st_autorefresh

    st.title("🙋 Visitor Check-In")

    query_params = st.query_params
    token = query_params.get("token", None)

    if not token:
        st.error("❌ Invalid or missing QR token")
        return

    data = load_data(DB_FILE)
    visitor = data.get("visitor", {})

    if not visitor or visitor.get("token") != token:
        st.error("❌ QR Code not recognized")
        return

    expiry_time = datetime.fromisoformat(visitor["expiry_time"])
    if datetime.now() > expiry_time:
        st.error("⏱ QR Expired (End of Day)")
        return

    if not visitor.get("id_uploaded"):
        st.subheader("📷 Upload Identification")
        uploaded_id = st.file_uploader("Upload your ID (Image Only)", type=["jpg", "jpeg", "png"])
        if uploaded_id:
            visitor["id_uploaded"] = True
            visitor["id_filename"] = uploaded_id.name
            data["visitor"] = visitor
            save_data(DB_FILE, data)
            st.success("✅ ID uploaded successfully.")
        else:
            st.warning("⚠ Please upload your ID to proceed.")
            return

    st.subheader("🎟 QR Code for Gate Entry")
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
# Page 3: Security Dashboard
# ---------------------------
def page_security():
    from streamlit_autorefresh import st_autorefresh

    st.title("🛡 Security Dashboard")

    query_params = st.query_params
    token = query_params.get("token", None)

    data = load_data(DB_FILE)
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
            scan_time = datetime.now()
            visitor["scan_time"] = scan_time.isoformat()
            data["visitor"] = visitor
            save_data(DB_FILE, data)
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

    eod_remaining = expiry_time - datetime.now()
    st.caption(f"🕛 QR valid until: {expiry_time.strftime('%H:%M:%S')} (end of day)")
    st.caption(f"📆 Time left today: {str(eod_remaining).split('.')[0]}")


# ---------------------------
# Main App Navigation
# ---------------------------
def main(public_url):
    PAGES = {
        "Generator": lambda: page_generator(public_url),
        "Visitor": page_visitor,
        "Security": page_security,
    }

    default_page = st.query_params.get("page", "Generator")
    if default_page not in PAGES:
        default_page = "Generator"

    # ✅ Only require login for the Generator page (homeowners)
    if default_page == "Generator" and not st.session_state.get("authenticated", False):
        page_login()
        return

    page = st.sidebar.radio(
        "Navigate", list(PAGES.keys()), index=list(PAGES.keys()).index(default_page)
    )
    PAGES[page]()


# ---------------------------
# App Entry Point
# ---------------------------
if __name__ == "__main__":
    st.session_state.setdefault("authenticated", False)
    st.session_state.setdefault("user_email", None)
    st.session_state.setdefault("public_url", "https://app-qrcode-kbtgae6rj8r2qrdxprggcm.streamlit.app/")  
    main(st.session_state["public_url"])
