import asyncio
import os
import tempfile
import time

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
URL_SITO_ORARIO = os.environ.get("URL_SITO_ORARIO", "")
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")
DISCORD_CHANNEL_ID = os.environ.get("DISCORD_CHANNEL_ID", "")

MAX_AVVISI = 8
# L'orario viene caricato via JavaScript dopo il click: diamo tempo alla pagina.
ATTESA_CARICAMENTO_ORARIO = 4
SEPARATORE = "‾" * 35


def crea_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")

    # Nel container Docker si usano Chromium e chromedriver di sistema;
    # in locale il driver viene scaricato da webdriver-manager.
    if os.environ.get("CHROME_BIN"):
        options.binary_location = os.environ["CHROME_BIN"]
    driver_path = os.environ.get("CHROMEDRIVER_PATH")
    if not driver_path:
        from webdriver_manager.chrome import ChromeDriverManager
        driver_path = ChromeDriverManager().install()

    return webdriver.Chrome(service=Service(driver_path), options=options)


def trova_link(soup, funzione_js, ricerca):
    """Cerca un link che richiama funzione_js il cui testo contiene la ricerca."""
    for link in soup.find_all("a", onclick=True):
        testo = link.get_text(strip=True)
        if funzione_js in link["onclick"] and ricerca in testo.upper():
            return link["onclick"], testo
    return None, None


def trova_tabella_orario(driver):
    # Il sito usa ID diversi a seconda della versione della pagina.
    for selettore in ((By.ID, "Tclassi2018"), (By.ID, "Torario"), (By.TAG_NAME, "table")):
        try:
            return driver.find_element(*selettore)
        except NoSuchElementException:
            continue
    raise NoSuchElementException("Nessuna tabella dell'orario trovata nella pagina")


def cattura_orario_sito(ricerca):
    """Restituisce (percorso_immagine, didascalia) oppure (None, messaggio_errore)."""
    driver = None
    try:
        driver = crea_driver()
        driver.get(URL_SITO_ORARIO)
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))

        soup = BeautifulSoup(driver.page_source, "html.parser")
        tipo = "CLASSE"
        script, nome = trova_link(soup, "OrarioClasse", ricerca)
        if not script:
            tipo = "DOCENTE"
            script, nome = trova_link(soup, "OrarioDocente", ricerca)
        if not script:
            return None, f"❌ Impossibile trovare '{ricerca}' tra le classi o i docenti."

        driver.execute_script(script)
        time.sleep(ATTESA_CARICAMENTO_ORARIO)

        fd, percorso = tempfile.mkstemp(prefix="orario_", suffix=".png")
        os.close(fd)
        trova_tabella_orario(driver).screenshot(percorso)
        return percorso, f"📅 *ORARIO SCOLASTICO - {tipo}: {nome}*"

    except Exception as e:
        return None, f"❌ Errore nel recupero dell'orario: {e}"
    finally:
        if driver:
            driver.quit()


def formatta_avvisi_recenti(messaggi):
    testo = "🔄 *ULTIMI AVVISI SOSTITUZIONI DA DISCORD*\n\n"
    for contenuto in messaggi[:MAX_AVVISI]:
        testo += f"📋 {contenuto}\n{SEPARATORE}\n"
    return testo


def formatta_sostituzioni_classe(messaggi, classe):
    # I trattini vengono ignorati nel confronto (es. "4A-EA2" corrisponde a "4AEA2").
    classe_normalizzata = classe.replace("-", "")
    trovate = [f"🔹 {m}" for m in messaggi if classe_normalizzata in m.upper().replace("-", "")]

    if not trovate:
        return (
            f"🔍 *SOSTITUZIONI CLASSE {classe}*\n\n"
            "✅ Ottimo! Non è stata trovata nessuna sostituzione per la tua classe tra gli ultimi avvisi pubblicati."
        )

    # Discord restituisce i messaggi dal più recente: li riportiamo in ordine cronologico.
    trovate.reverse()
    intestazione = f"🔍 *TUTTE LE SOSTITUZIONI TROVATE PER LA CLASSE {classe}*\n_(Oggi e Domani se presenti)_\n\n"
    return intestazione + "\n\n--------------------------\n\n".join(trovate)


