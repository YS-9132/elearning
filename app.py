import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import smtplib  # 追加
from email.mime.text import MIMEText  # 追加
from datetime import datetime, timedelta, timezone # JST対応
import os
import json

# --- 設定（Secretsから取得） ---
# os.environ.get ではなく st.secrets を使います
SPREADSHEET_ID = st.secrets.get('SPREADSHEET_ID', '1Cl0TlNamAjIC4JfTpDOWc5IRpUJx3UqYhyiGXIZh5Mc')
SENDER_EMAIL = st.secrets.get('SENDER_EMAIL', 'nakano@mdsy.jp')
SMTP_PASSWORD = st.secrets.get('SMTP_PASSWORD')

# --- ここにその1行を入れます ---
st.set_page_config(page_title="E-Learning", layout="centered")

# --- 認証情報を取得 ---
def get_credentials(scopes):
    # Streamlit CloudのSecretsから [GOOGLE_CREDENTIALS] セクションを取得
    creds_info = st.secrets.get('GOOGLE_CREDENTIALS')
    
    if creds_info:
        # すでに辞書形式になっているので json.loads は不要です
        return Credentials.from_service_account_info(creds_info, scopes=scopes)
    else:
        # ローカルPCでのテスト用
        try:
            return Credentials.from_service_account_file('credentials.json', scopes=scopes)
        except Exception:
            st.error("認証情報が見つかりません。StreamlitのSecrets設定を確認してください。")
            return None

# Google Sheets 連携
@st.cache_resource
def get_spreadsheet():
    scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = get_credentials(scope)
    if not creds: return None
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID)

# Gmail API
@st.cache_resource
def get_gmail_service():
    scope = ['https://www.googleapis.com/auth/gmail.send']
    creds = get_credentials(scope)
    if not creds: return None
    return build('gmail', 'v1', credentials=creds)

# ユーザーマスター取得
def get_users():
    sh = get_spreadsheet()
    ws = sh.worksheet('ユーザーマスター')
    data = ws.get_all_values()
    users = {}
    for i in range(1, len(data)):
        if len(data[i]) > 0 and data[i][0]:
            users[data[i][0]] = data[i][1] if len(data[i]) > 1 else ''
    return users

# 問題取得
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
                'question': data[i][1] if len(data[i]) > 1 else '',
                'options': [data[i][j] if len(data[i]) > j else '' for j in range(2, 7)],
                'correct': correct_answers,
                'is_multiple': data[i][8] == '複数選択' if len(data[i]) > 8 else False
            })
    return questions

# 管理者メールをリストですべて取得
def get_admin_emails():
    sh = get_spreadsheet()
    ws = sh.worksheet('管理者マスター')
    data = ws.get_all_values()
    # A列の2行目以降（A2, A3...）から空でないアドレスをすべて取得
    emails = [row[0] for row in data[1:] if row and len(row) > 0 and row[0]]
    return emails

# 結果保存
def save_result(name, email, score, passed):
    sh = get_spreadsheet()
    ws = sh.worksheet('受験結果')
    # --- ここから日本時間（JST）にする処理 ---
    JST = timezone(timedelta(hours=+9), 'JST')
    ts = datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')
    # ---------------------------------------
    ws.append_row([ts, name, email, score, '合格' if passed else '不合格', ''])


def send_email(to_email, name, score, passed):
    if not SMTP_PASSWORD:
        st.error("SMTP_PASSWORD が設定されていません。")
        return False
    
    subject = '[E-Learning] 採点結果'
    body = f"{name} さん\n\nランサムウェア対策受験結果\n\n得点: {score}/5\n判定: {'合格' if passed else '不合格'}\n\n{'おめでとうございます！全問正解です。' if passed else f'あと{5-score}問で合格です。'}"
    
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = SENDER_EMAIL
    msg['To'] = to_email

    try:
        # Gmailのサーバーを使って直接送る
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(SENDER_EMAIL, SMTP_PASSWORD)
            
            # --- 1通目：受験者本人へ送信 ---
            server.send_message(msg)
            
            # --- 2通目以降：管理者マスター全員へ通知 ---
            admin_emails = get_admin_emails()
            for admin_email in admin_emails:
                admin_msg = MIMEText(body)
                admin_msg['Subject'] = f"【管理者通知】{subject}"
                admin_msg['From'] = SENDER_EMAIL
                admin_msg['To'] = admin_email
                
                server.send_message(admin_msg)
                
        return True
    except Exception as e:
        # エラーが出たら画面に表示されます
        st.error(f"メール送信エラー: {str(e)}")
        return False

