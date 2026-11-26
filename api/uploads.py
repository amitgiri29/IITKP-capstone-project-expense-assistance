"""Receipt upload validation before storage or any model call (P15, AC16)."""
import io
import struct
import zlib

from PIL import Image, UnidentifiedImageError

from api.errors import ApiError
from domain.registry import parameter

SIGNATURES = {b'\x89PNG\r\n\x1a\n': 'image/png', b'\xff\xd8\xff': 'image/jpeg'}


def limits():
    return parameter('PARAM-MAX-IMAGE-BYTES'), parameter('PARAM-MAX-IMAGES-PER-CLAIM')


def inspect_image(data, filename=''):
    """Return (mime, width, height) for decodable JPEG/PNG bytes or raise ApiError."""
    max_bytes, _ = limits()
    if len(data) > max_bytes:
        raise ApiError('PAYLOAD_TOO_LARGE', '%s is larger than the %d byte limit.' % (filename or 'Upload', max_bytes),
                       field='/files')
    mime = next((m for sig, m in SIGNATURES.items() if data.startswith(sig)), None)
    if mime is None:
        raise ApiError('UNSUPPORTED_MEDIA_TYPE', 'Only JPEG and PNG receipt images are accepted.', field='/files')
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ApiError('UNSUPPORTED_MEDIA_TYPE', 'The file is not a decodable JPEG or PNG image.', field='/files') from exc
    return mime, width, height


def tiny_png():
    """A valid 1x1 PNG built with the standard library."""
    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff)
    header = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
    pixels = zlib.compress(b'\x00\xff\xff\xff')
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', pixels) + chunk(b'IEND', b'')


def upload_from_payload(payload):
    """Materialize the test upload described by a case input (TEST_PROTOCOL section 4)."""
    if payload.get('upload'):
        spec = payload['upload']
        data = spec['bytes_text'].encode('utf-8') if 'bytes_text' in spec else bytes(spec.get('bytes', b''))
        return spec.get('filename', 'upload'), spec.get('mime', 'application/octet-stream'), data
    spec = payload['upload_generator']
    data = tiny_png()
    target = spec['valid_png_with_padding_bytes']
    return spec.get('filename', 'receipt.png'), 'image/png', data + b'\x00' * (target - len(data))


def validate_upload(payload, context):
    """Entrypoint validate_upload (GT117, GT118): send the bytes through the real POST /receipts route."""
    from api.main import local_client
    filename, mime, data = upload_from_payload(payload)
    traveler = next(iter(context.travelers))
    with local_client(context) as client:
        session = client.post('/sessions', json={'traveler_id': traveler}).json()
        response = client.post('/receipts', headers={'Authorization': 'Bearer ' + session['token']},
                               files=[('files', (filename, data, mime))])
    body = response.json()
    return {'http_status': response.status_code, 'error_code': body.get('error_code'),
            'message': body.get('message', ''), 'evidence_ids': ['P15']}
