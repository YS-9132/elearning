# -*- coding: utf-8 -*-
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import base64
import json
from datetime import datetime
from config import SPREADSHEET_ID, SENDER_EMAIL

st.set_page_config(page_title="E-Learning", layout="centered")

# ===================== Google連携 =====================
@st.cache_resource
def get_spreadsheet():
    scope = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    creds = Credentials.from_service_account_info(
        dict(st.secrets["GOOGLE_CREDENTIALS"]),
        scopes=scope
    )
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID)

@st.cache_resource
def get_gmail_service():
    scope = ['https://www.googleapis.com/auth/gmail.send']
    creds = Credentials.from_service_account_info(
        dict(st.secrets["GOOGLE_CREDENTIALS"]),
        scopes=scope
    )
    return build('gmail', 'v1', credentials=creds)

# ===================== データ取得 =====================

def get_users():
    """
    ユーザーマスター取得
    戻り値: {氏名: {email, dept_str, dept_list, role}}

    【権限ルール】
    - 権限が空欄 → 一般職（受験のみ、通知対象外）
    - 権限に値あり（部長・次長・課長・システム管理者等）→ 通知対象

    【部署ルール】
    - 単一部署：「営業」
    - 複数部署：「営業,修理室」（カンマ区切り）
    - 全部署：「全部署」
    """
    sh = get_spreadsheet()
    ws = sh.worksheet('ユーザーマスター')
    data = ws.get_all_values()
    users = {}
    for i in range(1, len(data)):
        row = data[i]
        if len(row) > 0 and row[0]:
            dept_str  = row[2].strip() if len(row) > 2 else ''
            dept_list = [d.strip() for d in dept_str.split(',') if d.strip()]
            users[row[0]] = {
                'email':     row[1].strip() if len(row) > 1 else '',
                'dept_str':  dept_str,
                'dept_list': dept_list,
                'role':      row[3].strip() if len(row) > 3 else ''
            }
    return users

def get_questions():
    """問題マスター取得"""
    sh = get_spreadsheet()
    ws = sh.worksheet('問題マスター')
    data = ws.get_all_values()
    questions = []
    for i in range(1, len(data)):
        row = data[i]
        if len(row) > 0 and row[0]:
            correct_answers = [x.strip() for x in row[7].split(',')] if len(row) > 7 else []
            questions.append({
                'id':          row[0],
                'question':    row[1] if len(row) > 1 else '',
                'options':     [row[j] if len(row) > j else '' for j in range(2, 7)],
                'correct':     correct_answers,
                'is_multiple': row[8] == '複数選択' if len(row) > 8 else False
            })
    return questions

def get_notify_targets(exam_dept: str, exam_role: str, exam_email: str, users: dict) -> list:
    """
    通知先メールアドレスを返す。

    【プライバシールール】
    - 受験者の権限が空欄（一般職）→ 通知マスターに基づき通知
    - 受験者の権限が空欄以外（管理職等）→ 本人のみ通知（他者には送らない）
    """
    # 管理職等が受験した場合は本人のみ（プライバシー保護）
    #if exam_role:
        #return []

    sh = get_spreadsheet()
    notify_ws   = sh.worksheet('通知マスター')
    notify_data = notify_ws.get_all_values()

    if len(notify_data) < 2:
        return []

    # ヘッダーから権限名を取得（B列以降）
    header    = notify_data[0]
    role_cols = header[1:]

    # 受験者の部署でONになっている権限を収集
    active_roles = set()
    for row in notify_data[1:]:
        if len(row) > 0 and row[0] in (exam_dept, '全部署'):
            for idx, role_name in enumerate(role_cols):
                col = idx + 1
                if len(row) > col and row[col].strip().upper() == 'ON':
                    active_roles.add(role_name)

    if not active_roles:
        return []

    # ユーザーマスターから通知対象を抽出
    emails = []
    for name, info in users.items():
        role      = info['role']
        dept_list = info['dept_list']
        mail      = info['email']

        if role not in active_roles:
            continue
        if mail == exam_email:
            continue

        if '全部署' in dept_list or exam_dept in dept_list:
            if mail:
                emails.append(mail)

    return list(set(emails))

def save_result(name: str, email: str, dept: str, role: str, score: int, passed: bool):
    """受験結果をスプレッドシートに保存（列の並びを修正）"""
    sh = get_spreadsheet()
    ws = sh.worksheet('受験結果')
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # 画像の並びに合わせて調整：受験日時, 氏名, メール, 部署, 役職, 得点, 合否
    row_data = [
        ts, 
        name, 
        email, 
        dept, 
        role if role else '一般職', 
        score, 
        '合格' if passed else '不合格'
    ]
    ws.append_row(row_data)