def leggi_sostituzioni_da_discord(classe=None):
    url = f"https://discord.com/api/v9/channels/{DISCORD_CHANNEL_ID}/messages?limit=50"
    headers = {
        "Authorization": DISCORD_TOKEN,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    try:
        risposta = requests.get(url, headers=headers, timeout=15)
    except requests.RequestException as e:
        return f"❌ Errore critico durante la lettura da Discord: {e}"

    if risposta.status_code == 401:
        return "❌ Errore Discord (401): il token è scaduto, va rigenerato."
    if risposta.status_code != 200:
        return f"❌ Errore di connessione a Discord (Codice {risposta.status_code})."

    messaggi = [m.get("content", "").strip() for m in risposta.json()]
    messaggi = [m for m in messaggi if m]
    if not messaggi:
        return "⚠️ Il canale Discord delle sostituzioni è vuoto."

    if classe:
        return formatta_sostituzioni_classe(messaggi, classe.upper())
    return formatta_avvisi_recenti(messaggi)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    testo = (
        "📚 *BOT ORARIO & SOSTITUZIONI ITI MEDI by Yamino*\n\n"
        "Comandi disponibili:\n\n"
        "📸 *Orario Scolastico:*\n"
        "`/orario nomeclasse` - Vedi screenshot orario classe\n\n"
        "📝 *Sostituzioni (da Discord):*\n"
        "`/sostituzioni nomeclasse` - Oggi e Domani (se disponibili)\n"
    )
    await update.message.reply_text(testo, parse_mode="Markdown")


async def orario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Specifica cosa cercare! Esempio: `/orario 4HI`", parse_mode="Markdown")
        return

    ricerca = " ".join(context.args).upper()
    attesa = await update.message.reply_text(f"📸 Ricerca per *{ricerca}* in corso...", parse_mode="Markdown")

    # Selenium è bloccante: lo eseguiamo in un thread per non fermare il bot.
    percorso, testo = await asyncio.to_thread(cattura_orario_sito, ricerca)
    if not percorso:
        await attesa.edit_text(testo, parse_mode="Markdown")
        return

    try:
        await attesa.delete()
        with open(percorso, "rb") as foto:
            await update.message.reply_photo(
                photo=foto, caption=testo, parse_mode="Markdown",
                read_timeout=60, write_timeout=60,
            )
    except Exception as e:
        await update.message.reply_text(f"❌ Errore nell'invio a Telegram: {e}")
    finally:
        os.remove(percorso)


async def sostituzioni(update: Update, context: ContextTypes.DEFAULT_TYPE):
    classe = context.args[0] if context.args else None
    if classe:
        testo_attesa = f"🔍 Ricerca di tutte le sostituzioni recenti per la classe *{classe.upper()}*..."
    else:
        testo_attesa = "🔍 Estrazione degli ultimi avvisi dal canale Discord..."

    attesa = await update.message.reply_text(testo_attesa, parse_mode="Markdown")
    risultato = await asyncio.to_thread(leggi_sostituzioni_da_discord, classe)
    await attesa.edit_text(risultato, parse_mode="Markdown")


def main():
    mancanti = [nome for nome in ("TELEGRAM_TOKEN", "URL_SITO_ORARIO", "DISCORD_TOKEN", "DISCORD_CHANNEL_ID")
                if not os.environ.get(nome)]
    if mancanti:
        raise SystemExit(f"Variabili d'ambiente mancanti: {', '.join(mancanti)}")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).read_timeout(60).write_timeout(60).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("orario", orario))
    app.add_handler(CommandHandler("sostituzioni", sostituzioni))

    print("Bot avviato.")
    app.run_polling()


if __name__ == "__main__":
    main()
