"""WebSocket (RFC 6455) mínimo, solo librería estándar.

Lo justo para que el navegador hable con un socket ya abierto: el apretón de manos, y leer y
escribir tramas de texto, binarias y de control. No hay extensiones, ni subprotocolos, ni
compresión: el único cliente es xterm.js de esta consola.

Las tramas del cliente vienen siempre enmascaradas y las del servidor van siempre sin
enmascarar; una trama del cliente sin máscara es un error de protocolo, no una alternativa.
"""

from __future__ import annotations

import base64
import hashlib

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_CONT, OP_TEXT, OP_BINARY, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA

CLOSE_NORMAL, CLOSE_PROTOCOL, CLOSE_TOO_BIG, CLOSE_INTERNAL = 1000, 1002, 1009, 1011

# Un mensaje de teclado es diminuto; lo que puede pesar es un pegado. 1 MiB deja pegar un
# fichero razonable y corta lo que ya es un abuso.
MAX_MESSAGE_BYTES = 1 << 20


class ProtocolError(Exception):
    def __init__(self, message: str, code: int = CLOSE_PROTOCOL):
        super().__init__(message)
        self.code = code


def accept_key(client_key: str) -> str:
    return base64.b64encode(hashlib.sha1((client_key + GUID).encode("ascii")).digest()).decode()


def encode_frame(opcode: int, payload: bytes = b"") -> bytes:
    """Una trama completa (FIN=1) sin máscara, como las manda un servidor."""
    size = len(payload)
    if size < 126:
        head = bytes([0x80 | opcode, size])
    elif size < 1 << 16:
        head = bytes([0x80 | opcode, 126]) + size.to_bytes(2, "big")
    else:
        head = bytes([0x80 | opcode, 127]) + size.to_bytes(8, "big")
    return head + payload


def encode_close(code: int = CLOSE_NORMAL, reason: str = "") -> bytes:
    return encode_frame(OP_CLOSE, code.to_bytes(2, "big") + reason.encode("utf-8")[:120])


def _unmask(data: bytes, mask: bytes) -> bytes:
    if not data:
        return data
    key = (mask * (len(data) // 4 + 1))[:len(data)]
    return (int.from_bytes(data, "big") ^ int.from_bytes(key, "big")).to_bytes(len(data), "big")


class FrameParser:
    """Acumula bytes del socket y devuelve los mensajes completos: `(opcode, carga)`.

    Recompone los mensajes fragmentados (el navegador puede partir uno grande) y deja pasar
    los de control (ping/pong/close) tal cual, que pueden colarse entre los fragmentos.
    """

    def __init__(self, max_message: int = MAX_MESSAGE_BYTES):
        self._buf = bytearray()
        self._max = max_message
        self._frag_opcode: int | None = None
        self._frag = bytearray()

    def feed(self, data: bytes) -> list[tuple[int, bytes]]:
        self._buf += data
        messages: list[tuple[int, bytes]] = []
        while True:
            frame = self._next_frame()
            if frame is None:
                return messages
            fin, opcode, payload = frame

            if opcode >= OP_CLOSE:
                if not fin or len(payload) > 125:
                    raise ProtocolError("trama de control fragmentada o demasiado larga")
                messages.append((opcode, payload))
                continue

            if opcode == OP_CONT:
                if self._frag_opcode is None:
                    raise ProtocolError("continuación sin mensaje empezado")
            elif opcode in (OP_TEXT, OP_BINARY):
                if self._frag_opcode is not None:
                    raise ProtocolError("mensaje nuevo con otro sin terminar")
                self._frag_opcode = opcode
            else:
                raise ProtocolError(f"opcode desconocido {opcode:#x}")

            self._frag += payload
            if len(self._frag) > self._max:
                raise ProtocolError("mensaje demasiado grande", CLOSE_TOO_BIG)
            if fin:
                messages.append((self._frag_opcode, bytes(self._frag)))
                self._frag_opcode = None
                self._frag = bytearray()

    def _next_frame(self) -> tuple[bool, int, bytes] | None:
        buf = self._buf
        if len(buf) < 2:
            return None
        fin = bool(buf[0] & 0x80)
        if buf[0] & 0x70:
            raise ProtocolError("bits RSV activos sin extensión negociada")
        opcode = buf[0] & 0x0F
        if not buf[1] & 0x80:
            raise ProtocolError("el cliente debe enmascarar sus tramas")
        size = buf[1] & 0x7F
        offset = 2
        if size == 126:
            if len(buf) < 4:
                return None
            size = int.from_bytes(buf[2:4], "big")
            offset = 4
        elif size == 127:
            if len(buf) < 10:
                return None
            size = int.from_bytes(buf[2:10], "big")
            offset = 10
        # Se corta antes de esperar la carga: no se reserva memoria por lo que diga la cabecera.
        if size > self._max:
            raise ProtocolError("trama demasiado grande", CLOSE_TOO_BIG)
        end = offset + 4 + size
        if len(buf) < end:
            return None
        mask = bytes(buf[offset:offset + 4])
        payload = _unmask(bytes(buf[offset + 4:end]), mask)
        del buf[:end]
        return fin, opcode, payload
