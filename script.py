from digi.xbee.devices import XBeeDevice, RemoteXBeeDevice, XBee64BitAddress
from digi.xbee.io import IOLine, IOValue, IOMode
import time
import threading
import subprocess
import pychromecast
from pychromecast.controllers.youtube import YouTubeController
import json
import os
from datetime import datetime
import smtplib
from email.message import EmailMessage

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options

# === CONFIGURAZIONE ===
PORT = "/dev/ttyUSB0"
BAUD_RATE = 9600

NODE_A_ADDR = "0013A200424957C7"  # Nodo A: touch sensor
NODE_B_ADDR = "0013A200424957CB"  # Nodo B: LED

PIN_TOUCH = IOLine.DIO0_AD0
PIN_LED_PWM = IOLine.DIO10_PWM0

# Configurazione email PPT
EMAIL_SENDER = "livetouch64@gmail.com"
EMAIL_PASSWORD = "$Liv&Touch46"
EMAIL_RECEIVER = "francescodecarne@live.com"
SLIDES_URL = "https://docs.google.com/presentation/d/18ePgm_ytSiJXVkWSCgmbCQsqELal2Sh1kVYaTQ2mnyk/edit?slide=id.p1#slide=id.p1"

# Variabili relè
relay_state = False
RELAY_ACTIVE_LOW = True

# File di configurazione JSON
CONFIG_FILE = "../config/config.json"

# Configurazione di default
DEFAULT_CONFIG = {
    "mode": "led",
    "chromecastName": "Office TV",
    "youtubeVideoId": "K3OLrDA_nto",
    "slidesUrl": "https://docs.google.com/presentation/d/18ePgm_ytSiJXVkWSCgmbCQsqELal2Sh1kVYaTQ2mnyk/edit?slide=id.p1#slide=id.p1",
    "emailReceiver": "francescodecarne@live.com",
    "lastUpdated": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
}

# Variabili globali
current_config = DEFAULT_CONFIG.copy()
touch_start_time = None

cast = None
yt = None
browser = None


def create_default_config():
    """Crea il file di configurazione di default se non esiste"""
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_CONFIG, f, indent=4, ensure_ascii=False)
        print(f"📁 Creato file di configurazione di default: {CONFIG_FILE}")


def load_config():
    """Carica la configurazione dal file JSON"""
    global current_config
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                new_config = json.load(f)
                
            # Verifica se la configurazione è cambiata
            if new_config != current_config:
                print(f"🔄 Configurazione aggiornata: {new_config}")
                old_mode = current_config.get("mode", "")
                current_config = new_config
                
                # Se è cambiata la modalità, gestisci la transizione
                if old_mode != current_config["mode"]:
                    handle_mode_change(old_mode, current_config["mode"])
                    
                return True
        else:
            create_default_config()
            
    except json.JSONDecodeError as e:
        print(f"⚠ Errore lettura JSON: {e}")
    except Exception as e:
        print(f"⚠ Errore caricamento config: {e}")
    
    return False


def handle_mode_change(old_mode, new_mode):
    """Gestisce il cambio di modalità chiudendo le risorse della modalità precedente"""
    global cast, browser
    
    print(f"🔄 Cambio modalità: {old_mode} → {new_mode}")
            
    # Stop Chromecast se cambio modalità e non è chromecast
    if new_mode != "chromecast":
        stop_youtube()


def connect_chromecast():
    """Connette al Chromecast usando il nome dalla configurazione"""
    global cast, yt, browser
    try:
        chromecast_name = current_config.get("chromecastName", "Office TV")
        print(f"📺 Cerco Chromecast: {chromecast_name}...")
        
        chromecasts, browser = pychromecast.get_chromecasts()
        cast = next((cc for cc in chromecasts if cc.name == chromecast_name), None)

        if not cast:
            print(f"⚠ Chromecast '{chromecast_name}' non trovato.")
            return False

        cast.wait()
        print(f"✅ Connesso a {cast.name}, pronto a controllare YouTube.")
        yt = YouTubeController()
        cast.register_handler(yt)
        return True

    except Exception as e:
        print(f"⚠ Errore connessione Chromecast: {e}")
        return False


