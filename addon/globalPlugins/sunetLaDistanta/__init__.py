# Sunet la distanță: aduce sunetul calculatorului controlat prin Remote-ul inclus în NVDA.
#
# Pe calculatorul controlat se preia sunetul (fără vocea NVDA, unde Windows permite) și se trimite
# prin aceeași legătură ca Remote-ul, cu mesaje proprii („x_sunet”). Pe calculatorul care controlează
# se redă. Addonul trebuie instalat pe amândouă calculatoarele.

import base64
import json
import threading
import time
from collections import deque

import addonHandler
import config
import globalPluginHandler
import gui
from gui import guiHelper, settingsDialogs
import nvwave
import ui
import wx
from logHandler import log
from scriptHandler import script

from . import actualizare, codec, opusCodec

addonHandler.initTranslation()

CATEGORIE = "Sunet la distanță"
MSG_AUDIO = "x_sunet"          # bucată de sunet: c = „opus” (p = pachete în base64) sau „ulaw” (a = base64), sr, ch
MSG_STARE = "x_sunet_stare"    # de la cel controlat: mod = „proces” sau „sistem”, eroare
MSG_CERE = "x_sunet_cere"      # de la cel care controlează: pornit = adevărat/fals (se repetă din 4 în 4 secunde)

config.conf.spec["sunetLaDistanta"] = {
	"pornireAutomata": "boolean(default=True)",
	"volum": "integer(default=80, min=0, max=100)",
	"bitrate": "integer(default=128000)",
	"permiteTrimiterea": "boolean(default=True)",
}


def _conf():
	return config.conf["sunetLaDistanta"]


def _remote():
	try:
		import _remoteClient
	except ImportError:
		return None
	return _remoteClient._remoteClient


def _connected(t) -> bool:
	return t is not None and getattr(t, "connected", False)


class Redare(threading.Thread):
	"""Redă sunetul primit, cu o mică rezervă (un sfert de secundă) ca să nu se rupă; nu lasă întârzierea să crească."""

	def __init__(self):
		super().__init__(name="SunetLaDistanta-redare", daemon=True)
		self._buf = deque()
		self._bytes = 0
		self._cv = threading.Condition()
		self._stop = False
		self._sr = 16000
		self._ch = 1
		self._player = None
		self._newSr = None
		self._dec = None

	def decodeOpus(self, packets):
		"""Pachetele Opus -> PCM stereo 48000 (decodorul ține minte sunetul dinainte, de aceea e unul singur)."""
		if self._dec is None:
			self._dec = opusCodec.Decoder()
		return b"".join(self._dec.decode(p) for p in packets)

	def push(self, pcm: bytes, sr: int, ch: int = 1):
		with self._cv:
			if sr != self._sr or ch != self._ch:
				self._buf.clear()
				self._bytes = 0
				self._sr = sr
				self._ch = ch
				self._newSr = sr
			self._buf.append(pcm)
			self._bytes += len(pcm)
			limit = self._sr * 2 * self._ch * 1.2   # cel mult 1,2 secunde în așteptare
			while self._bytes > limit and len(self._buf) > 1:
				self._bytes -= len(self._buf.popleft())
			self._cv.notify()

	def setVolume(self, pct: int):
		p = self._player
		if p:
			try:
				p.setVolume(all=max(0, min(100, pct)) / 100)
			except Exception:  # noqa: BLE001
				log.debugWarning("Sunet la distanță: nu pot schimba volumul", exc_info=True)

	def stopPlayback(self):
		with self._cv:
			self._stop = True
			self._buf.clear()
			self._bytes = 0
			self._cv.notify()

	def _makePlayer(self):
		if self._player:
			try:
				self._player.close()
			except Exception:  # noqa: BLE001
				pass
		try:
			dev = config.conf["audio"]["outputDevice"]
		except KeyError:
			dev = nvwave.WavePlayer.DEFAULT_DEVICE_KEY
		self._player = nvwave.WavePlayer(channels=self._ch, samplesPerSec=self._sr, bitsPerSample=16, outputDevice=dev, wantDucking=False)
		try:
			self._player.enableTrimmingLeadingSilence(False)
		except Exception:  # noqa: BLE001
			pass
		self.setVolume(_conf()["volum"])

	def run(self):
		playing = False
		lastData = time.time()
		while True:
			with self._cv:
				while not self._stop:
					need = 1 if playing else self._sr * 2 * self._ch // 4   # pornește după un sfert de secundă de sunet
					if self._bytes >= need:
						break
					if playing and time.time() - lastData > 0.6:
						playing = False
					self._cv.wait(0.2)
					if self._player and not self._buf and time.time() - lastData > 2:
						try:
							self._player.idle()
						except Exception:  # noqa: BLE001
							pass
				if self._stop:
					break
				chunk = self._buf.popleft()
				self._bytes -= len(chunk)
				newSr = self._newSr
				self._newSr = None
			if self._player is None or newSr:
				try:
					self._makePlayer()
				except Exception:  # noqa: BLE001
					log.error("Sunet la distanță: nu pot deschide placa de sunet", exc_info=True)
					time.sleep(1)
					continue
			playing = True
			lastData = time.time()
			try:
				self._player.feed(chunk)
			except Exception:  # noqa: BLE001
				log.debugWarning("Sunet la distanță: eroare la redare", exc_info=True)
				self._player = None
		if self._player:
			try:
				self._player.stop()
				self._player.close()
			except Exception:  # noqa: BLE001
				pass
			self._player = None


