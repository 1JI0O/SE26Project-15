from app.services.code_analysis.lsp_bridge import decode_lsp_messages, encode_lsp_message


def test_encode_lsp_message_wraps_json() -> None:
    payload = {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
    encoded = encode_lsp_message(payload)
    assert encoded.startswith(b"Content-Length:")
    assert b"\r\n\r\n" in encoded
    assert b'"method":"initialize"' in encoded


def test_decode_lsp_messages_single_frame() -> None:
    body = '{"jsonrpc":"2.0","id":1,"result":{}}'
    buffer = bytearray(encode_lsp_message(body))
    messages, remaining = decode_lsp_messages(buffer)
    assert messages == [body]
    assert remaining == bytearray()


def test_decode_lsp_messages_multiple_frames() -> None:
    first = '{"jsonrpc":"2.0","id":1}'
    second = '{"jsonrpc":"2.0","id":2}'
    buffer = bytearray(encode_lsp_message(first) + encode_lsp_message(second))
    messages, remaining = decode_lsp_messages(buffer)
    assert messages == [first, second]
    assert remaining == bytearray()