def play_youtube():
    """Avvia il video YouTube usando l'ID dalla configurazione"""
    global cast, yt
    if cast is None:
        if not connect_chromecast():
            return
    try:
        video_id = current_config.get("youtubeVideoId", "K3OLrDA_nto")
        print(f"▶ Avvio video {video_id} su Chromecast.")
        yt.play_video(video_id)
    except Exception as e:
        print(f"⚠ Errore avvio video: {e}")


def pause_resume_youtube():
    """Pausa/riprende il video YouTube"""
    global cast, yt
    if cast is None:
        if not connect_chromecast():
            return
    try:
        cast.media_controller.update_status()
        player_state = cast.media_controller.status.player_state
        if player_state is None or player_state == "UNKNOWN":
            player_state = "IDLE"

        if player_state == "IDLE":
            video_id = current_config.get("youtubeVideoId", "K3OLrDA_nto")
            print(f"▶ Nessun video in riproduzione, avvio il video {video_id}...")
            yt.play_video(video_id)
        elif player_state == "PLAYING":
            print("⏸ Pausa riproduzione.")
            cast.media_controller.pause()
        elif player_state == "PAUSED":
            print("▶ Riprendo riproduzione.")
            cast.media_controller.play()
        else:
            print(f"ℹ Stato player non gestito: {player_state}")

    except Exception as e:
        print(f"⚠ Errore controllo stato media: {e}")


def stop_youtube():
    """Ferma il video e disconnette dal Chromecast"""
    global cast, browser
    if cast:
        try:
            print("🛑 Stop video e disconnessione Chromecast.")
            cast.media_controller.stop()
            cast.disconnect()
            cast = None
            if browser:
                browser.stop_discovery()
                browser = None
        except Exception as e:
            print(f"⚠ Errore stop video: {e}")


def ensure_pin_mode_pwm(remote):
    """Configura DIO10 come PWM (per modalità LED)."""
    try:
        remote.set_io_configuration(PIN_LED_PWM, IOMode.PWM)
        return True
    except Exception as e:
        print(f"⚠ Errore set PWM mode: {e}")
        return False


def ensure_pin_mode_digital(remote, default_high=True):
    """
    Configura DIO10 come uscita digitale.
    default_high=True -> DIGITAL_OUT_HIGH (sicuro per relè active-LOW)
    """
    try:
        mode = IOMode.DIGITAL_OUT_HIGH if default_high else IOMode.DIGITAL_OUT_LOW
        remote.set_io_configuration(PIN_LED_PWM, mode)
        return True
    except Exception as e:
        print(f"⚠ Errore set Digital Output mode: {e}")
        return False


def set_relay(remote, on: bool):
    """Comanda il relè rispettando la logica active-low/high."""
    try:
        if RELAY_ACTIVE_LOW:
            value = IOValue.LOW if on else IOValue.HIGH
        else:
            value = IOValue.HIGH if on else IOValue.LOW
        remote.set_dio_value(PIN_LED_PWM, value)
    except Exception as e:
        print(f"⚠ Errore comando relè: {e}")


def relay_safe_off(remote):
    """Porta il relè a OFF in sicurezza secondo la logica."""
    set_relay(remote, False)


def send_ppt_email():
    """Invia email con link presentazione"""
    try:
        slides_url = current_config.get("slidesUrl", SLIDES_URL)
        
        msg = EmailMessage()
        msg['Subject'] = "Avvia la presentazione"
        msg['From'] = EMAIL_SENDER
        msg['To'] = EMAIL_RECEIVER
        msg.set_content(f"Clicca qui per aprire la presentazione: {slides_url}")
        
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(EMAIL_SENDER, EMAIL_PASSWORD)
            smtp.send_message(msg)
        print("✅ Email con presentazione inviata!")
        return True
    except Exception as e:
        print(f"⚠ Errore invio email: {e}")
        return False


