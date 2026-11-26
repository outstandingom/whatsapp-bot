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


def get_meta_api_version() -> str:
    """Return configured Meta Graph API version (defaults to v23.0 for typing_indicator support)."""
    return get_env_var("WHATSAPP_API_VERSION", "v23.0") or "v23.0"


def send_meta_typing_indicator(message_id: str, phone_id: str = None, token: str = None) -> tuple[bool, str]:
    """
    Mark an incoming WhatsApp message as read and trigger the native WhatsApp 'typing...' bubble.
    Falls back to a plain read receipt if the API version/endpoint rejects typing_indicator.
    """
    token = (token or get_env_var("WHATSAPP_TOKEN")).strip()
    phone_id = (phone_id or get_env_var("WHATSAPP_PHONE_NUMBER_ID")).strip()
    msg_id = (message_id or "").strip()

    if not token or not phone_id or not msg_id:
        return False, "Missing WhatsApp token, phone_id, or incoming message_id."

    api_ver = get_meta_api_version()
    url = f"https://graph.facebook.com/{api_ver}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": msg_id,
        "typing_indicator": {"type": "text"},
    }

    try:
        with httpx.Client(timeout=5.0) as client:
            res = client.post(url, headers=headers, json=payload)
            if res.status_code == 200:
                return True, res.text
            logger.warning(f"[Meta Typing Indicator] Status {res.status_code}: {res.text}. Trying plain read receipt...")
            fallback_payload = {
                "messaging_product": "whatsapp",
                "status": "read",
                "message_id": msg_id,
            }
            fb = client.post(url, headers=headers, json=fallback_payload)
            return fb.status_code == 200, fb.text
    except Exception as e:
        logger.warning(f"[Meta Typing Indicator] Error: {e}")
        return False, str(e)


def send_meta_whatsapp_message(recipient_number: str, message_text: str, phone_id: str = None, token: str = None):
    """
    Send text message to user via Meta WhatsApp Cloud API.
    Returns (success: bool, response_or_error: str).
    """
    token = (token or get_env_var("WHATSAPP_TOKEN")).strip()
    phone_id = (phone_id or get_env_var("WHATSAPP_PHONE_NUMBER_ID")).strip()

    if not token or not phone_id:
        return False, "Meta WhatsApp Token or Phone Number ID is not configured."

    url = f"https://graph.facebook.com/{get_meta_api_version()}/{phone_id}/messages"
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


def upload_meta_media(file_bytes: bytes, filename: str, mime_type: str = "application/octet-stream", phone_id: str = None, token: str = None) -> str:
    """
    Uploads photo or document binary to Meta WhatsApp Media API and returns media_id.
    """
    token = (token or get_env_var("WHATSAPP_TOKEN")).strip()
    phone_id = (phone_id or get_env_var("WHATSAPP_PHONE_NUMBER_ID")).strip()
    if not token or not phone_id:
        return None

    url = f"https://graph.facebook.com/{get_meta_api_version()}/{phone_id}/media"
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


def send_meta_whatsapp_media(recipient_number: str, media_type: str, media_id: str = None, media_link: str = None, caption: str = "", filename: str = "", phone_id: str = None, token: str = None):
    """
    Send photo or document to user via Meta WhatsApp Cloud API.
    Returns (success: bool, response_or_error: str).
    """
    token = (token or get_env_var("WHATSAPP_TOKEN")).strip()
    phone_id = (phone_id or get_env_var("WHATSAPP_PHONE_NUMBER_ID")).strip()
    if not token or not phone_id:
        return False, "Meta WhatsApp Token or Phone Number ID is not configured."

    url = f"https://graph.facebook.com/{get_meta_api_version()}/{phone_id}/messages"
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


def download_meta_media(media_id: str, default_ext: str = ".bin", token: str = None) -> tuple:
    """
    Downloads incoming media from Meta WhatsApp Cloud API and saves locally to /uploads.
    Returns (url, filename, mime_type).
    """
    token = (token or get_env_var("WHATSAPP_TOKEN")).strip()
    if not token or not media_id:
        return None, None, None

    try:
        meta_url = f"https://graph.facebook.com/{get_meta_api_version()}/{media_id}"
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
