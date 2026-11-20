# App Android (APK)

Stessa pagina `portafoglio.html` del programma per PC, dentro un involucro [Capacitor](https://capacitorjs.com). **Non tocca** `build.py`, `portafoglio.html` né `portafogli/`: l'app usa una copia modificata al momento della compilazione.

| File | A cosa serve |
|---|---|
| `motore.js` | il programma Python (`build.py` + `fonti.py`) riscritto in JavaScript: elenco, salvataggio ed eliminazione dei portafogli (nella memoria dell'app), scarico da justETF, scheda dei titoli, prezzi |
| `prepara.py` | prepara `www/`: copia `portafoglio.html` con tre modifiche in memoria, scrive `seed.js` con i portafogli di `portafogli/`, le schede note dei titoli e le tabelle di `fonti.py` |
| `overlay/` | codice nativo Android aggiunto in compilazione: `MyMoneyFolderPlugin` (cartella scelta con il selettore di Android, sul telefono o su Google Drive), `MyMoneyWidget` + plugin (widget della schermata Home), risorse e permessi |
| `capacitor.config.json`, `package.json` | involucro Capacitor; `CapacitorHttp` rende nativo `fetch`, così justETF risponde senza limiti CORS |
| `../.github/workflows/android.yml` | compila l'APK e lo pubblica nella release **`android-latest`** (Releases del repository) |

## Come si ottiene l'APK

- Si compila da solo a ogni modifica di `portafoglio.html`, `portafogli/`, `fonti.py`, `icons/` o `app-android/` su `main`; oppure a mano da **Actions → Android APK → Run workflow**.
- Scaricalo da **Releases → App Android** (file `myMoney-Portafogli.apk`) e installalo sul telefono (consenti l'installazione da fonti sconosciute).
- Firma: se nel repository c'è il segreto `MYMONEY_KEYSTORE_B64` l'APK è firmato con quella chiave fissa e si installa sopra la versione precedente; altrimenti la firma è casuale e per aggiornare va disinstallata la versione precedente.

## Cartella dei portafogli (telefono o Google Drive)

Pulsante **Cartella…** in alto: si apre direttamente il selettore di cartelle di Android, dove scegli la memoria interna, la scheda SD o Google Drive. **Scollega** (compare con una cartella collegata) torna alla memoria dell'app. Quando la cartella è collegata:
- all'apertura i JSON della cartella diventano i portafogli dell'app; se la cartella è vuota riceve quelli dell'app (e `schema.json`);
- «Salva come nuovo portafoglio» e «Carica JSON» scrivono lì un `nome_Vn.json`; «Elimina» sposta il file nella sottocartella `_eliminati`.

## Widget della schermata Home

Aggiungi il widget «myMoney» dalla schermata Home (tieni premuto su uno spazio vuoto → Widget). Mostra il nome del portafoglio aperto, il **valore**, la **rendita** (sull'investito se hai inserito acquisti, altrimenti nell'ultimo anno), la variazione di oggi e il **grafico** dell'andamento. Si ridimensiona (più è alto, più dettagli). La pagina passa i dati al widget mentre l'app è aperta; il widget poi aggiorna il valore da solo con i prezzi di justETF (ogni 5 minuti a schermo acceso, se Android lo consente) e un tocco apre l'app.

## Cosa fa e cosa no

- Come sul PC: apre l'ultimo portafoglio, scarica da justETF i dati e i prezzi **all'apertura**, salva/elimina portafogli, carica un JSON, frontiera, ribilanciamento.
- I portafogli stanno nella memoria dell'app (si parte da quelli della cartella `portafogli/`). Gli acquisti inseriti restano nell'app.
- Nell'app non ci sono «Report PDF» e «Scarica JSON» (stampa e scarico di file non sono disponibili nella pagina dell'app).
- Prova sul computer: `python app-android/prepara.py`, poi servi `app-android/www` con un server statico.
