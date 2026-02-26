import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import json
from config import SPREADSHEET_ID

st.set_page_config(page_title="E-Learning", layout="centered")

# ===================== Google連携 (最小限) =====================
@st.cache_resource
def get_spreadsheet():
    scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    conf = st.secrets["GOOGLE_CREDENTIALS"]
    if isinstance(conf, str):
        conf = json.loads(conf, strict=False)
    
    # 秘密鍵のクリーニング
    if "private_key" in conf:
        conf["private_key"] = conf["private_key"].replace("\\n", "\n").strip()
        
    creds = Credentials.from_service_account_info(conf, scopes=scope)
    return gspread.authorize(creds).open_by_key(SPREADSHEET_ID)

# ===================== データ取得 =====================
def get_users():
    try:
        sh = get_spreadsheet()
        data = sh.worksheet('ユーザーマスター').get_all_values()
        users = {row[0]: row[2] for row in data[1:] if row[0]}
        return users
    except Exception as e:
        st.error(f"スプレッドシートが読み込めません: {e}")
        return {}

# ===================== メイン画面 =================
