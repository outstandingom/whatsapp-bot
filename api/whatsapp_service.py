"""
Meta WhatsApp Cloud API Service module.
Handles outbound messaging, media upload/download, and Cloud API communication.
"""

import os
import logging
import httpx

logger = logging.getLogger("whatsapp_service")

# Static directory for uploaded and received photos/documents
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def get_env_var(key: str, default: str = "") -> str:
    """Retrieve stripped environment variable or fallback default."""
    return os.getenv(key, default).strip()


def send_meta_whatsapp_message(recipient_number: str, message_text: str, phone_id: str = None):
    """
    Send text message to user via Meta WhatsApp Cloud API.
    Returns (success: bool, response_or_error: str).
    """
    token = get_env_var("WHATSAPP_TOKEN")
    phone_id = (phone_id or get_env_var("WHATSAPP_PHONE_NUMBER_ID")).strip()

    if not token or not phone_id:
        return False, "Meta WhatsApp Token or Phone Number ID is not configured."

    url = f"https://graph.facebook.com/v21.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient_number,
        "type": "text",
        "text": {"preview_url": False, "body": message_text}
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            res = client.post(url, headers=headers, json=payload)
            return res.status_code == 200, res.text
    except Exception as e:
        logger.error(f"[Meta Send Message] Error sending to {recipient_number}: {e}")
        return False, str(e)


def upload_meta_media(file_bytes: bytes, filename: str, mime_type: str = "application/octet-stream") -> str:
    """
    Uploads photo or document binary to Meta WhatsApp Media API and returns media_id.
    """
    token = get_env_var("WHATSAPP_TOKEN")
    phone_id = get_env_var("WHATSAPP_PHONE_NUMBER_ID")
    if not token or not phone_id:
        return None

    url = f"https://graph.facebook.com/v21.0/{phone_id}/media"
    headers = {"Authorization": f"Bearer {token}"}
    files = {
        "file": (filename, file_bytes, mime_type),
    }
    data = {"messaging_product": "whatsapp"}

    try:
        with httpx.Client(timeout=30.0) as client:
            res = client.post(url, headers=headers, files=files, data=data)
            if res.status_code == 200:
                return res.json().get("id")
            logger.error(f"[Meta Media Upload] Failed {res.status_code}: {res.text}")
            return None
    except Exception as e:
        logger.error(f"[Meta Media Upload] Exception: {e}")
        return None


def send_meta_whatsapp_media(recipient_number: str, media_type: str, media_id: str = None, media_link: str = None, caption: str = "", filename: str = "", phone_id: str = None):
    """
    Send photo or document to user via Meta WhatsApp Cloud API.
    Returns (success: bool, response_or_error: str).
    """
    token = get_env_var("WHATSAPP_TOKEN")
    phone_id = (phone_id or get_env_var("WHATSAPP_PHONE_NUMBER_ID")).strip()
    if not token or not phone_id:
        return False, "Meta WhatsApp Token or Phone Number ID is not configured."

    url = f"https://graph.facebook.com/v21.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    media_payload = {}
    if media_id:
        media_payload["id"] = media_id
    elif media_link:
        media_payload["link"] = media_link

    if caption:
        media_payload["caption"] = caption
    if media_type == "document" and filename:
        media_payload["filename"] = filename

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient_number,
        "type": media_type,
        media_type: media_payload
    }

    try:
        with httpx.Client(timeout=20.0) as client:
            res = client.post(url, headers=headers, json=payload)
            return res.status_code == 200, res.text
    except Exception as e:
        logger.error(f"[Meta Send Media] Error sending to {recipient_number}: {e}")
        return False, str(e)


def download_meta_media(media_id: str, default_ext: str = ".bin") -> tuple:
    """
    Downloads incoming media from Meta WhatsApp Cloud API and saves locally to /uploads.
    Returns (url, filename, mime_type).
    """
    token = get_env_var("WHATSAPP_TOKEN")
    if not token or not media_id:
        return None, None, None

    try:
        meta_url = f"https://graph.facebook.com/v21.0/{media_id}"
        headers = {"Authorization": f"Bearer {token}"}
        with httpx.Client(timeout=20.0) as client:
            res1 = client.get(meta_url, headers=headers)
            if res1.status_code != 200:
                logger.error(f"[Meta Media Download] Metadata failed for {media_id}: {res1.text}")
                return None, None, None

            data = res1.json()
            download_url = data.get("url")
            mime_type = data.get("mime_type", "application/octet-stream")

            res2 = client.get(download_url, headers={"Authorization": f"Bearer {token}", "User-Agent": "WhatsAppBot/1.0"})
            if res2.status_code == 200:
                ext = default_ext
                if "jpeg" in mime_type or "jpg" in mime_type:
                    ext = ".jpg"
                elif "png" in mime_type:
                    ext = ".png"
                elif "pdf" in mime_type:
                    ext = ".pdf"
                elif "webp" in mime_type:
                    ext = ".webp"

                fname = f"wa_{media_id}{ext}"
                local_path = os.path.join(UPLOAD_DIR, fname)
                with open(local_path, "wb") as f:
                    f.write(res2.content)
                return f"/uploads/{fname}", fname, mime_type
    except Exception as e:
        logger.error(f"[Meta Media Download] Error: {e}")

    return None, None, None
