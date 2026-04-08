# MandraoKodi: Anatomia Tecnica e Flusso Dati

Questo documento descrive il funzionamento interno dell'addon MandraoKodi per facilitare future integrazioni in CBTV.

## 1. Gateway API e Autenticazione
Tutte le richieste passano attraverso un bridge Heroku che filtra i contenuti e gestisce le chiavi DRM.

*   **Endpoint Principale**: `https://test34344.herokuapp.com/filter.php`
*   **User-Agent (Mandatorio)**: `MandraKodi2@@1.2.80@@MandraKodi3@@S63TDC`
    *   *Nota*: Senza questo esatto UA, il server restituisce errore o liste vuote.

## 2. Parametri `numTest` (Sezioni)
Le liste dei canali vengono caricate passando il parametro `numTest` all'endpoint principale.

| Sezione | Codice `numTest` | Note |
| :--- | :--- | :--- |
| **Main Menu** | `A1A1` | Punto di ingresso principale |
| **Sky Live (TV)** | `A1A260` | Cinema, Serie TV, Documentari |
| **Sky Sport** | `A1A165` | La lista sportiva più stabile (non Sky 2) |
| **Sky Sport 2** | `A1A165A` | Lista alternativa |
| **MPD Nazioni** | `A1A134A` | Canali sportivi internazionali DASH |
| **Risolutore Sky** | `A1A159` | Richiede anche parametro `&id=[chid]` |

## 3. Risoluzione dei Canali (Il "Segreto")
Mandrao non espone link diretti nelle liste, ma stringhe di comando (es. `sky@@skyuno`).

### Flusso di Riproduzione Sky:
1.  **Chiamata**: `https://test34344.herokuapp.com/filter.php?numTest=A1A159&id=skyuno`
2.  **Risposta**: Un JSON contenente un campo crittografato `"data"`.
3.  **Decriptazione**: Il campo `"data"` è una stringa Base64 offuscata con **XOR**.
    *   **Chiave XOR**: `my_secret_key`
4.  **Risultato**: Un JSON in chiaro con:
    *   `manifest`: URL del file `.mpd` (DASH).
    *   `kid`: Key ID per DRM ClearKey.
    *   `key`: Chiave per DRM ClearKey.

## 4. Algoritmo di Decriptazione (Python)
```python
import base64

def decrypt_mandrao(data_b64, key="my_secret_key"):
    data = base64.b64decode(data_b64)
    key_bytes = key.encode()
    out = bytearray()
    for i in range(len(data)):
        out.append(data[i] ^ key_bytes[i % len(key_bytes)])
    return out.decode("utf-8")
```

## 5. Configurazione Player (Kodi)
Per riprodurre questi flussi su Kodi è necessario impostare `inputstream.adaptive`:
*   **MimeType**: `application/dash+xml`
*   **License Type**: `clearkey`
*   **Property**: `inputstream.adaptive.drm_legacy` = `org.w3.clearkey|KID:KEY`
*   **Headers**: Simulare NowTV per evitare blocchi IP (`Referer: https://www.nowtv.it`).

## 6. Note Storiche
*   In passato Mandrao usava `skyTV@@` che puntava direttamente alle API di Sky Italia, ma ora usa questo bridge Heroku (`A1A159`) che è molto più affidabile e gestisce il ClearKey in autonomia.