class PanouSetari(settingsDialogs.SettingsPanel):
	title = CATEGORIE

	def makeSettings(self, settingsSizer):
		h = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
		self.auto = h.addItem(wx.CheckBox(self, label="&Pornește sunetul automat când mă conectez cu Remote-ul"))
		self.auto.SetValue(_conf()["pornireAutomata"])
		self.trimite = h.addItem(wx.CheckBox(self, label="&Trimite sunetul acestui calculator când e controlat"))
		self.trimite.SetValue(_conf()["permiteTrimiterea"])
		self._rates = [96000, 128000, 192000]
		self.calitate = h.addLabeledControl("&Calitatea sunetului trimis", wx.Choice, choices=["Normală", "Bună", "Foarte bună"])
		br = _conf()["bitrate"]
		self.calitate.SetSelection(self._rates.index(br) if br in self._rates else 1)

	def onSave(self):
		_conf()["bitrate"] = self._rates[max(0, self.calitate.GetSelection())]
		_conf()["pornireAutomata"] = self.auto.GetValue()
		_conf()["permiteTrimiterea"] = self.trimite.GetValue()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	scriptCategory = CATEGORIE

	def __init__(self):
		super().__init__()
		self._redare = None
		self._captura = None
		self._ceruta = 0.0           # ultima cerere de sunet primită de la cel care controlează
		self._ultimaCerere = 0.0     # ultima cerere trimisă de noi
		self._stareTrimisa = 0.0
		self._primitStare = False
		self._avertizat = set()
		self._leaderConectatDin = None
		self._activ = _conf()["pornireAutomata"]   # pentru legătura de acum; la fiecare conectare nouă se ia din setări
		self._patchTransport()
		settingsDialogs.NVDASettingsDialog.categoryClasses.append(PanouSetari)
		self._timer = wx.CallLater(1000, self._tick)
		actualizare.verifica_mai_tarziu()

	def terminate(self):
		try:
			self._timer.Stop()
		except Exception:  # noqa: BLE001
			pass
		self._opresteRedarea()
		self._opresteCaptura()
		self._unpatchTransport()
		try:
			settingsDialogs.NVDASettingsDialog.categoryClasses.remove(PanouSetari)
		except ValueError:
			pass
		rc = _remote()
		if rc:
			for s in (self.script_comuta, self.script_maiTare, self.script_maiIncet):
				rc.unregisterLocalScript(s)
		super().terminate()

	# ---------------------------------------------------------------- legătura cu Remote-ul
	def _patchTransport(self):
		try:
			from _remoteClient import transport
		except ImportError:
			log.warning("Sunet la distanță: Remote-ul inclus în NVDA nu există în această versiune.")
			return
		self._transportCls = transport.TCPTransport
		self._origParse = transport.TCPTransport.parse
		plugin = self
		orig = self._origParse

		def parse(tself, line: bytes):
			if b'"x_sunet' in line:
				try:
					obj = json.loads(line)
				except ValueError:
					obj = None
				if obj and str(obj.get("type", "")).startswith(MSG_AUDIO):
					plugin._primit(tself, obj)
					return
			return orig(tself, line)

		transport.TCPTransport.parse = parse

	def _unpatchTransport(self):
		if getattr(self, "_origParse", None):
			self._transportCls.parse = self._origParse
			self._origParse = None

	def _primit(self, transport, obj):
		"""Rulează în firul de citire al Remote-ului: trebuie să fie scurt."""
		t = obj.get("type")
		rc = _remote()
		if rc is None:
			return
		if t == MSG_AUDIO and transport is rc.leaderTransport:
			if not self._activ or self._redare is None:
				return
			try:
				if obj.get("c") == "opus":
					if not opusCodec.load():
						if "opus" not in self._avertizat:
							self._avertizat.add("opus")
							wx.CallAfter(ui.message, "Sunet la distanță: nu pot încărca Opus pe acest calculator.")
						return
					pcm = self._redare.decodeOpus([base64.b64decode(x) for x in obj.get("p", [])])
					self._redare.push(pcm, opusCodec.RATE, opusCodec.CHANNELS)
				else:
					pcm = codec.decode(base64.b64decode(obj.get("a", "")))
					self._redare.push(pcm, int(obj.get("sr", 16000)), 1)
			except Exception:  # noqa: BLE001
				log.debugWarning("Sunet la distanță: bucată de sunet stricată", exc_info=True)
		elif t == MSG_STARE and transport is rc.leaderTransport:
			self._primitStare = True
			mod, eroare = obj.get("mod"), obj.get("eroare")
			if eroare and "eroare" not in self._avertizat:
				self._avertizat.add("eroare")
				wx.CallAfter(ui.message, "Sunet la distanță: pe calculatorul controlat nu se poate prelua sunetul.")
			elif mod == "sistem" and "sistem" not in self._avertizat:
				self._avertizat.add("sistem")
				wx.CallAfter(ui.message, "Sunet la distanță: calculatorul controlat are Windows 10, așa că în sunet se aude și vocea NVDA de acolo.")
		elif t == MSG_CERE and transport is rc.followerTransport:
			self._ceruta = time.time() if obj.get("pornit") else 0.0

	# ---------------------------------------------------------------- verificarea din secundă în secundă
	def _tick(self):
		try:
			self._verifica()
		except Exception:  # noqa: BLE001
			log.debugWarning("Sunet la distanță: eroare la verificare", exc_info=True)
		finally:
			self._timer = wx.CallLater(1000, self._tick)

	def _verifica(self):
		rc = _remote()
		if rc is None:
			self._opresteRedarea()
			self._opresteCaptura()
			return
		for s in (self.script_comuta, self.script_maiTare, self.script_maiIncet):
			if s not in rc.localScripts:
				rc.registerLocalScript(s)
		now = time.time()

		# eu controlez: cer sunetul și îl redau
		lt = rc.leaderTransport
		if _connected(lt):
			if self._leaderConectatDin is None:
				self._leaderConectatDin = now
				self._primitStare = False
				self._avertizat.clear()
				self._activ = _conf()["pornireAutomata"]
				self._ultimaCerere = 0.0
			on = self._activ
			if on and self._redare is None:
				self._redare = Redare()
				self._redare.start()
			if not on:
				self._opresteRedarea()
			if now - self._ultimaCerere > 4:
				self._ultimaCerere = now
				lt.send(MSG_CERE, pornit=on)
			if on and not self._primitStare and now - self._leaderConectatDin > 10 and "lipsa" not in self._avertizat:
				self._avertizat.add("lipsa")
				ui.message("Sunet la distanță: nu primesc sunet. Addonul trebuie instalat și pe calculatorul controlat.")
		else:
			self._leaderConectatDin = None
			self._opresteRedarea()

		# sunt controlat: trimit sunetul cât timp mi se cere
		ft = rc.followerTransport
		vrea = _connected(ft) and _conf()["permiteTrimiterea"] and now - self._ceruta < 12
		if vrea and self._captura is None:
			self._pornesteCaptura(ft)
		elif not vrea and self._captura is not None:
			self._opresteCaptura()
		if self._captura is not None and _connected(ft) and now - self._stareTrimisa > 3:
			self._stareTrimisa = now
			c = self._captura
			ft.send(MSG_STARE, mod=c.mode or "", eroare=c.error or "")
			if c.error:
				log.warning("Sunet la distanță: captura s-a oprit: " + c.error)

	def _opresteRedarea(self):
		if self._redare is not None:
			self._redare.stopPlayback()
			self._redare = None

	def _pornesteCaptura(self, ft):
		from .captura import Captura

		useOpus = opusCodec.load()
		enc = None
		if useOpus:
			try:
				br = int(_conf()["bitrate"])
				enc = opusCodec.Encoder(br if br in (96000, 128000, 192000) else 128000)
			except Exception:  # noqa: BLE001
				log.warning("Sunet la distanță: Opus nu merge, folosesc codarea simplă", exc_info=True)
				useOpus = False
		sr, ch = (opusCodec.RATE, opusCodec.CHANNELS) if useOpus else (16000, 1)

		def send(t, **kw):
			q = getattr(t, "queue", None)
			if q is not None and q.qsize() > 25:
				return   # legătura nu ține pasul: sar peste bucata asta ca vorbirea să nu întârzie
			t.send(MSG_AUDIO, **kw)

		def onChunk(pcm):
			if codec.isSilent(pcm):
				return
			t = _remote()
			t = t.followerTransport if t else None
			if not _connected(t):
				return
			if useOpus:
				fb = opusCodec.FRAME_BYTES
				packets = [base64.b64encode(enc.encode(pcm[i:i + fb])).decode("ascii") for i in range(0, len(pcm) - fb + 1, fb)]
				send(t, c="opus", p=packets)
			else:
				send(t, c="ulaw", a=base64.b64encode(codec.encode(pcm)).decode("ascii"), sr=sr)

		self._captura = Captura(sr, onChunk, channels=ch)
		self._captura.start()
		self._stareTrimisa = 0.0

	def _opresteCaptura(self):
		if self._captura is not None:
			c = self._captura
			self._captura = None
			threading.Thread(target=c.stop, daemon=True).start()

	# ---------------------------------------------------------------- comenzi
	@script(description="Pornește sau oprește sunetul de la calculatorul controlat", gesture="kb:NVDA+shift+control+s")
	def script_comuta(self, gesture):
		self._activ = not self._activ
		self._ultimaCerere = 0.0
		if not self._activ:
			self._opresteRedarea()
		ui.message("Sunetul de la distanță pornit" if self._activ else "Sunetul de la distanță oprit")

	def _volum(self, delta):
		c = _conf()
		c["volum"] = max(0, min(100, c["volum"] + delta))
		if self._redare:
			self._redare.setVolume(c["volum"])
		ui.message("Volum %d la sută" % c["volum"])

	@script(description="Dă mai tare sunetul de la calculatorul controlat", gestures=["kb:NVDA+shift+control+=", "kb:NVDA+shift+control+numpadPlus"])
	def script_maiTare(self, gesture):
		self._volum(10)

	@script(description="Dă mai încet sunetul de la calculatorul controlat", gestures=["kb:NVDA+shift+control+-", "kb:NVDA+shift+control+numpadMinus"])
	def script_maiIncet(self, gesture):
		self._volum(-10)
