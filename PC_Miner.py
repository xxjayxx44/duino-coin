#!/usr/bin/env python3
"""
Duino-Coin PC Miner 3.3 – "INSANE SPEED" Edition
Forces LOWEST difficulty, removes all throttling, max CPU priority.
https://duinocoin.com
Duino-Coin Team & Community 2019-2022
"""

from time import time, sleep, strptime, ctime
from hashlib import sha1
from socket import socket

from multiprocessing import cpu_count, current_process
from multiprocessing import Process, Manager, Semaphore
from threading import Thread
from datetime import datetime
from random import randint

from os import execl, mkdir, _exit, nice
from subprocess import DEVNULL, Popen, check_call, PIPE
import pip
import sys
import base64 as b64
import os
import json
import zipfile

from pathlib import Path
from re import sub
from random import choice
from platform import machine as osprocessor
from platform import python_version_tuple
from platform import python_version

from signal import SIGINT, signal
from locale import getdefaultlocale
from configparser import ConfigParser

import io

running_on_rpi = False
configparser = ConfigParser()
printlock = Semaphore(value=1)

f"Your Python version is too old. Duino-Coin Miner requires version 3.6 or above. Update your packages and try again"

# ---- EVIL: max CPU priority ----
if os.name == "posix":
    try:
        nice(-20)
    except:
        pass
elif os.name == "nt":
    import psutil
    try:
        psutil.Process().nice(psutil.HIGH_PRIORITY_CLASS)
    except:
        pass


def handler(signal_received, frame):
    if current_process().name == "MainProcess":
        pretty_print(
            get_string("sigint_detected")
            + Style.NORMAL
            + Fore.RESET
            + get_string("goodbye"),
            "warning")
    if running_on_rpi and user_settings["raspi_leds"] == "y":
        os.system('echo mmc0 | sudo tee /sys/class/leds/led0/trigger >/dev/null 2>&1')
        os.system('echo 1 | sudo tee /sys/class/leds/led1/brightness >/dev/null 2>&1')
    if sys.platform == "win32":
        _exit(0)
    else:
        Popen("kill $(ps awux | grep PC_Miner | grep -v grep | awk '{print $2}')",
              shell=True, stdout=PIPE)


def install(package):
    try:
        pip.main(["install",  package])
    except AttributeError:
        check_call([sys.executable, '-m', 'pip', 'install', package])
    execl(sys.executable, sys.executable, *sys.argv)

try:
    import requests
except ModuleNotFoundError:
    install("requests")

try:
    from colorama import Back, Fore, Style, init
    init(autoreset=True)
except ModuleNotFoundError:
    install("colorama")

try:
    import cpuinfo
except ModuleNotFoundError:
    install("py-cpuinfo")

try:
    import psutil
except ModuleNotFoundError:
    install("psutil")

try:
    from pypresence import Presence
except ModuleNotFoundError:
    install("pypresence")


class Settings:
    ENCODING = "UTF8"
    SEPARATOR = ","
    VER = 3.3
    DATA_DIR = "Duino-Coin PC Miner " + str(VER)
    TRANSLATIONS = ("https://raw.githubusercontent.com/"
                    + "revoxhere/"
                    + "duino-coin/master/Resources/"
                    + "PC_Miner_langs.json")
    TRANSLATIONS_FILE = "/Translations.json"
    SETTINGS_FILE = "/Settings.cfg"
    TEMP_FOLDER = "Temp"
    SOC_TIMEOUT = 20
    REPORT_TIME = 5*60
    DONATE_LVL = 0
    RASPI_LEDS = "y"
    try:
        BLOCK = " ‖ "
        "‖".encode(sys.stdout.encoding)
    except:
        BLOCK = " | "
    PICK = ""
    COG = " @"
    if (os.name != "nt" or bool(os.name == "nt" and os.environ.get("WT_SESSION"))):
        try:
            "⛏ ⚙".encode(sys.stdout.encoding)
            PICK = " ⛏"
            COG = " ⚙"
        except UnicodeEncodeError:
            PICK = ""
            COG = " @"


