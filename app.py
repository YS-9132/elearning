# -*- coding: utf-8 -*-
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import requests
from datetime import datetime
from config import SPREADSHEET_ID, GAS_URL

st.set_page_config(page_title="E-Learning", layout="centered")

# ===================== Google連携 =====================
@st.cache_resource
def get_spreadsheet():
    scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(dict(st.secrets["GOOGLE_CREDENTIALS"]), scopes=scope)
    return gspread.authorize(creds).open_by_key(SPREADSHEET_ID)

# ===================== データ取得 =====================
def get_users():
    sh = get_spreadsheet()
    data = sh.worksheet('ユーザーマスター').get_all_values()
    users = {}
    for i in range(1, len(data)):
        row = data[i]
        if len(row) > 0 and row[0]:
            users[row[0]] = {
                'email': row[1].strip(), 
                'dept_str': row[2].strip(),
                'dept_list': [d.strip() for d in row[2].split(',') if d.strip()],
                'role': row[3].strip() if len(row) > 3 else ''
            }
    return users

def get_questions():
    sh = get_spreadsheet()
    data = sh.worksheet('問題マスター').get_all_values()
    qs = []
    for i in range(1, len(data)):
        row = data[i]
        if len(row) > 0 and row[0]:
            qs.append({
                'id': row[0], 'question': row[1], 'options': [row[j] for j in range(2, 7)],
                'correct': [x.strip() for x in row[7].split(',')], 'is_multiple': row[8] == '複数選択'
            })
    return qs

def get_notify_targets(exam_dept, exam_email, users):
    sh = get_spreadsheet()
    data = sh.worksheet('通知マスター').get_all_values()
    if len(data) < 2: return []
    header, rows = data[0], data[1:]
    active_roles = set()
    for row in rows:
        if row[0] in (exam_dept, '全部署'):
            for idx, val in enumerate(row[1:]):
                if val.strip().upper() == 'ON': active_roles.add(header[idx+1])
    emails = [u['email'] for u in users.values() if u['role'] in active_roles and u['email'] != exam_email and ('全部署' in u['dept_list'] or exam_dept in u['dept_list'])]
    return list(set(emails))

# ===================== 保存・送信 =====================
def save_result(name, email, dept, role, score, passed):
    """スプレッドシート A:日時, B:氏名, C:メール, D:得点, E:合否 の順に保存"""
    ws = get_spreadsheet().worksheet('受験結果')
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    row_data = [ts, name, email, score, '合格' if passed else '不合格', dept, role]
    ws.append_row(row_data)

def send_email(to_email, name, dept, score, passed, total, users):
    try:
        subject = '[E-Learning] 採点結果'
        body = f"{name}様\n得点: {score}/{total}\n判定: {'合格' if passed else '不合格'}"
        def _s(addr, b): requests.post(GAS_URL, json={'to': addr, 'subject': subject, 'body': b}, allow_redirects=True)
        
        _s(to_email, body)
        targets = get_notify_targets(dept, to_email, users)
        for t in targets: 
            _s(t, f"管理者通知: {name}様が受験しました。\n判定: {'合格' if passed else '不合格'}")
        return targets
    except Exception as e:
        st.session_state.debug_error = str(e)
        return []

# ===================== 画面制御 =====================
if 'page' not in st.session_state: st.session_state.page = 'home'

def home_page():
    st.title('📚 E-Learning')
    users = get_users()
    name = st.selectbox('氏名を選択してください', sorted(users.keys()))
    if st.button('開始', type='primary', use_container_width=True):
        st.session_state.update({'u_name': name, 'u_email': users[name]['email'], 'u_dept': users[name]['dept_str'], 'u_role': users[name]['role'], 'page': 'exam', 'ans': {}})
        st.rerun()

def exam_page():
    st.title('📝 受験中')
    qs = get_questions()
    for i, q in enumerate(qs):
        st.write(f"### Q{i+1}: {q['question']}")
        st.session_state.ans[i] = st.radio(f"選択肢", ['A','B','C','D','E'], key=f"q{i}", index=None)
        for j, opt in enumerate(q['options']): 
            if opt: st.write(f"{chr(65+j)}. {opt}")
        st.write("---")
    if st.button('採点する', type='primary', use_container_width=True):
        score = sum(1 for i, q in enumerate(qs) if [st.session_state.ans.get(i)] == q['correct'])
        passed = (score == len(qs))
        save_result(st.session_state.u_name, st.session_state.u_email, st.session_state.u_dept, st.session_state.u_role, score, passed)
        st.session_state.debug_list = send_email(st.session_state.u_email, st.session_state.u_name, st.session_state.u_dept, score, passed, len(qs), get_users())
        st.session_state.update({'score': score, 'passed': passed, 'total': len(qs), 'page': 'result'})
        st.rerun()

def result_page():
    st.title('🎓 結果発表')
    if 'debug_list' in st.session_state: st.warning(f"🔍 通知送信先: {st.session_state.debug_list}")
    st.metric("得点", f"{st.session_state.score}/{st.session_state.total}")
    if st.session_state.passed: st.success("合格です！")
    else: st.error("不合格です。再挑戦してください。")
    if st.button('ホームへ戻る'): st.session_state.page = 'home'; st.rerun()

if st.session_state.page == 'home': home_page()
elif st.session_state.page == 'exam': exam_page()
elif st.session_state.page == 'result': result_page()
