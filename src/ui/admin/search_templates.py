import streamlit as st

PROVIDERS = ["google", "bing"]

VARIABLES = {
    "{industry}": "Industry — e.g. Healthcare",
    "{product}": "Product / service / subject — e.g. Doctor",
    "{geography}": "Geography — e.g. India",
    "{role}": "Role / job title — e.g. Doctor",
    "{keyword}": "User-supplied keyword(s)",
    "{target_type}": "Target type — people, companies, or both",
}


def _patch(api, template_id, payload):
    response = api("PATCH", f"/admin/search-templates/{template_id}", json=payload)
    response.raise_for_status()


def render_search_templates(api, api_json, api_error, **kwargs):
    st.subheader("Search Templates")
    st.caption("Manage deterministic search patterns. Templates may use only the approved variables below.")

    with st.expander("Approved template variables", expanded=True):
        st.caption("These are the only variables administrators can place inside a template. Values come from the user's approved New Scrap interpretation.")
        rows = [{"Variable": key, "Meaning": value} for key, value in VARIABLES.items()]
        st.table(rows)

    try:
        categories = api_json("GET", "/admin/search-template-categories")
    except Exception as exc:
        st.error(f"Could not load search categories: {exc}")
        categories = []

    active_categories = sum(bool(c.get("active")) for c in categories)
    m1, m2, m3 = st.columns(3)
    m1.metric("Categories", len(categories))
    m2.metric("Active categories", active_categories)
    m3.metric("Approved variables", len(VARIABLES))

    with st.expander("＋ Add category", expanded=False):
        with st.form("add-search-category", clear_on_submit=True):
            name = st.text_input("Category name", placeholder="e.g. Decision Makers")
            if st.form_submit_button("Add category", use_container_width=True):
                if not name.strip():
                    st.warning("Enter a category name.")
                else:
                    try:
                        api("POST", "/admin/search-template-categories", json={"name": name.strip()}).raise_for_status()
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Could not add category: {exc}")

    if not categories:
        st.info("No search categories exist yet.")
        return

    variable_caption = ", ".join(VARIABLES.keys())

    for category_index, category in enumerate(categories):
        try:
            templates = api_json("GET", f"/admin/search-template-categories/{category['id']}/templates")
        except Exception as exc:
            st.error(f"Could not load templates for {category['name']}: {exc}")
            templates = []

        with st.container(border=True):
            head, actions = st.columns([7, 3])
            head.markdown(f"### {category['name']}")
            head.caption(f"{len(templates)} template(s) · {'Active' if category.get('active') else 'Inactive'}")
            with actions:
                up, down, toggle = st.columns(3)
                if up.button("↑", key=f"cat-up-{category['id']}", disabled=category_index == 0, help="Move category up"):
                    api("PATCH", f"/admin/search-template-categories/{category['id']}", json={"position": category_index - 1}).raise_for_status()
                    st.rerun()
                if down.button("↓", key=f"cat-down-{category['id']}", disabled=category_index == len(categories) - 1, help="Move category down"):
                    api("PATCH", f"/admin/search-template-categories/{category['id']}", json={"position": category_index + 1}).raise_for_status()
                    st.rerun()
                if toggle.button("On/Off", key=f"cat-toggle-{category['id']}", help="Enable or disable category"):
                    api("PATCH", f"/admin/search-template-categories/{category['id']}", json={"active": not category["active"]}).raise_for_status()
                    st.rerun()

            if templates:
                for template_index, item in enumerate(templates):
                    with st.container(border=True):
                        top, rank = st.columns([7, 3])
                        top.markdown(f"**{template_index + 1}. {item['provider'].upper()}** · {item['family']}")
                        top.caption("ACTIVE" if item["active"] else "INACTIVE")
                        with rank:
                            r1, r2 = st.columns(2)
                            if r1.button("↑", key=f"up-{item['id']}", disabled=template_index == 0, help="Increase priority"):
                                _patch(api, item["id"], {"position": template_index - 1})
                                st.rerun()
                            if r2.button("↓", key=f"down-{item['id']}", disabled=template_index == len(templates) - 1, help="Decrease priority"):
                                _patch(api, item["id"], {"position": template_index + 1})
                                st.rerun()

                        st.code(item["template"], language="text")
                        st.caption(f"Approved variables: {variable_caption}")

                        e1, e2, e3 = st.columns(3)
                        if e1.button("Edit", key=f"edit-{item['id']}", use_container_width=True):
                            st.session_state[f"editing-template-{item['id']}"] = not st.session_state.get(f"editing-template-{item['id']}", False)
                            st.rerun()
                        if e2.button("Toggle status", key=f"toggle-{item['id']}", use_container_width=True):
                            _patch(api, item["id"], {"active": not item["active"]})
                            st.rerun()
                        if e3.button("Delete", key=f"delete-{item['id']}", use_container_width=True):
                            try:
                                api("DELETE", f"/admin/search-templates/{item['id']}").raise_for_status()
                                st.rerun()
                            except Exception as exc:
                                st.error(str(exc))

                        if st.session_state.get(f"editing-template-{item['id']}", False):
                            with st.form(f"edit-form-{item['id']}"):
                                ec1, ec2 = st.columns(2)
                                provider = ec1.selectbox("Provider", PROVIDERS, index=PROVIDERS.index(item["provider"]), key=f"edit-provider-{item['id']}")
                                family = ec2.text_input("Family", value=item["family"], key=f"edit-family-{item['id']}")
                                pattern = st.text_area("Template pattern", value=item["template"], key=f"edit-pattern-{item['id']}", help=f"Approved variables only: {variable_caption}")
                                save, cancel = st.columns(2)
                                if save.form_submit_button("Save changes", use_container_width=True):
                                    if not family.strip() or not pattern.strip():
                                        st.warning("Family and template pattern are required.")
                                    else:
                                        try:
                                            _patch(api, item["id"], {"provider": provider, "family": family.strip(), "template": pattern.strip()})
                                            st.session_state.pop(f"editing-template-{item['id']}", None)
                                            st.rerun()
                                        except Exception as exc:
                                            st.error(f"Could not update template: {exc}")
                                if cancel.form_submit_button("Cancel", use_container_width=True):
                                    st.session_state.pop(f"editing-template-{item['id']}", None)
                                    st.rerun()
            else:
                st.info("No templates in this category yet.")

            with st.expander("＋ Add template", expanded=False):
                with st.form(f"add-template-{category['id']}", clear_on_submit=True):
                    c1, c2 = st.columns(2)
                    provider = c1.selectbox("Provider", PROVIDERS, key=f"provider-{category['id']}")
                    family = c2.text_input("Family", value=category["name"].lower(), key=f"family-{category['id']}")
                    pattern = st.text_area("Template pattern", placeholder="{product} {role} {geography} contact", help=f"Approved variables only: {variable_caption}", key=f"template-{category['id']}")
                    st.caption("Example: {product} {role} {geography} contact")
                    if st.form_submit_button("Add template", use_container_width=True):
                        if not family.strip() or not pattern.strip():
                            st.warning("Family and template pattern are required.")
                        else:
                            try:
                                api("POST", "/admin/search-templates", json={"category_id": category["id"], "provider": provider, "family": family.strip(), "template": pattern.strip()}).raise_for_status()
                                st.rerun()
                            except Exception as exc:
                                st.error(f"Could not add template: {exc}")
