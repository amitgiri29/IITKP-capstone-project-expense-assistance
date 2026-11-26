"""Image capability check (P15, FR02). This build reads receipts from TEXT only.

Reading numbers from a receipt photo needs a vision model or OCR. OCR is not permitted in this project, and the
configured model (model.supports_vision) decides whether vision exists. Without it, the interim path is user
transcription: typed or pasted receipt details, text receipts and digital PDFs that contain real text.
"""

INTERIM_PATH = ('Type or paste the receipt details (merchant, date, amount, taxes), or upload a text receipt or a '
                'digital PDF invoice that contains real text. Scanned images cannot be read in this build.')


def vision_available(context, requested=None):
    """True only when the configured model accepts images (and the caller does not say otherwise)."""
    configured = bool(context is not None and context.model is not None and context.settings.model.supports_vision)
    return configured if requested is None else bool(requested) and configured


def check_image_capability(payload, context=None):
    """Evaluation entrypoint check_image_capability (GT119)."""
    supports = payload.get('model_supports_vision')
    if supports is None and context is not None:
        supports = vision_available(context)
    ocr = bool(payload.get('ocr_permitted'))
    if context is not None:
        context.events.emit('observation', name='claim_image_parsed', value=False)
    if not supports and not ocr:
        return {'run_status': 'UNSUPPORTED_CAPABILITY', 'claim_image_parsed': False,
                'action': 'Offer user transcription as the interim path.', 'message': INTERIM_PATH,
                'evidence_ids': ['P15', 'P20']}
    return {'run_status': 'OK', 'claim_image_parsed': False,
            'action': 'Image input is supported by the configured model; parse it in the receipt review route.',
            'message': 'Image reading is available.', 'evidence_ids': ['P15']}
