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

## Prima volta: l'ordine giusto

1. **Scarica elenco titoli**: scegli le borse (a Milano, circa 2.300 titoli in meno di un minuto) e premi il pulsante. Compare una clessidra con l'avanzamento.
2. **Scarica dati justETF** (consigliato): aggiunge ISIN verificati, replica, domicilio, rendimenti, classe e area ufficiali. La prima volta 10–30 minuti per le verifiche OpenFIGI; con una chiave gratuita di openfigi.com bastano pochi minuti. Windows (PowerShell): `$env:OPENFIGI_KEY="la-tua-chiave"`; Windows (Prompt): `set OPENFIGI_KEY=la-tua-chiave`; Mac/Linux: `export OPENFIGI_KEY=la-tua-chiave`, **prima** di lanciare il programma.
3. **Crea portafoglio**: imposta importo, numero di ETF, massimi per classe e criteri, poi «Calcola le proposte». Il calcolo scarica da solo lo storico dei prezzi dei titoli che passano i criteri (qualche minuto la prima volta).

I lavori lunghi si possono **annullare** e **riprendere**: quanto già scaricato resta nel database. Per scaricare di notte senza il browser: `python mymoney.py scarica --schede` (tutte le borse e le schede dei fondi, può durare ore) e `python mymoney.py justetf`.

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

1. **Scarica elenco titoli**: tutti gli ETF/ETC/ETN delle borse scelte (Milano, Xetra, Parigi, Amsterdam, Londra, SIX) con nome, tipo, valuta, prezzo, bid, ask, spread, volume medio, TER e patrimonio quando Yahoo li dà, rendimento a 1 anno e data di primo scambio. Circa 2.300 titoli per Milano in meno di un minuto.
   *Facoltativo*: «Scarica anche le schede dei fondi» aggiunge la composizione (azioni, obbligazioni, liquidità) e completa TER e patrimonio. Una richiesta per fondo: può durare ore, ma si può interrompere e riprendere.