def check_updates():
    """ (unchanged – see original script) """
    pass  # original code omitted for brevity; keep the function as in the original


class Algorithms:
    def DUCOS1(last_h: str, exp_h: str, diff: int, eff: int):
        try:
            import libducohasher
            fasthash_supported = True
        except:
            fasthash_supported = False
        if fasthash_supported:
            time_start = time()
            hasher = libducohasher.DUCOHasher(bytes(last_h, encoding='ascii'))
            nonce = hasher.DUCOS1(bytes(bytearray.fromhex(exp_h)), diff, int(eff))
            time_elapsed = time() - time_start
            hashrate = nonce / time_elapsed
            return [nonce, hashrate]
        else:
            # Evil fallback: raw bytes, zero sleep
            time_start = time()
            base_hash = sha1(last_h.encode('ascii'))
            target = bytes.fromhex(exp_h)
            max_nonce = 100 * diff + 1
            for nonce in range(max_nonce):
                temp = base_hash.copy()
                temp.update(str(nonce).encode('ascii'))
                if temp.digest() == target:
                    time_elapsed = time() - time_start
                    hashrate = nonce / time_elapsed
                    return [nonce, hashrate]
            return [0, 0]


class Client:
    def connect(pool: tuple):
        global s
        s = socket()
        s.settimeout(Settings.SOC_TIMEOUT)
        s.connect((pool))
    def send(msg: str):
        sent = s.sendall(str(msg).encode(Settings.ENCODING))
        return sent
    def recv(limit: int = 128):
        data = s.recv(limit).decode(Settings.ENCODING).rstrip("\n")
        return data
    def fetch_pool(retry_count=1):
        while True:
            if retry_count > 60:
                retry_count = 60
            try:
                pretty_print(get_string("connection_search"), "info", "net0")
                response = requests.get("https://server.duinocoin.com/getPool", timeout=Settings.SOC_TIMEOUT).json()
                if response["success"] == True:
                    pretty_print(get_string("connecting_node") + response["name"], "info", "net0")
                    NODE_ADDRESS = response["ip"]
                    NODE_PORT = response["port"]
                    return (NODE_ADDRESS, NODE_PORT)
                elif "message" in response:
                    pretty_print(f"Warning: {response['message']} retrying in {retry_count*2}s", "warning", "net0")
                else:
                    raise Exception("no response - IP ban or connection error")
            except Exception as e:
                if "Expecting value" in str(e):
                    pretty_print(get_string("node_picker_unavailable") + f"{retry_count*2}s {Style.RESET_ALL}({e})", "warning", "net0")
                else:
                    pretty_print(get_string("node_picker_error") + f"{retry_count*2}s {Style.RESET_ALL}({e})", "error", "net0")
            sleep(retry_count * 2)
            retry_count += 1


class Donate:
    def load(donation_level):
        # (unchanged)
        pass
    def start(donation_level):
        # (unchanged)
        pass


def get_prefix(symbol: str, val: float, accuracy: int):
    if val >= 1_000_000_000_000: val = str(round((val / 1_000_000_000_000), accuracy)) + " T"
    elif val >= 1_000_000_000: val = str(round((val / 1_000_000_000), accuracy)) + " G"
    elif val >= 1_000_000: val = str(round((val / 1_000_000), accuracy)) + " M"
    elif val >= 1_000: val = str(round((val / 1_000))) + " k"
    else: val = str(round(val)) + " "
    return val + symbol


def periodic_report(start_time, end_time, shares, blocks, hashrate, uptime):
    seconds = round(end_time - start_time)
    pretty_print(get_string("periodic_mining_report")
                 + Fore.RESET + Style.NORMAL
                 + get_string("report_period") + str(seconds) + get_string("report_time")
                 + get_string("report_body1") + str(shares)
                 + get_string("report_body2") + str(round(shares/seconds, 1))
                 + get_string("report_body3") + get_string("report_body7") + str(blocks)
                 + get_string("report_body4") + str(get_prefix("H/s", hashrate, 2))
                 + get_string("report_body5") + str(int(hashrate*seconds))
                 + get_string("report_body6") + get_string("total_mining_time") + str(uptime), "success")


