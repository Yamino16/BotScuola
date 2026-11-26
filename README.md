# BotScuola

Bot Telegram per gli studenti dell'ITI Medi: restituisce l'orario di una classe o di un docente e le sostituzioni del giorno, senza dover aprire il sito della scuola.

## Comandi

| Comando | Esempio | Risultato |
| --- | --- | --- |
| `/start` | | Elenco dei comandi |
| `/orario <classe o docente>` | `/orario 4HI` | Screenshot della tabella dell'orario |
| `/sostituzioni [classe]` | `/sostituzioni 4A-EA2` | Sostituzioni che riguardano la classe; senza argomento, gli ultimi 8 avvisi |

## Come funziona

- **Orario**: il sito dell'orario genera le tabelle via JavaScript, quindi una semplice richiesta HTTP non basta. Il bot apre la pagina con Selenium e Chromium headless, cerca con BeautifulSoup il link della classe (o, in alternativa, del docente) corrispondente alla ricerca, esegue la funzione JavaScript associata e salva lo screenshot della tabella.
- **Sostituzioni**: gli avvisi sono pubblicati in un canale Discord. Il bot legge gli ultimi 50 messaggi tramite l'API REST di Discord e filtra quelli che contengono la classe richiesta, ignorando i trattini (`4A-EA2` e `4AEA2` sono equivalenti). I risultati sono mostrati in ordine cronologico.
- Le operazioni bloccanti (Selenium, richieste HTTP) girano in un thread separato, così il bot resta reattivo mentre elabora più richieste; ogni screenshot usa un file temporaneo distinto.

## Stack

Python 3.10 · python-telegram-bot 20 · Selenium · BeautifulSoup · Requests · Docker

## Configurazione

Il bot legge la configurazione da variabili d'ambiente (vedi `.env.example`):

| Variabile | Descrizione |
| --- | --- |
| `TELEGRAM_TOKEN` | Token del bot fornito da @BotFather |
| `URL_SITO_ORARIO` | Pagina con l'elenco di classi e docenti |
| `DISCORD_TOKEN` | Token usato per leggere il canale delle sostituzioni |
| `DISCORD_CHANNEL_ID` | ID del canale Discord |

## Avvio

Con Docker (Chromium e chromedriver sono inclusi nell'immagine):

```bash
cp .env.example .env    # compilare i valori
docker build -t botscuola .
docker run --env-file .env botscuola
```

In locale (serve Google Chrome o Chromium installato; il driver viene scaricato da webdriver-manager):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export $(grep -v '^#' .env | xargs)
python bot.py
```
