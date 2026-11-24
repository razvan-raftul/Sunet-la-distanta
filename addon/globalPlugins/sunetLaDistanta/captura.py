# Sunet la distanță: preluarea sunetului calculatorului (WASAPI loopback).
#
# Pe Windows 11 se folosește „process loopback”: se preia tot sunetul, în afară de NVDA și de
# programele pornite de el (de exemplu sintetizatoarele), ca vocea NVDA să nu ajungă de două ori la
# cel care controlează. Unde nu se poate (Windows 10), se preia tot sunetul de pe ieșirea implicită.
# Rezultatul e mereu PCM 16 biți, mono sau stereo, la frecvența cerută.

import ctypes
import os
import threading
import time
from array import array
from ctypes import POINTER, Structure, byref, c_int, c_longlong, c_uint32, c_uint64, c_ulong, c_ushort, c_void_p, c_wchar_p
from ctypes.wintypes import DWORD, HANDLE, WORD

import comtypes
from comtypes import COMMETHOD, COMObject, GUID, HRESULT, IUnknown

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateEventW.restype = HANDLE
_k32.CreateEventW.argtypes = [c_void_p, ctypes.c_bool, ctypes.c_bool, c_wchar_p]
_k32.WaitForSingleObject.restype = DWORD
_k32.WaitForSingleObject.argtypes = [HANDLE, DWORD]
_k32.CloseHandle.argtypes = [HANDLE]

CLSCTX_ALL = 23
AUDCLNT_SHAREMODE_SHARED = 0
AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000
AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY = 0x08000000
AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM = 0x80000000
AUDCLNT_BUFFERFLAGS_SILENT = 0x2
WAVE_FORMAT_PCM = 1
WAVE_FORMAT_IEEE_FLOAT = 3
WAVE_FORMAT_EXTENSIBLE = 0xFFFE
VT_BLOB = 65
eRender = 0
eConsole = 0
BUFFER_100NS = 2_000_000  # 200 ms


class WAVEFORMATEX(Structure):
	_pack_ = 1
	_fields_ = [
		("wFormatTag", WORD),
		("nChannels", WORD),
		("nSamplesPerSec", DWORD),
		("nAvgBytesPerSec", DWORD),
		("nBlockAlign", WORD),
		("wBitsPerSample", WORD),
		("cbSize", WORD),
	]


class WAVEFORMATEXTENSIBLE(Structure):
	_pack_ = 1
	_fields_ = [
		("Format", WAVEFORMATEX),
		("wValidBitsPerSample", WORD),
		("dwChannelMask", DWORD),
		("SubFormat", GUID),
	]


class IAudioClient(IUnknown):
	_iid_ = GUID("{1CB9AD4C-DBFA-4c32-B178-C2F568A703B2}")
	_methods_ = [
		COMMETHOD(
			[], HRESULT, "Initialize",
			(["in"], c_int, "ShareMode"),
			(["in"], DWORD, "StreamFlags"),
			(["in"], c_longlong, "hnsBufferDuration"),
			(["in"], c_longlong, "hnsPeriodicity"),
			(["in"], POINTER(WAVEFORMATEX), "pFormat"),
			(["in"], POINTER(GUID), "AudioSessionGuid"),
		),
		COMMETHOD([], HRESULT, "GetBufferSize", (["out"], POINTER(c_uint32), "pNumBufferFrames")),
		COMMETHOD([], HRESULT, "GetStreamLatency", (["out"], POINTER(c_longlong), "phnsLatency")),
		COMMETHOD([], HRESULT, "GetCurrentPadding", (["out"], POINTER(c_uint32), "pNumPaddingFrames")),
		COMMETHOD(
			[], HRESULT, "IsFormatSupported",
			(["in"], c_int, "ShareMode"),
			(["in"], POINTER(WAVEFORMATEX), "pFormat"),
			(["out"], POINTER(POINTER(WAVEFORMATEX)), "ppClosestMatch"),
		),
		COMMETHOD([], HRESULT, "GetMixFormat", (["out"], POINTER(POINTER(WAVEFORMATEX)), "ppDeviceFormat")),
		COMMETHOD(
			[], HRESULT, "GetDevicePeriod",
			(["out"], POINTER(c_longlong), "phnsDefaultDevicePeriod"),
			(["out"], POINTER(c_longlong), "phnsMinimumDevicePeriod"),
		),
		COMMETHOD([], HRESULT, "Start"),
		COMMETHOD([], HRESULT, "Stop"),
		COMMETHOD([], HRESULT, "Reset"),
		COMMETHOD([], HRESULT, "SetEventHandle", (["in"], HANDLE, "eventHandle")),
		COMMETHOD([], HRESULT, "GetService", (["in"], POINTER(GUID), "riid"), (["out"], POINTER(c_void_p), "ppv")),
	]


