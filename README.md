# myMoney

Una sola pagina, **`portafoglio.html`**, da cui si fa tutto. Ogni portafoglio è un file **JSON** nella cartella **`portafogli/`**. Un piccolo programma Python apre la pagina con l'ultimo portafoglio caricato e scarica da **justETF** i dati dei titoli e i prezzi aggiornati.

| File / cartella | A cosa serve |
|---|---|
| `avvia.cmd` | doppio clic su Windows: lancia `build.py` |
| `build.py` | il programma: server locale (solo su 127.0.0.1), scarico da justETF, lettura e salvataggio dei portafogli |
| `fonti.py` | scarica da justETF i dati di un titolo (scheda del fondo e storico dei prezzi in euro) |
| `widget.py`, `avvia-widget.cmd` | **widget per il desktop** (Windows, anche macOS/Linux): doppio clic su `avvia-widget.cmd` |
| `portafoglio.html` | **la pagina**: il codice di tutto; i dati del portafoglio scelto vengono inseriti dal programma |
| `portafogli/` | i portafogli: `nome_V1.json`, `nome_V2.json`… e lo schema |
| `portafogli/schema.json` | lo **schema JSON** (JSON Schema) del formato di un portafoglio |
| `portafogli/titoli/` | schede già complete dei titoli noti (caratteristiche e composizione); i prezzi si scaricano sempre |
| `icons/` | l'icona dell'app: `myMoney.ico` (Windows, per il collegamento sul desktop), `myMoney.icns` (macOS), `myMoney-256.png` (Linux) e le immagini per telefono e web |
| `crea-collegamento.cmd` | doppio clic su Windows: crea sul Desktop il collegamento «myMoney» con l'icona (altrimenti: tasto destro su `avvia.cmd` → Invia a → Desktop, poi Proprietà → Cambia icona → `icons\myMoney.ico`) |

Serve Python 3.9 o più recente, nient'altro.

## Uso

1. `avvia.cmd` (oppure `python build.py`). Si apre `portafoglio.html` con **l'ultimo portafoglio caricato** (`--file nome_V1.json` per forzarne uno). Dal menu «Portafoglio» in alto si passa a qualsiasi altro JSON della cartella.
2. **All'apertura parte da solo il download** dei prezzi da justETF (lo stato compare sotto i pulsanti). Alla prima apertura di un portafoglio, o in un giorno nuovo, il programma scarica anche scheda e storico dei suoi titoli: una finestra mostra l'avanzamento, poi la pagina si apre.
3. **Aggiorna i valori**: rifà lo scarico dei prezzi quando vuoi (finestra con l'avanzamento).
4. **Carica portafoglio (JSON)**: scegli un file nel formato qui sotto. Il programma lo salva in `portafogli/` (nome e versione esistenti non si sovrascrivono: cambia la versione), scarica i dati dei titoli e apre il portafoglio.
5. **Quante quote comprare…** (in Composizione, finché non hai acquisti tuoi): scrivi il totale da investire e per ogni titolo vedi, in base al peso e al prezzo di oggi, quante quote intere comprare e quanto spendi; il resto non investito è indicato. «Usa come miei acquisti» li registra come tuoi acquisti.
6. **Salva**: dalla schermata «Modifica portafoglio…» («Salva…») o dalla frontiera efficiente («Salva come nuovo portafoglio…») si scrive un nuovo `nome_Vn.json` in `portafogli/`, con nome (solo lettere e cifre), versione (1, 2, 3…) e descrizione.
7. **Modifica**: cambia nome, versione o descrizione del portafoglio aperto. Se nome e versione restano uguali si riscrive lo stesso file, altrimenti il file viene rinominato (gli acquisti inseriti nel browser lo seguono). Funziona sul PC e nell'app.
8. **Modifica portafoglio…** (in Composizione, sopra la tabella; la sezione col valore dell'investimento non c'è più): togli titoli o aggiungine scrivendo l'ISIN; un titolo nuovo entra all'1% (o col peso che scrivi) e gli altri si riducono in proporzione; se ne togli uno, gli altri crescono in proporzione; i pesi si possono cambiare a mano e vengono sempre riportati a 100. Per ogni titolo puoi inserire **gli acquisti e le vendite** (data, tipo, quote, prezzo; anche più di una operazione): senza prezzo si usa la chiusura del giorno, per un titolo nuovo il prezzo va scritto; non si può vendere più di quanto si ha. Le operazioni inserite sostituiscono quelle del portafoglio e finiscono nel campo `transazioni` del nuovo file. Nella stessa schermata **«Salva…»** scrive il risultato come nuova versione di questo portafoglio o come nuovo portafoglio (menu «Nuova versione di…» o nome nuovo; i dati dei titoli nuovi vengono scaricati da justETF), **«Annulla»** scarta tutto, **«Ribilancia…»** apre una **bozza non salvata** (il file originale non cambia): ribilanci i pesi con la **frontiera efficiente** (un titolo nuovo può entrare fino al 30%, i limiti si cambiano) e, quando il portafoglio è buono, **Salva…** lo scrive come nuovo portafoglio oppure come nuova versione di uno esistente (scelta nel menu della finestra). Funziona sul PC e nell'app. Gli acquisti e le vendite dei titoli tolti non passano nella bozza.
9. **Elimina**: cancella il JSON del portafoglio aperto (chiede conferma).
10. **Cartella…**: sceglie dove stanno i JSON dei portafogli, **sul computer o su Google Drive**. Si apre una finestra con le cartelle suggerite (Google Drive per desktop, se installato: l'unità virtuale `G:\Il mio Drive` o `My Drive`, la cartella in `Google Drive` nella home o in `Library/CloudStorage`; e Documenti), il pulsante **Sfoglia…** (finestra di scelta del sistema) e il campo del percorso. Una cartella `portafogli` dentro Drive o Documenti, se non c'è, viene creata. **Google Drive online, senza sincronizzarlo sul computer**: nella finestra, «Google Drive» apre la sezione per collegare una cartella online tramite una piccola web app di Google Apps Script (`drive/mymoney_drive.gs`, pulsante «Copia lo script»): si incolla in script.google.com, si cambia la CHIAVE, si distribuisce come «App web» (Esegui come: Me, Accesso: Chiunque) e si incolla in myMoney l'indirizzo con `?key=…`. Il programma legge i portafogli dalla cartella online `myMoneyPortafogli` (copia di lavoro nella cartella dell'utente, riletta ogni 20 secondi) e ogni salvataggio, modifica o eliminazione va online; se Google non risponde il salvataggio non avviene. Chi conosce l'indirizzo con la chiave può leggere e modificare i portafogli. Se la cartella nuova non ha portafogli, riceve una copia di quelli della cartella di prima (che restano dove sono) e `schema.json`. «Cartella del programma» torna alla cartella `portafogli/` del repository. La scelta è ricordata (`config.json` nella cartella dell'utente) e si può dare anche da riga di comando: `python build.py --cartella "G:\Il mio Drive\portafogli"` (`--cartella ""` per tornare a quella del programma). Le schede note dei titoli restano nel programma.
11. **Scarica JSON**: esporta la definizione del portafoglio aperto (con i vincoli della frontiera).

