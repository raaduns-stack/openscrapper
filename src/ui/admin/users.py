import requests
import streamlit as st

def toggle_admin_user(user_id):
    selected=st.session_state.admin_selected_users
    key=f'admin-select-user-{user_id}'
    if st.session_state.get(key,False):
        if len(selected) < 200: selected.add(user_id)
        else: st.session_state[key]=False
    else: selected.discard(user_id)

def render_users(api, api_json, api_error, **kwargs):
    with admin_tabs[2]:
        st.subheader('Users')
        st.caption('Delete test or unwanted accounts. Deletion cascades all owned data. The logged-in admin cannot delete itself.')
        try:
            user_filter=st.text_input('Filter users by email',key='admin-user-filter',placeholder='e.g. test@ or @example.com')
            page_size=st.selectbox('Users per page',[25,50,100,200],index=[25,50,100,200].index(st.session_state.admin_user_page_size),key='admin-user-page-size')
            if page_size != st.session_state.admin_user_page_size:
                st.session_state.admin_user_page_size=page_size;st.session_state.admin_user_page=1;st.rerun()
            data=api_json('GET','/admin/users/paged',params={'page':st.session_state.admin_user_page,'page_size':page_size,'search':user_filter.strip()})
            users=data['users'];total=data['total'];total_pages=max(1,data['total_pages'])
            if st.session_state.admin_user_page > total_pages:
                st.session_state.admin_user_page=total_pages;st.rerun()
            visible_ids={u['id'] for u in users if u['email'].lower()!=st.session_state.user['email'].lower()}
            selected_count=len(st.session_state.admin_selected_users)
            st.write(f"{total} users found · page {data['page']} of {total_pages}")
            top=st.columns([2,2,4])
            new_ids=visible_ids-st.session_state.admin_selected_users
            if top[0].button('SELECT ALL ON PAGE',key='admin-select-page',disabled=(not new_ids or selected_count + len(new_ids) > 200)):
                st.session_state.admin_selected_users.update(new_ids)
                for uid in new_ids: st.session_state[f'admin-select-user-{uid}']=True
                st.rerun()
            if top[1].button('CLEAR SELECTION',key='admin-clear-users',disabled=not st.session_state.admin_selected_users):
                for uid in list(st.session_state.admin_selected_users): st.session_state[f'admin-select-user-{uid}']=False
                st.session_state.admin_selected_users.clear();st.rerun()
            if selected_count:
                st.warning(f'{selected_count} user(s) selected')
                if selected_count > 200: st.error('Selection cannot exceed 200 users.')
                elif st.button(f'DELETE SELECTED ({selected_count})',key='admin-delete-selected',type='primary',disabled=selected_count==0):
                    st.session_state.pending_bulk_delete_users=list(st.session_state.admin_selected_users);st.rerun()
                if st.session_state.pending_bulk_delete_users:
                    ids=st.session_state.pending_bulk_delete_users
                    st.warning(f'Delete {len(ids)} selected user(s) permanently? This cannot be undone.')
                    confirm,cancel=st.columns(2)
                    if confirm.button('CONFIRM BULK DELETE',key='confirm-bulk-delete-users',type='primary'):
                        try:
                            r=api('POST','/admin/users/bulk-delete',json={'user_ids':ids});r.raise_for_status();deleted=r.json()['deleted']
                            for uid in ids: st.session_state.pop(f'admin-select-user-{uid}',None)
                            st.session_state.admin_selected_users.clear();st.session_state.pending_bulk_delete_users=None;st.success(f'Deleted {deleted} user(s).');st.rerun()
                        except requests.RequestException as exc: st.error(f'Could not delete selected users: {exc}')
                    if cancel.button('CANCEL',key='cancel-bulk-delete-users'): st.session_state.pending_bulk_delete_users=None;st.rerun()
            for u in users:
                cols=st.columns([1,5,2,1])
                is_self=u['email'].lower()==st.session_state.user['email'].lower()
                cols[0].checkbox('Select',value=(u['id'] in st.session_state.admin_selected_users),key=f"admin-select-user-{u['id']}",label_visibility='collapsed',disabled=is_self,on_change=toggle_admin_user,args=(u['id'],))
                cols[1].write(u['email']);cols[2].write(f"${u['balance_cents']/100:.2f}")
                if cols[3].button('DELETE',key=f"admin-delete-user-{u['id']}"):
                    st.session_state.pending_delete_user=u['id'];st.rerun()
                if st.session_state.pending_delete_user==u['id']:
                    st.warning(f"Delete user '{u['email']}' permanently? This cannot be undone.")
                    confirm,cancel=st.columns(2)
                    if confirm.button('CONFIRM DELETE',key=f"confirm-delete-user-{u['id']}",type='primary'):
                        try:
                            r=api('DELETE',f"/admin/users/{u['id']}");r.raise_for_status();st.session_state.admin_selected_users.discard(u['id']);st.session_state.pending_delete_user=None;st.rerun()
                        except requests.RequestException as exc: st.error(f'Could not delete user: {exc}')
                    if cancel.button('CANCEL',key=f"cancel-delete-user-{u['id']}"): st.session_state.pending_delete_user=None;st.rerun()
            nav=st.columns([1,1,2,1,1])
            if nav[0].button('FIRST',disabled=data['page']<=1,key='admin-users-first'): st.session_state.admin_user_page=1;st.rerun()
            if nav[1].button('PREVIOUS',disabled=data['page']<=1,key='admin-users-prev'): st.session_state.admin_user_page-=1;st.rerun()
            nav[2].write(f"Page {data['page']} / {total_pages}")
            if nav[3].button('NEXT',disabled=data['page']>=total_pages,key='admin-users-next'): st.session_state.admin_user_page+=1;st.rerun()
            if nav[4].button('LAST',disabled=data['page']>=total_pages,key='admin-users-last'): st.session_state.admin_user_page=total_pages;st.rerun()
        except Exception as exc: st.error(f'Could not load users: {exc}')
