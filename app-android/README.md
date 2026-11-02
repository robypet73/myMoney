# App Android

Stessa pagina `index.html` dentro un involucro Capacitor. Il codice nativo (CapacitorHttp) non ha il blocco CORS del browser,
quindi `native.js` scarica da Yahoo Finance e justETF direttamente dal telefono, senza GitHub né server.

L'APK si costruisce con il workflow **Android APK** (Actions → Android APK → Run workflow, o a ogni modifica di `index.html`,
`native.js` o `sw.js`) e si pubblica nella release `android-latest`: da telefono apri
`https://github.com/robypet73/myMoney/releases/tag/android-latest`, scarica `myMoney.apk` e installalo
(Impostazioni → consenti l'installazione da questa fonte).