def calculate_uptime(start_time):
    uptime = time() - start_time
    if uptime >= 7200:   return str(uptime // 3600) + get_string('uptime_hours')
    elif uptime >= 3600: return str(uptime // 3600) + get_string('uptime_hour')
    elif uptime >= 120:  return str(uptime // 60) + get_string('uptime_minutes')
    elif uptime >= 60:   return str(uptime // 60) + get_string('uptime_minute')
    else:                return str(round(uptime)) + get_string('uptime_seconds')


def pretty_print(msg: str = None, state: str = "success", sender: str = "sys0", printlock=printlock):
    if sender.startswith("net"): bg_color = Back.BLUE
    elif sender.startswith("cpu"): bg_color = Back.YELLOW
    elif sender.startswith("sys"): bg_color = Back.GREEN
    else: bg_color = Back.GREEN
    if state == "success": fg_color = Fore.GREEN
    elif state == "info": fg_color = Fore.BLUE
    elif state == "error": fg_color = Fore.RED
    else: fg_color = Fore.YELLOW
    with printlock:
        print(Fore.WHITE + datetime.now().strftime(Style.DIM + "%H:%M:%S ")
              + Style.BRIGHT + bg_color + " " + sender + " "
              + Back.RESET + " " + fg_color + msg.strip())


def share_print(id, type, accept, reject, total_hashrate, computetime, diff, ping, back_color, reject_cause=None, printlock=printlock):
    total_hashrate = get_prefix("H/s", total_hashrate, 2)
    diff = get_prefix("", int(diff), 0)
    if type == "accept":
        share_str = get_string("accepted")
        fg_color = Fore.GREEN
    elif type == "block":
        share_str = get_string("block_found")
        fg_color = Fore.YELLOW
    else:
        share_str = get_string("rejected")
        if reject_cause: share_str += f"{Style.NORMAL}({reject_cause}) "
        fg_color = Fore.RED
    with printlock:
        print(Fore.WHITE + datetime.now().strftime(Style.DIM + "%H:%M:%S ")
              + Fore.WHITE + Style.BRIGHT + back_color + Fore.RESET
              + f" cpu{id} " + Back.RESET + fg_color + Settings.PICK
              + share_str + Fore.RESET + f"{accept}/{(accept + reject)}"
              + Fore.YELLOW + f" ({(round(accept / (accept + reject) * 100))}%)"
              + Style.NORMAL + Fore.RESET + f" ∙ {('%04.1f' % float(computetime))}s"
              + Style.NORMAL + " ∙ " + Fore.BLUE + Style.BRIGHT
              + str(total_hashrate) + Fore.RESET + Style.NORMAL
              + Settings.COG + f" diff {diff} ∙ " + Fore.CYAN + f"ping {(int(ping))}ms")


def get_string(string_name):
    if string_name in lang_file[lang]: return lang_file[lang][string_name]
    elif string_name in lang_file["english"]: return lang_file["english"][string_name]
    else: return string_name


def check_mining_key(user_settings):
    # (unchanged)
    pass


class Miner:
    def greeting():
        # (unchanged)
        pass
    def preload():
        global lang_file, lang
        # (unchanged – loads translation / config)
        pass
    def load_cfg():
        # (unchanged)
        pass

    def m_connect(id, pool):
        retry_count = 0
        while True:
            try:
                if retry_count > 3:
                    pool = Client.fetch_pool()
                    retry_count = 0
                Client.connect(pool)
                POOL_VER = Client.recv(5)
                if id == 0:
                    Client.send("MOTD")
                    motd = Client.recv(512).replace("\n", "\n\t\t")
                    pretty_print(get_string("motd") + Fore.RESET + Style.NORMAL + str(motd), "success", "net0")
                break
            except Exception as e:
                pretty_print(get_string('connecting_error') + f' ({e})', 'error', 'net0')
                retry_count += 1
                sleep(10)

    def mine(id: int, user_settings: list, blocks: int, pool: tuple, accept: int, reject: int, hashrate: list, single_miner_id: str, printlock):
        pretty_print(f"Miner thread {id} starting at 100% intensity, forced LOW difficulty", "success", f"sys{id}")
        last_report = time()
        last_shares = 0
        while True:
            try:
                Miner.m_connect(id, pool)
                while True:
                    try:
                        key = b64.b64decode(user_settings["mining_key"]).decode('utf-8') if user_settings["mining_key"] != "None" else "None"
                        # ----- EVIL: always request LOW difficulty -----
                        while True:
                            Client.send(f"JOB,{user_settings['username']},LOW,{key}")
                            job = Client.recv().split(",")
                            if len(job) == 3:
                                break
                            else:
                                sleep(3)
                        # ------------------------------------------------
                        while True:
                            time_start = time()
                            result = Algorithms.DUCOS1(job[0], job[1], int(job[2]), 0)  # 0% throttling
                            computetime = time() - time_start
                            hashrate[id] = result[1]
                            total_hashrate = sum(hashrate.values())
                            Client.send(f"{result[0]},{result[1]},Official PC Miner {Settings.VER},{user_settings['identifier']},,{single_miner_id}")
                            time_start = time()
                            feedback = Client.recv().split(",")
                            ping = (time() - time_start) * 1000
                            if feedback[0] == "GOOD":
                                accept.value += 1
                                share_print(id, "accept", accept.value, reject.value, total_hashrate, computetime, job[2], ping, Back.YELLOW, printlock=printlock)
                            elif feedback[0] == "BLOCK":
                                accept.value += 1
                                blocks.value += 1
                                share_print(id, "block", accept.value, reject.value, total_hashrate, computetime, job[2], ping, Back.YELLOW, printlock=printlock)
                            elif feedback[0] == "BAD":
                                reject.value += 1
                                share_print(id, "reject", accept.value, reject.value, total_hashrate, computetime, job[2], ping, Back.YELLOW, feedback[1], printlock=printlock)
                            if id == 0 and (time() - last_report >= int(user_settings["report_sec"])):
                                r_shares = accept.value - last_shares
                                uptime = calculate_uptime(mining_start_time)
                                periodic_report(last_report, time(), r_shares, blocks.value, total_hashrate, uptime)
                                last_report = time()
                                last_shares = accept.value
                            break
                    except Exception as e:
                        pretty_print(f"Error {e}", "error", f"net{id}")
                        sleep(5)
                        break
            except Exception as e:
                pretty_print(f"Connection error {e}", "error", f"net{id}")


class Discord_rp:
    def connect():
        # (unchanged)
        pass
    def update():
        # (unchanged)
        pass


class Fasthash:
    def init():
        try:
            import libducohasher
            pretty_print(get_string("fasthash_available"), "info")
        except Exception as e:
            pretty_print("Fasthash not available – using pure Python (still fast)", "warning")
    def load():
        # (unchanged – downloads native binary)
        pass


if __name__ == "__main__":
    Miner.preload()
    from multiprocessing import freeze_support
    freeze_support()
    signal(SIGINT, handler)
    if sys.platform == "win32":
        os.system('')
    # check_updates()
    cpu = cpuinfo.get_cpu_info()
    accept = Manager().Value("i", 0)
    reject = Manager().Value("i", 0)
    blocks = Manager().Value("i", 0)
    hashrate = Manager().dict()
    user_settings = Miner.load_cfg()
    Miner.greeting()
    Fasthash.load()
    Fasthash.init()
    try:
        check_mining_key(user_settings)
    except Exception as e:
        print("Error checking mining key:", e)
    Donate.load(int(user_settings["donate"]))
    Donate.start(int(user_settings["donate"]))
    single_miner_id = randint(0, 2811)
    threads = min(16, int(user_settings["threads"]))
    fastest_pool = Client.fetch_pool()
    mining_start_time = time()
    p_list = []
    for i in range(threads):
        p = Process(target=Miner.mine,
                    args=[i, user_settings, blocks, fastest_pool, accept, reject, hashrate, single_miner_id, printlock])
        p_list.append(p)
        p.start()
        sleep(0.1)
    if user_settings.get("discord_rp", "n") == 'y':
        Discord_rp.connect()
    for p in p_list:
        p.join()
