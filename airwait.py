import subprocess
import time
import socket
import struct
import statistics
import os
import sys
import random
import tkinter as tk
from tkinter import messagebox
from datetime import datetime, timezone, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# ==========================================
# システム設定
# ==========================================
def get_chrome_path():
    if sys.platform == "win32":
        paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")
        ]
    elif sys.platform == "darwin":
        paths = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    else:
        paths = []
    for p in paths:
        if os.path.exists(p): return p
    return None

def get_free_port():
    while True:
        port = random.randint(20000, 60000)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('127.0.0.1', port)) != 0: return port

# ==========================================
# NTP同期システム
# ==========================================
NTP_SERVERS = ["ntp.nict.jp", "ntp.jst.mfeed.ad.jp", "time.google.com"]
JST = timezone(timedelta(hours=9))
GLOBAL_NTP_OFFSET = 0.0

def sync_ntp_offset():
    global GLOBAL_NTP_OFFSET
    thetas = []
    for host in NTP_SERVERS:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.5)
            pkt = bytearray(48); pkt[0] = 0b00_100_011
            t1 = time.time()
            struct.pack_into("!II", pkt, 40, int(t1) + 2208988800, int((t1 - int(t1)) * (1 << 32)))
            s.sendto(pkt, (host, 123))
            data, _ = s.recvfrom(48)
            t4 = time.time()
            o_sec, o_frac, r_sec, r_frac, t_sec, t_frac = struct.unpack("!IIIIII", data[24:48])
            t2 = (r_sec - 2208988800) + r_frac / (1 << 32); t3 = (t_sec - 2208988800) + t_frac / (1 << 32)
            thetas.append(((t2 - t1) + (t3 - t4)) / 2.0)
        except: pass
    GLOBAL_NTP_OFFSET = statistics.median(thetas) if thetas else 0.0

def get_current_ntp_time():
    return datetime.fromtimestamp(time.time() + GLOBAL_NTP_OFFSET, JST).replace(tzinfo=None)

# ==========================================
# GUIクラス
# ==========================================
class AppGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("AirWait 自動受付ツール")
        self.root.geometry("500x380")
        tk.Label(root, text="店舗URL:").pack(pady=5)
        self.url_entry = tk.Entry(root, width=60); self.url_entry.insert(0, "https://airwait.jp/WCSP/storeDetail?storeNo=AKR2233593754"); self.url_entry.pack()
        tk.Label(root, text="開始時刻 (YYYY-MM-DD HH:MM:SS):").pack(pady=5)
        self.time_entry = tk.Entry(root, width=30); self.time_entry.insert(0, datetime.now().strftime("%Y-%m-%d %H:%M:00")); self.time_entry.pack()
        tk.Label(root, text="オフセット秒 (例: -0.05):").pack(pady=5)
        self.offset_entry = tk.Entry(root, width=10); self.offset_entry.insert(0, "-0.05"); self.offset_entry.pack()
        self.start_button = tk.Button(root, text="ブラウザ起動 & ログイン準備", command=self.start_app, bg="lightblue", height=2); self.start_button.pack(pady=20)
        self.params = None
    def start_app(self):
        try:
            target_time = datetime.strptime(self.time_entry.get(), "%Y-%m-%d %H:%M:%S")
            offset = float(self.offset_entry.get())
            url = self.url_entry.get()
            self.params = (url, target_time, offset); self.root.destroy()
        except Exception as e: messagebox.showerror("入力エラー", f"形式が正しくありません。\n{e}")

