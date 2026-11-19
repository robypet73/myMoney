# myMoney

App Python con interfaccia nel browser che scarica da Yahoo Finance l'anagrafica e i prezzi di ETF, ETC ed ETN, li salva in un database SQLite (`etf.db`) e propone tre portafogli: **Sharpe**, **bilanciato** e **aggressivo**.

## Requisiti

- **Python 3.9 o successivo** (python.org; su Windows spunta «Add Python to PATH» durante l'installazione). Non serve altro: la pagina usa il browser che hai già.
- Connessione a internet (Yahoo Finance, justETF, OpenFIGI, ESMA, BCE).
- Circa 100–300 MB di spazio per il database, secondo quanti storici scarichi.

## Installazione e avvio (nessuna build)

Scarica o clona il repository, apri un terminale nella sua cartella ed esegui:

**Windows** (PowerShell o Prompt dei comandi)
```
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python mymoney.py
```

**Mac e Linux**
```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python mymoney.py
```

Si apre il browser su `http://127.0.0.1:8765` (se non si apre, copia l'indirizzo che il programma stampa). **Il programma resta acceso nel terminale**: fa da ponte verso Yahoo, che non si può interrogare direttamente da una pagina web, e verso il database. Per chiuderlo: Ctrl+C. Il server ascolta solo sul tuo computer.

Le volte successive basta riattivare l'ambiente (`.venv\Scripts\activate` o `source .venv/bin/activate`) e lanciare `python mymoney.py`.

Opzioni: `--db FILE` (altro file di database), `--porta N` (se 8765 è occupata ne cerca una libera da sola), `--no-browser`.

## Build: programma unico senza Python (facoltativo)

Per avere un solo file da copiare e avviare con un doppio clic (`myMoney.exe` su Windows, `myMoney` su Mac e Linux), anche su computer senza Python:

```
pip install -r requirements.txt pyinstaller
python build.py
```

Il risultato è in `dist/myMoney` (circa 60 MB; la build richiede 1–2 minuti). **Va costruito su ogni sistema operativo per cui serve**: un `.exe` si crea solo su Windows. Il database `etf.db` viene creato **accanto al programma**, quindi copia o sposta il file insieme al database. Gli stessi comandi della riga di comando valgono senza `python mymoney.py`: `myMoney justetf`, `myMoney esporta`, ecc. Windows e macOS possono avvisare che il programma non è firmato («SmartScreen», «sviluppatore non identificato»): è normale per un programma fatto in casa. Ho provato la build e l'avvio solo su Linux; su Windows e Mac non l'ho provata.

## Prima volta

1. Premi **Scarica titoli** e lascia lavorare: crea tutto da solo (clessidra con avanzamento, «Annulla» per fermarti; quando riparti riprende da dove era arrivato). La prima volta sono ore, soprattutto per lo storico dei prezzi (circa un secondo a titolo) e per la verifica degli ISIN. **Per accorciare la verifica degli ISIN** (10–30 minuti senza chiave) usa una chiave gratuita di openfigi.com, impostata **prima** di lanciare il programma: Windows (PowerShell) `$env:OPENFIGI_KEY="la-tua-chiave"`; Windows (Prompt) `set OPENFIGI_KEY=la-tua-chiave`; Mac/Linux `export OPENFIGI_KEY=la-tua-chiave`.
2. Se hai già un archivio creato su un altro computer: **Importa archivio…** con lo zip esportato da lì, poi **Scarica titoli** per aggiornarlo.
3. **Crea portafoglio**: imposta importo, numero di ETF, massimi per classe e criteri, poi «Calcola le proposte».

Per scaricare di notte senza il browser: `python mymoney.py scarica`.

## Problemi comuni

- **«Yahoo non risponde» o errori 429**: Yahoo limita le richieste. Il programma aspetta e riprova da solo; se persiste, riprova più tardi. Quanto scaricato è salvato.
- **Titoli «senza storico» o «senza quotazione»** nell'avviso finale: non più negoziati o senza dati su Yahoo; restano fuori dal calcolo.
- **`pip` o `python` non trovato**: su Windows usa `py` al posto di `python`; su Mac e Linux `python3` e `pip3`.
- **Errore all'installazione di scipy**: aggiorna pip (`python -m pip install --upgrade pip`) e riprova; con Python troppo vecchio (< 3.9) installa una versione più recente.
- **Cancellare tutto e ripartire**: chiudi il programma e cancella `etf.db`.

## Dove sono i dati

- **`portafogli/`** (accanto al database): un file `.json` per ogni portafoglio salvato.
- **`etf.db`** (SQLite) nella cartella del programma. Per metterlo altrove: `python mymoney.py --db /percorso/etf.db` o la variabile `MYMONEY_DB`. Per salvarlo su Drive o altro, basta puntare la cartella lì. Per fare una copia, copia il file; per ripartire da zero, cancellalo.
- Le **impostazioni** della pagina (criteri, importo…) stanno nel browser (`localStorage`). I **CSV** li scarica il browser nella cartella dei download.

### Come si uniscono le fonti: una scheda per fondo

Ogni fonte scrive nel suo posto e poi si uniscono con una chiave comune:

| Fonte | Dove arriva | Chiave |
|---|---|---|
| Yahoo (elenco, prezzi, schede, storico) | tabella `etf` (una riga per quotazione) e `prezzi` | simbolo, es. `SWDA.MI` |
| justETF (TER, replica, domicilio, rendimenti…) | tabella `jetf` | ISIN |
| OpenFIGI + registro ESMA | tabelle `isin_ref`, `firds` | ISIN ↔ ticker + borsa |
| BCE (cambi) | tabella `fx` | valuta e data |

Il collegamento ISIN ↔ simbolo è quello **verificato** descritto sotto; solo allora i dati justETF si copiano nella riga `etf`. La **vista `fondo`** mostra poi **una sola scheda per fondo** (una riga per ISIN; una per simbolo se l'ISIN manca) con i dati di tutte le fonti, la quotazione preferita (EUR, poi Borsa Italiana, Xetra, Parigi, Amsterdam, Londra, poi il volume), l'elenco di tutti i simboli dello stesso fondo (`quotazioni`) e le fonti usate (`fonti`). È quella che esporta «Scarica il CSV».

## Uso

La schermata **Archivio** ha **un solo pulsante di scaricamento**:

1. **Scarica titoli**: se non c'è ancora un archivio lo crea da zero; se c'è già lo **aggiorna in modo incrementale** (solo ciò che è nuovo o cambiato). Fa tutto da solo, in quattro passi, su tutte le borse (Milano, Xetra, Parigi, Amsterdam, Londra, SIX): elenco dei titoli e prezzi attuali; dati justETF e ISIN verificati (solo i fondi nuovi per le verifiche OpenFIGI); storico dei prezzi (5 anni la prima volta, poi solo i giorni nuovi, con riallineamento dei dividendi); schede dei fondi (solo quelle mancanti o vecchie di oltre 60 giorni). La prima volta può durare ore (soprattutto storico e verifiche degli ISIN) e si può **interrompere e riprendere**. Un passo che fallisce non ferma gli altri: l'errore compare negli avvisi. Compare una **clessidra** con l'avanzamento e «Annulla»; alla fine un avviso elenca **errori e dati mancanti**.
2. **Controllo a campione**: prende 15 fondi a caso e confronta ogni informazione con fonti indipendenti scaricate in quel momento, e con la coerenza interna dei dati. Per ogni fondo un elenco di controlli con esito ✔ ⚠ ✖ o «non verificabile»; il rapporto completo si salva in `controlli/`. Non corregge nulla. Vedi sotto.
3. **Archivio tra computer**: «Esporta archivio» scarica uno zip con il database e i portafogli salvati; «Importa archivio…» lo carica su un altro computer **sostituendo** l'archivio attuale (accanto resta una copia, `etf.db.prima-dell-importazione`, e il file viene controllato prima: se non è valido non si tocca nulla). Dopo l'importazione «Scarica titoli» aggiorna solo il nuovo. «Esporta CSV» dà una riga per fondo con tutti i dati (apribile in Excel).
4. **Crea portafoglio** (seconda schermata): la pagina interroga il database **mentre cambi i criteri** e mostra subito quanti fondi passano, il conteggio per classe di attivo e la tabella dei fondi (simbolo, ISIN, nome, classe, area, borsa, TER, patrimonio, volume, spread, rendimenti a 1/3/5 anni, volatilità, perdita massima, replica, domicilio, storico già scaricato), ordinabile cliccando sulle intestazioni. **Non si scrive nulla**: tutto si imposta con cursori (a due estremi per gli intervalli) o con selezioni multiple, e **tutti i criteri partono disattivati** (all'estremo del cursore il limite non c'è).
   - **Primo criterio: correlazione e diversificazione.** «Diversificazione minima» e «Correlazione media massima» valgono per tutte le proposte e per la frontiera. Se non si possono raggiungere con i fondi analizzati, la pagina dice il massimo (o minimo) possibile.
   - **Numero di ETF.** Ogni proposta e ogni punto della frontiera ha tra il minimo e il massimo di ETF scelti, ognuno con almeno il 3% di peso: nessun fondo a peso zero.
   - **Rendimenti storici a monte.** Si può filtrare per rendimento a 1, 3 e 5 anni, volatilità e perdita massima. La pagina mostra per quanti fondi il dato c'è; per i fondi che passano gli altri criteri ma non hanno lo storico compare «Scarica lo storico dei N fondi senza rendimenti».
   - **Dati puliti.** Gli errori di Yahoo (picchi isolati, frazionamenti non corretti) si correggono; i fondi con movimenti giornalieri oltre il 50% si escludono, e così quelli con meno di 2 anni di storia che accorcerebbero il periodo degli altri: la pagina lo segnala.
   Imposta importo, numero di ETF, peso massimo per ETF, massimi per classe. «Calcola le proposte» scarica lo storico dei prezzi che manca e mostra le tre proposte con pesi, importi e quote intere. **Ogni criterio ha la sua «i»** con cos'è, come si usa e le soglie di riferimento.
5. **Proposta sulla frontiera efficiente**: dopo il calcolo, le tre proposte (rombi colorati) appaiono sul grafico della **frontiera efficiente** dei loro fondi (rischio sull'asse orizzontale, rendimento storico sul verticale). Muovi il cursore **«Incertezza»** (volatilità), oppure clicca o trascina sul grafico: pesi, importi e quote cambiano subito; clicca un rombo o «Torna alla proposta» per tornare a una proposta.
6. **Salva o elimina**: «Salva con nome…» scrive un file **JSON** nella cartella `portafogli/` accanto al database (nome, descrizione, importo, fonte del punto scelto, periodo dei dati, criteri usati, metriche, posizioni con ISIN, peso, importo, quote e prezzo). «Elimina la proposta» la scarta senza salvare. La schermata **Portafogli salvati** elenca i file, mostra le posizioni, li scarica o li elimina.

Dalla riga di comando (per i download lunghi, anche senza browser): `python mymoney.py scarica` (tutto, come il pulsante), `controlla` (controllo a campione), `backup file.zip` e `ripristina file.zip`, `esporta etf.csv`, `info`. Per un passo solo: `storico`, `justetf`, `aggiorna`.

## Controllo a campione: cosa confronta

Per ognuno dei 15 fondi (in maggioranza con ISIN verificato, alcuni quotati su più borse, alcuni senza ISIN), **con dati scaricati in quel momento**:

| Controllo | Confronto |
|---|---|
| ISIN | formato e cifra di controllo; prefisso del paese e domicilio; come è stato verificato |
| Quotazione | prezzo, valuta e nome contro Yahoo ora |
| Borsa e ticker | OpenFIGI conferma ticker e borsa; registro ESMA conferma che l'ISIN è attivo su quella borsa |
| Caratteristiche | TER, patrimonio, rendimento e volatilità a 1 anno, domicilio, replica, distribuzione, data di lancio contro justETF ora |
| Storico | completezza (buchi, punti attesi), movimenti anomali, aggiornamento, nuovo scarico degli ultimi 60 giorni da Yahoo contro quello salvato (rileva dividendi usciti nel frattempo) |
| Coerenza | prezzo attuale contro ultima chiusura; stesso fondo su altre borse (prezzo in euro) |

Le fonti non raggiungibili danno «non verificabile», mai ✔. Alcuni scarti sono attesi e segnalati come avvisi, non errori: il rendimento justETF include i dividendi, il TER di Yahoo è poco affidabile, i nomi del registro ESMA sono abbreviati. Il controllo è **a campione**: dice se le fonti concordano su quei fondi, non garantisce tutto l'archivio.

## ISIN e dati justETF

Yahoo non fornisce l'ISIN, quindi arriva da fonti dirette e **si assegna a un titolo solo se una fonte ufficiale lo lega al suo simbolo** (ticker + borsa):

- **OpenFIGI** (interfaccia gratuita): per ogni ISIN, i ticker su Milano, Xetra, Parigi, Amsterdam, Londra e SIX. Senza chiave sono 25 richieste al minuto e 10 ISIN per richiesta (10–30 minuti la prima volta secondo le borse scaricate, poi solo i fondi nuovi); con una chiave gratuita (variabile d'ambiente `OPENFIGI_KEY`, registrazione su openfigi.com) bastano pochi minuti.
- **Registro ufficiale ESMA (FIRDS)**, in JSON: gli ISIN attivi su Borsa Italiana (ETFplus: ETF, ETC, ETN, ETP), Xetra, Parigi e Amsterdam. Conferma che l'ISIN è davvero negoziato su quella borsa e risolve i simboli contesi. Londra e SIX non sono nel registro UE: lì vale solo OpenFIGI.
- Controllo di coerenza: se il nome justETF di quell'ISIN non somiglia a quello del titolo, non si assegna. Se due ISIN si contendono lo stesso simbolo e il registro non ne indica uno solo, non si assegna.
- L'abbinamento dal nome o dal ticker resta solo come **ipotesi** (`isin_guess`, visibile nel CSV) e non serve per attribuire dati: in una prova sul 4% dei casi era sbagliato (stesso nome, ISIN diversi).
- **Cambi**: dalla BCE (dati ufficiali, interfaccia SDMX); Yahoo solo per le valute che la BCE non pubblica.

Il passo «Dati justETF e ISIN» di «Scarica titoli» (o `python mymoney.py justetf`) legge l'elenco justETF (~5.000 ETF, circa 70 secondi), verifica gli ISIN e **solo ai titoli con ISIN verificato** aggiunge, con precedenza sui dati di Yahoo:

- TER, patrimonio, data di lancio, distribuzione, numero di titoli, fondo sostenibile (ESG), rendimento da dividendi;
- **replica** (fisica completa, a campione, sintetica) e **domicilio**;
- rendimenti a 1, 3 e 5 anni (3 e 5 anni annui), volatilità a 1 e 3 anni, perdita massima;
- **classe di attivo e area** ufficiali (al posto di quelle dedotte dal nome).

Non si legge nessuna pagina web: tutte le fonti danno i dati direttamente (JSON o CSV). Per i titoli senza ISIN verificato, o che justETF non elenca (molti ETN/ETP e prodotti a leva), restano i dati di Yahoo; rendimenti, volatilità e perdita massima si calcolano dallo storico quando lo scarichi. Il database dice la fonte dell'ISIN (`isin_src`: `figi` o `figi+firds`). I primi 10 titoli e i settori, quando ci sono, vengono dalla scheda del fondo di Yahoo (facoltativa, «schede dei fondi»).

## Come si calcolano le proposte

- Un solo titolo per fondo (lo stesso fondo quotato su più borse conta una volta: si preferisce EUR, poi la borsa nell'ordine scelto, poi il volume). Al massimo «Titoli analizzati» fondi, i più grandi per patrimonio.
- Prezzi di chiusura aggiustati (dividendi inclusi), convertiti in EUR al cambio del giorno. Rendimenti a 5 giorni sovrapposti, sulla finestra in comune dei titoli (al massimo 3 anni).
- **Sharpe**: massimo (rendimento − tasso privo di rischio) / volatilità, solo posizioni lunghe, con tetto per ETF e massimi per classe.
- **Bilanciato**: titoli scelti per diversificazione (rapporto di diversificazione, Choueifaty–Coignard 2008) e pesi a parità di rischio.
- **Aggressivo**: massimo rendimento con volatilità fino al limite scelto.
- Per scegliere i pesi i rendimenti storici sono portati per metà verso la media dei titoli (sono molto rumorosi); le cifre mostrate sono quelle storiche reali del portafoglio.
- Sono simulazioni sul passato, non previsioni né consulenza.

## Limiti

- Yahoo non ha l'ISIN: i titoli si identificano dal simbolo (es. `SWDA.MI`); l'ISIN arriva da fonti ufficiali (vedi sopra) e può mancare: meglio nessun ISIN che uno sbagliato.
- Classe di attivo, area e distribuzione sono dedotte dal nome (e, con le schede, dalla composizione): possono sbagliare.
- Patrimonio e TER mancano per una parte dei titoli: un criterio su un dato mancante esclude il titolo, salvo la spunta «Includi i titoli senza il dato».
- Yahoo limita le richieste: se risponde 429 il programma aspetta e riprova da solo.

`python selftest.py` prova selezione e proposte con dati inventati, senza rete.
