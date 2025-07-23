from digi.xbee.devices import XBeeDevice, RemoteXBeeDevice, XBee64BitAddress
from digi.xbee.io import IOLine, IOValue
import time
import threading
import subprocess
import pyautogui
import pychromecast
from pychromecast.controllers.youtube import YouTubeController
import json
import os
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options

# === CONFIGURAZIONE ===
PORT = "COM10"
BAUD_RATE = 9600

NODE_A_ADDR = "0013A200424957C7"  # Nodo A: touch sensor
NODE_B_ADDR = "0013A200424957CB"  # Nodo B: LED

PIN_TOUCH = IOLine.DIO0_AD0
PIN_LED_PWM = IOLine.DIO10_PWM0

livelli_pwm = [0, 0.25, 0.5, 0.75, 1.0]

ppt_path = r"C:\Users\Giacomo\OneDrive - Politecnico di Bari\Desktop\MECHATRONICS\Project.pptx[1].pptx"  # Percorso PPT

# File di configurazione JSON
CONFIG_FILE = "../config/config.json"

# Configurazione di default
DEFAULT_CONFIG = {
    "mode": "led",
    "webUrl": "https://www.youtube.com/watch?v=K3OLrDA_nto",
    "chromecastName": "Office TV",
    "youtubeVideoId": "K3OLrDA_nto",
    "lastUpdated": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
}

# Variabili globali
current_config = DEFAULT_CONFIG.copy()
driver = None
web_state = 0
web_toggle_counter = 0
touch_start_time = None

ppt_process = None
ppt_opened = False

cast = None
yt = None
browser = None


def create_default_config():
    """Crea il file di configurazione di default se non esiste"""
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_CONFIG, f, indent=4, ensure_ascii=False)
        print(f"📝 Creato file di configurazione di default: {CONFIG_FILE}")


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
        print(f"❌ Errore lettura JSON: {e}")
    except Exception as e:
        print(f"❌ Errore caricamento config: {e}")
    
    return False


def handle_mode_change(old_mode, new_mode):
    """Gestisce il cambio di modalità chiudendo le risorse della modalità precedente"""
    global driver, ppt_process, ppt_opened, cast, browser
    
    print(f"🔄 Cambio modalità: {old_mode} → {new_mode}")
    
    # Chiudi browser se cambio modalità e non è web
    if new_mode != "web" and driver:
        driver.quit()
        print("🌐 Browser chiuso per cambio modalità.")
        driver = None
        
    # Chiudi PPT se cambio modalità e non è ppt
    if new_mode != "ppt" and ppt_opened:
        try:
            subprocess.run(["taskkill", "/IM", "POWERPNT.EXE", "/F"], shell=True)
            ppt_process = None
            ppt_opened = False
            print("🛑 PowerPoint chiuso per cambio modalità.")
        except Exception as e:
            print(f"⚠️ Errore chiusura PPT: {e}")
            
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
            print(f"❌ Chromecast '{chromecast_name}' non trovato.")
            return False

        cast.wait()
        print(f"✅ Connesso a {cast.name}, pronto a controllare YouTube.")
        yt = YouTubeController()
        cast.register_handler(yt)
        return True

    except Exception as e:
        print(f"⚠️ Errore connessione Chromecast: {e}")
        return False


def play_youtube():
    """Avvia il video YouTube usando l'ID dalla configurazione"""
    global cast, yt
    if cast is None:
        if not connect_chromecast():
            return
    try:
        video_id = current_config.get("youtubeVideoId", "K3OLrDA_nto")
        print(f"▶️ Avvio video {video_id} su Chromecast.")
        yt.play_video(video_id)
    except Exception as e:
        print(f"⚠️ Errore avvio video: {e}")


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
            print(f"▶️ Nessun video in riproduzione, avvio il video {video_id}...")
            yt.play_video(video_id)
        elif player_state == "PLAYING":
            print("⏸ Pausa riproduzione.")
            cast.media_controller.pause()
        elif player_state == "PAUSED":
            print("▶️ Riprendo riproduzione.")
            cast.media_controller.play()
        else:
            print(f"ℹ️ Stato player non gestito: {player_state}")

    except Exception as e:
        print(f"⚠️ Errore controllo stato media: {e}")


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
            print(f"⚠️ Errore stop video: {e}")


def config_polling_thread():
    """Thread che controlla il file di configurazione ogni secondo"""
    while True:
        load_config()
        time.sleep(1.0)  # Polling ogni 1 secondo