# ==========================================
# メインロジック
# ==========================================
def main():
    root = tk.Tk(); app = AppGUI(root); root.mainloop()
    if not app.params: return
    TARGET_URL, TARGET_TIME, TIME_OFFSET = app.params
    chrome_path = get_chrome_path()
    if not chrome_path: return

    base_dir = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
    profile_path = os.path.join(base_dir, "Profile_AirWait")
    chrome_port = get_free_port()

    print(f"ブラウザを起動中... ポート:{chrome_port}")
    subprocess.Popen([chrome_path, f"--remote-debugging-port={chrome_port}", f"--user-data-dir={profile_path}", "--no-first-run", TARGET_URL])
    
    time.sleep(3)
    chrome_options = Options(); chrome_options.add_experimental_option("debuggerAddress", f"127.0.0.1:{chrome_port}")
    driver = webdriver.Chrome(options=chrome_options)

    print("\n1. ログインを済ませ、完了後 Enter を押してください。")
    input(">>> Enterを押すと再アクセスして待機を開始 <<<")

    driver.get(TARGET_URL)
    sync_ntp_offset()
    actual_target = TARGET_TIME + timedelta(seconds=TIME_OFFSET)

    while (actual_target - get_current_ntp_time()).total_seconds() > 0:
        diff = (actual_target - get_current_ntp_time()).total_seconds()
        if diff > 1: time.sleep(0.5)
        else: time.sleep(0.001)

    # --- 実行フェーズ ---
    try:
        print(f"時間です！ [{get_current_ntp_time().strftime('%H:%M:%S.%f')}] 更新")
        driver.refresh()

        # XPath定義
        xpath_start = "//button[@data-testid='extraButton']"
        xpath_recruit = "//*[contains(text(), 'リクルートIDで受付')] | //a[contains(@class, 'btn-recruit')]"
        xpath_confirm = "//*[contains(text(), '内容確認へ進む')] | //button[@type='submit']"
        xpath_submit = "//*[contains(text(), '受付する')] | //button[contains(@class, 'btn-primary')]"

        # 1. 「順番待ち受付をする」ボタン連打
        print("「順番待ち受付をする」ボタンを連打中...")
        while True:
            try:
                btn = driver.find_element(By.XPATH, xpath_start)
                driver.execute_script("arguments[0].click();", btn)
                # 次のいずれかのボタンが見つかれば遷移成功
                if driver.find_elements(By.XPATH, xpath_recruit) or driver.find_elements(By.XPATH, xpath_confirm):
                    print(" -> 遷移を確認しました")
                    break
            except:
                pass
            time.sleep(0.05)

        # 2. 「リクルートIDで受付する」確認とクリック
        # スキップ対応ロジック
        print("「リクルートIDで受付する」を確認中（なければスキップします）...")
        while True:
            # 既に次の「内容確認」ボタンが出ているかチェック
            if driver.find_elements(By.XPATH, xpath_confirm):
                print(" -> 「内容確認へ進む」ボタンを検知。ステップをスキップします。")
                break
            
            # リクルートIDボタンがあればクリック
            try:
                btn = driver.find_element(By.XPATH, xpath_recruit)
                driver.execute_script("arguments[0].click();", btn)
            except:
                pass
            time.sleep(0.05)

        # 3. 「内容確認へ進む」
        print("「内容確認へ進む」をクリック中...")
        while True:
            try:
                # 既に最終ボタンが出ているかチェック
                if driver.find_elements(By.XPATH, xpath_submit):
                    break
                
                btn = driver.find_element(By.XPATH, xpath_confirm)
                driver.execute_script("arguments[0].click();", btn)
            except:
                pass
            time.sleep(0.05)

        # 4. 「受付する」最終連打
        print("最終ボタン連打開始...")
        timeout_limit = time.time() + 20
        while time.time() < timeout_limit:
            try:
                btn = driver.find_element(By.XPATH, xpath_submit)
                driver.execute_script("arguments[0].click();", btn)
                if "complete" in driver.current_url.lower() or "finish" in driver.current_url.lower():
                    print("🎉 受付完了画面を確認！")
                    break
            except:
                pass
            time.sleep(0.03)

    except Exception as e:
        print(f"\n❌ エラー: {e}")

    finally:
        input("\nEnterで終了します。")
        driver.quit()

if __name__ == "__main__":
    main()