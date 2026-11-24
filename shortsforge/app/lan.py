"""
lan.py - helpers for "use ShortsForge from your phone" (same Wi-Fi as the PC).

WHY it exists:
    The app runs on your PC, but you may want to use it from a phone or tablet. The phone opens
    a web address that points to your PC; the PC still does all the video work.

HOW it works:
    - local_ip(): finds the PC's address on your home network (like 192.168.1.20).
    - is_private_host(): the server only accepts requests addressed to a PRIVATE network address,
      never to a public one.
    - qr_svg(): draws the web address as a QR code (pure Python, `segno` package) so you can
      scan it with the phone camera instead of typing a long address.
    This mode is OFF until you press "Turn on phone access" in Settings.

SAFETY NOTES:
    - Needs the secret token (it is inside the QR code) for every request.
    - Traffic on your Wi-Fi is not encrypted (plain http), so use it only on a Wi-Fi you trust.
    - Windows will ask once to allow network access: choose "Private networks".
    - Phones cannot use the PC's file picker or open folders on the PC; uploads work instead.

HOW TO IMPROVE:
    - Add https with a self-signed certificate, or a one-time pairing code.
    - Show the address as text too, for phones that cannot scan.
"""

import io
import ipaddress
import socket


def local_ip() -> str:
    """This PC's address on the local network, or '' if it is not on a network."""
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("10.255.255.255", 1))           # no data is sent; it only picks a route
        address = probe.getsockname()[0]
        probe.close()
        if address and not address.startswith("127."):
            return address
    except OSError:
        pass
    try:
        address = socket.gethostbyname(socket.gethostname())
        return "" if address.startswith("127.") else address
    except OSError:
        return ""


def is_private_host(host: str) -> bool:
    """True for private-network addresses (192.168.x.x, 10.x.x.x, 172.16-31.x.x) and *.local."""
    host = (host or "").strip().lower()
    if host.endswith(".local"):
        return True
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return False


def qr_svg(text: str) -> str:
    """The text as a QR code, returned as SVG markup (ready to put in a web page)."""
    import segno
    buffer = io.BytesIO()
    segno.make(text, error="m").save(buffer, kind="svg", scale=6, border=2, xmldecl=False,
                                     svgns=True, dark="#1b2226", light="#ffffff")
    return buffer.getvalue().decode("utf-8")
