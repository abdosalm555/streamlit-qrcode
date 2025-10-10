import streamlit as st
import qrcode
import json
import os
from datetime import datetime, timedelta
from io import BytesIO
import base64
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15
from Crypto.Hash import SHA256

DB_FILE = "scans.json"
PRIVATE_KEY_FILE = "private.pem"
PUBLIC_KEY_FILE = "public.pem"

# ---------------------------
# RSA Setup
# ---------------------------
def generate_rsa_keys():
    """Generate RSA keys if not already present"""
    if not os.path.exists(PRIVATE_KEY_FILE) or not os.path.exists(PUBLIC_KEY_FILE):
        key = RSA.generate(2048)
        private_key = key.export_key()
        public_key = key.publickey().export_key()

        with open(PRIVATE_KEY_FILE, "wb") as f:
            f.write(private_key)
        with open(PUBLIC_KEY_FILE, "wb") as f:
            f.write(public_key)

def load_keys():
    """Load RSA private and public keys"""
    with open(PRIVATE_KEY_FILE, "rb") as f:
        private_key = RSA.import_key(f.read())
    with open(PUBLIC_KEY_FILE, "rb") as f:
        public_key = RSA.import_key(f.read())
    return private_key, public_key

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
# Sign / Verify
# ---------------------------
def sign_token(token: str, private_key):
    h = SHA256.new(token.encode())
    signature = pkcs1_15.new(private_key).sign(h)
    return base64.urlsafe_b64encode(signature).decode()

def verify_token(token: str, signature: str, public_key):
    try:
        sig_bytes = base64.urlsafe_b64decode(signature)
        h = SHA256.new(token.encode())
        pkcs1_15.new(public_key).verify(h, sig_bytes)
        return True
    except (ValueError, TypeError):
        return False

# ---------------------------
# Page 1: Generator
# ---------------------------
def page_generator(public_url):
    st.title("🔑 QR Code Generator (Authenticated)")

    visitor_name = st.text_input("Visitor Name")
    homeowner_name = st.text_input("Name of Home Owner")
    block_number = st.text_input("Block Number")
    purpose = st.text_area("Purpose of Visit")
    estimated_time = st.text_input("Estimated Time of Stay (e.g., 1 hour, 30 mins)")

    if st.button("Generate Secure QR Link"):
        private_key, public_key = load_keys()
        token = base64.urlsafe_b64encode(os.urandom(6)).decode("utf-8")

        # 🔐 Sign the token
        signature = sign_token(token, private_key)

        scan_link = f"{public_url}/?page=Visitor&token={token}&sig={signature}"
        expiry_time = get_end_of_day()

        data = {
            "visitor": {
                "token": token,
                "signature": signature,
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

        st.success(f"✅ Secure link generated:\n{scan_link}")
        st.info(f"QR valid until **{expiry_time.strftime('%H:%M:%S')}** today")

# ---------------------------
# Page 2: Visitor
# ---------------------------
def page_visitor():
    from streamlit_autorefresh import st_autorefresh
    st.title("🙋 Visitor Check-In")

    query_params = st.query_params
    token = query_params.get("token", None)
    signature = query_params.get("sig", None)

    if not token or not signature:
        st.error("❌ Missing authentication signature")
        return

    _, public_key = load_keys()

    if not verify_token(token, signature, public_key):
        st.error("🚫 Invalid or tampered QR code (Authentication failed)")
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
            visitor["id_filename"] = uploaded_id.name
            data["visitor"] = visitor
            save_data(data)
            st.success("✅ ID uploaded successfully.")
        else:
            st.warning("⚠ Please upload your ID to proceed.")
            return

    st.subheader("QR Code for Gate Entry")
    scan_link = f"{st.session_state.get('public_url', '')}/?page=Security&token={token}&sig={signature}"
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
# Page 3: Security
# ---------------------------
def page_security():
    from streamlit_autorefresh import st_autorefresh
    st.title("🛡 Security Dashboard (Authenticated)")

    query_params = st.query_params
    token = query_params.get("token", None)
    signature = query_params.get("sig", None)

    if not token or not signature:
        st.error("❌ Missing authentication data in QR")
        return

    _, public_key = load_keys()

    if not verify_token(token, signature, public_key):
        st.error("🚫 Invalid QR code — authentication failed.")
        return

    data = load_data()
    visitor = data.get("visitor")

    if not visitor or visitor.get("token") != token:
        st.error("❌ No matching visitor record.")
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
            save_data(data)
            st.success("Entry confirmed. Timer started.")
            st.rerun()
    else:
        scanned_at = datetime.fromisoformat(visitor["scan_time"])
        estimated_duration = parse_estimated_time(visitor["estimated_time"])
        end_time = scanned_at + estimated_duration
        remaining = end_time - datetime.now()
        if remaining.total_seconds() > 0:
            st.success(f"⏳ Time Left: {str(remaining).split('.')[0]}")
        else:
            st.error("⏱ Visitor's estimated time has expired.")
        st_autorefresh(interval=1000, key="security_refresh")

# ---------------------------
# Main App Navigation
# ---------------------------
def main(public_url):
    generate_rsa_keys()  # ensure RSA keys exist

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
    st.session_state.setdefault("public_url", "https://app-qrcode-kbtgae6rj8r2qrdxprggcm.streamlit.app/")
    main(st.session_state["public_url"])
