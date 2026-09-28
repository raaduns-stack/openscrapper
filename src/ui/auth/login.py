import time
import requests
import streamlit as st
from .session import persist

def login(api,email,password,register=False,cookies=None):
    r=requests.post(f'{api}/auth/{"register" if register else "login"}',json={'email':email,'password':password},timeout=20); r.raise_for_status()
    data=r.json(); st.session_state.token=data['token']; st.session_state.user={'email':data['email']}; persist(data['token'],cookies)

def render(api,cookies=None):
    st.markdown("<style>section[data-testid='stSidebar']{display:none!important;}[data-testid='collapsedControl']{display:none!important;}</style>", unsafe_allow_html=True)
    st.title('Scrappee'); st.caption('Lead research workspace')
    tab1,tab2=st.tabs(['Sign in','Create account'])
    with tab1:
        with st.form('login'):
            e=st.text_input('Email'); p=st.text_input('Password',type='password'); ok=st.form_submit_button('Sign in',type='primary')
        if ok:
            try:
                login(api,e,p,cookies=cookies); time.sleep(0.5); st.rerun()
            except Exception: st.error('Sign in failed. Check your email and password.')
    with tab2:
        with st.form('register'):
            e=st.text_input('Email',key='reg-email'); p=st.text_input('Password',type='password',key='reg-password'); ok=st.form_submit_button('Create account',type='primary')
        if ok:
            try:
                login(api,e,p,register=True,cookies=cookies); time.sleep(0.5); st.rerun()
            except Exception: st.error('Account creation failed. Check your details or use another email.')
