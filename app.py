import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import json
from config import SPREADSHEET_ID

st.set_page_config(page_title="E-Learning", layout="centered")

# ===================== Google連携 (最終補正版) =====================
@st.cache_resource
def get_spreadsheet():
    scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    conf = st.secrets["GOOGLE_CREDENTIALS"]
    
    if isinstance(conf, str):
        # 余計な前後の空白や引用符を徹底的に排除
        conf = conf.strip().strip('"').strip("'")
        conf = json.loads(conf, strict=False)
    
    if "private_key" in conf:
        # 鍵の中身を掃除
        p_key = conf["private_key"]
        # 改行コードの変換
        p_key = p_key.replace("\\n", "\n")
        # 万が一、鍵自体が引用符で囲まれてしまっている場合の除去
        p_key = p_key.strip().strip('"').strip("'")
        conf["private_key"] = p_key
        
    creds = Credentials.from_service_account_info(conf, scopes=scope)
    return gspread.authorize(creds).open_by_key(SPREADSHEET_ID)

# ===================== データ取得 =====================
def get_users():
    try:
        sh = get_spreadsheet()
        data = sh.worksheet('ユーザーマスター').get_all_values()
        # A列:氏名, C列:部署 を取得
        return {row[0]: row[2] for row in data[1:] if len(row) > 2 and row[0]}
    except Exception as e:
        # エラー内容をデバッグ用に表示
        st.error(f"詳細エラー: {e}")
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
