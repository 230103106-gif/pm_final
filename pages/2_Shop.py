from __future__ import annotations

import h3
import streamlit as st

from core.database import get_session
from core.utils import ValidationError, currency, initialize_page, render_detail_grid, render_page_header
from services import order_service, product_service


user = initialize_page("Shop", icon="🛒", allowed_roles=["customer", "admin", "warehouse_manager"])
render_page_header(
    "Customer Ordering",
    "Browse furniture inventory and place delivery requests through a staged order workflow.",
    "The order is not created until delivery details, quantity, and final confirmation all pass validation.",
)

if "shop_step" not in st.session_state:
    st.session_state.shop_step = 1
if "shop_product_id" not in st.session_state:
    st.session_state.shop_product_id = None
if "shop_draft" not in st.session_state:
    st.session_state.shop_draft = {}

with get_session() as session:
    category_filter, search_filter = st.columns([0.3, 0.7], gap="large")
    categories = ["All"] + product_service.categories(session)
    with category_filter:
        selected_category = st.selectbox("Category", categories)
    with search_filter:
        search_term = st.text_input("Search the catalog", placeholder="Search by SKU, name, or description")

    products = product_service.list_products(session, category=selected_category, search=search_term)
    st.dataframe(product_service.product_rows(products), use_container_width=True, hide_index=True)

    if user.role != "customer":
        st.info("This page is in catalog preview mode for your role. Only customer accounts can submit new orders.")
        st.stop()

    product_options = {f"{product.sku} · {product.name}": product.id for product in products}
    city_options = {city["name"]: city for city in order_service.city_catalog()}

    st.subheader("Order builder")
    progress_cols = st.columns(3)
    for idx, title in enumerate(["1. Select product", "2. Delivery details", "3. Review and confirm"], start=1):
        with progress_cols[idx - 1]:
            st.markdown(
                f"**{title}**" if st.session_state.shop_step == idx else title
            )

    if st.session_state.shop_step == 1:
        with st.form("shop_select_product"):
            if not product_options:
                st.warning("No active products match the current filters.")
            selected_label = st.selectbox("Choose product", list(product_options.keys()) or ["No products available"])
            continue_clicked = st.form_submit_button("Continue to delivery details", type="primary")
            if continue_clicked and product_options:
                st.session_state.shop_product_id = product_options[selected_label]
                st.session_state.shop_step = 2
                st.rerun()

    elif st.session_state.shop_step == 2:
        selected_product = product_service.get_product(session, st.session_state.shop_product_id)
        st.markdown(
            f"""
            <div class="surface-card">
                <strong>{selected_product.name}</strong><br>
                <span class="mini-note">{selected_product.category} · {selected_product.material} · {currency(selected_product.price)}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        default_city_name = st.session_state.shop_draft.get("city", next(iter(city_options)))
        default_city = city_options[default_city_name]
        with st.form("shop_delivery_form"):
            recipient_name = st.text_input("Recipient name", value=st.session_state.shop_draft.get("recipient_name", user.full_name))
            phone = st.text_input("Phone", value=st.session_state.shop_draft.get("phone", "+1 "))
            address_line1 = st.text_input("Address line 1", value=st.session_state.shop_draft.get("address_line1", ""))
            address_line2 = st.text_input("Address line 2", value=st.session_state.shop_draft.get("address_line2", ""))
            city_name = st.selectbox("City", list(city_options.keys()), index=list(city_options.keys()).index(default_city_name))
            city = city_options[city_name]
            postal_code = st.text_input("Postal code", value=st.session_state.shop_draft.get("postal_code", ""))
            quantity = st.number_input("Quantity", min_value=1, max_value=max(selected_product.stock_quantity, 1), value=int(st.session_state.shop_draft.get("quantity", 1)))
            latitude = st.number_input("Latitude", min_value=-90.0, max_value=90.0, value=float(st.session_state.shop_draft.get("latitude", city["latitude"])), format="%.6f")
            longitude = st.number_input("Longitude", min_value=-180.0, max_value=180.0, value=float(st.session_state.shop_draft.get("longitude", city["longitude"])), format="%.6f")
            notes = st.text_area("Delivery instructions", value=st.session_state.shop_draft.get("notes", ""), height=110)
            left, right = st.columns(2)
            with left:
                back = st.form_submit_button("Back to product selection")
            with right:
                continue_review = st.form_submit_button("Review order", type="primary")
            if back:
                st.session_state.shop_step = 1
                st.rerun()
            if continue_review:
                st.session_state.shop_draft = {
                    "recipient_name": recipient_name,
                    "phone": phone,
                    "address_line1": address_line1,
                    "address_line2": address_line2,
                    "city": city_name,
                    "state": city["state"],
                    "postal_code": postal_code,
                    "country": city["country"],
                    "quantity": int(quantity),
                    "latitude": float(latitude),
                    "longitude": float(longitude),
                    "notes": notes,
                }
                st.session_state.shop_step = 3
                st.rerun()

    elif st.session_state.shop_step == 3:
        selected_product = product_service.get_product(session, st.session_state.shop_product_id)
        draft = st.session_state.shop_draft
        draft_region = h3.latlng_to_cell(draft["latitude"], draft["longitude"], order_service.settings.h3_resolution)
        st.subheader("Review before creating the order")
        left, right = st.columns([1.1, 0.9], gap="large")
        with left:
            render_detail_grid(
                {
                    "Product": selected_product.name,
                    "SKU": selected_product.sku,
                    "Quantity": str(draft["quantity"]),
                    "Unit Price": currency(selected_product.price),
                    "Order Total": currency(selected_product.price * draft["quantity"]),
                    "Recipient": draft["recipient_name"],
                    "City": f"{draft['city']}, {draft['state']}",
                    "H3 Region": draft_region,
                }
            )
            st.markdown(
                f"""
                <div class="surface-card" style="margin-top:1rem;">
                    <strong>Delivery address</strong>
                    <div class="mini-note">{draft['address_line1']} {draft['address_line2']}</div>
                    <div class="mini-note">{draft['city']}, {draft['state']} {draft['postal_code']}</div>
                    <div class="mini-note">Phone: {draft['phone']}</div>
                    <div class="mini-note">Instructions: {draft['notes'] or 'None provided'}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with right:
            with st.form("confirm_order_form"):
                confirm = st.checkbox("I confirm the quantity, delivery details, and regional assignment are correct.")
                back = st.form_submit_button("Back to details")
                create = st.form_submit_button("Create order", type="primary")
                if back:
                    st.session_state.shop_step = 2
                    st.rerun()
                if create:
                    if not confirm:
                        st.error("Please confirm the order details before submitting.")
                    else:
                        try:
                            order = order_service.create_order(
                                session,
                                user,
                                product_id=selected_product.id,
                                quantity=draft["quantity"],
                                recipient_name=draft["recipient_name"],
                                phone=draft["phone"],
                                address_line1=draft["address_line1"],
                                address_line2=draft["address_line2"],
                                city=draft["city"],
                                state=draft["state"],
                                postal_code=draft["postal_code"],
                                country=draft["country"],
                                latitude=draft["latitude"],
                                longitude=draft["longitude"],
                                notes=draft["notes"],
                            )
                            st.session_state.shop_step = 1
                            st.session_state.shop_product_id = None
                            st.session_state.shop_draft = {}
                            st.success(f"Order {order.order_number} created successfully.")
                            st.switch_page("pages/3_My_Orders.py")
                        except ValidationError as exc:
                            st.error(str(exc))
