# screens/return_exchange_screen.py
import flet as ft
from datetime import datetime
from typing import Dict, List


class ReturnExchangeScreen:
    """Écran de gestion des retours et échanges"""
    
    def __init__(self, page: ft.Page, db, sync_service, auth_service, current_user, invoice: Dict):
        self.page = page
        self.db = db
        self.sync_service = sync_service
        self.auth_service = auth_service
        self.current_user = current_user
        self.invoice = invoice
        self.items = []
        self.selected_products = {}
        self.results = []
        self.exchange_dialog = None
        
    def _branch_id(self) -> str:
        """Récupère l'ID de la branche"""
        branch_id = (self.current_user.get("active_branch_id") or 
                    self.current_user.get("branch_id") or
                    self.current_user.get("current_branch_id"))
        return str(branch_id) if branch_id else None
    
    def _format_money(self, amount) -> str:
        """Formate un montant en monnaie locale"""
        try:
            return f"{float(amount):,.0f} FC"
        except:
            return "0 FC"
    
    def _load_items(self):
        """Charge les articles de la facture"""
        invoice_number = self.invoice.get('invoice_number')
        if invoice_number:
            self.items = self.db.get_invoice_items(invoice_number)
            print(f"DEBUG: Items chargés: {len(self.items)}")  # Pour debug
            for item in self.items:
                print(f"  - {item.get('product_name')}: qty={item.get('quantity')}, returned={item.get('returned_quantity', 0)}")
    
    def _go_back(self, e):
        """Retour à l'écran de détail"""
        from screens.invoice_detail_screen import InvoiceDetailScreen
        detail_screen = InvoiceDetailScreen(
            self.page, self.db, self.sync_service, 
            self.auth_service, self.current_user, self.invoice
        )
        detail_screen.show()
    
    def _show_snackbar(self, message: str, is_error: bool = False):
        """Affiche une notification"""
        self.page.snack_bar = ft.SnackBar(
            content=ft.Text(message),
            bgcolor=ft.Colors.RED_700 if is_error else ft.Colors.GREEN_700,
            duration=3000,
        )
        self.page.snack_bar.open = True
        self.page.update()
    
    def _create_product_row(self, item: Dict):
        """Crée une ligne de sélection pour un produit"""
        product_id = item.get('product_id')
        product_name = item.get('product_name', 'Produit')
        quantity = item.get('quantity', 1)
        returned_qty = item.get('returned_quantity', 0)
        remaining_qty = quantity - returned_qty
        unit_price = item.get('unit_price', 0)
        
        if remaining_qty <= 0:
            return None
        
        # Champ quantité
        qty_field = ft.TextField(
            value="0",
            width=80,
            text_align=ft.TextAlign.CENTER,
            input_filter=ft.InputFilter(allow=True, regex_string=r"^[0-9]*$"),
            hint_text="Qté",
        )
        
        # Type de retour
        return_type = ft.Dropdown(
            options=[
                ft.dropdown.Option("return", "Retour simple"),
                ft.dropdown.Option("exchange", "Échange"),
            ],
            value="return",
            width=140,
        )
        
        # Stocker les références
        self.selected_products[product_id] = {
            'item': item,
            'qty_field': qty_field,
            'return_type': return_type,
            'max_qty': remaining_qty,
            'product_name': product_name,
            'unit_price': unit_price,
        }
        
        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Column(
                        controls=[
                            ft.Text(product_name, size=14, weight=ft.FontWeight.W_500),
                            ft.Text(f"Prix: {self._format_money(unit_price)}", size=11, color=ft.Colors.GREY_600),
                            ft.Text(f"Disponible: {remaining_qty}", size=11, color=ft.Colors.BLUE_700),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    qty_field,
                    return_type,
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(vertical=8, horizontal=5),
            border=ft.border.all(0.5, ft.Colors.GREY_300),
            border_radius=8,
            margin=ft.Margin.only(bottom=5),
        )
    
    def _process_return(self, product_data: Dict, qty: int) -> bool:
        """Traite un retour simple"""
        item = product_data['item']
        
        return self.db.process_return({
            'invoice_number': self.invoice.get('invoice_number'),
            'product_id': item.get('product_id'),
            'product_name': item.get('product_name'),
            'quantity': qty,
            'unit_price': item.get('unit_price', 0),
            'total_price': qty * item.get('unit_price', 0),
            'reason': "Retour client",
            'branch_id': self._branch_id(),
            'customer_name': self.invoice.get('customer_name'),
            'sale_id': item.get('sale_id')
        })
    
    def _show_exchange_modal(self, product_data: Dict, return_qty: int):
        """Affiche une modal pour l'échange"""
        products = self.db.get_products(self._branch_id())
        original_item = product_data['item']
        original_price = original_item.get('unit_price', 0)
        original_total = original_price * return_qty
        
        # Récupérer l'ID original pour comparaison
        original_product_id = original_item.get('product_id')
        
        # Filtrer les produits
        product_options = []
        for product in products:
            # Comparer les IDs en string
            if str(product.server_id) != str(original_product_id):
                # CORRECTION: Utiliser l'attribut 'stock' ou 'quantity'
                stock_qty = product.stock if hasattr(product, 'stock') else (product.quantity if hasattr(product, 'quantity') else 0)
                product_options.append(
                    ft.dropdown.Option(
                        str(product.server_id),
                        f"{product.name} - {self._format_money(product.selling_price)} (Stock: {stock_qty})"
                    )
                )
        
        if not product_options:
            self._show_snackbar("Aucun autre produit disponible pour l'échange", True)
            return
        
        # Variables pour stocker les valeurs sélectionnées
        selected_product_id = [None]
        exchange_qty = [return_qty]
        
        exchange_product_dropdown = ft.Dropdown(
            options=product_options,
            hint_text="Sélectionner le produit d'échange",
            expand=True,
        )
        
        exchange_qty_field = ft.TextField(
            value=str(return_qty),
            width=80,
            text_align=ft.TextAlign.CENTER,
            input_filter=ft.InputFilter(allow=True, regex_string=r"^[0-9]*$"),
        )
        
        price_info_text = ft.Text("", size=12)
        
        def update_price_info(e):
            selected_id = exchange_product_dropdown.value
            if selected_id:
                for p in products:
                    if str(p.server_id) == selected_id:
                        try:
                            qty_val = int(exchange_qty_field.value or return_qty)
                            exchange_total = p.selling_price * qty_val
                            diff = exchange_total - original_total
                            
                            if diff > 0:
                                price_info_text.value = f"💰 Différence à payer: {self._format_money(diff)}"
                                price_info_text.color = ft.Colors.RED_700
                            elif diff < 0:
                                price_info_text.value = f"💰 À rembourser au client: {self._format_money(abs(diff))}"
                                price_info_text.color = ft.Colors.GREEN_700
                            else:
                                price_info_text.value = "💰 Montant identique"
                                price_info_text.color = ft.Colors.GREY_700
                        except:
                            pass
                        break
        
        exchange_product_dropdown.on_change = update_price_info
        exchange_qty_field.on_change = update_price_info
        
        def confirm_exchange(e):
            exchange_product_id_str = exchange_product_dropdown.value
            if not exchange_product_id_str:
                self._show_snackbar("Veuillez sélectionner un produit d'échange", True)
                return
            
            try:
                new_qty = int(exchange_qty_field.value or return_qty)
                if new_qty <= 0:
                    self._show_snackbar("Quantité invalide", True)
                    return
            except ValueError:
                self._show_snackbar("Quantité invalide", True)
                return
            
            # Récupérer le produit d'échange
            exchange_product = None
            for p in products:
                if str(p.server_id) == exchange_product_id_str:
                    exchange_product = p
                    break
            
            if not exchange_product:
                self._show_snackbar("Produit d'échange non trouvé", True)
                return
            
            exchange_price = exchange_product.selling_price
            exchange_total = exchange_price * new_qty
            amount_difference = exchange_total - original_total
            
            # CORRECTION: Vérifier le stock avec l'attribut correct
            stock_qty = exchange_product.stock if hasattr(exchange_product, 'stock') else (exchange_product.quantity if hasattr(exchange_product, 'quantity') else 0)
            if stock_qty < new_qty:
                self._show_snackbar(f"Stock insuffisant pour {exchange_product.name}", True)
                return
            
            # Traiter l'échange
            success = self.db.process_exchange({
                'invoice_number': self.invoice.get('invoice_number'),
                'original_product_id': str(original_item.get('product_id')),  # Convertir en string
                'original_product_name': original_item.get('product_name'),
                'original_quantity': return_qty,
                'original_unit_price': original_price,
                'original_total_price': original_total,
                'new_product_id': str(exchange_product.server_id),  # Convertir en string
                'new_product_name': exchange_product.name,
                'new_quantity': new_qty,
                'new_unit_price': exchange_price,
                'amount_difference': amount_difference,
                'reason': "Échange produit",
                'branch_id': self._branch_id(),
                'customer_name': self.invoice.get('customer_name'),
                'sale_id': original_item.get('sale_id')
            })
            
            if success:
                self.results.append(f"✅ Échange: {return_qty} x {original_item.get('product_name')} → {new_qty} x {exchange_product.name}")
                if amount_difference > 0:
                    self.results.append(f"   À payer: {self._format_money(amount_difference)}")
                
                if self.exchange_dialog:
                    self.exchange_dialog.open = False
                    self.page.update()
                
                self._finish_processing()
            else:
                self._show_snackbar("Erreur lors de l'échange", True)
        
        def close_modal(e):
            if self.exchange_dialog:
                self.exchange_dialog.open = False
                self.page.update()
        
        # Créer la modal
        self.exchange_dialog = ft.AlertDialog(
            title=ft.Text("Échange de produit"),
            content=ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text(f"Produit retourné: {original_item.get('product_name')} x{return_qty}", size=14),
                        ft.Text(f"Valeur: {self._format_money(original_total)}", size=12, color=ft.Colors.BLUE_700),
                        ft.Divider(),
                        ft.Text("Produit d'échange:", size=14, weight=ft.FontWeight.BOLD),
                        exchange_product_dropdown,
                        ft.Row(
                            controls=[
                                ft.Text("Quantité:", expand=True),
                                exchange_qty_field,
                            ],
                            spacing=10,
                        ),
                        price_info_text,
                    ],
                    spacing=12,
                    tight=True,
                ),
                width=450,
                height=350,
                padding=10,
            ),
            actions=[
                ft.TextButton("Annuler", on_click=close_modal),
                ft.ElevatedButton("Confirmer l'échange", on_click=confirm_exchange),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        self.page.dialog = self.exchange_dialog
        self.exchange_dialog.open = True
        self.page.update()
    
    def _process_selected(self, e):
        """Traite les produits sélectionnés"""
        self.results = []
        
        # Vérifier d'abord toutes les validations
        for product_id, data in self.selected_products.items():
            try:
                qty = int(data['qty_field'].value or "0")
            except ValueError:
                qty = 0
            
            if qty > 0 and qty > data['max_qty']:
                self._show_snackbar(f"Quantité invalide pour {data['product_name']} (max {data['max_qty']})", True)
                return
        
        # Traiter les retours simples d'abord
        exchange_items = []
        
        for product_id, data in self.selected_products.items():
            try:
                qty = int(data['qty_field'].value or "0")
            except ValueError:
                continue
            
            if qty <= 0:
                continue
            
            return_type = data['return_type'].value
            
            if return_type == 'return':
                success = self._process_return(data, qty)
                if success:
                    self.results.append(f"✅ Retour de {qty} x {data['product_name']}")
                else:
                    self.results.append(f"❌ Erreur retour pour {data['product_name']}")
            
            elif return_type == 'exchange':
                exchange_items.append((data, qty))
        
        # S'il y a des échanges, traiter le premier
        if exchange_items:
            data, qty = exchange_items[0]
            self._show_exchange_modal(data, qty)
        else:
            self._finish_processing()
    
    def _finish_processing(self):
        """Termine le traitement et retourne à l'écran de détail"""
        if self.results:
            # Afficher les résultats
            message = "\n".join(self.results[:3])
            self.page.snack_bar = ft.SnackBar(
                content=ft.Text(message),
                bgcolor=ft.Colors.GREEN_700 if "✅" in message else ft.Colors.ORANGE_700,
                duration=4000,
            )
            self.page.snack_bar.open = True
            self.page.update()
        
        # Retourner à l'écran de détail
        from screens.invoice_detail_screen import InvoiceDetailScreen
        detail_screen = InvoiceDetailScreen(
            self.page, self.db, self.sync_service,
            self.auth_service, self.current_user, self.invoice
        )
        detail_screen.show()
    
    def show(self):
        """Affiche l'écran de retour/échange"""
        self._load_items()
        
        invoice_number = self.invoice.get('invoice_number', 'N/A')
        customer_name = self.invoice.get('customer_name', 'Client comptant')
        
        # Header
        header = ft.Container(
            content=ft.Row(
                controls=[
                    ft.IconButton(
                        icon=ft.Icons.ARROW_BACK,
                        on_click=self._go_back,
                        icon_color=ft.Colors.WHITE,
                    ),
                    ft.Text(
                        f"Retour / Échange - {invoice_number}",
                        size=20,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.WHITE,
                        expand=True,
                    ),
                ],
                alignment=ft.MainAxisAlignment.START,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=15,
            bgcolor=ft.Colors.ORANGE_700,
        )
        
        # Informations client
        info_card = ft.Card(
            content=ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.PERSON, size=20, color=ft.Colors.GREY_600),
                        ft.Text(f"Client: {customer_name}", size=14, expand=True),
                        ft.Icon(ft.Icons.RECEIPT, size=20, color=ft.Colors.GREY_600),
                        ft.Text(f"Facture: {invoice_number}", size=14),
                    ],
                    spacing=10,
                ),
                padding=12,
            ),
            margin=10,
        )
        
        # Instructions
        instructions = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("Instructions:", size=14, weight=ft.FontWeight.BOLD),
                    ft.Text("• Sélectionnez les produits à retourner ou échanger", size=12, color=ft.Colors.GREY_700),
                    ft.Text("• Pour un retour simple, le produit sera restocké", size=12, color=ft.Colors.GREY_700),
                    ft.Text("• Pour un échange, vous pourrez choisir un autre produit", size=12, color=ft.Colors.GREY_700),
                ],
                spacing=5,
            ),
            padding=10,
            bgcolor=ft.Colors.BLUE_50,
            border_radius=8,
            margin=10,
        )
        
        # Liste des produits
        product_rows = []
        for item in self.items:
            row = self._create_product_row(item)
            if row:
                product_rows.append(row)
        
        if not product_rows:
            empty_container = ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Icon(ft.Icons.CHECK_CIRCLE, size=50, color=ft.Colors.GREEN_400),
                        ft.Text("Aucun produit disponible pour retour/échange", size=14, color=ft.Colors.GREY_600),
                        ft.Text("Tous les produits ont déjà été retournés", size=12, color=ft.Colors.GREY_500),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=10,
                ),
                padding=40,
                alignment=ft.Alignment.CENTER,
            )
            product_rows = [empty_container]
        
        products_column = ft.Column(
            controls=product_rows,
            spacing=5,
            scroll=ft.ScrollMode.AUTO,
        )
        
        products_container = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("Produits disponibles:", size=14, weight=ft.FontWeight.BOLD),
                    products_column,
                ],
                spacing=10,
            ),
            padding=ft.Padding.symmetric(horizontal=10),
            expand=True,
        )
        
        # Boutons d'action
        actions_row = ft.Row(
            controls=[
                ft.ElevatedButton(
                    "Annuler",
                    icon=ft.Icons.CLOSE,
                    on_click=self._go_back,
                ),
                ft.ElevatedButton(
                    "Valider les retours/échanges",
                    icon=ft.Icons.CHECK,
                    on_click=self._process_selected,
                    style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE),
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            spacing=10,
        )
        
        # Assemblage principal
        main_content = ft.Column(
            controls=[
                header,
                ft.Container(
                    content=ft.Column(
                        controls=[
                            info_card,
                            instructions,
                            products_container,
                            ft.Container(content=actions_row, padding=10),
                        ],
                        spacing=10,
                        expand=True,
                    ),
                    expand=True,
                    bgcolor=ft.Colors.GREY_50,
                ),
            ],
            expand=True,
            spacing=0,
        )
        
        self.page.clean()
        self.page.add(main_content)
        self.page.update()