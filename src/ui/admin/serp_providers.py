import streamlit as st

def render_serp_providers(api, api_json, api_error, **kwargs):
        st.subheader('Premium SERP Providers')
        st.caption('Exactly four providers are supported. Credentials are stored encrypted server-side.')
        try: providers=api_json('GET','/admin/premium-providers')
        except Exception as exc: providers=[]; st.error(f'Could not load Premium providers: {exc}')
        for cfg in providers:
            provider=cfg['provider']; label={'serper':'Serper','dataforseo':'DataForSEO','serpapi':'SerpApi','brightdata':'Bright Data'}[provider]
            status='CONFIGURED' if cfg.get('configured') else 'NOT CONFIGURED'
            default=' — DEFAULT' if cfg['is_default'] else ''
            with st.expander(f"{label} — {status}{default}",expanded=cfg['is_default']):
                enabled=st.checkbox('Enabled',value=cfg['enabled'],key=f'prov-enabled-{provider}')
                make_default=st.checkbox('Make default',value=cfg['is_default'],key=f'prov-default-{provider}')
                creds={};settings=dict(cfg.get('settings') or {})
                if provider=='serper':
                    if cfg.get('configured'): st.caption('Credential configured — leave blank to keep the existing key.')
                    creds['api_key']=st.text_input('API key',type='password',placeholder='Configured — leave blank to keep',key=f'prov-key-{provider}')
                    settings['endpoint']=st.text_input('API URL',value=settings.get('endpoint','https://google.serper.dev/search'),key=f'prov-url-{provider}')
                elif provider=='dataforseo':
                    if cfg.get('configured'): st.caption('Credentials configured — leave blank to keep the existing credentials.')
                    creds['login']=st.text_input('API login',type='password',placeholder='Configured — leave blank to keep',key=f'prov-login-{provider}')
                    creds['password']=st.text_input('API password',type='password',placeholder='Configured — leave blank to keep',key=f'prov-password-{provider}')
                    settings['base_url']=st.text_input('API URL',value=settings.get('base_url','https://api.dataforseo.com'),key=f'prov-url-{provider}')
                    settings['location_code']=st.number_input('Location code',value=int(settings.get('location_code',2840)),min_value=1,key=f'prov-location-{provider}')
                    settings['language_code']=st.text_input('Language code',value=settings.get('language_code','en'),key=f'prov-language-{provider}')
                elif provider=='serpapi':
                    if cfg.get('configured'): st.caption('Credential configured — leave blank to keep the existing key.')
                    creds['api_key']=st.text_input('API key',type='password',placeholder='Configured — leave blank to keep',key=f'prov-key-{provider}')
                    settings['endpoint']=st.text_input('API URL',value=settings.get('endpoint','https://serpapi.com/search.json'),key=f'prov-url-{provider}')
                else:
                    if cfg.get('configured'): st.caption('Credential configured — leave blank to keep the existing key.')
                    creds['api_key']=st.text_input('API key',type='password',placeholder='Configured — leave blank to keep',key=f'prov-key-{provider}')
                    settings['endpoint']=st.text_input('API URL',value=settings.get('endpoint','https://api.brightdata.com/request'),key=f'prov-url-{provider}')
                    settings['zone']=st.text_input('SERP zone',value=settings.get('zone','serp_api1'),key=f'prov-zone-{provider}')
                if st.button('SAVE PROVIDER',key=f'prov-save-{provider}',type='primary'):
                    try: api('POST',f'/admin/premium-providers/{provider}',json={'credentials':creds,'settings':settings,'enabled':enabled,'make_default':make_default}).raise_for_status();st.rerun()
                    except Exception as exc: st.error(f'Could not save {label}: {exc}')
