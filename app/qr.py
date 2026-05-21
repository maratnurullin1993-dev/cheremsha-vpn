from io import BytesIO

import qrcode


def make_qr_png(data: str) -> bytes:
    qr = qrcode.QRCode(version=1, box_size=8, border=3)
    qr.add_data(data)
    qr.make(fit=True)
    image = qr.make_image(fill_color="#E6FBFF", back_color="#081019")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()

