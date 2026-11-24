# Sunet la distanță: codare μ-law (G.711), 8 biți pe eșantion, fără biblioteci în plus.
# Sunetul de 16 biți se înjumătățește, iar vorbirea și muzica se aud destul de clar.

from array import array


def _lin2ulaw(sample: int) -> int:
	BIAS = 0x84
	CLIP = 32635
	sign = 0x80 if sample < 0 else 0
	if sample < 0:
		sample = -sample
	if sample > CLIP:
		sample = CLIP
	sample += BIAS
	exponent = 7
	mask = 0x4000
	while exponent > 0 and not (sample & mask):
		exponent -= 1
		mask >>= 1
	mantissa = (sample >> (exponent + 3)) & 0x0F
	return ~(sign | (exponent << 4) | mantissa) & 0xFF


def _ulaw2lin(u: int) -> int:
	u = ~u & 0xFF
	sign = u & 0x80
	exponent = (u >> 4) & 0x07
	mantissa = u & 0x0F
	sample = ((mantissa << 3) + 0x84) << exponent
	sample -= 0x84
	return -sample if sign else sample


# tabel de codare: indexul e eșantionul de 16 biți citit fără semn (0…65535)
_ENC = bytes(_lin2ulaw(i - 65536 if i >= 32768 else i) for i in range(65536))
# tabel de decodare: fiecare octet μ-law dă doi octeți PCM (little-endian)
_DEC = [array("h", [_ulaw2lin(u)]).tobytes() for u in range(256)]


def encode(pcm16: bytes) -> bytes:
	"""PCM 16 biți mono (little-endian) -> μ-law."""
	a = array("H")
	a.frombytes(pcm16[: len(pcm16) // 2 * 2])
	return bytes(map(_ENC.__getitem__, a))


def decode(ulaw: bytes) -> bytes:
	"""μ-law -> PCM 16 biți mono."""
	return b"".join(map(_DEC.__getitem__, ulaw))


def isSilent(pcm16: bytes, threshold: int = 24) -> bool:
	"""Adevărat dacă bucata e liniște (nu are rost să fie trimisă)."""
	a = array("h")
	a.frombytes(pcm16[: len(pcm16) // 2 * 2])
	if not a:
		return True
	return max(a) < threshold and min(a) > -threshold