class IAudioCaptureClient(IUnknown):
	_iid_ = GUID("{C8ADBD64-E71E-48a0-A4DE-185C395CD317}")
	_methods_ = [
		COMMETHOD(
			[], HRESULT, "GetBuffer",
			(["out"], POINTER(c_void_p), "ppData"),
			(["out"], POINTER(c_uint32), "pNumFramesToRead"),
			(["out"], POINTER(DWORD), "pdwFlags"),
			(["out"], POINTER(c_uint64), "pu64DevicePosition"),
			(["out"], POINTER(c_uint64), "pu64QPCPosition"),
		),
		COMMETHOD([], HRESULT, "ReleaseBuffer", (["in"], c_uint32, "NumFramesRead")),
		COMMETHOD([], HRESULT, "GetNextPacketSize", (["out"], POINTER(c_uint32), "pNumFramesInNextPacket")),
	]


class IMMDevice(IUnknown):
	_iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
	_methods_ = [
		COMMETHOD(
			[], HRESULT, "Activate",
			(["in"], POINTER(GUID), "iid"),
			(["in"], DWORD, "dwClsCtx"),
			(["in"], c_void_p, "pActivationParams"),
			(["out"], POINTER(c_void_p), "ppInterface"),
		),
	]


class IMMDeviceEnumerator(IUnknown):
	_iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
	_methods_ = [
		COMMETHOD([], HRESULT, "EnumAudioEndpoints", (["in"], c_int, "dataFlow"), (["in"], DWORD, "dwStateMask"), (["out"], POINTER(c_void_p), "ppDevices")),
		COMMETHOD([], HRESULT, "GetDefaultAudioEndpoint", (["in"], c_int, "dataFlow"), (["in"], c_int, "role"), (["out"], POINTER(POINTER(IMMDevice)), "ppEndpoint")),
	]


CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")


# --- process loopback (Windows 11): ActivateAudioInterfaceAsync ---

class IActivateAudioInterfaceAsyncOperation(IUnknown):
	_iid_ = GUID("{72A22D78-CDE4-431D-B8CC-843A71199B6D}")
	_methods_ = [
		COMMETHOD(
			[], HRESULT, "GetActivateResult",
			(["out"], POINTER(c_int), "activateResult"),
			(["out"], POINTER(POINTER(IUnknown)), "activatedInterface"),
		),
	]


class IActivateAudioInterfaceCompletionHandler(IUnknown):
	_iid_ = GUID("{41D949AB-9862-444A-80F6-C261334DA5EB}")
	_methods_ = [
		COMMETHOD([], HRESULT, "ActivateCompleted", (["in"], POINTER(IActivateAudioInterfaceAsyncOperation), "activateOperation")),
	]


class IAgileObject(IUnknown):
	_iid_ = GUID("{94ea2b94-e9cc-49e0-c0ff-ee64ca8f5b90}")
	_methods_ = []


class _Handler(COMObject):
	_com_interfaces_ = [IActivateAudioInterfaceCompletionHandler, IAgileObject]

	def __init__(self):
		super().__init__()
		self.done = threading.Event()
		self.client = None
		self.hr = None

	def ActivateCompleted(self, activateOperation):
		try:
			hr, unk = activateOperation.GetActivateResult()
			self.hr = hr
			if hr >= 0 and unk:
				self.client = unk.QueryInterface(IAudioClient)
		except Exception as e:  # noqa: BLE001
			self.hr = getattr(e, "hresult", -1)
		finally:
			self.done.set()
		return 0


class AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS(Structure):
	_fields_ = [("TargetProcessId", DWORD), ("ProcessLoopbackMode", c_int)]


class AUDIOCLIENT_ACTIVATION_PARAMS(Structure):
	_fields_ = [("ActivationType", c_int), ("ProcessLoopbackParams", AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS)]


class BLOB(Structure):
	_fields_ = [("cbSize", c_ulong), ("pBlobData", c_void_p)]


