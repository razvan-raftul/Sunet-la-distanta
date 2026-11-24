# Sunet la distanță: Opus (aceeași codare ca în apelurile de pe internet), stereo, 48000 Hz.
# opus.dll (x64, v1.4, licență BSD în opus-licenta.txt) stă lângă acest fișier.

import ctypes
import os
from ctypes import POINTER, byref, c_int, c_int16, c_int32, c_void_p, c_char_p

RATE = 48000
CHANNELS = 2
FRAME = 960            # 20 ms la 48000 Hz
FRAME_BYTES = FRAME * CHANNELS * 2
OPUS_APPLICATION_AUDIO = 2049
OPUS_SET_BITRATE_REQUEST = 4002
OPUS_SET_COMPLEXITY_REQUEST = 4010
OPUS_SET_SIGNAL_REQUEST = 4024
OPUS_SIGNAL_MUSIC = 3002

_lib = None


def load():
	"""Încarcă opus.dll; întoarce False dacă nu se poate (atunci se folosește codarea veche)."""
	global _lib
	if _lib is not None:
		return True
	try:
		lib = ctypes.CDLL(os.path.join(os.path.dirname(__file__), "opus.dll"))
		lib.opus_encoder_create.restype = c_void_p
		lib.opus_encoder_create.argtypes = [c_int32, c_int, c_int, POINTER(c_int)]
		lib.opus_encode.restype = c_int32
		lib.opus_encode.argtypes = [c_void_p, POINTER(c_int16), c_int, c_char_p, c_int32]
		lib.opus_encoder_destroy.argtypes = [c_void_p]
		lib.opus_decoder_create.restype = c_void_p
		lib.opus_decoder_create.argtypes = [c_int32, c_int, POINTER(c_int)]
		lib.opus_decode.restype = c_int
		lib.opus_decode.argtypes = [c_void_p, c_char_p, c_int32, POINTER(c_int16), c_int, c_int]
		lib.opus_decoder_destroy.argtypes = [c_void_p]
		_lib = lib
		return True
	except OSError:
		return False


class Encoder:
	def __init__(self, bitrate: int):
		err = c_int()
		self._e = _lib.opus_encoder_create(RATE, CHANNELS, OPUS_APPLICATION_AUDIO, byref(err))
		if not self._e or err.value != 0:
			raise OSError("opus_encoder_create: %d" % err.value)
		_lib.opus_encoder_ctl(c_void_p(self._e), c_int(OPUS_SET_BITRATE_REQUEST), c_int(bitrate))
		_lib.opus_encoder_ctl(c_void_p(self._e), c_int(OPUS_SET_COMPLEXITY_REQUEST), c_int(8))
		_lib.opus_encoder_ctl(c_void_p(self._e), c_int(OPUS_SET_SIGNAL_REQUEST), c_int(OPUS_SIGNAL_MUSIC))
		self._out = ctypes.create_string_buffer(4000)

	def encode(self, pcm: bytes) -> bytes:
		"""Un cadru de 20 ms (PCM 16 biți stereo, 3840 de octeți) -> un pachet Opus."""
		buf = (c_int16 * (FRAME * CHANNELS)).from_buffer_copy(pcm)
		n = _lib.opus_encode(self._e, buf, FRAME, self._out, 4000)
		if n < 0:
			raise OSError("opus_encode: %d" % n)
		return self._out.raw[:n]

	def __del__(self):
		if getattr(self, "_e", None):
			_lib.opus_encoder_destroy(self._e)
			self._e = None


class Decoder:
	def __init__(self):
		err = c_int()
		self._d = _lib.opus_decoder_create(RATE, CHANNELS, byref(err))
		if not self._d or err.value != 0:
			raise OSError("opus_decoder_create: %d" % err.value)
		self._pcm = (c_int16 * (5760 * CHANNELS))()

	def decode(self, packet: bytes) -> bytes:
		n = _lib.opus_decode(self._d, packet, len(packet), self._pcm, 5760, 0)
		if n < 0:
			return b""
		return bytes(memoryview(self._pcm).cast("B")[: n * CHANNELS * 2])

	def __del__(self):
		if getattr(self, "_d", None):
			_lib.opus_decoder_destroy(self._d)
			self._d = None
