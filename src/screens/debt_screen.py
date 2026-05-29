import flet as ft
from datetime import datetime, timedelta
from uuid import uuid4


class DebtScreen:
    def __init__(self, page: ft.Page, db, sync_service, auth_service, current_user):
        self.page = page
        self.db = db
        self.sync_service = sync_service
        self.auth_service = auth_service
        self.current_user = current_user

        self.tab_view = None

        # Nouvel emprunt
        self.borrow_cart = []
        self.selected_product = None

        self.product_search = None
        self.product_list = None
        self.selected_product_text = None

        self.customer_name = None
        self.quantity_field = None
        self.unit_price_field = None
        self.due_date = None
        self.notes = None

        self.cart_list = None
        self.total_amount_text = None

        # Paiement
        self.debt_dropdown = None
        self.debt_details = None
        self.payment_amount = None
        self.payment_date = None
        self.selected_debt_id = None

        # Liste
        self.debt_list_view = None

    # =========================================================
    # OUTILS UI
    # =========================================================
    def notify(self, message: str, success: bool = False):
        snack = ft.SnackBar(
            content=ft.Text(message),
            bgcolor=ft.Colors.GREEN_700 if success else ft.Colors.RED_700,
            duration=4000,
        )

        if hasattr(self.page, "show_snack_bar"):
            self.page.show_snack_bar(snack)
        elif hasattr(self.page, "open"):
            self.page.open(snack)
        else:
            self.page.snack_bar = snack
            snack.open = True

        self.page.update()

    def show_error(self, message: str):
        self.notify(message, success=False)

    def show_success(self, message: str):
        self.notify(message, success=True)

    def _safe_float(self, value, default=0.0):
        try:
            if value is None or value == "":
                return default
            return float(value)
        except Exception:
            return default

    def _safe_int(self, value, default=0):
        try:
            if value is None or value == "":
                return default
            return int(float(value))
        except Exception:
            return default

    def _format_money(self, amount) -> str:
        try:
            return f"{float(amount):,.0f} FC"
        except Exception:
            return "0 FC"

    def _branch_id(self):
        branch_id = (self.current_user.get("active_branch_id") or 
                    self.current_user.get("branch_id") or
                    self.current_user.get("current_branch_id"))
        
        if branch_id is None:
            print("⚠️ ATTENTION: branch_id est None dans DebtScreen!")
            user = self.auth_service.get_current_user()
            if user:
                branch_id = user.get("active_branch_id") or user.get("branch_id")
        
        return branch_id

    # =========================================================
    # ÉCRAN
    # =========================================================
    def show(self):
        self.page.clean()
        
        # Variables pour suivre l'onglet actif
        self.current_tab_index = 0
        
        # Créer les contenus
        self.tab1_content = self.create_new_debt_tab()
        self.tab2_content = self.create_payment_tab()
        self.tab3_content = self.create_debt_list_tab()
        
        # Conteneur pour le contenu actif
        self.content_container = ft.Container(
            content=self.tab1_content,
            expand=True,
            padding=10,
        )
        
        # Barre d'onglets personnalisée
        tab_bar = ft.Container(
            content=ft.Row(
                controls=[
                    self._create_tab_button("Nouvel emprunt", ft.Icons.EDIT_NOTE, 0),
                    self._create_tab_button("Paiement", ft.Icons.PAYMENT, 1),
                    self._create_tab_button("Liste", ft.Icons.LIST_ALT, 2),
                ],
                alignment=ft.MainAxisAlignment.SPACE_EVENLY,
            ),
            bgcolor=ft.Colors.GREY_200,
            border_radius=ft.BorderRadius.all(10),
            padding=5,
        )
        
        header = ft.Container(
            content=ft.Row(
                controls=[
                    ft.IconButton(
                        icon=ft.Icons.ARROW_BACK,
                        on_click=lambda e: self.go_back(),
                        icon_color=ft.Colors.WHITE,
                    ),
                    ft.Text(
                        "Gestion des dettes",
                        size=22,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.WHITE,
                        expand=True,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.REFRESH,
                        on_click=lambda e: self.refresh_data(),
                        icon_color=ft.Colors.WHITE,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=12,
            bgcolor=ft.Colors.ORANGE_700,
            border_radius=10,
        )
        
        self.page.add(
            ft.Container(
                content=ft.Column(
                    controls=[
                        header,
                        tab_bar,
                        self.content_container,
                    ],
                    expand=True,
                ),
                expand=True,
                padding=10,
            )
        )
        self.page.update()

    def _create_tab_button(self, label, icon, index):
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Icon(icon, size=20, color=ft.Colors.GREY_700),
                    ft.Text(label, size=12, color=ft.Colors.GREY_700),
                ],
                spacing=2,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=15, vertical=8),
            border_radius=8,
            on_click=lambda e: self._switch_tab(index),
        )

    def _switch_tab(self, index):
        self.current_tab_index = index
        if index == 0:
            self.content_container.content = self.tab1_content
        elif index == 1:
            self.content_container.content = self.tab2_content
        else:
            self.content_container.content = self.tab3_content
        self.page.update()

    # =========================================================
    # ONGLET 1 - NOUVEL EMPRUNT MULTI-PRODUITS
    # =========================================================
    def create_new_debt_tab(self):
        self.product_search = ft.TextField(
            label="Rechercher un produit",
            hint_text="Tapez le nom du produit...",
            prefix_icon=ft.Icons.SEARCH,
            on_change=self.search_products,
            expand=True,
        )

        self.product_list = ft.Column(height=200, spacing=6, scroll=ft.ScrollMode.AUTO)
        self.selected_product_text = ft.Text(
            "Aucun produit sélectionné",
            size=12,
            color=ft.Colors.GREY_700,
        )

        self.customer_name = ft.TextField(
            label="Nom du client",
            hint_text="Nom de la personne qui emprunte",
            expand=True,
        )

        self.quantity_field = ft.TextField(
            label="Quantité",
            hint_text="Ex: 2",
            keyboard_type=ft.KeyboardType.NUMBER,
            expand=True,
            value="1",
        )

        self.unit_price_field = ft.TextField(
            label="Prix unitaire",
            hint_text="Ex: 2500",
            keyboard_type=ft.KeyboardType.NUMBER,
            expand=True,
        )

        self.due_date = ft.TextField(
            label="Date d'échéance",
            hint_text="JJ/MM/AAAA",
            value=(datetime.now() + timedelta(days=30)).strftime("%d/%m/%Y"),
            expand=True,
        )

        self.notes = ft.TextField(
            label="Notes",
            hint_text="Infos complémentaires...",
            multiline=True,
            min_lines=2,
            max_lines=3,
            expand=True,
        )

        self.total_amount_text = ft.Text(
            "Total général: 0 FC",
            size=16,
            weight=ft.FontWeight.BOLD,
            color=ft.Colors.ORANGE_700,
        )

        self.cart_list = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO)

        self.quantity_field.on_change = self.update_preview_total
        self.unit_price_field.on_change = self.update_preview_total

        add_product_button = ft.Button(
            content=ft.Text("Ajouter au panier d'emprunt"),
            icon=ft.Icons.ADD_SHOPPING_CART,
            on_click=self.add_selected_product_to_cart,
            height=48,
        )

        save_button = ft.Button(
            content=ft.Text("Enregistrer l'emprunt"),
            icon=ft.Icons.SAVE,
            on_click=self.save_debt,
            height=50,
            style=ft.ButtonStyle(
                bgcolor=ft.Colors.ORANGE_700,
                color=ft.Colors.WHITE,
            ),
        )

        form_block = ft.Column(
            controls=[
                ft.Text("1. Rechercher et sélectionner un produit", weight=ft.FontWeight.BOLD),
                self.product_search,
                ft.Container(content=self.product_list, height=220),
                self.selected_product_text,
                ft.Divider(),
                ft.Text("2. Renseigner les informations de l'article", weight=ft.FontWeight.BOLD),
                ft.Row(
                    controls=[
                        self.quantity_field,
                        self.unit_price_field,
                    ],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                add_product_button,
                ft.Divider(),
                ft.Text("3. Informations client", weight=ft.FontWeight.BOLD),
                self.customer_name,
                ft.Row(
                    controls=[
                        self.due_date,
                    ],
                    spacing=10,
                ),
                self.notes,
            ],
            spacing=12,
        )

        cart_block = ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Text("Produits ajoutés", size=16, weight=ft.FontWeight.BOLD, expand=True),
                        ft.TextButton(
                            "Vider",
                            icon=ft.Icons.DELETE_SWEEP,
                            on_click=self.clear_cart,
                        ),
                    ]
                ),
                ft.Container(
                    content=self.cart_list,
                    padding=10,
                    border=ft.Border.all(color=ft.Colors.GREY_300),
                    border_radius=10,
                    height=200,
                ),
                self.total_amount_text,
                save_button,
            ],
            spacing=12,
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    form_block,
                    ft.Divider(height=20),
                    cart_block,
                ],
                spacing=12,
                scroll=ft.ScrollMode.AUTO,
            ),
            expand=True,
            padding=10,
        )

    def search_products(self, e):
        search_term = (self.product_search.value or "").strip().lower()

        self.product_list.controls.clear()

        if not search_term:
            self.page.update()
            return

        products = self.db.get_products(self._branch_id())
        filtered = []
        
        for p in products:
            # CORRECTION: Vérifier le type de l'objet et accéder aux attributs correctement
            if hasattr(p, 'name'):
                # C'est un objet Product
                name = p.name
                stock = getattr(p, 'quantity', 0) or getattr(p, 'stock', 0)
                price = getattr(p, 'selling_price', 0) or getattr(p, 'price', 0)
            elif isinstance(p, dict):
                # C'est un dictionnaire
                name = p.get("name", "")
                stock = p.get("quantity", 0) or p.get("stock", 0)
                price = p.get("selling_price", 0) or p.get("price", 0)
            else:
                continue
            
            if search_term in str(name).lower():
                filtered.append({
                    'obj': p,
                    'name': name,
                    'stock': stock,
                    'price': price
                })

        for product_data in filtered[:12]:
            product = product_data['obj']
            stock = self._safe_int(product_data['stock'], 0)
            price = self._safe_float(product_data['price'], 0)
            name = str(product_data['name'])

            tile = ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Column(
                            controls=[
                                ft.Text(name, weight=ft.FontWeight.BOLD),
                                ft.Text(f"Stock: {stock} | Prix: {self._format_money(price)}", size=11),
                            ],
                            spacing=2,
                            expand=True,
                        ),
                        ft.Icon(ft.Icons.ADD_CIRCLE, color=ft.Colors.ORANGE_700),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                padding=8,
                bgcolor=ft.Colors.GREY_100,
                border_radius=8,
                on_click=lambda ev, p=product: self.select_product(p),
            )
            self.product_list.controls.append(tile)

        self.page.update()

    def select_product(self, product):
        self.selected_product = product

        # CORRECTION: Accès aux attributs selon le type
        if hasattr(product, 'quantity'):
            stock = getattr(product, 'quantity', 0) or getattr(product, 'stock', 0)
            price = getattr(product, 'selling_price', 0) or getattr(product, 'price', 0)
            name = getattr(product, 'name', "Produit sans nom")
        else:
            stock = self._safe_int(product.get("quantity", 0), 0)
            price = self._safe_float(product.get("selling_price", 0), 0)
            name = str(product.get("name", "Produit sans nom"))

        self.selected_product_text.value = f"✓ Produit sélectionné: {name} | Stock: {stock}"
        self.product_search.value = name
        self.unit_price_field.value = str(int(price) if price.is_integer() else price)
        
        self.page.update()

    def update_preview_total(self, e=None):
        qty = self._safe_int(self.quantity_field.value, 0)
        unit_price = self._safe_float(self.unit_price_field.value, 0)
        line_total = qty * unit_price

        base_total = sum(item["total_price"] for item in self.borrow_cart)
        self.total_amount_text.value = f"Total général: {self._format_money(base_total + line_total)}"
        self.page.update()

    def add_selected_product_to_cart(self, e):
        if not self.selected_product:
            self.show_error("Veuillez d'abord sélectionner un produit.")
            return

        qty = self._safe_int(self.quantity_field.value, 0)
        if qty <= 0:
            self.show_error("Veuillez entrer une quantité valide.")
            return

        # CORRECTION: Accès aux attributs selon le type
        if hasattr(self.selected_product, 'quantity'):
            available_stock = getattr(self.selected_product, 'quantity', 0) or getattr(self.selected_product, 'stock', 0)
            product_id = getattr(self.selected_product, 'server_id', None) or getattr(self.selected_product, 'id', None)
            product_name = getattr(self.selected_product, 'name', "Produit")
            default_price = getattr(self.selected_product, 'selling_price', 0) or getattr(self.selected_product, 'price', 0)
        else:
            available_stock = self._safe_int(self.selected_product.get("quantity", 0), 0)
            product_id = self.selected_product.get("server_id") or self.selected_product.get("id")
            product_name = self.selected_product.get("name", "Produit")
            default_price = self._safe_float(self.selected_product.get("selling_price", 0), 0)
        
        available_stock = self._safe_int(available_stock, 0)
        
        unit_price = self._safe_float(self.unit_price_field.value, 0)
        if unit_price <= 0:
            unit_price = default_price
        
        if unit_price <= 0:
            self.show_error("Veuillez entrer un prix unitaire valide.")
            return

        if qty > available_stock:
            self.show_error(f"Stock insuffisant. Disponible: {available_stock}.")
            return

        if not product_id:
            self.show_error("ID du produit introuvable.")
            return

        existing = next((x for x in self.borrow_cart if x["product_id"] == str(product_id)), None)

        if existing:
            new_qty = existing["quantity"] + qty
            if new_qty > available_stock:
                self.show_error(
                    f"Quantité totale trop élevée pour {product_name}. Disponible: {available_stock}."
                )
                return
            existing["quantity"] = new_qty
            existing["total_price"] = new_qty * existing["unit_price"]
            self.show_success(f"{product_name}: quantité mise à jour ({new_qty})")
        else:
            self.borrow_cart.append(
                {
                    "product_id": str(product_id),
                    "product_name": product_name,
                    "quantity": qty,
                    "unit_price": unit_price,
                    "total_price": qty * unit_price,
                    "available_stock": available_stock,
                }
            )
            self.show_success(f"{product_name} ajouté au panier d'emprunt.")

        self.quantity_field.value = "1"
        self.unit_price_field.value = str(int(unit_price) if unit_price.is_integer() else unit_price)
        self.selected_product = None
        self.selected_product_text.value = "Aucun produit sélectionné"
        self.product_list.controls.clear()
        self.product_search.value = ""

        self.refresh_cart_ui()
        self.update_preview_total()

    def refresh_cart_ui(self):
        self.cart_list.controls.clear()

        if not self.borrow_cart:
            self.cart_list.controls.append(
                ft.Text("Aucun produit ajouté.", color=ft.Colors.GREY_700)
            )
            self.total_amount_text.value = "Total général: 0 FC"
            self.page.update()
            return

        total = 0

        for index, item in enumerate(self.borrow_cart):
            total += item["total_price"]

            card = ft.Card(
                content=ft.Container(
                    padding=10,
                    content=ft.Row(
                        controls=[
                            ft.Column(
                                controls=[
                                    ft.Text(
                                        item["product_name"],
                                        weight=ft.FontWeight.BOLD,
                                        size=14,
                                    ),
                                    ft.Text(
                                        f"Qté: {item['quantity']} x {self._format_money(item['unit_price'])}",
                                        size=12,
                                    ),
                                ],
                                spacing=4,
                                expand=True,
                            ),
                            ft.Column(
                                controls=[
                                    ft.Text(
                                        self._format_money(item["total_price"]),
                                        weight=ft.FontWeight.BOLD,
                                        color=ft.Colors.ORANGE_700,
                                        size=14,
                                    ),
                                    ft.IconButton(
                                        icon=ft.Icons.DELETE_OUTLINE,
                                        icon_size=20,
                                        tooltip="Retirer",
                                        on_click=lambda e, i=index: self.remove_cart_item(i),
                                    ),
                                ],
                                horizontal_alignment=ft.CrossAxisAlignment.END,
                                spacing=4,
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                )
            )
            self.cart_list.controls.append(card)

        self.total_amount_text.value = f"Total général: {self._format_money(total)}"
        self.page.update()

    def remove_cart_item(self, index: int):
        if 0 <= index < len(self.borrow_cart):
            removed = self.borrow_cart.pop(index)
            self.refresh_cart_ui()
            self.update_preview_total()
            self.show_success(f"{removed['product_name']} retiré du panier.")

    def clear_cart(self, e=None):
        if self.borrow_cart:
            self.borrow_cart = []
            self.refresh_cart_ui()
            self.update_preview_total()
            self.show_success("Panier vidé.")

    def save_debt(self, e):
        if not self.customer_name.value or not self.customer_name.value.strip():
            self.show_error("Veuillez entrer le nom du client.")
            return

        if not self.borrow_cart:
            self.show_error("Ajoutez au moins un produit.")
            return

        try:
            due_date_str = self.due_date.value.strip()
            due_date_iso = datetime.strptime(due_date_str, "%d/%m/%Y").isoformat()
        except Exception:
            self.show_error("Date d'échéance invalide. Format attendu: JJ/MM/AAAA.")
            return

        customer_name = self.customer_name.value.strip()
        note_text = (self.notes.value or "").strip()
        branch_id = self._branch_id()
        
        if not branch_id:
            self.show_error("ID de la succursale introuvable.")
            return
            
        now_iso = datetime.now().isoformat()
        lot_code = f"LOT-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}"
        
        total_general = sum(item["total_price"] for item in self.borrow_cart)

        # CORRECTION: Utiliser le context manager correctement
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()

                # Vérification des stocks
                for item in self.borrow_cart:
                    cursor.execute(
                        "SELECT quantity, name FROM products WHERE server_id = ? AND branch_id = ?",
                        (item["product_id"], branch_id),
                    )
                    row = cursor.fetchone()
                    current_stock = self._safe_int(row[0] if row else 0, 0)

                    if item["quantity"] > current_stock:
                        raise ValueError(
                            f"Stock insuffisant pour {item['product_name']} (disponible: {current_stock})."
                        )

                # Décrémentation des stocks
                for item in self.borrow_cart:
                    cursor.execute(
                        "UPDATE products SET quantity = quantity - ? WHERE server_id = ? AND branch_id = ?",
                        (item["quantity"], item["product_id"], branch_id),
                    )

                # Enregistrement des dettes
                for item in self.borrow_cart:
                    cursor.execute("""
                        INSERT INTO debts
                        (customer_name, amount, remaining_amount, due_date, status, branch_id,
                        notes, product_id, product_name, quantity, unit_price, created_at, updated_at, is_synced)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        customer_name,
                        item["total_price"],
                        item["total_price"],
                        due_date_iso,
                        "pending",
                        branch_id,
                        f"[{lot_code}] {note_text}".strip(),
                        item["product_id"],
                        item["product_name"],
                        item["quantity"],
                        item["unit_price"],
                        now_iso,
                        now_iso,
                        0,
                    ))

                conn.commit()

            # Réinitialisation
            self.borrow_cart = []
            self.selected_product = None
            self.product_search.value = ""
            self.product_list.controls.clear()
            self.selected_product_text.value = "Aucun produit sélectionné"
            self.customer_name.value = ""
            self.quantity_field.value = "1"
            self.unit_price_field.value = ""
            self.notes.value = ""
            self.refresh_cart_ui()
            self.update_preview_total()
            
            self.load_debts_for_dropdown()
            self.load_debt_list()

            self.show_success(f"✅ Dette de {self._format_money(total_general)} enregistrée pour {customer_name}")

        except Exception as err:
            self.show_error(f"Erreur: {str(err)}")
            import traceback
            traceback.print_exc()

    # =========================================================
    # ONGLET 2 - PAIEMENT
    # =========================================================
    def create_payment_tab(self):
        self.debt_dropdown = ft.Dropdown(
            label="Sélectionner une dette",
            hint_text="Choisir une dette",
            expand=True,
        )
        self.debt_dropdown.on_change = self.load_debt_details

        self.debt_details = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("Client:", weight=ft.FontWeight.BOLD),
                    ft.Text("---"),
                    ft.Text("Produit:", weight=ft.FontWeight.BOLD),
                    ft.Text("---"),
                    ft.Text("Montant total:", weight=ft.FontWeight.BOLD),
                    ft.Text("---"),
                    ft.Text("Montant restant:", weight=ft.FontWeight.BOLD),
                    ft.Text("---", color=ft.Colors.RED),
                    ft.Text("Échéance:", weight=ft.FontWeight.BOLD),
                    ft.Text("---"),
                ],
                spacing=5,
            ),
            padding=10,
            bgcolor=ft.Colors.GREY_100,
            border_radius=10,
            visible=False,
        )

        self.payment_amount = ft.TextField(
            label="Montant à payer",
            hint_text="Ex: 5000",
            keyboard_type=ft.KeyboardType.NUMBER,
            expand=True,
        )

        self.payment_date = ft.TextField(
            label="Date du paiement",
            value=datetime.now().strftime("%d/%m/%Y"),
            expand=True,
        )

        payment_button = ft.Button(
            content=ft.Text("Enregistrer le paiement"),
            icon=ft.Icons.PAYMENT,
            on_click=self.save_payment,
            height=48,
            style=ft.ButtonStyle(
                bgcolor=ft.Colors.GREEN_700,
                color=ft.Colors.WHITE,
            ),
        )

        self.load_debts_for_dropdown()

        return ft.Container(
            content=ft.Column(
                controls=[
                    self.debt_dropdown,
                    self.debt_details,
                    ft.Divider(),
                    ft.Row(
                        controls=[
                            self.payment_amount,
                            self.payment_date,
                        ],
                        spacing=10,
                    ),
                    payment_button,
                ],
                spacing=12,
                scroll=ft.ScrollMode.AUTO,
            ),
            expand=True,
            padding=10,
        )

    def load_debts_for_dropdown(self):
        if not self.debt_dropdown:
            return

        debts = self.db.get_active_debts(self._branch_id())
        options = []
        for debt in debts:
            if hasattr(debt, 'id'):
                # C'est un objet Debt
                remaining = getattr(debt, 'remaining_amount', 0)
                customer = getattr(debt, 'customer_name', 'Client')
                product = getattr(debt, 'product_name', 'Produit')
                options.append(
                    ft.DropdownOption(
                        key=str(debt.id),
                        text=f"{customer} | {product} | Reste: {self._format_money(remaining)}",
                    )
                )
            elif isinstance(debt, dict):
                # C'est un dictionnaire
                remaining = debt.get('remaining_amount', 0)
                customer = debt.get('customer_name', 'Client')
                product = debt.get('product_name', 'Produit')
                options.append(
                    ft.DropdownOption(
                        key=str(debt.get('id')),
                        text=f"{customer} | {product} | Reste: {self._format_money(remaining)}",
                    )
                )
        self.debt_dropdown.options = options
        self.page.update()

    def load_debt_details(self, e):
        if not self.debt_dropdown.value:
            self.debt_details.visible = False
            self.page.update()
            return

        debt_id = int(self.debt_dropdown.value)
        debt = self.db.get_debt_by_id(debt_id)

        if not debt:
            self.debt_details.visible = False
            self.page.update()
            return

        # Gérer les deux formats possibles (objet ou dict)
        if hasattr(debt, 'customer_name'):
            # C'est un objet Debt
            customer_name = debt.customer_name
            product_name = getattr(debt, 'product_name', '---')
            amount = debt.amount
            remaining = debt.remaining_amount
            due_date = debt.due_date
        elif isinstance(debt, dict):
            # C'est un dictionnaire
            customer_name = debt.get("customer_name", "---")
            product_name = debt.get("product_name", "---")
            amount = debt.get("amount", 0)
            remaining = debt.get("remaining_amount", 0)
            due_date = debt.get("due_date")
        else:
            self.show_error("Format de dette invalide")
            return

        # Mettre à jour l'affichage
        controls = self.debt_details.content.controls
        controls[1].value = customer_name
        controls[3].value = product_name
        controls[5].value = self._format_money(amount)
        controls[7].value = self._format_money(remaining)
        controls[9].value = (
            datetime.fromisoformat(due_date).strftime("%d/%m/%Y")
            if due_date
            else "---"
        )
        controls[7].color = ft.Colors.RED if remaining > 0 else ft.Colors.GREEN

        self.selected_debt_id = debt_id
        self.debt_details.visible = True
        self.page.update()

    def save_payment(self, e):
        if not self.selected_debt_id:
            self.show_error("Veuillez sélectionner une dette.")
            return

        amount = self._safe_float(self.payment_amount.value, 0)
        if amount <= 0:
            self.show_error("Veuillez entrer un montant valide.")
            return

        try:
            # Récupérer la dette
            debt = self.db.get_debt_by_id(self.selected_debt_id)
            
            if not debt:
                self.show_error("Dette non trouvée.")
                return
                
            # Extraire le montant restant (que ce soit un dict ou un objet)
            if hasattr(debt, 'remaining_amount'):
                remaining = debt.remaining_amount
            elif isinstance(debt, dict):
                remaining = debt.get("remaining_amount", 0)
            else:
                self.show_error("Format de dette invalide.")
                return
            
            if amount > remaining:
                self.show_error(f"Le montant dépasse le reste dû ({self._format_money(remaining)}).")
                return

            new_remaining = remaining - amount
            new_status = "paid" if new_remaining <= 0 else "partial"

            # Mettre à jour la dette
            success = self.db.update_debt(
                self.selected_debt_id,
                remaining_amount=new_remaining,
                status=new_status
            )
            
            if not success:
                self.show_error("Erreur lors de l'enregistrement du paiement.")
                return

            # Réinitialiser le champ de paiement
            self.payment_amount.value = ""
            
            # Rafraîchir les listes
            self.load_debts_for_dropdown()
            self.load_debt_list()
            
            # Réinitialiser l'affichage des détails
            self.debt_details.visible = False
            self.selected_debt_id = None
            self.debt_dropdown.value = None
            
            self.page.update()
            
            self.show_success(f"Paiement de {self._format_money(amount)} enregistré. Reste: {self._format_money(new_remaining)}.")

        except Exception as err:
            self.show_error(f"Erreur: {str(err)}")
            import traceback
            traceback.print_exc()

    # =========================================================
    # ONGLET 3 - LISTE
    # =========================================================
    def create_debt_list_tab(self):
        self.filter_dropdown = ft.Dropdown(
            label="Filtrer par statut",
            value="all",
            expand=True,
            options=[
                ft.DropdownOption(key="all", text="Toutes les dettes"),
                ft.DropdownOption(key="pending", text="En attente"),
                ft.DropdownOption(key="partial", text="Paiement partiel"),
                ft.DropdownOption(key="paid", text="Payées"),
                ft.DropdownOption(key="overdue", text="En retard"),
            ],
        )
        self.filter_dropdown.on_change = self.filter_debts
        
        self.debt_list_view = ft.ListView(expand=True, spacing=10)
        self.load_debt_list()
        
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Container(content=self.filter_dropdown, padding=ft.Padding.only(bottom=10)),
                    self.debt_list_view,
                ],
                spacing=10,
                expand=True,
            ),
            padding=10,
            expand=True,
        )

    def filter_debts(self, e):
        self.load_debt_list()

    def load_debt_list(self):
        if not self.debt_list_view:
            return

        # CORRECTION: Utiliser get_debts() au lieu de get_all_debts()
        all_debts = self.db.get_debts(self._branch_id())
        
        filter_value = self.filter_dropdown.value if hasattr(self, 'filter_dropdown') else "all"
        
        debts = []
        for d in all_debts:
            if hasattr(d, 'status'):
                debt_dict = {
                    'id': d.id,
                    'customer_name': d.customer_name,
                    'product_name': getattr(d, 'product_name', 'N/A'),
                    'amount': d.amount,
                    'remaining_amount': d.remaining_amount,
                    'due_date': d.due_date,
                    'status': d.status,
                    'quantity': getattr(d, 'quantity', 0),
                    'unit_price': getattr(d, 'unit_price', 0),
                }
            else:
                debt_dict = d
            
            if filter_value == "all":
                debts.append(debt_dict)
            elif filter_value == "overdue":
                if self._is_overdue(debt_dict):
                    debts.append(debt_dict)
            else:
                if debt_dict.get("status") == filter_value:
                    debts.append(debt_dict)
        
        self.debt_list_view.controls.clear()

        if not debts:
            self.debt_list_view.controls.append(
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Icon(ft.Icons.MONEY_OFF, size=64, color=ft.Colors.GREY_400),
                            ft.Text("Aucune dette trouvée", size=16, color=ft.Colors.GREY_600),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    alignment=ft.Alignment.CENTER,
                    expand=True,
                )
            )
        else:
            customers = {}
            for debt in debts:
                customer_name = debt.get("customer_name", "Client inconnu")
                if customer_name not in customers:
                    customers[customer_name] = []
                customers[customer_name].append(debt)
            
            for customer_name, customer_debts in customers.items():
                total_customer_debt = sum(self._safe_float(d.get("remaining_amount", 0)) for d in customer_debts)
                
                customer_header = ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.PERSON, color=ft.Colors.ORANGE_700),
                            ft.Text(
                                customer_name,
                                size=16,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.ORANGE_700,
                            ),
                            ft.Text(
                                f"Total restant: {self._format_money(total_customer_debt)}",
                                size=12,
                                color=ft.Colors.RED if total_customer_debt > 0 else ft.Colors.GREEN,
                                expand=True,
                                text_align=ft.TextAlign.END,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.START,
                    ),
                    padding=ft.Padding.symmetric(vertical=8, horizontal=5),
                    bgcolor=ft.Colors.ORANGE_50,
                    border_radius=ft.BorderRadius.all(8),
                )
                self.debt_list_view.controls.append(customer_header)
                
                for debt in customer_debts:
                    self.debt_list_view.controls.append(self.create_debt_card(debt))
                
                self.debt_list_view.controls.append(ft.Divider(height=10, color=ft.Colors.TRANSPARENT))

        self.page.update()

    def _is_overdue(self, debt):
        due_iso = debt.get("due_date")
        if not due_iso:
            return False
        try:
            # ✅ CORRECTION: Gérer le format avec T00:00:00
            due_str = str(due_iso)
            if 'T' in due_str:
                due_str = due_str.split('T')[0]
            due_dt = datetime.fromisoformat(due_str)
            remaining = self._safe_float(debt.get("remaining_amount", 0))
            status = debt.get("status", "pending")
            return datetime.now() > due_dt and remaining > 0 and status != "paid"
        except Exception as e:
            print(f"Erreur vérification dette: {e}")
            return False

    def create_debt_card(self, debt):
        status = debt.get("status", "pending")
        remaining = self._safe_float(debt.get("remaining_amount", 0))
        total = self._safe_float(debt.get("amount", 0))
        
        if self._is_overdue(debt):
            status_text = "EN RETARD"
            status_color = ft.Colors.RED_900
        elif status == "paid":
            status_text = "PAYÉE"
            status_color = ft.Colors.GREEN
        elif status == "partial":
            status_text = "PAIEMENT PARTIEL"
            status_color = ft.Colors.ORANGE
        else:
            status_text = "EN ATTENTE"
            status_color = ft.Colors.RED
        
        due_iso = debt.get("due_date")
        due_date = "---"
        if due_iso:
            try:
                due_dt = datetime.fromisoformat(due_iso)
                due_date = due_dt.strftime("%d/%m/%Y")
            except Exception:
                pass
        
        progress_value = 1 if total <= 0 else (total - remaining) / total
        
        quick_pay_button = None
        if remaining > 0:
            quick_pay_button = ft.IconButton(
                icon=ft.Icons.PAYMENT,
                icon_size=20,
                tooltip="Effectuer un paiement",
                on_click=lambda e, d=debt: self.show_quick_payment_dialog(d),
            )
        
        return ft.Card(
            content=ft.Container(
                padding=10,
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Column(
                                    controls=[
                                        ft.Text(
                                            debt.get("product_name", "N/A"),
                                            size=14,
                                            weight=ft.FontWeight.BOLD,
                                        ),
                                        ft.Text(
                                            f"Qté: {debt.get('quantity', 0)} | PU: {self._format_money(debt.get('unit_price', 0))}",
                                            size=11,
                                            color=ft.Colors.GREY_600,
                                        ),
                                    ],
                                    spacing=3,
                                    expand=True,
                                ),
                                ft.Container(
                                    content=ft.Text(status_text, size=11, weight=ft.FontWeight.BOLD),
                                    bgcolor=status_color,
                                    padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                                    border_radius=10,
                                ),
                            ],
                        ),
                        ft.Row(
                            controls=[
                                ft.Text(f"Total: {self._format_money(total)}", size=12),
                                ft.Text(
                                    f"Reste: {self._format_money(remaining)}",
                                    size=12,
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.RED if remaining > 0 else ft.Colors.GREEN,
                                ),
                                ft.Text(f"Échéance: {due_date}", size=11, color=ft.Colors.GREY_600),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.ProgressBar(value=progress_value, color=ft.Colors.GREEN, height=6),
                        ft.Row(
                            controls=[
                                ft.Text(""),
                                quick_pay_button if quick_pay_button else ft.Text(""),
                            ],
                            alignment=ft.MainAxisAlignment.END,
                            spacing=5,
                        ),
                    ],
                    spacing=8,
                ),
            )
        )

    def show_quick_payment_dialog(self, debt):
        remaining = self._safe_float(debt.get("remaining_amount", 0))
        debt_id = debt.get("id")
        customer_name = debt.get("customer_name", "Client")
        product_name = debt.get("product_name", "N/A")
        total = debt.get("amount", 0)
        
        payment_amount = ft.TextField(
            label="Montant à payer",
            hint_text=f"Reste dû: {self._format_money(remaining)}",
            keyboard_type=ft.KeyboardType.NUMBER,
            width=300,
        )
        
        def confirm_payment(e):
            amount = self._safe_float(payment_amount.value, 0)
            if amount <= 0:
                self.show_error("Veuillez entrer un montant valide.")
                return
            if amount > remaining:
                self.show_error(f"Le montant dépasse le reste dû ({self._format_money(remaining)}).")
                return
            
            try:
                new_remaining = remaining - amount
                new_status = "paid" if new_remaining <= 0 else "partial"
                
                self.db.update_debt(
                    debt_id,
                    remaining_amount=new_remaining,
                    status=new_status
                )
                
                dialog.open = False
                self.page.update()
                
                self.load_debts_for_dropdown()
                self.load_debt_list()
                
                if new_remaining <= 0:
                    self.show_success(f"✅ Dette entièrement payée ! {self._format_money(amount)} reçu.")
                else:
                    self.show_success(f"✅ Paiement de {self._format_money(amount)} enregistré. Reste: {self._format_money(new_remaining)}.")
                    
            except Exception as err:
                self.show_error(f"Erreur: {str(err)}")
        
        dialog = ft.AlertDialog(
            title=ft.Text(f"Paiement - {customer_name}"),
            content=ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text(f"Produit: {product_name}", size=14),
                        ft.Text(f"Montant total: {self._format_money(total)}", size=12),
                        ft.Text(f"Reste dû: {self._format_money(remaining)}", size=12, color=ft.Colors.RED),
                        ft.Divider(),
                        payment_amount,
                    ],
                    spacing=10,
                ),
                width=350,
                padding=10,
            ),
            actions=[
                ft.TextButton("Annuler", on_click=lambda e: self.close_dialog(dialog)),
                ft.Button("Confirmer", on_click=confirm_payment, bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE),
            ],
        )
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()

    def close_dialog(self, dialog):
        dialog.open = False
        self.page.update()

    # =========================================================
    # DIVERS
    # =========================================================
    def refresh_data(self, e=None):
        self.load_debts_for_dropdown()
        self.load_debt_list()
        self.refresh_cart_ui()
        self.update_preview_total()
        self.show_success("Données rafraîchies.")

    def go_back(self):
        from screens.dashboard_screen import DashboardScreen

        dashboard = DashboardScreen(
            self.page,
            self.db,
            self.sync_service,
            self.auth_service,
            self.current_user,
        )
        dashboard.show()

    def show_debt_receipt(self, debt_id, debt_data, payment_data=None):
        from screens.receipt_export_screen import ReceiptExportScreen

        receipt_screen = ReceiptExportScreen(
            self.page,
            self.db,
            self.sync_service,
            self.auth_service,
            self.current_user,
        )

        if payment_data:
            receipt_screen.show_debt_receipt(debt_id, debt_data, payment_data)
        else:
            receipt_screen.show_debt_receipt(debt_id, debt_data)