class PROPVARIANT(Structure):
	_fields_ = [("vt", c_ushort), ("r1", c_ushort), ("r2", c_ushort), ("r3", c_ushort), ("blob", BLOB)]


AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK = 1
PROCESS_LOOPBACK_MODE_EXCLUDE_TARGET_PROCESS_TREE = 1
VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK = "VAD\\Process_Loopback"


def _formatPcm(rate: int, channels: int = 1) -> WAVEFORMATEX:
	f = WAVEFORMATEX()
	f.wFormatTag = WAVE_FORMAT_PCM
	f.nChannels = channels
	f.nSamplesPerSec = rate
	f.wBitsPerSample = 16
	f.nBlockAlign = 2 * channels
	f.nAvgBytesPerSec = rate * f.nBlockAlign
	f.cbSize = 0
	return f


def _activateProcessLoopback():
	"""IAudioClient care preia tot sunetul în afară de NVDA, sau None dacă Windows nu știe asta."""
	params = AUDIOCLIENT_ACTIVATION_PARAMS()
	params.ActivationType = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK
	params.ProcessLoopbackParams.TargetProcessId = os.getpid()
	params.ProcessLoopbackParams.ProcessLoopbackMode = PROCESS_LOOPBACK_MODE_EXCLUDE_TARGET_PROCESS_TREE
	pv = PROPVARIANT()
	pv.vt = VT_BLOB
	pv.blob.cbSize = ctypes.sizeof(params)
	pv.blob.pBlobData = ctypes.cast(byref(params), c_void_p)
	handler = _Handler()
	pHandler = handler.QueryInterface(IActivateAudioInterfaceCompletionHandler)
	op = POINTER(IActivateAudioInterfaceAsyncOperation)()
	fn = ctypes.WinDLL("Mmdevapi").ActivateAudioInterfaceAsync
	fn.restype = HRESULT
	fn.argtypes = [c_wchar_p, POINTER(GUID), POINTER(PROPVARIANT), POINTER(IActivateAudioInterfaceCompletionHandler), POINTER(POINTER(IActivateAudioInterfaceAsyncOperation))]
	iid = GUID(str(IAudioClient._iid_))
	fn(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK, byref(iid), byref(pv), pHandler, byref(op))
	if not handler.done.wait(5):
		return None
	if handler.hr is None or handler.hr < 0:
		return None
	return handler.client


def _activateSystemLoopback():
	"""IAudioClient pe ieșirea implicită: preia tot sunetul, inclusiv vocea NVDA."""
	enum = comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, CLSCTX_ALL)
	dev = enum.GetDefaultAudioEndpoint(eRender, eConsole)
	iid = GUID(str(IAudioClient._iid_))
	p = dev.Activate(byref(iid), CLSCTX_ALL, None)
	return ctypes.cast(c_void_p(p), POINTER(IAudioClient))


