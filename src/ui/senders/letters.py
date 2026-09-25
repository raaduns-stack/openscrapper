from __future__ import annotations

import streamlit as st

def render_letters(api, api_error, letters):
    st.subheader('Letters'); st.caption('Reusable outbound message templates.')
    with st.expander('Create letter',expanded=not bool(letters)):
        with st.form('letter-create'):
            lname=st.text_input('Letter name'); subject=st.text_input('Subject'); body=st.text_area('Plain-text body',height=220); variables=st.text_input('Variables',placeholder='first_name, company_name'); save=st.form_submit_button('SAVE LETTER',type='primary')
        if save:
            try: api('POST','/letters',json={'name':lname,'subject':subject,'body_text':body,'variables':[x.strip() for x in variables.split(',') if x.strip()]}).raise_for_status(); st.success('Letter saved.'); st.rerun()
            except Exception as exc: st.error(api_error(exc,'Could not save letter.'))
    if letters:
        for letter in letters:
            with st.container(border=True):
                x,y=st.columns([5,1]); x.markdown(f"**{letter['name']}**"); x.caption(f"Subject: {letter['subject']} · {'Active' if letter['active'] else 'Archived'}")
                if y.button('DELETE',key=f"delete-letter-{letter['id']}"):
                    try: api('DELETE',f"/letters/{letter['id']}").raise_for_status(); st.rerun()
                    except Exception as exc: st.error(api_error(exc,'Could not delete letter.'))
    else: st.info('No letters configured.')
