# Sunet la distanță – note pentru o sesiune nouă cu Claude
Folderul proiectului: C:\Users\Razvan\Documents\Claude working\Sunet la distanta (făcut pe 31 oct. 2026).

Addon NVDA (2026.1 și mai nou; Răzvan are 2026.3, cu Remote-ul inclus în NVDA) care aduce sunetul calculatorului controlat, nu doar vocea NVDA. Calculatorul controlat e departe, prin internet. Addonul se instalează pe ambele calculatoare.

## Cum merge (versiunea 0.2.0; 0.1.x a mers la Răzvan pe 31 oct., dar se auzea prost)
- __init__.py: înlocuiește _remoteClient.transport.TCPTransport.parse ca să prindă mesajele proprii „x_sunet…” înainte ca Remote-ul să le arunce (tipurile necunoscute sunt ignorate de Remote, iar serverul de legătură le dă mai departe ca pe orice mesaj).
- Cel care controlează trimite din 4 în 4 secunde x_sunet_cere (pornit da/nu). Cel controlat preia sunetul cât timp a primit o cerere în ultimele 12 secunde, trimite x_sunet (a = μ-law în base64, sr = 16000 implicit, bucăți de 100 ms, liniștea nu se trimite) și din 3 în 3 secunde x_sunet_stare (mod „proces” sau „sistem”, eroare). Dacă în coada Remote-ului sunt peste 25 de mesaje, sare bucata, ca vorbirea să nu întârzie.
- captura.py: WASAPI. Întâi process loopback (ActivateAudioInterfaceAsync, VAD\Process_Loopback, exclude NVDA și programele pornite de el, cu eveniment), merge pe Windows 11. Altfel loopback pe ieșirea implicită (Windows 10: se aude și vocea NVDA de acolo, iar cel care controlează e anunțat o dată). AUTOCONVERTPCM dă direct 16 biți mono; dacă nu merge, se convertește din formatul plăcii.
- Din 0.2.0 sunetul e Opus, stereo, 48000 Hz (opusCodec.py + opus.dll x64 v1.4 de la ShiftMediaProject, licența în opus-licenta.txt; are nevoie de VCRUNTIME140, pe care îl are NVDA). Mesaj x_sunet cu c="opus", p = 5 pachete de 20 ms în base64. Calitatea din Setări: Normală 96, Bună 128 (implicit), Foarte bună 192 kbps (conf bitrate). Dacă opus.dll nu se încarcă, rămâne codec.py: μ-law mono 16 kHz (c="ulaw").
- Redare: nvwave.WavePlayer (canalele și frecvența după ce vine), un sfert de secundă de rezervă, cel mult 1,2 secunde întârziere.
- Comenzi (merg și în timp ce controlezi, sunt înregistrate ca locale în Remote): NVDA+Control+Shift+S pornește/oprește (doar pentru legătura de acum), NVDA+Control+Shift+plus/minus volumul din 10 în 10, și de pe tastatura numerică (alese de Răzvan pe 31 oct.). Setările în config.conf["sunetLaDistanta"]: pornireAutomata (implicit da: la fiecare conectare cu Remote-ul sunetul pornește singur), volum, bitrate, permiteTrimiterea; pornireAutomata și permiteTrimiterea sunt și în Setări NVDA, categoria Sunet la distanță (PanouSetari).
- Anunțuri: „nu primesc sunet, addonul trebuie instalat și pe calculatorul controlat” (după 10 secunde fără stare), eroare de preluare, Windows 10.

## De urmărit
- Netestat pe Windows: posibile erori în declarațiile COM din captura.py (comtypes). Jurnalul NVDA arată „Sunet la distanță: …”.
- Serverul public al Remote-ului s-ar putea să nu lase atâta sunet; varianta de rezervă e un server propriu.
