# screens/invoice_detail_screen.py
import flet as ft
from datetime import datetime
from typing import Dict, List


class InvoiceDetailScreen:
    """Écran de détail d'une facture"""
    
    def __init__(self, page: ft.Page, db, sync_service, auth_service, current_user, invoice: Dict):
        self.page = page
        self.db = db
        self.sync_service = sync_service
        self.auth_service = auth_service
        self.current_user = current_user
        self.invoice = invoice
        self.items = []
        
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
    
    def _format_date(self, date_str: str) -> str:
        """Formate une date pour l'affichage"""
        try:
            if not date_str:
                return ""
            if 'T' in date_str:
                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                return dt.strftime("%d/%m/%Y %H:%M")
            return date_str
        except:
            return date_str
    
    def _load_items(self):
        """Charge les articles de la facture"""
        invoice_number = self.invoice.get('invoice_number')
        if invoice_number:
            self.items = self.db.get_invoice_items(invoice_number)
    
    def _go_back(self, e):
        """Retour à l'écran précédent"""
        from screens.invoice_screen import InvoiceScreen
        invoice_screen = InvoiceScreen(
            self.page, self.db, self.sync_service, 
            self.auth_service, self.current_user
        )
        invoice_screen.show()
    
    def _print_invoice(self, e):
        """Imprime la facture"""
        from utils.print_manager import PrintManager
        print_manager = PrintManager(self.page, self.db, self.current_user)
        print_manager.print_invoice(self.invoice, self.items)
    
    def _open_return_exchange(self, e):
        """Ouvre l'écran de retour/échange"""
        from screens.return_exchange_screen import ReturnExchangeScreen
        return_screen = ReturnExchangeScreen(
            self.page, self.db, self.sync_service, 
            self.auth_service, self.current_user, self.invoice
        )
        return_screen.show()
    
    def _create_product_card(self, item: Dict) -> ft.Container:
        """Crée une carte pour un produit"""
        product_name = item.get('product_name', 'Produit')
        quantity = item.get('quantity', 1)
        unit_price = item.get('unit_price', 0)
        total_price = item.get('total_price', quantity * unit_price)
        is_returned = item.get('is_returned', 0)
        returned_qty = item.get('returned_quantity', 0)
        
        # État du produit
        if is_returned:
            if returned_qty >= quantity:
                status_color = ft.Colors.RED_700
                status_text = "Complètement retourné"
            else:
                status_color = ft.Colors.ORANGE_700
                status_text = f"Partiellement retourné ({returned_qty}/{quantity})"
        else:
            status_color = ft.Colors.GREEN_700
            status_text = "Non retourné"
        
        # Informations d'échange
        exchange_info = ""
        if item.get('exchange_product_name'):
            exchange_qty = item.get('exchange_quantity', 0)
            exchange_info = f"→ Échangé: {item.get('exchange_product_name')} x{exchange_qty}"
        
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text(product_name, size=16, weight=ft.FontWeight.W_500, expand=True),
                            ft.Text(self._format_money(total_price), size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_700),
                        ],
                    ),
                    ft.Row(
                        controls=[
                            ft.Text(f"Quantité: {quantity}", size=13, color=ft.Colors.GREY_600),
                            ft.Text(f"Prix unitaire: {self._format_money(unit_price)}", size=13, color=ft.Colors.GREY_600),
                        ],
                        spacing=20,
                    ),
                    ft.Row(
                        controls=[
                            ft.Container(
                                content=ft.Text(status_text, size=11, color=ft.Colors.WHITE),
                                bgcolor=status_color,
                                border_radius=10,
                                padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                            ),
                            ft.Text(exchange_info, size=11, color=ft.Colors.BLUE_600) if exchange_info else ft.Container(),
                        ],
                        spacing=10,
                    ),
                ],
                spacing=5,
            ),
            padding=10,
            bgcolor=ft.Colors.WHITE,
            border_radius=8,
            margin=ft.Margin.only(bottom=5),
        )
    
    def show(self):
        """Affiche l'écran de détail de la facture"""
        self._load_items()
        
        invoice_number = self.invoice.get('invoice_number', 'N/A')
        customer_name = self.invoice.get('customer_name', 'Client comptant')
        total_amount = self.invoice.get('total_amount', 0)
        sale_date = self._format_date(self.invoice.get('sale_date', ''))
        payment_method = self.invoice.get('payment_method', 'cash')
        seller_name = self.invoice.get('seller_name', 'N/A')
        status = self.invoice.get('status', 'completed')
        is_modified = self.invoice.get('is_modified', 0)
        
        payment_text = "Espèces" if payment_method == 'cash' else "Carte"
        payment_icon = ft.Icons.MONEY if payment_method == 'cash' else ft.Icons.CREDIT_CARD
        
        # Header
        header = ft.Container(
            content=ft.Row(
                controls=[
                    ft.IconButton(
                        icon=ft.Icons.ARROW_BACK,
                        on_click=self._go_back,
                        icon_color=ft.Colors.WHITE,
                    ),
                    ft.Column(
                        controls=[
                            ft.Text(
                                f"Facture N° {invoice_number}",
                                size=20,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.WHITE,
                            ),
                            ft.Text(
                                sale_date,
                                size=12,
                                color=ft.Colors.WHITE70,
                            ),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    ft.Row(
                        controls=[
                            ft.IconButton(
                                icon=ft.Icons.PRINT,
                                on_click=self._print_invoice,
                                icon_color=ft.Colors.WHITE,
                                tooltip="Imprimer",
                            ),
                            ft.IconButton(
                                icon=ft.Icons.SWAP_HORIZ,
                                on_click=self._open_return_exchange,
                                icon_color=ft.Colors.WHITE,
                                tooltip="Retour/Échange",
                            ),
                        ],
                        spacing=0,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=15,
            bgcolor=ft.Colors.BLUE_700,
        )
        
        # Informations client
        info_card = ft.Card(
            content=ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("Informations", size=16, weight=ft.FontWeight.BOLD),
                        ft.Row(
                            controls=[
                                ft.Icon(ft.Icons.PERSON, size=20, color=ft.Colors.GREY_600),
                                ft.Text(customer_name, size=14, expand=True),
                            ],
                            spacing=10,
                        ),
                        ft.Row(
                            controls=[
                                ft.Icon(payment_icon, size=20, color=ft.Colors.GREY_600),
                                ft.Text(f"Moyen de paiement: {payment_text}", size=14, expand=True),
                            ],
                            spacing=10,
                        ),
                        ft.Row(
                            controls=[
                                ft.Icon(ft.Icons.PERSON_OUTLINE, size=20, color=ft.Colors.GREY_600),
                                ft.Text(f"Vendeur: {seller_name}", size=14, expand=True),
                            ],
                            spacing=10,
                        ),
                        ft.Row(
                            controls=[
                                ft.Icon(ft.Icons.INFO_OUTLINE, size=20, color=ft.Colors.GREY_600),
                                ft.Text(f"Statut: {status}", size=14, expand=True),
                            ],
                            spacing=10,
                        ),
                        ft.Row(
                            controls=[
                                ft.Icon(ft.Icons.EDIT, size=20, color=ft.Colors.GREY_600),
                                ft.Text(f"Modifiée: {'Oui' if is_modified else 'Non'}", size=14, expand=True),
                            ],
                            spacing=10,
                            visible=is_modified == 1,
                        ),
                    ],
                    spacing=12,
                ),
                padding=15,
            ),
            margin=10,
        )
        
        # Liste des produits
        products_header = ft.Row(
            controls=[
                ft.Text("Produits", size=16, weight=ft.FontWeight.BOLD),
                ft.Text(f"{len(self.items)} article(s)", size=12, color=ft.Colors.GREY_600),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
        
        # Créer la liste des produits
        product_cards = []
        for item in self.items:
            card = self._create_product_card(item)
            product_cards.append(card)
            product_cards.append(ft.Divider(height=1, color=ft.Colors.GREY_200))
        
        products_column = ft.Column(
            controls=product_cards[:-1] if product_cards else [ft.Text("Aucun produit", color=ft.Colors.GREY_500)],
            spacing=5,
            scroll=ft.ScrollMode.AUTO,
        )
        
        products_container = ft.Container(
            content=ft.Column(
                controls=[
                    products_header,
                    products_column,
                ],
                spacing=10,
            ),
            padding=ft.Padding.symmetric(horizontal=10),
            expand=True,
        )
        
        # Total
        total_card = ft.Card(
            content=ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Text("TOTAL", size=18, weight=ft.FontWeight.BOLD),
                        ft.Text(
                            self._format_money(total_amount),
                            size=22,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.GREEN_700,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                padding=15,
                bgcolor=ft.Colors.GREY_50,
            ),
            margin=10,
        )
        
        # Actions
        actions_row = ft.Row(
            controls=[
                ft.Button(
                    "Retour",
                    icon=ft.Icons.ARROW_BACK,
                    on_click=self._go_back,
                ),
                ft.Button(
                    "Imprimer",
                    icon=ft.Icons.PRINT,
                    on_click=self._print_invoice,
                    style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE),
                ),
                ft.Button(
                    "Retour/Échange",
                    icon=ft.Icons.SWAP_HORIZ,
                    on_click=self._open_return_exchange,
                    style=ft.ButtonStyle(bgcolor=ft.Colors.ORANGE_700, color=ft.Colors.WHITE),
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
                            products_container,
                            total_card,
                            ft.Container(content=actions_row, padding=10),
                        ],
                        spacing=5,
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