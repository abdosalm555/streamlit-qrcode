import streamlit as st
import qrcode
import json
import os
from datetime import datetime
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

# ---------------------------
# Page 1: Generator
# ---------------------------
def page_generator(public_url):
    st.title("🔑 QR Code Generator")

    visitor_name = st.text_input("Visitor Name")
    visitor_id = st.text_input("Visitor ID/License Number")

    if st.button("Generate QR"):
        token = base64.urlsafe_b64encode(os.urandom(6)).decode("utf-8")
        scan_link = f"{public_url}/?page=Visitor&token={token}"

        # Store visitor reservation (expiry set to end of today)
        expiry_time = get_end_of_day()
        data = {
            "visitor": {
                "name": visitor_name,
                "id_number": visitor_id,
                "token": token,
                "scan_time": None,
                "expiry_time": expiry_time.isoformat()
            }
        }
        save_data(data)

        qr_bytes = generate_qr(scan_link)
        st.image(qr_bytes, caption="Visitor QR Code")

        st.success(f"✅ Share this link with visitor:\n{scan_link}")
        st.info(f"QR valid until **{expiry_time.strftime('%H:%M:%S')}** today")

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

    # Check if expired
    expiry_time = datetime.fromisoformat(visitor["expiry_time"])
    if datetime.now() > expiry_time:
        st.error("⏱ QR Expired (End of Day)")
        return

    st.write(f"Welcome **{visitor['name']}**, please upload your ID for verification.")

    uploaded_id = st.file_uploader("Upload ID / License", type=["png", "jpg", "jpeg", "pdf"])

    if uploaded_id and st.button("Submit & Confirm Entry"):
        scan_time = datetime.now()
        visitor["scan_time"] = scan_time.isoformat()
        data["visitor"] = visitor
        save_data(data)

        st.success("✅ Verification complete. You may proceed to the gate.")
        st.info(f"⏳ QR valid until {expiry_time.strftime('%H:%M:%S')} today")

# ---------------------------
# Page 3: Security
# ---------------------------
def page_security():
    from streamlit_autorefresh import st_autorefresh
    st.title("🛡 Security Dashboard")

    data = load_data()
    visitor = data.get("visitor")

    if not visitor:
        st.info("No active visitor records yet.")
        return

    expiry_time = datetime.fromisoformat(visitor["expiry_time"])
    if datetime.now() > expiry_time:
        st.error("⏱ QR Expired (End of Day)")
        return

    st.subheader("Visitor Information")
    st.write(f"**Name:** {visitor['name']}")
    st.write(f"**ID Number:** {visitor['id_number']}")
    if visitor.get("scan_time"):
        st.write(f"**Scanned At:** {visitor['scan_time']}")
    else:
        st.warning("⚠ Visitor has not scanned yet.")

    # Auto-refresh every second
    st_autorefresh(interval=1000, key="security_refresh")
    remaining = expiry_time - datetime.now()
    if remaining.total_seconds() <= 0:
        st.error("⏱ QR Expired (End of Day)")
    else:
        st.warning(f"⏳ Time Left Today: {str(remaining).split('.')[0]}")

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
    # public_url injected from Colab startup
    st.session_state.setdefault("public_url", "https://app-qrcode-kbtgae6rj8r2qrdxprggcm.streamlit.app/")
    main(st.session_state["public_url"])