2. **Storico dei prezzi e rendimenti**: «Scarica o aggiorna lo storico dei prezzi» (o la spunta «Scarica anche lo storico…» insieme all'elenco, o `python mymoney.py storico`) scarica 5 anni di prezzi giornalieri in euro per **tutti i fondi** dell'archivio, dai più grandi, e ne ricava rendimenti a 1/3/5 anni, volatilità e perdita massima, così puoi filtrare a monte per rendimento. La prima volta è lungo (circa un secondo a titolo; una quarantina di minuti per Borsa Italiana) e si può interrompere e riprendere. **Le volte successive scarica solo i giorni nuovi** (con 10 giorni di sovrapposizione): i prezzi aggiustati per i dividendi del passato cambiano quando esce un dividendo, quindi lo storico vecchio viene riallineato sul periodo in comune. Le richieste a Yahoo restano una per titolo, ma sono molto più leggere.
3. **Aggiorna prezzi attuali**: ultimo prezzo, bid, ask, volume.
4. **Scarica il CSV**: una riga per fondo con i dati di tutte le fonti (apribile in Excel).

Durante ogni scaricamento compare una **clessidra** con l'avanzamento e «Annulla»; a lavoro finito, un avviso elenca **errori e dati mancanti** (titoli senza prezzo o storico, fonti non raggiungibili, ISIN dubbi). Quanto scaricato resta salvato e si può riprendere.
5. **Crea portafoglio** (seconda schermata): la pagina interroga il database **mentre cambi i criteri** e mostra subito quanti fondi passano, il conteggio per classe di attivo e la tabella dei fondi (simbolo, ISIN, nome, classe, area, borsa, TER, patrimonio, volume, spread, rendimenti a 1/3/5 anni, volatilità, perdita massima, replica, domicilio, storico già scaricato), ordinabile cliccando sulle intestazioni. **Non si scrive nulla**: tutto si imposta con cursori (a due estremi per gli intervalli) o con selezioni multiple, e **tutti i criteri partono disattivati** (all'estremo del cursore il limite non c'è).
   - **Primo criterio: correlazione e diversificazione.** «Diversificazione minima» e «Correlazione media massima» valgono per tutte le proposte e per la frontiera. Se non si possono raggiungere con i fondi analizzati, la pagina dice il massimo (o minimo) possibile.
   - **Numero di ETF.** Ogni proposta e ogni punto della frontiera ha tra il minimo e il massimo di ETF scelti, ognuno con almeno il 3% di peso: nessun fondo a peso zero.
   - **Rendimenti storici a monte.** Puoi filtrare per rendimento a 1, 3 e 5 anni, volatilità e perdita massima. La pagina mostra per quanti fondi il dato c'è (viene da justETF, da Yahoo o dallo storico dei prezzi); il pulsante **«Scarica lo storico dei N fondi senza rendimenti»** scarica quello mancante per i fondi che passano gli altri criteri (riprendibile) e calcola i rendimenti.
   - **Dati puliti.** Gli errori di Yahoo (picchi isolati, frazionamenti non corretti) si correggono; i fondi con movimenti giornalieri oltre il 50% si escludono e così quelli con meno di 2 anni di storia che accorcerebbero il periodo degli altri: la pagina lo segnala.
   Imposta importo, numero di ETF, peso massimo per ETF, massimi per classe. «Calcola le proposte» scarica lo storico dei prezzi (5 anni, in EUR) dei soli fondi analizzati che mancano e mostra le tre proposte con pesi, importi e quote intere. **Ogni criterio ha la sua «i»** con cos'è, come si usa e le soglie di riferimento; la «i» accanto a «Portafoglio» spiega **come si scelgono i portafogli** e quella delle proposte come leggere i risultati.
6. **Proposta sulla frontiera efficiente**: dopo il calcolo, le tre proposte (rombi colorati) appaiono sul grafico della **frontiera efficiente** dei loro fondi (rischio sull'asse orizzontale, rendimento storico sul verticale). Muovi il cursore **«Incertezza»** (volatilità), oppure clicca o trascina sul grafico: pesi, importi e quote cambiano subito; clicca un rombo o «Torna alla proposta» per tornare a una proposta. La «i» accanto al titolo spiega come leggerla.
7. **Salva o elimina**: «Salva con nome…» scrive un file **JSON** nella cartella `portafogli/` accanto al database (nome, descrizione, importo, fonte del punto scelto, periodo dei dati, criteri usati, metriche, posizioni con ISIN, peso, importo, quote e prezzo). «Elimina la proposta» la scarta senza salvare. La schermata **Portafogli salvati** elenca i file, mostra le posizioni, li scarica o li elimina.

Dalla riga di comando (utile per i download lunghi): `python mymoney.py scarica --borse MIL GER --schede`, `aggiorna`, `esporta etf.csv`, `info`.

## ISIN e dati justETF

Yahoo non fornisce l'ISIN, quindi arriva da fonti dirette e **si assegna a un titolo solo se una fonte ufficiale lo lega al suo simbolo** (ticker + borsa):

- **OpenFIGI** (interfaccia gratuita): per ogni ISIN, i ticker su Milano, Xetra, Parigi, Amsterdam, Londra e SIX. Senza chiave sono 25 richieste al minuto e 10 ISIN per richiesta (10–30 minuti la prima volta secondo le borse scaricate, poi solo i fondi nuovi); con una chiave gratuita (variabile d'ambiente `OPENFIGI_KEY`, registrazione su openfigi.com) bastano pochi minuti.
- **Registro ufficiale ESMA (FIRDS)**, in JSON: gli ISIN attivi su Borsa Italiana (ETFplus: ETF, ETC, ETN, ETP), Xetra, Parigi e Amsterdam. Conferma che l'ISIN è davvero negoziato su quella borsa e risolve i simboli contesi. Londra e SIX non sono nel registro UE: lì vale solo OpenFIGI.
- Controllo di coerenza: se il nome justETF di quell'ISIN non somiglia a quello del titolo, non si assegna. Se due ISIN si contendono lo stesso simbolo e il registro non ne indica uno solo, non si assegna.
- L'abbinamento dal nome o dal ticker resta solo come **ipotesi** (`isin_guess`, visibile nel CSV) e non serve per attribuire dati: in una prova sul 4% dei casi era sbagliato (stesso nome, ISIN diversi).
- **Cambi**: dalla BCE (dati ufficiali, interfaccia SDMX); Yahoo solo per le valute che la BCE non pubblica.

Il pulsante «Scarica dati justETF» (o `python mymoney.py justetf`) legge l'elenco justETF (~5.000 ETF, circa 70 secondi), verifica gli ISIN e **solo ai titoli con ISIN verificato** aggiunge, con precedenza sui dati di Yahoo:

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
