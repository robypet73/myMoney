/* myMoney · cartella dei portafogli su Google Drive, letta e scritta direttamente online.
   Incolla questo script in https://script.google.com (Nuovo progetto), cambia CHIAVE, poi
   Distribuisci → Nuova distribuzione → App web → Esegui come: Me · Chi ha accesso: Chiunque.
   L'indirizzo della web app + ?key=LA-TUA-CHIAVE si incolla in myMoney (Cartella… → Google Drive).
   Chi conosce l'indirizzo con la chiave può leggere e scrivere i portafogli: tienili riservati. */
const CHIAVE = 'CAMBIA-QUESTA-FRASE-SEGRETA';   // una frase lunga, difficile da indovinare
const CARTELLA = 'myMoneyPortafogli';            // nome della cartella in Drive (si crea se manca)

function cartella_() {
  const it = DriveApp.getFoldersByName(CARTELLA);
  return it.hasNext() ? it.next() : DriveApp.createFolder(CARTELLA);
}
function out_(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}
function doGet(e) {  // elenco dei JSON: {files: [{name, text, mtime}]}
  if (!e || !e.parameter || e.parameter.key !== CHIAVE) return out_({ errore: 'chiave errata' });
  const files = [], it = cartella_().getFiles();
  while (it.hasNext()) {
    const f = it.next(), n = f.getName();
    if (/\.json$/i.test(n)) files.push({ name: n, text: f.getBlob().getDataAsString('UTF-8'), mtime: f.getLastUpdated().getTime() });
  }
  return out_({ files: files });
}
function doPost(e) {  // {key, write: [{name, text}], trash: [name]}
  let r;
  try { r = JSON.parse(e.postData.contents); } catch (x) { return out_({ errore: 'richiesta non valida' }); }
  if (!r || r.key !== CHIAVE) return out_({ errore: 'chiave errata' });
  const c = cartella_();
  (r.write || []).forEach(function (w) {
    if (!/^[A-Za-z0-9_.-]+\.json$/.test(w.name)) return;
    const it = c.getFilesByName(w.name);
    if (it.hasNext()) it.next().setContent(w.text); else c.createFile(w.name, w.text, MimeType.PLAIN_TEXT);
  });
  (r.trash || []).forEach(function (n) {
    const it = c.getFilesByName(n);
    while (it.hasNext()) it.next().setTrashed(true);
  });
  return out_({ ok: true });
}
