import streamlit as st

def render_billing(api, api_json, api_error, **kwargs):
        st.subheader('Billing & Research Limits')
        try:
            bill=api_json('GET','/billing')
            with st.form('admin-limits'):
                scrap_price=st.number_input('New Scrap price ($)',min_value=0.0,value=bill['scrap_creation_price_cents']/100,step=0.01)
                premium_price=st.number_input('Premium SERP price ($)',min_value=0.0,value=bill['premium_serp_price_cents']/100,step=0.01)
                paid_unit_price=st.number_input('Paid Enrichment unit price ($/Lead)',min_value=0.000001,value=bill['paid_enrichment_unit_micros_usd']/1000000,step=0.001,format='%.6f')
                admin_research=api_json('GET','/admin/settings')
                serp_limit=st.number_input('SERP result limit',min_value=1,max_value=1000000,value=int(admin_research.get('serp_result_limit',1000)),step=100)
                default_max_leads=st.number_input('Default leads per Scrap',min_value=1,max_value=100000,value=int(admin_research.get('research_default_max_leads',100)),step=10)
                max_leads_limit=st.number_input('Maximum leads allowed per Scrap',min_value=1,max_value=100000,value=int(admin_research.get('research_max_leads',10000)),step=10)
                timeout_hours=st.number_input('Research timeout (hours)',min_value=1,max_value=720,value=int(admin_research.get('research_timeout_hours',48)),step=1)
                st.caption('A Scrap stops when it reaches its lead target or the research timeout, whichever comes first.')
                if st.form_submit_button('SAVE BILLING & LIMITS',type='primary'):
                    if default_max_leads > max_leads_limit: st.error('Default leads cannot exceed the maximum allowed leads.')
                    else:
                        api('POST','/admin/scrap-price',params={'amount_cents':round(scrap_price*100)}).raise_for_status()
                        api('POST','/admin/premium-serp-price',json={'amount_cents':round(premium_price*100)}).raise_for_status()
                        api('POST','/admin/paid-enrichment-price',json={'unit_micros_usd':round(paid_unit_price*1000000)}).raise_for_status()
                        api('POST','/admin/serp-limit',json={'limit':int(serp_limit)}).raise_for_status()
                        api('POST','/admin/research-settings',json={'default_max_leads':int(default_max_leads),'max_leads':int(max_leads_limit),'timeout_hours':int(timeout_hours)}).raise_for_status();st.success('Billing and research limits saved.');st.rerun()
        except Exception as exc: st.error(f'Could not load admin billing settings: {exc}')