def main():
    """Funzione principale"""
    global current_config, driver, ppt_process, ppt_opened, web_state, web_toggle_counter, touch_start_time
    
    # Crea configurazione di default se non esiste
    create_default_config()
    
    # Carica configurazione iniziale
    load_config()
    
    device = XBeeDevice(PORT, BAUD_RATE)

    try:
        device.open()
        print("✅ Coordinator aperto.")

        node_a = RemoteXBeeDevice(device, XBee64BitAddress.from_hex_string(NODE_A_ADDR))
        node_b = RemoteXBeeDevice(device, XBee64BitAddress.from_hex_string(NODE_B_ADDR))

        livello_corrente = 0
        direzione = 1
        prev_value = IOValue.LOW

        # Imposto LED spento all'avvio
        node_b.set_pwm_duty_cycle(PIN_LED_PWM, livelli_pwm[livello_corrente])
        print("💡 LED inizialmente spento.")

        # Avvia thread per il polling della configurazione
        threading.Thread(target=config_polling_thread, daemon=True).start()
        print(f"🔄 Avviato polling configurazione (file: {CONFIG_FILE})")

        while True:
            value = node_a.get_dio_value(PIN_TOUCH)

            # Tocco RILEVATO
            if value == IOValue.HIGH and prev_value == IOValue.LOW:
                touch_start_time = time.time()

            # Fine tocco (rilascio)
            if value == IOValue.LOW and prev_value == IOValue.HIGH:
                touch_duration = time.time() - touch_start_time if touch_start_time else 0
                modalità_corrente = current_config.get("mode", "led")

                if modalità_corrente == "led":
                    # Gestione LED PWM
                    livello_corrente += direzione
                    if livello_corrente >= len(livelli_pwm):
                        livello_corrente = len(livelli_pwm) - 2
                        direzione = -1
                    elif livello_corrente < 0:
                        livello_corrente = 1
                        direzione = 1

                    pwm_duty = livelli_pwm[livello_corrente]
                    node_b.set_pwm_duty_cycle(PIN_LED_PWM, pwm_duty)
                    print(f"🔆 LED intensità: {pwm_duty * 100:.0f}%")

                elif modalità_corrente == "web":
                    if touch_duration >= 3.0:
                        if driver:
                            print("🛑 Tocco lungo → Chiudo video.")
                            driver.quit()
                            driver = None
                            web_state = 0
                            web_toggle_counter = 0
                    else:
                        if web_state == 0:
                            web_url = current_config.get("webUrl", "https://www.youtube.com/watch?v=K3OLrDA_nto")
                            print(f"🌐 Tocco 1 → Apro il video: {web_url}")
                            chrome_options = Options()
                            chrome_options.add_experimental_option("detach", True)
                            driver = webdriver.Chrome(options=chrome_options)
                            driver.get(web_url)
                            web_state = 1
                            web_toggle_counter = 1
                        else:
                            web_toggle_counter += 1
                            action = "⏸ Pausa" if web_toggle_counter % 2 == 0 else "▶️ Play"
                            print(f"Tocco {web_toggle_counter} → {action}")
                            try:
                                driver.find_element(By.TAG_NAME, "body").send_keys(Keys.SPACE)
                            except Exception as e:
                                print("⚠️ Errore invio SPACE:", e)

                elif modalità_corrente == "ppt":
                    if touch_duration >= 3.0:
                        # Tocco lungo chiude PPT
                        if ppt_opened:
                            try:
                                subprocess.run(["taskkill", "/IM", "POWERPNT.EXE", "/F"], shell=True)
                                ppt_process = None
                                ppt_opened = False
                                print("🛑 Tocco lungo → PowerPoint chiuso.")
                            except Exception as e:
                                print(f"⚠️ Errore chiusura PPT: {e}")
                        else:
                            print("ℹ️ PPT non era aperto.")
                    else:
                        if not ppt_opened:
                            print("📽 Tocco → Apro PowerPoint.")
                            try:
                                ppt_process = subprocess.Popen(['start', '', ppt_path], shell=True)
                                ppt_opened = True
                            except Exception as e:
                                print(f"⚠️ Errore apertura PPT: {e}")
                        else:
                            print("➡️ Tocco → Avanzo slide PowerPoint.")
                            try:
                                pyautogui.press('right')
                            except Exception as e:
                                print(f"⚠️ Errore invio tasto avanti slide: {e}")

                elif modalità_corrente == "chromecast":
                    if touch_duration >= 3.0:
                        print("🛑 Tocco lungo → Stop video Chromecast.")
                        stop_youtube()
                    else:
                        print("👆 Tocco breve → Pausa/riprendi video Chromecast.")
                        pause_resume_youtube()

            prev_value = value
            time.sleep(0.1)

    except Exception as e:
        print(f"❌ Errore: {e}")

    finally:
        if device and device.is_open():
            device.close()
            print("🔒 Coordinator chiuso.")
        if driver:
            driver.quit()
        if ppt_opened:
            subprocess.run(["taskkill", "/IM", "POWERPNT.EXE", "/F"], shell=True)
        if cast:
            try:
                cast.disconnect()
            except:
                pass
        if browser:
            browser.stop_discovery()


if __name__ == "__main__":
    main()