# ページ状態初期化
if 'page' not in st.session_state:
    st.session_state.page = 'home'
if 'user_name' not in st.session_state:
    st.session_state.user_name = None
if 'user_email' not in st.session_state:
    st.session_state.user_email = None
if 'answers' not in st.session_state:
    st.session_state.answers = {}

# ホーム画面
def home_page():
    st.title('📚 E-Learning システム')
    st.markdown('### ランサムウェア対策について学習します')
    st.markdown('**問題数：5問**')
    st.markdown('---')
    
    users = get_users()
    user_list = sorted(list(users.keys()))
    
    selected_user = st.selectbox('氏名を選択してください', user_list)
    
    if st.button('学習を開始', use_container_width=True, type='primary'):
        st.session_state.user_name = selected_user
        st.session_state.user_email = users[selected_user]
        st.session_state.page = 'exam'
        st.session_state.answers = {}
        st.rerun()

# 受験画面
def exam_page():
    st.title('📝 受験画面')
    st.markdown(f'**受験者：{st.session_state.user_name}**')
    st.markdown('---')
    
    questions = get_questions()
    
    progress = len([a for a in st.session_state.answers.values() if a])
    st.progress(progress / len(questions), text=f'{progress}/{len(questions)}問 回答済み')
    
    for i, q in enumerate(questions):
        st.markdown(f"### Q{i+1}: {q['question']}")
        
        if q['is_multiple']:
            answers = st.multiselect(
                '複数選択',
                ['A', 'B', 'C', 'D', 'E'],
                default=st.session_state.answers.get(i, []),
                key=f'q{i}'
            )
        else:
            answer = st.radio(
                '選択肢',
                ['A', 'B', 'C', 'D', 'E'],
                key=f'q{i}',
                index=None
            )
            answers = [answer] if answer else []
        
        st.session_state.answers[i] = answers
        
        for j, opt in enumerate(q['options']):
            if opt:
                st.write(f"**{chr(65+j)}. {opt}**")
        
        st.markdown('---')
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button('戻る', use_container_width=True):
            st.session_state.page = 'home'
            st.rerun()
    
    with col2:
        if st.button('完了して採点', use_container_width=True, type='primary'):
            questions = get_questions()
            score = 0
            for i, q in enumerate(questions):
                user_answers = sorted(st.session_state.answers.get(i, []))
                correct_answers = sorted(q['correct'])
                if user_answers == correct_answers:
                    score += 1
            
            passed = score == 5
            
            # 結果保存
            save_result(st.session_state.user_name, st.session_state.user_email, score, passed)
            
            # メール送信
            send_email(st.session_state.user_email, st.session_state.user_name, score, passed)
            
            st.session_state.page = 'result'
            st.session_state.score = score
            st.session_state.passed = passed
            st.rerun()

# 結果画面
def result_page():
    st.title('🎓 採点結果')
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.markdown(f"### 得点")
        st.markdown(f"# {st.session_state.score}/5")
    
    with col2:
        st.markdown(f"### 判定")
        if st.session_state.passed:
            st.success('# 合格')
        else:
            st.error('# 不合格')
    
    st.markdown('---')
    
    if st.session_state.passed:
        st.balloons()
        st.markdown('### 🎉 おめでとうございます！全問正解で合格です。')
    else:
        st.markdown(f"### あと {5 - st.session_state.score}問で合格となります。")
    
    st.markdown('### メールで結果を送信しました。')
    
    st.markdown('---')
    
    if st.button('終了', use_container_width=True, type='primary'):
        st.session_state.page = 'home'
        st.rerun()

# ページ表示
if st.session_state.page == 'home':
    home_page()
elif st.session_state.page == 'exam':
    exam_page()
elif st.session_state.page == 'result':
    result_page()
