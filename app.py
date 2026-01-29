import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone

# --- 設定（Secretsから取得） ---
SPREADSHEET_ID = st.secrets.get('SPREADSHEET_ID', '1Cl0TlNamAjIC4JfTpDOWc5IRpUJx3UqYhyiGXIZh5Mc')
SENDER_EMAIL = st.secrets.get('SENDER_EMAIL', 'nakano.mdsy@gmail.com')
SMTP_PASSWORD = st.secrets.get('SMTP_PASSWORD')

st.set_page_config(page_title="E-Learning", layout="centered")

# --- 共通関数 ---
def get_credentials(scopes):
    creds_info = st.secrets.get('GOOGLE_CREDENTIALS')
    if creds_info:
        return Credentials.from_service_account_info(creds_info, scopes=scopes)
    return None

@st.cache_resource
def get_spreadsheet():
    scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = get_credentials(scope)
    if not creds: return None
    return gspread.authorize(creds).open_by_key(SPREADSHEET_ID)

def get_users():
    sh = get_spreadsheet()
    ws = sh.worksheet('ユーザーマスター')
    data = ws.get_all_values()
    return {row[0]: row[1] for row in data[1:] if row and len(row) > 1}

def get_questions():
    sh = get_spreadsheet()
    ws = sh.worksheet('問題マスター')
    data = ws.get_all_values()
    questions = []
    for i in range(1, len(data)):
        if len(data[i]) > 0 and data[i][0]:
            correct_answers = [x.strip() for x in data[i][7].split(',')] if len(data[i]) > 7 else []
            questions.append({
                'id': data[i][0],
                'question': data[i][1],
                'options': [data[i][j] for j in range(2, 7)],
                'correct': correct_answers,
                'is_multiple': data[i][8] == '複数選択'
            })
    return questions

def get_admin_emails():
    sh = get_spreadsheet()
    ws = sh.worksheet('管理者マスター')
    data = ws.get_all_values()
    return [row[0].strip() for row in data[1:] if row and row[0]]

def send_email(to_email, name, score, passed):
    subject = '[E-Learning] 採点結果'
    body = f"{name} さん\n\n受験結果のお知らせ\n\n得点: {score}/5\n判定: {'合格' if passed else '不合格'}"
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(SENDER_EMAIL, SMTP_PASSWORD)
            # 本人へ
            msg = MIMEText(body); msg['Subject'] = subject; msg['From'] = SENDER_EMAIL; msg['To'] = to_email
            server.send_message(msg)
            # 管理者全員へ
            for admin_email in get_admin_emails():
                admin_msg = MIMEText(body); admin_msg['Subject'] = f"【管理者通知】{subject}"; admin_msg['From'] = SENDER_EMAIL; admin_msg['To'] = admin_email
                server.send_message(admin_msg)
        return True
    except Exception as e:
        st.error(f"メール送信エラー: {str(e)}"); return False

# --- 画面制御 ---
if 'page' not in st.session_state: st.session_state.page = 'home'
if 'answers' not in st.session_state: st.session_state.answers = {}

def home_page():
    st.title('📚 E-Learning システム')
    users = get_users()
    name = st.selectbox('氏名を選択', sorted(users.keys()))
    if st.button('学習を開始', use_container_width=True, type='primary'):
        st.session_state.user_name, st.session_state.user_email = name, users[name]
        st.session_state.page = 'exam'; st.rerun()

def exam_page():
    st.title('📝 受験画面')
    st.write(f"受験者: {st.session_state.user_name}")
    
    # フォームを使うことで複数選択中のリロードを防ぐ
    with st.form("exam_form"):
        questions = get_questions()
        temp_answers = {}
        
        for i, q in enumerate(questions):
            st.markdown(f"### Q{i+1}: {q['question']}")
            if q['is_multiple']:
                temp_answers[i] = st.multiselect('（複数選択可）', ['A', 'B', 'C', 'D', 'E'], key=f"m{i}")
            else:
                ans = st.radio('選択してください', ['A', 'B', 'C', 'D', 'E'], key=f"r{i}", index=None)
                temp_answers[i] = [ans] if ans else []
            
            for j, opt in enumerate(q['options']):
                if opt: st.write(f"{chr(65+j)}. {opt}")
            st.write("---")
        
        # フォーム内のボタンが押された時だけ処理が進む
        submitted = st.form_submit_button("完了して採点", use_container_width=True, type="primary")
        
        if submitted:
            score = sum(1 for i, q in enumerate(questions) if sorted(temp_answers[i]) == sorted(q['correct']))
            passed = (score == 5)
            # 保存と送信
            sh = get_spreadsheet(); ws = sh.worksheet('受験結果')
            ts = datetime.now(timezone(timedelta(hours=+9))).strftime('%Y-%m-%d %H:%M:%S')
            ws.append_row([ts, st.session_state.user_name, st.session_state.user_email, score, '合格' if passed else '不合格'])
            send_email(st.session_state.user_email, st.session_state.user_name, score, passed)
            
            st.session_state.score, st.session_state.passed = score, passed
            st.session_state.page = 'result'; st.rerun()

def result_page():
    st.title('🎓 採点結果')
    st.metric("得点", f"{st.session_state.score}/5")
    if st.session_state.passed: st.success('合格！'); st.balloons()
    else: st.error('不合格')
    if st.button('ホームに戻る', use_container_width=True):
        st.session_state.page = 'home'; st.session_state.answers = {}; st.rerun()

# 実行
if st.session_state.page == 'home': home_page()
elif st.session_state.page == 'exam': exam_page()
elif st.session_state.page == 'result': result_page()
