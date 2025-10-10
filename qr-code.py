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
# Key Generation (only first run)
# ---------------------------
def generate_rsa_keys():
    if not os.path.exists(PRIVATE_KEY_FILE) or not os.path.exists(PUBLIC_KEY_FILE):
        key = RSA.generate(2048)
        private_key = key.export_key()
        public_key = key.publickey().export_key()
        with open(PRIVATE_KEY_FILE, "wb") as f:
            f.write(private_key)
        with open(PUBLIC_KEY_FILE, "wb") as f:
            f.write(public_key)

generate_rsa_keys()

# Load keys
with open(PRIVATE_KEY_FILE, "rb") as f:
    private_key = RSA.import_key(f.read())
with open(PUBLIC_KEY_FILE, "rb") as f:
    public_key = RSA.import_key(f.read())

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

def sign_data(data: str) -> str:
    """Sign data using the private key."""
    h = SHA256.new(data.encode('utf-8'))
    signature = pkcs1_15.new(private_key).sign(h)
    return base64.b64encode(signature).decode('utf-8')

def verify_signature(data: str, signature: str) -> bool:
    """Verify the QR data signature using the public key."""
    try:
        h = SHA256.new(data.encode('utf-8'))
        pkcs1_15.new(public_key).verify(h, base64.b64decode(signature))
        return True
    except (ValueError, TypeError):
        return False

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
# Page 1: Generator (with Authentication)
# ---------------------------
def page_generator(public_url):
    st.title("🔑 QR Code Generator (Authenticated)")

    visitor_name = st.text_input("Visitor Name")
    homeowner_name = st.text_input("Homeowner Name")
    block_number = st.text_input("Block Number")
    purpose = st.text_area("Purpose of Visit")
    estimated_time = st.text_input("Estimated Time of Stay (e.g., 1 hour, 30 mins)")

    if st.button("Generate Secure QR"):
        token = base64.urlsafe_b64encode(os.urandom(6)).decode("utf-8")
        payload = f"{visitor_name}|{homeowner_name}|{block_number}|{estimated_time}|{token}"

        # 🔒 Sign the payload
        signature = sign_data(payload)

        scan_link = f"{public_url}/?page=Visitor&token={token}&sig={signature}"
        expiry_time = get_end_of_day()

        data = {
            "visitor": {
                "token": token,
                "visitor_name": visitor_name,
                "homeowner_name": homeowner_name,
                "block_number": block_number,
                "purpose": purpose,
                "estimated_time": estimated_time,
                "expiry_time": expiry_time.isoformat(),
                "scan_time": None,
                "id_uploaded": False,
                "signature": signature,
            }
        }
        save_data(data)

        st.success("✅ Secure QR Code Generated")
        qr_bytes = generate_qr(scan_link)
        st.image(qr_bytes, caption="Secure QR Code")
        st.info(f"Link valid until {expiry_time.strftime('%H:%M:%S')} today")

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
        st.error("❌ Invalid or missing QR token/signature")
        return

    data = load_data()
    visitor = data.get("visitor", {})

    # Verify authenticity
    expected_payload = f"{visitor.get('visitor_name','')}|{visitor.get('homeowner_name','')}|{visitor.get('block_number','')}|{visitor.get('estimated_time','')}|{token}"
    if not verify_signature(expected_payload, signature):
        st.error("🚫 QR code verification failed (tampered or invalid).")
        return

    expiry_time = datetime.fromisoformat(visitor["expiry_time"])
    if datetime.now() > expiry_time:
        st.error("⏱ QR Expired")
        return

    if not visitor["id_uploaded"]:
        uploaded_id = st.file_uploader("Upload ID (image)", type=["jpg", "jpeg", "png"])
        if uploaded_id:
            visitor["id_uploaded"] = True
            visitor["id_filename"] = uploaded_id.name
            data["visitor"] = visitor
            save_data(data)
            st.success("✅ ID uploaded successfully.")
            st.rerun()
        else:
            return

    st.subheader("QR Verified ✅ (Awaiting Security Confirmation)")

    if visitor.get("scan_time"):
        scanned_at = datetime.fromisoformat(visitor["scan_time"])
        estimated_duration = parse_estimated_time(visitor["estimated_time"])
        end_time = scanned_at + estimated_duration
        remaining = end_time - datetime.now()

        if remaining.total_seconds() > 0:
            st.success(f"⏳ Time left: {str(remaining).split('.')[0]}")
        else:
            st.error("⏱ Time expired.")
        st_autorefresh(interval=1000, key="visitor_refresh")
    else:
        st.info("⌛ Waiting for Security confirmation...")

# ---------------------------
# Page 3: Security
# ---------------------------
def page_security():
    from streamlit_autorefresh import st_autorefresh
    st.title("🛡 Security Dashboard")

    query_params = st.query_params
    token = query_params.get("token", None)
    signature = query_params.get("sig", None)

    data = load_data()
    visitor = data.get("visitor", {})

    if not visitor or visitor.get("token") != token:
        st.error("❌ Invalid or unrecognized QR.")
        return

    # Verify authenticity again
    payload = f"{visitor['visitor_name']}|{visitor['homeowner_name']}|{visitor['block_number']}|{visitor['estimated_time']}|{token}"
    if not verify_signature(payload, signature):
        st.error("🚫 QR code failed verification (possible forgery).")
        return

    expiry_time = datetime.fromisoformat(visitor["expiry_time"])
    if datetime.now() > expiry_time:
        st.error("⏱ QR Expired")
        return

    st.write(f"**Visitor Name:** {visitor['visitor_name']}")
    st.write(f"**Homeowner:** {visitor['homeowner_name']}")
    st.write(f"**Block:** {visitor['block_number']}")
    st.write(f"**Purpose:** {visitor['purpose']}")
    st.write(f"**Stay:** {visitor['estimated_time']}")

    if not visitor.get("scan_time"):
        if st.button("✅ Confirm Entry"):
            visitor["scan_time"] = datetime.now().isoformat()
            data["visitor"] = visitor
            save_data(data)
            st.success("Entry confirmed. Timer started.")
            st.rerun()
    else:
        scanned_at = datetime.fromisoformat(visitor["scan_time"])
        remaining = (scanned_at + parse_estimated_time(visitor["estimated_time"])) - datetime.now()
        if remaining.total_seconds() > 0:
            st.success(f"⏳ Time left: {str(remaining).split('.')[0]}")
        else:
            st.error("⏱ Time expired.")
        st_autorefresh(interval=1000, key="security_refresh")

# ---------------------------
# Main App
# ---------------------------
def main(public_url):
    pages = {"Generator": lambda: page_generator(public_url), "Visitor": page_visitor, "Security": page_security}
    default = st.query_params.get("page", "Generator")
    page = st.sidebar.radio("Navigate", list(pages.keys()), index=list(pages.keys()).index(default))
    pages[page]()

if __name__ == "__main__":
    st.session_state.setdefault("public_url", "https://app-yourappname.streamlit.app/")
    main(st.session_state["public_url"])
