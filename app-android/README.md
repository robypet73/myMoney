# App Android (APK)

Stessa pagina `portafoglio.html` del programma per PC, dentro un involucro [Capacitor](https://capacitorjs.com). **Non tocca** `build.py`, `portafoglio.html` né `portafogli/`: l'app usa una copia modificata al momento della compilazione.

| File | A cosa serve |
|---|---|
| `motore.js` | il programma Python (`build.py` + `fonti.py`) riscritto in JavaScript: elenco, salvataggio ed eliminazione dei portafogli (nella memoria dell'app), scarico da justETF, scheda dei titoli, prezzi |
| `prepara.py` | prepara `www/`: copia `portafoglio.html` con tre modifiche in memoria, scrive `seed.js` con i portafogli di `portafogli/`, le schede note dei titoli e le tabelle di `fonti.py` |
| `capacitor.config.json`, `package.json` | involucro Capacitor; `CapacitorHttp` rende nativo `fetch`, così justETF risponde senza limiti CORS |
| `../.github/workflows/android.yml` | compila l'APK e lo pubblica nella release **`android-latest`** (Releases del repository) |

## Come si ottiene l'APK

- Si compila da solo a ogni modifica di `portafoglio.html`, `portafogli/`, `fonti.py`, `icons/` o `app-android/` su `main`; oppure a mano da **Actions → Android APK → Run workflow**.
- Scaricalo da **Releases → App Android** (file `myMoney-Portafogli.apk`) e installalo sul telefono (consenti l'installazione da fonti sconosciute).
- Firma: se nel repository c'è il segreto `MYMONEY_KEYSTORE_B64` l'APK è firmato con quella chiave fissa e si installa sopra la versione precedente; altrimenti la firma è casuale e per aggiornare va disinstallata la versione precedente.

## Cosa fa e cosa no

- Come sul PC: apre l'ultimo portafoglio, scarica da justETF i dati e i prezzi **all'apertura**, salva/elimina portafogli, carica un JSON, frontiera, ribilanciamento.
- I portafogli stanno nella memoria dell'app (si parte da quelli della cartella `portafogli/`). Gli acquisti inseriti restano nell'app.
- Nell'app non ci sono «Report PDF» e «Scarica JSON» (stampa e scarico di file non sono disponibili nella pagina dell'app).
- Prova sul computer: `python app-android/prepara.py`, poi servi `app-android/www` con un server statico.
