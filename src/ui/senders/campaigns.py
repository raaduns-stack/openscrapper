from __future__ import annotations

import re
import streamlit as st


def _lead_label(lead):
    data = lead.get('data') or {}
    name = ' '.join(x for x in [data.get('first_name'), data.get('last_name')] if x)
    return f"{name or 'Unnamed Lead'} · {data.get('email') or 'no email'} · {data.get('company_name') or '—'}"


def _sender_reply_to(api, sender_id, sender_email):
    try:
        detail = api('GET', f"/senders/{sender_id}")
        detail.raise_for_status()
        config = detail.json().get('config') or {}
        return config.get('reply_to') or sender_email
    except Exception:
        return sender_email


def _sender_label(sender):
    provider = (sender.get('provider') or 'smtp').replace('_', ' ').upper()
    return f"{sender.get('display_name') or sender.get('email')} · {sender.get('email')} · {provider}"


def _audience_label(audience):
    return f"{audience['name']} · {audience['completed_count']:,} Completed Leads"


def _step_state():
    return int(st.session_state.get('campaign-step', 1))


def _draft():
    return st.session_state.setdefault('campaign-draft', {})


def _go(step):
    st.session_state['campaign-step'] = max(1, min(4, step))
    st.rerun()


def render_campaigns(api, api_json, api_error, senders, letters, campaigns):
    st.subheader('Campaigns')
    st.caption('Create a campaign by choosing the audience, sender, message, and final review.')

    if not senders:
        st.info('Add a sender in Sender Configuration before creating a campaign.')
    else:
        audiences = api_json('GET', '/campaign-audiences')
        sender_map = {x['id']: x for x in senders}

        selected_sender_id = st.session_state.get('campaign-sender-id')
        selected_sender = sender_map.get(selected_sender_id) if selected_sender_id else None
        if selected_sender is None:
            selected_sender = senders[0]
            st.session_state['campaign-sender-id'] = selected_sender['id']

        step = _step_state()
        labels = [
            '1 · Campaign & Leads',
            '2 · Senders',
            '3 · Letter',
            '4 · Review / Sending Status',
        ]
        selected_label = st.radio(
            'Campaign steps',
            labels,
            index=step - 1,
            horizontal=True,
            label_visibility='collapsed',
        )
        selected_step = labels.index(selected_label) + 1
        if selected_step != step:
            st.session_state['campaign-step'] = selected_step
            step = selected_step

        if step == 1:
            st.markdown('### Campaign & Leads')
            st.caption('Choose the audience for this campaign and where replies should go.')

            draft = _draft()
            if 'campaign-name' not in st.session_state:
                st.session_state['campaign-name'] = draft.get('name', '')
            cname = st.text_input(
                'Campaign Name',
                placeholder='e.g. California Farmers — September Outreach',
                key='campaign-name',
            )

            if audiences:
                audience_ids = [x['id'] for x in audiences]
                current_audience = st.session_state.get('campaign-audience-id')
                audience_index = audience_ids.index(current_audience) if current_audience in audience_ids else 0
                audience_choice = st.selectbox(
                    'Lead Group / Search Group',
                    audiences,
                    index=audience_index,
                    format_func=_audience_label,
                    key='campaign-audience-choice',
                )
                st.session_state['campaign-audience-id'] = audience_choice['id']
                st.caption(f"{audience_choice['completed_count']:,} Completed Leads in this audience.")
            else:
                audience_choice = None
                st.info('No completed Lead groups are available yet.')

            if 'campaign-sender-name' not in st.session_state:
                st.session_state['campaign-sender-name'] = draft.get('sender_name', '')
            st.text_input(
                'Sender Name',
                placeholder='e.g. John Williams',
                key='campaign-sender-name',
                help='This is the name recipients will see in the From field of this campaign.',
            )

            reply_default = _sender_reply_to(api, selected_sender['id'], selected_sender['email'])
            if 'campaign-reply-to' not in st.session_state:
                st.session_state['campaign-reply-to'] = draft.get('reply_to', reply_default)
            st.text_input(
                'Reply To',
                key='campaign-reply-to',
                help='Replies to this campaign will be sent to this address.',
            )

            st.divider()
            if st.button('NEXT → Senders', type='primary', use_container_width=True):
                if not cname.strip():
                    st.error('Enter a campaign name.')
                elif not audience_choice:
                    st.error('Select a Lead Group / Search Group.')
                else:
                    draft['name'] = cname.strip()
                    draft['audience_scrap_id'] = audience_choice['id']
                    draft['audience_name'] = audience_choice['name']
                    draft['sender_name'] = st.session_state.get('campaign-sender-name', '').strip()
                    draft['reply_to'] = st.session_state.get('campaign-reply-to', reply_default).strip()
                    draft['sender_id'] = selected_sender['id']
                    _go(2)

        elif step == 2:
            st.markdown('### Senders')
            st.caption('Choose the sender account this campaign will use.')

            sender_ids = [s['id'] for s in senders]
            saved_sender_ids = st.session_state.get('campaign-sender-ids') or _draft().get('sender_ids') or []
            saved_sender_ids = [sid for sid in saved_sender_ids if sid in sender_ids]
            if not saved_sender_ids:
                saved_sender_ids = [st.session_state.get('campaign-sender-id') or senders[0]['id']]
            sender_pool = st.multiselect(
                'Sender Accounts',
                senders,
                default=[s for s in senders if s['id'] in saved_sender_ids],
                format_func=_sender_label,
                key='campaign-sender-pool',
                help='Select as many configured sender accounts as this campaign should use.',
            )
            selected_sender_ids = [s['id'] for s in sender_pool]
            st.session_state['campaign-sender-ids'] = selected_sender_ids
            if not selected_sender_ids:
                st.warning('Select at least one sender account.')
            else:
                primary_sender = sender_pool[0]
                st.session_state['campaign-sender-id'] = primary_sender['id']
                _draft()['sender_id'] = primary_sender['id']
                _draft()['sender_ids'] = selected_sender_ids
                _draft()['sender_name'] = st.session_state.get('campaign-sender-name', '').strip()

                st.caption(f'{len(sender_pool)} sender account(s) selected.')
                st.markdown('**Selected senders**')
                for sender in sender_pool:
                    st.markdown(f"- {sender.get('display_name') or '—'} · {sender.get('email') or '—'} · {(sender.get('provider') or 'smtp').replace('_', ' ').upper()}")

            st.caption('Each reusable sender account remains independent; selecting it here does not modify its configuration.')

            col_back, col_next = st.columns(2)
            with col_back:
                if st.button('← BACK', use_container_width=True):
                    _go(1)
            with col_next:
                if st.button('NEXT → Letter', type='primary', use_container_width=True):
                    if not st.session_state.get('campaign-sender-ids'):
                        st.warning('Select at least one sender account.')
                    else:
                        st.session_state['campaign-step'] = 3
                        st.rerun()

        elif step == 3:
            st.markdown('### Letter')
            st.caption('Choose the reusable message for this campaign, or create a new one.')

            with st.expander('＋ Create Letter'):
                with st.form('campaign-letter-create'):
                    new_letter_name = st.text_input('Letter Name')
                    new_letter_subject = st.text_input('Subject')
                    new_letter_body = st.text_area('Message')
                    create_letter = st.form_submit_button('CREATE LETTER', type='primary')
                if create_letter:
                    try:
                        if not new_letter_name.strip() or not new_letter_subject.strip() or not new_letter_body.strip():
                            raise ValueError('Letter name, subject and message are required.')
                        created = api('POST', '/letters', json={
                            'name': new_letter_name.strip(),
                            'subject': new_letter_subject.strip(),
                            'body_text': new_letter_body,
                            'body_html': None,
                            'variables': [],
                            'active': True,
                        })
                        created.raise_for_status()
                        created_letter = created.json()
                        st.session_state['campaign-created-letter-id'] = created_letter.get('id')
                        st.session_state['campaign-letter-notice'] = f"Letter '{created_letter.get('name') or new_letter_name.strip()}' created and selected."
                        st.rerun()
                    except Exception as exc:
                        st.error(api_error(exc, 'Could not create Letter.'))

            letter_notice = st.session_state.pop('campaign-letter-notice', None)
            if letter_notice:
                st.success(letter_notice)

            if letters:
                selected_letter_id = (
                    st.session_state.get('campaign-created-letter-id')
                    or _draft().get('letter_id')
                )
                selected_letter_index = next(
                    (i for i, item in enumerate(letters) if item['id'] == selected_letter_id),
                    0,
                )
                letter_choice = st.selectbox(
                    'Letter',
                    letters,
                    index=selected_letter_index,
                    format_func=lambda x: x['name'],
                    key='campaign-letter-choice',
                )
                st.markdown(f"**Subject:** {letter_choice.get('subject') or '—'}")
                st.text_area(
                    'Message Preview',
                    value=letter_choice.get('body_text') or '',
                    height=220,
                    disabled=True,
                    key='campaign-letter-preview',
                )
            else:
                letter_choice = None
                st.info('Create a Letter before continuing.')

            col_back, col_next = st.columns(2)
            with col_back:
                if st.button('← BACK', use_container_width=True):
                    _go(2)
            with col_next:
                if st.button('NEXT → Review', type='primary', use_container_width=True):
                    if not letter_choice:
                        st.error('Select or create a Letter.')
                    else:
                        _draft()['letter_id'] = letter_choice['id']
                        _draft()['letter_name'] = letter_choice['name']
                        _go(4)

        else:
            draft = _draft()
            cname = draft.get('name', '')
            audience_id = draft.get('audience_scrap_id')
            audience_choice = next((x for x in audiences if x['id'] == audience_id), None)
            selected_sender = sender_map.get(draft.get('sender_id')) or senders[0]
            selected_sender_ids = draft.get('sender_ids') or st.session_state.get('campaign-sender-ids') or [selected_sender['id']]
            selected_senders = [sender_map[sid] for sid in selected_sender_ids if sid in sender_map]
            letter_choice = next((x for x in letters if x['id'] == draft.get('letter_id')), None)
            sender_name = draft.get('sender_name') or selected_sender.get('display_name') or selected_sender.get('email') or ''
            reply_to = draft.get('reply_to') or _sender_reply_to(
                api, selected_sender['id'], selected_sender['email']
            )

            st.markdown('### Review')
            st.caption('Check your campaign details before creating the campaign.')

            st.markdown(f"**Campaign Name:** {cname or '—'}")
            st.markdown(
                f"**Audience:** {_audience_label(audience_choice) if audience_choice else 'Not selected'}"
            )
            st.markdown(f"**Sender Name:** {sender_name or '—'}")
            st.markdown(f"**Sender Accounts:** {len(selected_senders)} selected")
            for sender in selected_senders:
                st.caption(f"{sender.get('display_name') or '—'} · {sender.get('email') or '—'} · {(sender.get('provider') or 'smtp').replace('_', ' ').upper()}")
            st.markdown(f"**Reply To:** {reply_to or '—'}")
            st.markdown(f"**Letter:** {letter_choice.get('name') if letter_choice else '—'}")
            st.markdown(f"**Subject:** {letter_choice.get('subject') if letter_choice else '—'}")
            if letter_choice and letter_choice.get('body_text'):
                st.text_area(
                    'Message Preview',
                    value=letter_choice['body_text'],
                    height=180,
                    disabled=True,
                )

            st.divider()
            col_back, col_create = st.columns(2)
            with col_back:
                if st.button('← BACK', use_container_width=True):
                    _go(3)
            with col_create:
                if st.button('CREATE CAMPAIGN', type='primary', use_container_width=True):
                    try:
                        if not cname.strip():
                            raise ValueError('Enter a campaign name.')
                        if not audience_choice:
                            raise ValueError('Select a Lead Group / Search Group.')
                        if not letter_choice:
                            raise ValueError('Select a Letter.')
                        if not sender_name.strip():
                            raise ValueError('Enter a Sender Name.')
                        if not selected_senders:
                            raise ValueError('Select at least one sender account.')
                        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", reply_to.strip()):
                            raise ValueError('Reply To must be a valid email address.')

                        api('POST', '/campaigns', json={
                            'name': cname.strip(),
                            'sender_id': selected_sender['id'],
                            'letter_id': letter_choice['id'],
                            'audience_scrap_id': audience_choice['id'],
                            'lead_ids': [],
                            'config': {
                                'sender_name': sender_name.strip(),
                                'reply_to': reply_to.strip(),
                                'sender_ids': [s['id'] for s in selected_senders],
                            },
                        }).raise_for_status()

                        st.success('Campaign created.')
                        st.session_state.pop('campaign-draft', None)
                        for key in (
                            'campaign-name',
                            'campaign-audience-id',
                            'campaign-audience-choice',
                            'campaign-reply-to',
                            'campaign-sender-name',
                            'campaign-sender-name-default',
                            'campaign-reply-to-sender-id',
                            'campaign-sender-ids',
                            'campaign-sender-pool',
                            'campaign-sender-id',
                            'campaign-sender-choice',
                            'campaign-letter-choice',
                            'campaign-step',
                        ):
                            st.session_state.pop(key, None)
                        st.rerun()
                    except Exception as exc:
                        st.error(api_error(exc, 'Could not create campaign.'))

    st.divider()
    if campaigns:
        st.markdown('### Existing campaigns')
        for campaign in campaigns:
            audience = (campaign.get('config') or {}).get('audience') or {}
            sender = next((x for x in senders if x['id'] == campaign['sender_id']), None)
            letter = next((x for x in letters if x['id'] == campaign['letter_id']), None)
            with st.container(border=True):
                st.markdown(f"**{campaign['name']}**")
                if audience.get('type') == 'lead_group':
                    group = next((x for x in api_json('GET', '/campaign-audiences') if x['id'] == audience.get('scrap_id')), None)
                    audience_text = _audience_label(group) if group else 'Lead Group'
                else:
                    audience_text = 'Custom audience'
                st.caption(
                    f"{campaign['status'].upper()} · {audience_text} · "
                    f"{sender['email'] if sender else 'sender unavailable'} · "
                    f"{letter['name'] if letter else 'letter unavailable'}"
                )
                campaign_reply = (campaign.get('config') or {}).get('reply_to')
                if campaign_reply:
                    st.caption(f"Reply To: {campaign_reply}")

                if campaign['status'] == 'draft':
                    selected = api_json('GET', f"/campaigns/{campaign['id']}/leads")
                    if selected:
                        choices = {x['id']: x for x in selected}
                        choice = st.selectbox(
                            'Test recipient',
                            list(choices),
                            format_func=lambda i: _lead_label(choices[i]),
                            key=f"campaign-test-lead-{campaign['id']}",
                        )
                        if st.button(
                            'SEND TEST EMAIL',
                            key=f"campaign-test-send-{campaign['id']}",
                            type='primary',
                        ):
                            try:
                                api(
                                    'POST',
                                    f"/campaigns/{campaign['id']}/send-test",
                                    json={'lead_id': choice},
                                ).raise_for_status()
                                st.success('Test email sent.')
                                st.rerun()
                            except Exception as exc:
                                st.error(api_error(exc, 'Could not send test email.'))
                    else:
                        st.caption('No test recipient is available yet.')
    else:
        st.info('No campaigns yet.')
