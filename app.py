import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import json
from config import SPREADSHEET_ID

st.set_page_config(page_title="E-Learning", layout="centered")

# ===================== Google連携 (エラー回避強化版) =====================
@st.cache_resource
def get_spreadsheet():
    scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    
    # Secretsから取得
    conf = st.secrets["GOOGLE_CREDENTIALS"]
    
    # もし「文字列」として読み込まれていたら、辞書に変換
    if isinstance(conf, str):
        conf = json.loads(conf, strict=False)
    
    # 【最重要】秘密鍵の形式をGoogleが読み込める形に強制変換
    if "private_key" in conf:
        # 1. すでにある改行を統一
        p_key = conf["private_key"].replace("\\n", "\n")
        # 2. 前後の不要な空白やクォーテーションを除去
        p_key = p_key.strip().strip('"').strip("'")
        conf["private_key"] = p_key
        
    creds = Credentials.from_service_account_info(conf, scopes=scope)
    return gspread.authorize(creds).open_by_key(SPREADSHEET_ID)

# ===================== データ取得 =====================
def get_users():
    try:
        sh = get_spreadsheet()
        data = sh.worksheet('ユーザーマスター').get_all_values()
        # A列:氏名, C列:部署 を取得 (1行目はヘッダーなので飛ばす)
        users = {row[0]: row[2] for row in data[1:] if len(row) > 2 and row[0]}
        return users
    except Exception as e:
        st.error(f"データの読み込みに失敗しました。秘密鍵の設定を確認してください。")
        return {}

# ===================== 画面表示 =====================
st.title('📚 E-Learning システム')
st.write('ランサムウェア対策について学習します')

users = get_users()

if users:
    name = st.selectbox('氏名を選択してください', sorted(users.keys()))
    st.info(f"部署：{users[name]}")
    if st.button('学習を開始', type='primary', use_container_width=True):
        st.success(f"準備完了！{name}さんの学習を開始します。")
else:
    st.warning("現在、システムにアクセスできません。")