def config_polling_thread():
    """Thread che controlla il file di configurazione ogni secondo"""
    while True:
        load_config()
        time.sleep(1.0)  # Polling ogni 1 secondo


def main():
    """Funzione principale"""
    global current_config, touch_start_time, relay_state
    
    # Crea configurazione di default se non esiste
    create_default_config()
    
    # Carica configurazione iniziale
    load_config()
    
    device = XBeeDevice(PORT, BAUD_RATE)

    device.open()
    print("✅ Coordinator aperto.")

    node_a = RemoteXBeeDevice(device, XBee64BitAddress.from_hex_string(NODE_A_ADDR))
    node_b = RemoteXBeeDevice(device, XBee64BitAddress.from_hex_string(NODE_B_ADDR))

    # Safe-state iniziale: configura come Digital Output e metti il relay OFF
    try:
        if ensure_pin_mode_digital(node_b):
            relay_safe_off(node_b)
            print("🔌 Relè inizialmente spento.")
    except Exception as e:
        if "TX failure" in str(e):
            print(f"⚠ Errore set Digital Output mode: TX failure (iniziale, script continua)")
        else:
            print(f"⚠ Errore set Digital Output mode: {e}")

    prev_value = IOValue.LOW

    # Avvia thread per il polling della configurazione
    threading.Thread(target=config_polling_thread, daemon=True).start()
    print(f"🔄 Avviato polling configurazione (file: {CONFIG_FILE})")

    while True:
        try:
            value = node_a.get_dio_value(PIN_TOUCH)
        except Exception as e:
            if "TX failure" in str(e):
                print(f"⚠ Errore: TX failure (get_dio_value, script continua)")
                time.sleep(0.5)
                continue
            else:
                print(f"⚠ Errore: {e}")
                time.sleep(0.5)
                continue

        # Tocco RILEVATO
        if value == IOValue.HIGH and prev_value == IOValue.LOW:
            touch_start_time = time.time()

        # Fine tocco (rilascio)
        if value == IOValue.LOW and prev_value == IOValue.HIGH:
            touch_duration = time.time() - touch_start_time if touch_start_time else 0
            modalità_corrente = current_config.get("mode", "led")

            if modalità_corrente == "led":
                # MODALITÀ RELAY (rinominata da LED)
                try:
                    if ensure_pin_mode_digital(node_b):
                        if touch_duration >= 3.0:
                            relay_state = False
                            try:
                                set_relay(node_b, relay_state)
                            except Exception as e:
                                if "TX failure" in str(e):
                                    print("⚠ Errore comando relè: TX failure (script continua)")
                                else:
                                    print(f"⚠ Errore comando relè: {e}")
                            print("� Tocco lungo → RELAY OFF.")
                        else:
                            relay_state = not relay_state
                            try:
                                set_relay(node_b, relay_state)
                            except Exception as e:
                                if "TX failure" in str(e):
                                    print("⚠ Errore comando relè: TX failure (script continua)")
                                else:
                                    print(f"⚠ Errore comando relè: {e}")
                            print(f"🔀 Tocco breve → RELAY {'ON' if relay_state else 'OFF'}.")
                except Exception as e:
                    if "TX failure" in str(e):
                        print("⚠ Errore set Digital Output mode: TX failure (script continua)")
                    else:
                        print(f"⚠ Errore set Digital Output mode: {e}")

            elif modalità_corrente == "ppt":
                print("📧 Tocco → Invio email con link presentazione")
                send_ppt_email()

            elif modalità_corrente == "chromecast":
                if touch_duration >= 3.0:
                    print("� Tocco lungo → Stop video Chromecast.")
                    stop_youtube()
                else:
                    print("👆 Tocco breve → Pausa/riprendi video Chromecast.")
                    pause_resume_youtube()

        prev_value = value
        time.sleep(0.1)

    # Il ciclo while non termina mai, quindi la connessione rimane aperta


if __name__ == "__main__":
    main()
