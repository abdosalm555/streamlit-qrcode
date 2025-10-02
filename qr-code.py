import streamlit as st
import qrcode
import json
import os
from datetime import datetime, timedelta
from io import BytesIO
import base64

DB_FILE = "scans.json"

# ---------------------------
# Helpers
# ---------------------------
def load_data():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DB_FILE, "w") as f:
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
    time_str = time_str.lower()
    if "hour" in time_str:
        num = int(time_str.split()[0])
        return timedelta(hours=num)
    elif "min" in time_str:
        num = int(time_str.split()[0])
        return timedelta(minutes=num)
    return timedelta(minutes=30)

# ---------------------------
# Page 1: Generator
# ---------------------------
def page_generator(public_url):
    st.title("🔑 QR Code Generator")

    visitor_name = st.text_input("Visitor Name")
    homeowner_name = st.text_input("Name of Home Owner")
    block_number = st.text_input("Block Number")
    purpose = st.text_area("Purpose of Visit")
    estimated_time = st.text_input("Estimated Time of Stay (e.g., 1 hour, 30 mins)")

    if st.button("Generate QR"):
        token = base64.urlsafe_b64encode(os.urandom(6)).decode("utf-8")
        qr_scan_link = f"{public_url}/?page=Security&token={token}"  # QR for security scan
        visitor_link = f"{public_url}/?page=Visitor&token={token}"   # Visitor link

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
        save_data(data)

        qr_bytes = generate_qr(qr_scan_link)
        st.image(qr_bytes, caption="Security QR Code")

        st.success(f"✅ Share this link with the visitor:\n{visitor_link}")
        st.info(f"QR can be used until **{expiry_time.strftime('%H:%M:%S')}** today")

# ---------------------------
# Page 2: Visitor
# ---------------------------
def page_visitor():
    st.title("🙋 Visitor Check-In")

    query_params = st.query_params
    token = query_params.get("token", None)

    if not token:
        st.error("❌ Invalid or missing QR token")
        return

    data = load_data()
    visitor = data.get("visitor", {})

    if not visitor or visitor.get("token") != token:
        st.error("❌ QR Code not recognized")
        return

    expiry_time = datetime.fromisoformat(visitor["expiry_time"])
    if datetime.now() > expiry_time:
        st.error("⏱ QR Expired (End of Day)")
        return

    if not visitor.get("id_uploaded"):
        st.subheader("Upload Identification")
        uploaded_id = st.file_uploader("Upload your ID (Image Only)", type=["jpg", "jpeg", "png"])
        if uploaded_id:
            visitor["id_uploaded"] = True
            visitor["id_filename"] = uploaded_id.name  # simulate storage
            data["visitor"] = visitor
            save_data(data)
            st.success("✅ ID uploaded successfully.")
        else:
            st.warning("⚠ Please upload your ID to proceed.")
            return  # Don't show QR yet

    st.subheader("QR Code for Gate Entry")
    scan_link = f"{st.session_state.get('public_url', '')}/?page=Security&token={token}"
    qr_bytes = generate_qr(scan_link)
    st.image(qr_bytes, caption="Security QR Code")

    if st.button("Confirm Entry"):
        if not visitor.get("scan_time"):
            scan_time = datetime.now()
            visitor["scan_time"] = scan_time.isoformat()
            data["visitor"] = visitor
            save_data(data)
            st.success("✅ Entry confirmed. Welcome!")
        else:
            st.warning("⚠ This QR has already been confirmed earlier.")

# ---------------------------
# Page 3: Security
# ---------------------------
def page_security():
    from streamlit_autorefresh import st_autorefresh
    st.title("🛡 Security Dashboard")

    query_params = st.query_params
    token = query_params.get("token", None)

    data = load_data()
    visitor = data.get("visitor")

    if not visitor or (token and visitor.get("token") != token):
        st.error("❌ No matching visitor or invalid token")
        return

    expiry_time = datetime.fromisoformat(visitor["expiry_time"])
    if datetime.now() > expiry_time:
        st.error("⏱ QR Expired (End of Day)")
        return

    scan_time = visitor.get("scan_time")
    if scan_time:
        st.error("⚠ This QR code has already been scanned and is no longer valid.")
        scanned_at = datetime.fromisoformat(scan_time)
        st.write(f"**Originally Scanned At:** {scanned_at.strftime('%H:%M:%S')}")
        return

    # Show visitor info
    st.subheader("Visitor Information")
    st.write(f"**Visitor Name:** {visitor['visitor_name']}")
    st.write(f"**Homeowner Name:** {visitor['homeowner_name']}")
    st.write(f"**Block Number:** {visitor['block_number']}")
    st.write(f"**Purpose:** {visitor['purpose']}")
    st.write(f"**Estimated Time:** {visitor['estimated_time']}")

    # Confirm scan
    if st.button("Confirm Visitor Entry"):
        scan_time = datetime.now()
        visitor["scan_time"] = scan_time.isoformat()
        data["visitor"] = visitor
        save_data(data)
        st.success("✅ Visitor scanned and entry logged.")

        # Show countdown
        estimated_duration = parse_estimated_time(visitor['estimated_time'])
        end_time = scan_time + estimated_duration
        remaining = end_time - datetime.now()

        if remaining.total_seconds() > 0:
            st.info(f"⏳ Time Left: {str(remaining).split('.')[0]}")
        else:
            st.warning("⏱ Visitor’s estimated time has expired.")

    # Show QR overall expiry
    eod_remaining = expiry_time - datetime.now()
    st.caption(f"🕛 QR valid until: {expiry_time.strftime('%H:%M:%S')}")
    st.caption(f"📆 Time left today: {str(eod_remaining).split('.')[0]}")

    st_autorefresh(interval=1000, key="security_refresh")

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

    page = st.sidebar.radio("Navigate", list(PAGES.keys()),
                            index=list(PAGES.keys()).index(default_page))
    PAGES[page]()

if __name__ == "__main__":
    st.session_state.setdefault("public_url", "https://your-deployment-url.app")
    main(st.session_state["public_url"])