class Captura:
	"""Preia sunetul într-un fir separat și dă bucăți de PCM 16 biți mono la onChunk(bytes)."""

	def __init__(self, rate: int, onChunk, chunkMs: int = 100, channels: int = 1):
		self.rate = rate
		self.channels = channels
		self.onChunk = onChunk
		self.chunkBytes = rate * 2 * channels * chunkMs // 1000
		self.mode = None  # „proces” (fără NVDA) sau „sistem” (tot sunetul)
		self.error = None
		self._stop = threading.Event()
		self._thread = threading.Thread(target=self._run, name="SunetLaDistanta-captura", daemon=True)
		self._ready = threading.Event()
		self._event = None

	def start(self):
		self._thread.start()
		self._ready.wait(8)

	def stop(self):
		self._stop.set()
		if self._thread.is_alive():
			self._thread.join(2)

	@property
	def running(self) -> bool:
		return self._thread.is_alive() and not self._stop.is_set()

	def _open(self):
		"""Deschide captura; întoarce (client, format, conversie). conversie=None înseamnă că Windows dă deja formatul nostru."""
		want = _formatPcm(self.rate, self.channels)
		flags = AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY
		client = None
		try:
			client = _activateProcessLoopback()
		except Exception:  # noqa: BLE001
			client = None
		if client is not None:
			# captura fără NVDA merge doar cu eveniment (Windows anunță când are sunet)
			client.Initialize(AUDCLNT_SHAREMODE_SHARED, flags | AUDCLNT_STREAMFLAGS_EVENTCALLBACK, BUFFER_100NS, 0, byref(want), None)
			self._event = _k32.CreateEventW(None, False, False, None)
			client.SetEventHandle(self._event)
			self.mode = "proces"
			return client, want, None
		# Windows 10: tot sunetul de pe ieșirea implicită
		client = _activateSystemLoopback()
		try:
			client.Initialize(AUDCLNT_SHAREMODE_SHARED, flags, BUFFER_100NS, 0, byref(want), None)
			self.mode = "sistem"
			return client, want, None
		except Exception:  # noqa: BLE001
			client = _activateSystemLoopback()
			mix = client.GetMixFormat().contents
			fmt = WAVEFORMATEX.from_buffer_copy(mix)
			isFloat = fmt.wFormatTag == WAVE_FORMAT_IEEE_FLOAT or (fmt.wFormatTag == WAVE_FORMAT_EXTENSIBLE and fmt.wBitsPerSample == 32)
			client.Initialize(AUDCLNT_SHAREMODE_SHARED, AUDCLNT_STREAMFLAGS_LOOPBACK, BUFFER_100NS, 0, ctypes.cast(client.GetMixFormat(), POINTER(WAVEFORMATEX)), None)
			self.mode = "sistem"
			return client, fmt, (isFloat, fmt.nChannels, fmt.nSamplesPerSec, fmt.wBitsPerSample)

	def _convert(self, data: bytes, conv) -> bytes:
		"""Din formatul plăcii (de obicei float 32 biți, stereo, 48000) în 16 biți mono la frecvența noastră."""
		isFloat, ch, srcRate, bits = conv
		if isFloat:
			a = array("f")
			a.frombytes(data[: len(data) // 4 * 4])
			scale = 32767.0
		elif bits == 16:
			a = array("h")
			a.frombytes(data[: len(data) // 2 * 2])
			scale = 1.0
		else:
			return b""
		chans = [a[i::ch] for i in range(ch)]
		if self.channels == 1:
			outs = [[sum(v) / ch for v in zip(*chans)] if ch > 1 else list(chans[0])]
		else:
			outs = [list(chans[0]), list(chans[1] if ch > 1 else chans[0])]
		step = max(1, round(srcRate / self.rate))
		if step > 1:
			res = []
			for c in outs:
				parts = [c[i::step] for i in range(step)]
				n = min(len(p) for p in parts)
				res.append([sum(p[k] for p in parts) / step for k in range(n)])
			outs = res
		if len(outs) == 1:
			seq = outs[0]
		else:
			seq = [x for pair in zip(outs[0], outs[1]) for x in pair]
		out = array("h", (max(-32768, min(32767, int(x * scale))) for x in seq))
		return out.tobytes()

	def _run(self):
		comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
		client = None
		try:
			client, fmt, conv = self._open()
			cap = ctypes.cast(c_void_p(client.GetService(byref(GUID(str(IAudioCaptureClient._iid_))))), POINTER(IAudioCaptureClient))
			block = fmt.nBlockAlign
			client.Start()
			self._ready.set()
			pending = bytearray()
			while not self._stop.is_set():
				if self._event:
					_k32.WaitForSingleObject(self._event, 100)
				else:
					time.sleep(0.01)
				n = cap.GetNextPacketSize()
				while n:
					ptr, frames, flags, _dev, _qpc = cap.GetBuffer()
					size = frames * block
					if flags & AUDCLNT_BUFFERFLAGS_SILENT or not ptr:
						data = bytes(size)
					else:
						data = ctypes.string_at(ptr, size)
					cap.ReleaseBuffer(frames)
					pending += self._convert(data, conv) if conv else data
					n = cap.GetNextPacketSize()
				while len(pending) >= self.chunkBytes:
					chunk = bytes(pending[: self.chunkBytes])
					del pending[: self.chunkBytes]
					try:
						self.onChunk(chunk)
					except Exception:  # noqa: BLE001
						pass
			client.Stop()
		except Exception as e:  # noqa: BLE001
			self.error = repr(e)
		finally:
			self._ready.set()
			self._stop.set()
			client = None
			if self._event:
				_k32.CloseHandle(self._event)
				self._event = None
			try:
				comtypes.CoUninitialize()
			except Exception:  # noqa: BLE001
				pass