## Widget per il desktop

`avvia-widget.cmd` apre una piccola finestra sempre in primo piano, come il widget Android: valore del portafoglio, rendita sull'investito, **rendimento nel periodo del grafico** (1 mese… YTD, Tutto) e variazione di oggi, grafico con gli assi e l'ora dell'ultimo aggiornamento. Usa gli stessi portafogli e la stessa cartella scelta nel programma (anche Google Drive) e scarica da justETF i prezzi aggiornati, da solo (ogni ora, scelta dalle impostazioni). Serve solo Python con Tkinter, già incluso nell'installazione normale di Python per Windows.

- **Port. ›**: passa al portafoglio successivo, in cerchio.
- **⚙** (o tasto destro): periodo del grafico, frequenza di aggiornamento (15 minuti… 6 ore), dimensione (piccolo, medio, grande), «Avvia con Windows», «Aggiorna ora», «Chiudi il widget».
- Si sposta trascinandolo con il mouse (la posizione è ricordata); il doppio clic aggiorna subito.
- **Posizione rispetto alle altre finestre** (nelle impostazioni): «Dietro le finestre» (predefinita: se ci passi sopra con un'altra finestra il widget resta sotto, come un widget sul desktop), «Normale» o «Sempre in primo piano».
- **Avvio automatico con Windows**: la spunta «Avvia con Windows» nelle impostazioni, oppure un doppio clic su `widget-avvio-automatico.cmd` (per toglierlo: `widget-avvio-automatico.cmd off`). Mette un piccolo file `myMoney-widget.vbs` nella cartella Esecuzione automatica dell'utente, che avvia il widget senza finestre nere.
- Non ha bisogno che `avvia.cmd` sia aperto: legge i file JSON direttamente. `python widget.py --prova` stampa i valori senza aprire la finestra.

## Sintesi e grafici

- **Valore attuale** e **Investito**: l'investito è il costo (a costo medio) di ciò che hai ancora in portafoglio; quello che hai venduto non ne fa parte.
- **Risultato**: guadagno non realizzato (valore − investito) più guadagno realizzato con le vendite, in euro e in percentuale **sull'investito**, con il rendimento annuo ponderato nel tempo (XIRR).
- **Rendita strategia**: come saresti oggi se avessi messo 1 € su ogni titolo che hai in portafoglio il giorno del suo primo acquisto (media dei titoli): misura la bontà della scelta dei titoli a prescindere dagli importi.
- **Zoom orizzontale** sui grafici nel tempo: con la rotellina del mouse (PC) ci si avvicina o allontana attorno al cursore, con il pizzico a due dita (telefono, app Android); trascinando ci si sposta nel tempo; «↺ tutto» o il doppio clic mostrano di nuovo tutto il periodo. A grafico intero la rotellina fa scorrere la pagina.
- I grafici nel tempo hanno i periodi 1, 3, 5 anni, **YTD** (da inizio anno) e Tutto; anche il grafico del widget Android.
- **Ribilanciamento…** (in Frontiera efficiente): quante quote comprare o vendere per arrivare a un obiettivo, con le spunte **Permetti acquisti** e **Permetti vendite**. Una spunta tolta significa che il ribilanciamento non tocca quelle operazioni e usa solo l'altra: solo acquisti (le quote che hai restano e il «Nuovo versamento» va ai fondi sotto obiettivo), solo vendite (si vende l'eccesso e il ricavato resta liquido), nessuna spunta (nessuna operazione).

