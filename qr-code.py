import streamlit as st
import json
import qrcode
import io
from datetime import datetime, timedelta
from Crypto.PublicKey import RSA
from streamlit_autorefresh import st_autorefresh

# ---------- Helper Functions ----------

def generate_qr(data: str) -> bytes:
    """Generate a QR code image as bytes."""
    qr = qrcode.QRCode(version=1, box_size=6, border=3)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer

def load_data():
    """Load visitor data from file."""
    try:
        with open("scans.json", "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_data(data):
    """Save visitor data to file."""
    with open("scans.json", "w") as f:
        json.dump(data, f, indent=4)

def parse_estimated_time(time_str):
    """Convert '10 min', '30 min', '1 hour' to timedelta."""
    if "min" in time_str:
        return timedelta(minutes=int(time_str.split()[0]))
    elif "hour" in time_str:
        return timedelta(hours=int(time_str.split()[0]))
    else:
        return timedelta(minutes=15)

# ---------- Pages ----------

def page_generator():
    st.title("🕒 Visit Generator Page")

    visitor_name = st.text_input("Visitor Name")
    estimated_time = st.selectbox("Estimated Visit Time", ["10 min", "30 min", "1 hour"])

    if st.button("Generate Visit Token"):
        key = RSA.generate(1024)
        token = key.export_key().decode()
        data = load_data()
        data["visitor"] = {
            "name": visitor_name,
            "estimated_time": estimated_time,
            "token": token,
            "scan_time": None
        }
        save_data(data)
        st.success(f"✅ Token generated for {visitor_name}")
        st.session_state.generated_token = token

def page_visitor():
    st.title("👤 Visitor Page")

    data = load_data()
    visitor = data.get("visitor", {})

    if not visitor:
        st.info("No visitor data found. Please generate a token first.")
        return

    uploaded_id = st.file_uploader("Upload your ID card (image)", type=["jpg", "png", "jpeg"])

    if uploaded_id is not None:
        st.success("✅ ID uploaded successfully!")
        token = visitor["token"]
        scan_link = f"{st.session_state.get('public_url', '')}/?page=Security&token={token}"
        qr_bytes = generate_qr(scan_link)
        st.image(qr_bytes, caption="Show this QR to Security")

    if visitor.get("scan_time"):
        st.subheader("⏳ Time Remaining")
        scanned_at = datetime.fromisoformat(visitor["scan_time"])
        duration = parse_estimated_time(visitor["estimated_time"])
        end_time = scanned_at + duration
        remaining = end_time - datetime.now()

        if remaining.total_seconds() > 0:
            st.success(f"Time Left: {str(remaining).split('.')[0]}")
        else:
            st.error("⏱ Time expired.")

        st_autorefresh(interval=1000, key="visitor_refresh")
    else:
        st.info("⌛ Waiting for Security to confirm your entry.")

def page_security():
    st.title("🛡️ Security Page")

    token = st.query_params.get("token", [None])[0] if hasattr(st, "query_params") else None
    data = load_data()
    visitor = data.get("visitor", {})

    if not visitor or (token and token != visitor.get("token")):
        st.error("❌ Invalid or expired token.")
        return

    st.subheader("Visitor Info")
    st.write(f"**Name:** {visitor['name']}")
    st.write(f"**Estimated Time:** {visitor['estimated_time']}")

    # Confirm entry button (starts timer)
    if not visitor.get("scan_time"):
        if st.button("✅ Confirm Entry"):
            scan_time = datetime.now()
            visitor["scan_time"] = scan_time.isoformat()
            data["visitor"] = visitor
            save_data(data)
            st.success("Entry confirmed. Timer started.")
            st.rerun()

    # Countdown display
    if visitor.get("scan_time"):
        st.subheader("⏳ Time Remaining")
        scanned_at = datetime.fromisoformat(visitor["scan_time"])
        duration = parse_estimated_time(visitor["estimated_time"])
        end_time = scanned_at + duration
        remaining = end_time - datetime.now()

        if remaining.total_seconds() > 0:
            st.success(f"Time Left: {str(remaining).split('.')[0]}")
        else:
            st.error("⏱ Time expired.")

        st_autorefresh(interval=1000, key="security_refresh")

# ---------- Page Navigation ----------

st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to", ["Generator", "Visitor", "Security"])

if page == "Generator":
    page_generator()
elif page == "Visitor":
    page_visitor()
elif page == "Security":
    page_security()
