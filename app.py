# -*- coding: utf-8 -*-
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import json
import requests
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
    conf = st.secrets["GOOGLE_CREDENTIALS"]
    
    if isinstance(conf, str):
        # 前後の余分な文字を除去してからパース
        conf = conf.strip()
        if conf.startswith('"') or conf.startswith("'"):
            conf = conf[1:-1]
        conf = json.loads(conf)
    else:
        conf = dict(conf)

    # private_keyの改行コードを修正
    if "private_key" in conf:
        conf["private_key"] = conf["private_key"].replace("\\n", "\n")

    creds = Credentials.from_service_account_info(conf, scopes=scope)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID)

# ===================== データ取得 =====================

def get_users():
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

    【追加ルール】
    - 受験者の権限が「部長」「次長」の場合 → 本人のみ通知（他者には送らない）
    - 受験者の権限がそれ以外の場合 → 通知マスターに基づき通知
    """
    # ① 部長・次長が受験した場合は、他者への通知リストを空にする（本人のみ受信）
    if exam_role in ['部長', '次長']:
        return []

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
        # 受験者の部署、または「全部署」行を参照
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

        # 通知マスターでONになっている役職かチェック
        if role not in active_roles:
            continue
        # 受験者本人は除外（二重送信防止）
        if mail == exam_email:
            continue

        # 部署が一致するか「全部署」設定の人ならリストに追加
        if '全部署' in dept_list or exam_dept in dept_list:
            if mail:
                emails.append(mail)

    return list(set(emails))

def save_result(name: str, email: str, dept: str, role: str, score: int, passed: bool):
    sh = get_spreadsheet()
    ws = sh.worksheet('受験結果')
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
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
    try:
        GAS_URL = st.secrets["GAS_URL"]

        subject = '[E-Learning] 採点結果'

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

        def _send(to_addr, body):
            res = requests.post(
                GAS_URL,
                data=json.dumps({
                    'to': to_addr,
                    'subject': subject,
                    'body': body
                }),
                headers={'Content-Type': 'application/json'},
                allow_redirects=True,
                timeout=10
            )
            st.session_state.debug_error = f"HTTP:{res.status_code} / {res.text[:300]}"
            return res.text

        _send(to_email, user_body)

        notify_emails = get_notify_targets(dept, role, to_email, users)

        for addr in notify_emails:
            try:
                _send(addr, admin_body)
            except Exception:
                pass

        return notify_emails

    except Exception as e:
        st.session_state.debug_error = str(e)
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

            sent_list = send_email(
                st.session_state.user_email,
                st.session_state.user_name,
                st.session_state.user_dept,
                st.session_state.user_role,
                score, passed, total, users
            )
            st.session_state.debug_list = sent_list

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