def send_email(to_email: str, name: str, dept: str, role: str,
               score: int, passed: bool, total: int, users: dict):
    """受験er本人＋通知対象者へメール送信"""
    try:
        service = get_gmail_service()
        subject = '[E-Learning] 採点結果'

        # --- ① 本文の作成 ---
        user_body = (
            f"{name} さん（{dept}）\n\n"
            f"ランサムウェア対策 受験結果\n\n"
            f"得点: {score}/{total}\n"
            f"判定: {'合格' if passed else '不合格'}\n\n"
            f"{'おめでとうございます！全問正解です。' if passed else f'あと {total - score} 問で合格です。'}"
        )

        admin_body = (
            f"【受験完了通知】\n\n"
            f"氏名: {name}\n"
            f"部署: {dept}\n"
            f"得点: {score}/{total}\n"
            f"判定: {'合格' if passed else '不合格'}\n"
            f"受験日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )

        # --- ② 送信用の関数定義 ---
        def _send(to_addr, body):
            raw = base64.urlsafe_b64encode(
                (
                    f"From: {SENDER_EMAIL}\n"
                    f"To: {to_addr}\n"
                    f"Subject: {subject}\n"
                    f"Content-Type: text/plain; charset=utf-8\n\n"
                    f"{body}"
                ).encode('utf-8')
            ).decode()
            service.users().messages().send(userId='me', body={'raw': raw}).execute()

        # ★ 本人送信（エラー詳細を表示）
        try:
            _send(to_email, user_body)
            st.success(f"✅ 本人送信成功: {to_email}")
        except Exception as e:
            # st.error ではなく session_state に保存する
            st.session_state.debug_error = str(e)  # ← これに変更
            return False

        notify_emails = get_notify_targets(dept, role, to_email, users)
        st.info(f"📋 通知先: {notify_emails}")

        # 4. 管理者に送る
        for addr in notify_emails:
            try:
                _send(addr, admin_body)
                st.success(f"✅ 管理者送信成功: {addr}")
            except Exception as e:
                st.error(f"❌ 管理者送信失敗 {addr}: {e}")

        return notify_emails

    except Exception as e:
        st.error(f"❌ 全体エラー: {e}")  # ← サービスアカウント取得失敗もここに出る
        return False
# ===================== ページ状態初期化 =====================
for key, default in [
    ('page', 'home'),
    ('user_name', None),
    ('user_email', None),
    ('user_dept', None),
    ('user_role', None),
    ('answers', {}),
    ('score', 0),
    ('passed', False),
    ('total', 0),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ===================== ホーム画面 =====================
def home_page():
    st.title('📚 E-Learning システム')
    st.markdown('### ランサムウェア対策について学習します')
    st.markdown('---')

    users = get_users()
    user_list = sorted(list(users.keys()))

    selected_user = st.selectbox('氏名を選択してください', user_list)

    if selected_user:
        info = users[selected_user]
        st.info(f"部署：{info['dept_str']}")

    if st.button('学習を開始', use_container_width=True, type='primary'):
        info = users[selected_user]
        st.session_state.user_name  = selected_user
        st.session_state.user_email = info['email']
        st.session_state.user_dept  = info['dept_str']
        st.session_state.user_role  = info['role']
        st.session_state.page       = 'exam'
        st.session_state.answers    = {}
        st.rerun()

# ===================== 受験画面 =====================
def exam_page():
    st.title('📝 受験画面')
    st.markdown(f"**受験者：{st.session_state.user_name}　部署：{st.session_state.user_dept}**")
    st.markdown('---')

    questions = get_questions()
    total = len(questions)

    progress = len([a for a in st.session_state.answers.values() if a])
    st.progress(progress / total, text=f'{progress}/{total}問 回答済み')

    for i, q in enumerate(questions):
        st.markdown(f"### Q{i+1}: {q['question']}")

        if q['is_multiple']:
            answers = st.multiselect(
                '複数選択（該当するものをすべて選んでください）',
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
            total  = len(questions)
            score  = 0
            for i, q in enumerate(questions):
                user_ans    = sorted(st.session_state.answers.get(i, []))
                correct_ans = sorted(q['correct'])
                if user_ans == correct_ans:
                    score += 1

            passed = (score == total)
            users  = get_users()

            save_result(
                st.session_state.user_name,
                st.session_state.user_email,
                st.session_state.user_dept,
                st.session_state.user_role,
                score, passed
            )

            # 【修正箇所】戻り値（リスト）を受け取って保存する
            sent_list = send_email(
                st.session_state.user_email,
                st.session_state.user_name,
                st.session_state.user_dept,
                st.session_state.user_role,
                score, passed, total, users
            )
            st.session_state.debug_list = sent_list # ここで保存！

            st.session_state.score  = score
            st.session_state.passed = passed
            st.session_state.total  = total
            st.session_state.page   = 'result'
            st.rerun()

# ===================== 結果画面 =====================
def result_page():
    st.title('🎓 採点結果')

    if 'debug_list' in st.session_state:
        st.warning(f"🔍 デバッグ通知先リスト: {st.session_state.debug_list}")

    # ★ これを追加
    if 'debug_error' in st.session_state and st.session_state.debug_error:
        st.error(f"❌ メール送信エラー詳細: {st.session_state.debug_error}")

    total = st.session_state.get('total', 5)

    col1, col2 = st.columns([1, 1])
    with col1:
        st.markdown("### 得点")
        st.markdown(f"# {st.session_state.score}/{total}")
    with col2:
        st.markdown("### 判定")
        if st.session_state.passed:
            st.success('# 合格')
        else:
            st.error('# 不合格')

    st.markdown('---')

    if st.session_state.passed:
        st.balloons()
        st.markdown('### 🎉 おめでとうございます！全問正解で合格です。')
    else:
        st.markdown(f"### あと {total - st.session_state.score} 問で合格となります。")

    st.markdown('### メールで結果を送信しました。')
    st.markdown('---')

    if st.button('終了', use_container_width=True, type='primary'):
        st.session_state.page = 'home'
        st.rerun()

# ===================== ページ表示 =====================
if st.session_state.page == 'home':
    home_page()
elif st.session_state.page == 'exam':
    exam_page()
elif st.session_state.page == 'result':
    result_page()