## Formato di un portafoglio

Lo schema è in [`portafogli/schema.json`](portafogli/schema.json). Esempio (`portafogli/esempio_V1.json`):

```json
{
  "$schema": "schema.json",
  "nome": "mioPortafoglio",
  "versione": "V1",
  "descrizione": "Una frase che spiega il portafoglio",
  "valore": 40000,
  "titoli": [
    {"isin": "IE00B4L5Y983", "peso": 60},
    {"isin": "IE00B1FZS798", "peso": 40}
  ],
  "vincoli": {
    "fondi": { "IE00B4L5Y983": [40, 70] },
    "classi": { "Azionario": [50, 80] }
  }
}
```

| Campo | Regola |
|---|---|
| `nome` | obbligatorio; solo lettere e cifre (niente spazi né simboli), al massimo 30 caratteri; il file si chiama `nome_Vn.json` |
| `versione` | obbligatoria; `V1`, `V2`, `V3`… (anche solo il numero) |
| `descrizione` | obbligatoria; al massimo 300 caratteri |
| `valore` | **facoltativo**; investimento totale in euro da ripartire sui pesi (se manca: 10.000) |
| `titoli` | da 1 a 30 elementi `{ "isin", "peso" }`; ISIN con cifra di controllo valida, non ripetuto; `peso` in percentuale (0 per un titolo già venduto), la somma deve dare 100 (tolleranza 0,5) |
| `vincoli` | **facoltativo**; limiti iniziali della frontiera in percentuale, `[minimo, massimo]`: `fondi` per ISIN e `classi` (`Azionario`, `Obbligazionario`, `Materie prime`). Se manca: peso del piano ±10 punti per fondo |
| `transazioni` | **facoltativo**; gli acquisti e le vendite reali: elementi `{ "isin", "data" (AAAA-MM-GG), "tipo" (`acquisto` o `vendita`), "quote", "prezzo" }`. Le quote sono sempre positive (la vendita si indica con il tipo); a pari data gli acquisti vengono prima; non si può vendere più di quanto si ha. Un titolo già venduto resta in `titoli` con `peso` 0. Con le transazioni la pagina calcola quote, costo medio (la vendita toglie quote al costo medio), rendita non realizzata e realizzata, andamento e rendimento nel tempo; se mancano, mostra acquisti d'esempio dal piano. |

## Dove stanno i dati

- **`portafogli/`** (nel repository, o la cartella scelta con «Cartella…»): i JSON dei portafogli e lo schema; le schede note dei titoli (`portafogli/titoli/<ISIN>.json`) restano sempre nel repository.
- **Cartella dell'utente** (`%LOCALAPPDATA%\myMoney`, oppure `~/.myMoney`): `prezzi.json` (ultimo scarico), `ultimo.json` (ultimo portafoglio aperto), `config.json` (cartella scelta) e `titoli/<ISIN>.json` (scheda e storico dei prezzi scaricati oggi da justETF).
- Gli acquisti inseriti nella pagina restano nel browser, separati per portafoglio.
- Nessun database.

## Limiti da conoscere

- Tutti i prezzi vengono da justETF, in euro. Lo **storico** è quello del grafico di justETF (riferimento XETRA); il **prezzo di oggi** è quello in tempo reale di **gettex** (media tra denaro e lettera), lo stesso che justETF mostra nel riquadro «Quotazione», così i valori coincidono con la pagina del titolo. Il prezzo gettex viene letto dal canale in tempo reale che usa il sito di justETF (non è un'interfaccia ufficiale: se non risponde o cambia, restano i prezzi XETRA del grafico e compare l'avviso «gettex non raggiunto»). Vale per la pagina, l'app, il widget Android e il widget del desktop. Possono restare piccole differenze con Borsa Italiana o con un'altra sede di negoziazione.
- Per un ISIN non presente in `portafogli/titoli/` la composizione viene dalla pagina di justETF, che elenca solo i primi paesi, settori e titoli: la quota restante finisce in «Altro». Aree geografiche e valute sono stimate dai paesi. «Scambi medi a Milano» non è disponibile per questi titoli («n.d.»).
- Lo storico in comune parte dal titolo con la storia più breve.
- Analisi tecnica sui dati storici, non consulenza.
