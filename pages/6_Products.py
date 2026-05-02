from __future__ import annotations

import streamlit as st

from core.database import get_session
from core.utils import ValidationError, initialize_page, render_page_header
from services import product_service


user = initialize_page("Products", icon="🪑", allowed_roles=["admin"])
render_page_header(
    "Product Catalog Management",
    "Curate the commercial catalog, keep stock levels honest, and retire inactive SKUs without deleting history.",
    "All product changes are audited and inventory counts feed directly into order validation.",
)

with get_session() as session:
    search_filter = st.text_input("Search products", placeholder="SKU, name, or description")
    products = product_service.list_products(session, include_inactive=True, search=search_filter)
    st.dataframe(product_service.product_rows(products), use_container_width=True, hide_index=True)

    export_path, export_payload = product_service.export_products_json(session)
    st.download_button("Download products.json", data=export_payload, file_name=export_path.name, mime="application/json")

    create_tab, edit_tab = st.tabs(["Create Product", "Edit Product"])
    with create_tab:
        with st.form("create_product_form"):
            sku = st.text_input("SKU")
            name = st.text_input("Name")
            category = st.text_input("Category")
            material = st.text_input("Material")
            dimensions = st.text_input("Dimensions")
            price = st.number_input("Price", min_value=0.01, value=499.0)
            stock_quantity = st.number_input("Stock quantity", min_value=0, value=10, step=1)
            description = st.text_area("Description", height=110)
            submit = st.form_submit_button("Create product", type="primary")
            if submit:
                try:
                    product_service.create_product(
                        session,
                        user,
                        {
                            "sku": sku,
                            "name": name,
                            "category": category,
                            "material": material,
                            "dimensions": dimensions,
                            "price": price,
                            "stock_quantity": int(stock_quantity),
                            "description": description,
                        },
                    )
                    st.success("Product created.")
                    st.rerun()
                except ValidationError as exc:
                    st.error(str(exc))

    with edit_tab:
        if not products:
            st.info("No products available to edit.")
        else:
            selection_map = {f"{product.sku} · {product.name}": product.id for product in products}
            selected_label = st.selectbox("Select product to edit", list(selection_map.keys()))
            product = product_service.get_product(session, selection_map[selected_label])
            with st.form("edit_product_form"):
                name = st.text_input("Name", value=product.name)
                category = st.text_input("Category", value=product.category)
                material = st.text_input("Material", value=product.material)
                dimensions = st.text_input("Dimensions", value=product.dimensions)
                price = st.number_input("Price", min_value=0.01, value=float(product.price))
                stock_quantity = st.number_input("Stock quantity", min_value=0, value=int(product.stock_quantity), step=1)
                is_active = st.checkbox("Active in catalog", value=product.is_active)
                description = st.text_area("Description", value=product.description, height=110)
                submit = st.form_submit_button("Save changes", type="primary")
                if submit:
                    try:
                        product_service.update_product(
                            session,
                            user,
                            product.id,
                            {
                                "name": name,
                                "category": category,
                                "material": material,
                                "dimensions": dimensions,
                                "price": price,
                                "stock_quantity": int(stock_quantity),
                                "is_active": is_active,
                                "description": description,
                            },
                        )
                        st.success("Product updated.")
                        st.rerun()
                    except ValidationError as exc:
                        st.error(str(exc))
