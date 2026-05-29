# return_screen.py - Version avec ConnectionManager

import flet as ft
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from services.connection_manager import ConnectionManager


class ReturnScreen:
    def __init__(self, page: ft.Page, db, sync_service, auth_service, current_user):
        self.page = page
        self.db = db
        self.sync_service = sync_service
        self.auth_service = auth_service
        self.current_user = current_user
        
        # ========== CONNECTION MANAGER ==========
        self.connection_manager = ConnectionManager()
        if sync_service:
            self.connection_manager.set_sync_service(sync_service)
        
        # Variables pour la navigation
        self.current_view = "invoices"  # "invoices" ou "history"
        
        # Conteneur principal pour le contenu
        self.content_area = None
        self.sidebar_container = None
        
        # Filtres
        self.search_field = None
        self.date_from_field = None
        self.date_to_field = None
        self.invoices_list_view = None
        self.history_list_view = None
        
        # Filtres historique
        self.history_date_from = None
        self.history_date_to = None
        self.history_type_filter = None
        
        self.selected_invoice = None
        
    def _branch_id(self):
        return (self.current_user.get("active_branch_id") or 
                self.current_user.get("branch_id") or
                self.current_user.get("current_branch_id"))
    
    def _safe_float(self, value, default=0.0):
        try:
            return float(value) if value else default
        except:
            return default
    
    def _safe_int(self, value, default=0):
        try:
            return int(float(value)) if value else default
        except:
            return default
    
    def _format_money(self, amount):
        try:
            return f"{float(amount):,.0f} FC"
        except:
            return "0 FC"
    
    def _format_date(self, date_str):
        """Formate une date ISO vers JJ/MM/AAAA"""
        if not date_str:
            return ""
        try:
            if 'T' in date_str:
                date_str = date_str.split('T')[0]
            dt = datetime.fromisoformat(date_str)
            return dt.strftime("%d/%m/%Y")
        except:
            return date_str
    
    def _is_online(self) -> bool:
        """Vérifie si on est en mode online"""
        return self.connection_manager.is_online_mode()
    
    def _is_force_offline(self) -> bool:
        """Vérifie si on est en mode offline forcé"""
        force_mode = self.connection_manager.get_force_mode()
        return force_mode is False
    
    def show_snackbar(self, message: str, color=None):
        snack = ft.SnackBar(
            content=ft.Text(message),
            bgcolor=color or ft.Colors.BLUE_700,
            show_close_icon=True,
            duration=4000,
        )
        self.page.snack_bar = snack
        snack.open = True
        self.page.update()
    
    def show_error(self, message: str):
        self.show_snackbar(message, ft.Colors.RED_700)
    
    def show_success(self, message: str):
        self.show_snackbar(message, ft.Colors.GREEN_700)
    
    def show_warning(self, message: str):
        self.show_snackbar(message, ft.Colors.ORANGE_700)
    
    def show(self):
        self.page.clean()
        self.page.bgcolor = ft.Colors.GREY_50
        self.page.padding = 0
        self.page.spacing = 0
        
        # Indicateur de mode offline/online
        status = self._get_status_indicator()
        
        # Header
        header = ft.Container(
            content=ft.Row(
                controls=[
                    ft.IconButton(
                        icon=ft.Icons.ARROW_BACK,
                        on_click=lambda e: self.go_back(),
                        icon_color=ft.Colors.WHITE,
                    ),
                    ft.Text(
                        "Retour / Échange",
                        size=22,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.WHITE,
                        expand=True,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    status,
                    ft.IconButton(
                        icon=ft.Icons.REFRESH,
                        on_click=lambda e: self.refresh_data(),
                        icon_color=ft.Colors.WHITE,
                        tooltip="Actualiser",
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            padding=12,
            bgcolor=ft.Colors.BLUE_700,
        )
        
        # Zone de contenu
        self.content_area = ft.Container(
            expand=True,
            bgcolor=ft.Colors.GREY_50,
            padding=10,
        )
        
        # Créer la sidebar
        sidebar = self._create_sidebar()
        
        # Organisation principale
        main_row = ft.Row(
            controls=[
                sidebar,
                ft.VerticalDivider(width=1),
                self.content_area,
            ],
            expand=True,
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        
        main_column = ft.Column(
            controls=[
                header,
                ft.Container(content=main_row, expand=True, padding=10),
            ],
            spacing=0,
            expand=True,
        )
        
        self.page.add(main_column)
        
        # Charger la vue par défaut
        self._load_view_content("invoices")
        self.page.update()
    
    def _get_status_indicator(self) -> ft.Container:
        """Crée un indicateur de statut de connexion"""
        status = self.connection_manager.get_display_status()
        force_mode = self.connection_manager.get_force_mode()
        
        color_map = {
            "green": ft.Colors.GREEN_400,
            "blue": ft.Colors.BLUE_400,
            "orange": ft.Colors.ORANGE_400,
            "red": ft.Colors.RED_400,
        }
        
        icon_map = {
            "🌐": ft.Icons.WIFI,
            "🔌": ft.Icons.WIFI,
            "✈️": ft.Icons.WIFI_OFF,
            "📡": ft.Icons.WIFI_OFF,
        }
        
        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(icon_map.get(status["icon"], ft.Icons.WIFI_OFF), size=16, color=color_map.get(status["color"], ft.Colors.GREY_400)),
                    ft.Text(status["text"], size=11, color=color_map.get(status["color"], ft.Colors.GREY_400)),
                ],
                spacing=4,
            ),
            bgcolor=ft.Colors.WHITE if self._is_mobile() else None,
            padding=ft.Padding.symmetric(horizontal=8, vertical=4),
            border_radius=15,
        )
    
    def _is_mobile(self) -> bool:
        """Détecte si l'appareil est mobile"""
        return (self.page.width or 0) < 600
    
    def _create_sidebar(self):
        """Crée la sidebar avec les menus"""
        menu_item_invoices = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.RECEIPT, size=20, color=ft.Colors.BLUE_700),
                    ft.Text("Factures", size=14, weight=ft.FontWeight.W_500, color=ft.Colors.BLUE_700),
                ],
                spacing=10,
            ),
            padding=ft.Padding.symmetric(horizontal=15, vertical=12),
            border_radius=8,
            bgcolor=ft.Colors.BLUE_50 if self.current_view == "invoices" else ft.Colors.TRANSPARENT,
            on_click=lambda e: self._switch_view("invoices"),
        )
        
        menu_item_history = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.HISTORY, size=20, color=ft.Colors.BLUE_700),
                    ft.Text("Historique", size=14, weight=ft.FontWeight.W_500, color=ft.Colors.BLUE_700),
                ],
                spacing=10,
            ),
            padding=ft.Padding.symmetric(horizontal=15, vertical=12),
            border_radius=8,
            bgcolor=ft.Colors.BLUE_50 if self.current_view == "history" else ft.Colors.TRANSPARENT,
            on_click=lambda e: self._switch_view("history"),
        )
        
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Container(height=10),
                    menu_item_invoices,
                    menu_item_history,
                ],
                spacing=5,
            ),
            width=200,
            bgcolor=ft.Colors.WHITE,
            border_radius=10,
            padding=10,
        )
    
    def _switch_view(self, view_name: str):
        """Change de vue"""
        if self.current_view == view_name:
            return
        self.current_view = view_name
        self._load_view_content(view_name)
        self._rebuild_sidebar()
    
    def _rebuild_sidebar(self):
        """Reconstruit la sidebar avec le bon élément actif"""
        self.show()
    
    def _load_view_content(self, view_name: str):
        """Charge le contenu de la vue sans reconstruire l'UI"""
        if view_name == "invoices":
            self.content_area.content = self.create_invoices_view()
            self.load_invoices()
        else:
            self.content_area.content = self.create_history_view()
            self.load_history()
        self.page.update()
    
    def create_invoices_view(self):
        """Crée la vue des factures"""
        # Zone de recherche
        self.date_from_field = ft.TextField(
            label="Date début",
            hint_text="JJ/MM/AAAA",
            prefix_icon=ft.Icons.CALENDAR_TODAY,
            expand=True,
        )
        
        self.date_to_field = ft.TextField(
            label="Date fin",
            hint_text="JJ/MM/AAAA",
            prefix_icon=ft.Icons.CALENDAR_MONTH,
            expand=True,
        )
        
        self.search_field = ft.TextField(
            label="Rechercher",
            hint_text="N° facture, client...",
            prefix_icon=ft.Icons.SEARCH,
            expand=True,
            on_change=lambda e: self.load_invoices(),
        )
        
        # Boutons de filtre
        today_btn = ft.ElevatedButton(
            content=ft.Text("Aujourd'hui"),
            icon=ft.Icons.TODAY,
            on_click=lambda e: self.set_today_filter(),
        )
        
        week_btn = ft.ElevatedButton(
            content=ft.Text("Cette semaine"),
            icon=ft.Icons.WEEKEND,
            on_click=lambda e: self.set_week_filter(),
        )
        
        month_btn = ft.ElevatedButton(
            content=ft.Text("Ce mois"),
            icon=ft.Icons.CALENDAR_MONTH,
            on_click=lambda e: self.set_month_filter(),
        )
        
        search_btn = ft.ElevatedButton(
            content=ft.Text("Rechercher"),
            icon=ft.Icons.SEARCH,
            on_click=lambda e: self.load_invoices(),
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE),
        )
        
        # Liste des factures
        self.invoices_list_view = ft.ListView(expand=True, spacing=10)
        
        # Organisation des filtres
        filters_card = ft.Card(
            content=ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[self.date_from_field, self.date_to_field],
                            spacing=10,
                        ),
                        ft.Row(
                            controls=[
                                self.search_field,
                                today_btn,
                                week_btn,
                                month_btn,
                                search_btn,
                            ],
                            spacing=10,
                            wrap=True,
                        ),
                    ],
                    spacing=10,
                ),
                padding=15,
            ),
            elevation=2,
        )
        
        # Avertissement mode offline
        offline_warning = None
        if self._is_force_offline():
            offline_warning = ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.WARNING_AMBER, color=ft.Colors.ORANGE, size=16),
                        ft.Text(
                            "Mode OFFLINE forcé - Les modifications seront synchronisées plus tard",
                            size=12,
                            color=ft.Colors.ORANGE,
                        ),
                    ],
                    spacing=5,
                ),
                margin=ft.Margin.only(bottom=10),
                padding=ft.Padding.all(8),
                bgcolor=ft.Colors.ORANGE_50,
                border_radius=8,
            )
        elif not self._is_online():
            offline_warning = ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.WIFI_OFF, color=ft.Colors.RED, size=16),
                        ft.Text(
                            "Mode hors-ligne - Les modifications seront synchronisées automatiquement lors du retour en ligne",
                            size=12,
                            color=ft.Colors.RED,
                        ),
                    ],
                    spacing=5,
                ),
                margin=ft.Margin.only(bottom=10),
                padding=ft.Padding.all(8),
                bgcolor=ft.Colors.RED_50,
                border_radius=8,
            )
        
        # Vue complète
        return ft.Column(
            controls=[
                filters_card,
                ft.Container(height=10),
                ft.Text("Liste des factures", size=16, weight=ft.FontWeight.BOLD),
                ft.Container(height=5),
            ] + ([offline_warning] if offline_warning else []) + [
                ft.Container(
                    content=self.invoices_list_view,
                    expand=True,
                    bgcolor=ft.Colors.WHITE,
                    border_radius=10,
                    padding=5,
                ),
            ],
            spacing=0,
            expand=True,
        )
    
    def create_history_view(self):
        """Crée la vue de l'historique"""
        # Filtres pour l'historique
        self.history_date_from = ft.TextField(
            label="Date début",
            hint_text="JJ/MM/AAAA",
            prefix_icon=ft.Icons.CALENDAR_TODAY,
            expand=True,
        )
        
        self.history_date_to = ft.TextField(
            label="Date fin",
            hint_text="JJ/MM/AAAA",
            prefix_icon=ft.Icons.CALENDAR_MONTH,
            expand=True,
        )
        
        self.history_type_filter = ft.Dropdown(
            label="Type",
            value="all",
            expand=True,
            options=[
                ft.DropdownOption(key="all", text="Tous"),
                ft.DropdownOption(key="return", text="Retours"),
                ft.DropdownOption(key="exchange", text="Échanges"),
            ],
        )
        
        self.history_list_view = ft.ListView(expand=True, spacing=10)
        
        # Organisation des filtres
        filters_card = ft.Card(
            content=ft.Container(
                content=ft.Row(
                    controls=[
                        self.history_date_from,
                        self.history_date_to,
                        self.history_type_filter,
                        ft.ElevatedButton(
                            content=ft.Text("Rechercher"),
                            icon=ft.Icons.SEARCH,
                            on_click=lambda e: self.load_history(),
                        ),
                    ],
                    spacing=10,
                    wrap=True,
                ),
                padding=15,
            ),
            elevation=2,
        )
        
        # Vue complète
        return ft.Column(
            controls=[
                filters_card,
                ft.Container(height=10),
                ft.Text("Historique des retours et échanges", size=16, weight=ft.FontWeight.BOLD),
                ft.Container(height=5),
                ft.Container(
                    content=self.history_list_view,
                    expand=True,
                    bgcolor=ft.Colors.WHITE,
                    border_radius=10,
                    padding=5,
                ),
            ],
            spacing=0,
            expand=True,
        )
    
    def set_today_filter(self):
        today = datetime.now().strftime("%d/%m/%Y")
        self.date_from_field.value = today
        self.date_to_field.value = today
        self.load_invoices()
    
    def set_week_filter(self):
        today = datetime.now().date()
        start_of_week = today - timedelta(days=today.weekday())
        self.date_from_field.value = start_of_week.strftime("%d/%m/%Y")
        self.date_to_field.value = today.strftime("%d/%m/%Y")
        self.load_invoices()
    
    def set_month_filter(self):
        today = datetime.now().date()
        start_of_month = today.replace(day=1)
        self.date_from_field.value = start_of_month.strftime("%d/%m/%Y")
        self.date_to_field.value = today.strftime("%d/%m/%Y")
        self.load_invoices()
    
    def _convert_date_to_iso(self, date_str: str) -> str:
        """Convertit une date JJ/MM/AAAA en format ISO YYYY-MM-DD"""
        if not date_str:
            return None
        try:
            dt = datetime.strptime(date_str, "%d/%m/%Y")
            return dt.strftime("%Y-%m-%d")
        except:
            return None
    
    def load_invoices(self):
        """Charge les factures selon les filtres"""
        branch_id = self._branch_id()
        
        if not branch_id:
            self.show_error("ID de succursale non trouvé")
            return
        
        start_date = self._convert_date_to_iso(self.date_from_field.value) if self.date_from_field and self.date_from_field.value else None
        end_date = self._convert_date_to_iso(self.date_to_field.value) if self.date_to_field and self.date_to_field.value else None
        search_term = self.search_field.value if self.search_field else ""
        
        # Récupérer les factures depuis la base
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                query = """
                    SELECT 
                        s.id, s.invoice_number, s.customer_name, s.total_price as total_amount, 
                        s.sale_date, s.payment_method, s.is_modified,
                        s.created_at, s.branch_id
                    FROM sales s
                    WHERE s.branch_id = ?
                """
                params = [branch_id]
                
                if start_date:
                    query += " AND date(s.sale_date) >= date(?)"
                    params.append(start_date)
                if end_date:
                    query += " AND date(s.sale_date) <= date(?)"
                    params.append(end_date)
                
                if search_term:
                    query += " AND (s.invoice_number LIKE ? OR s.customer_name LIKE ?)"
                    params.extend([f"%{search_term}%", f"%{search_term}%"])
                
                query += " ORDER BY s.sale_date DESC, s.id DESC"
                
                cursor.execute(query, params)
                columns = [description[0] for description in cursor.description]
                invoices = [dict(zip(columns, row)) for row in cursor.fetchall()]
            
        except Exception as e:
            print(f"Erreur lors du chargement des factures: {e}")
            invoices = []
        
        self.invoices_list_view.controls.clear()
        
        if not invoices:
            self.invoices_list_view.controls.append(
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Icon(ft.Icons.RECEIPT_OUTLINED, size=64, color=ft.Colors.GREY_400),
                            ft.Text("Aucune facture trouvée", size=16, color=ft.Colors.GREY_600),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    alignment=ft.Alignment.CENTER,
                    expand=True,
                )
            )
        else:
            for invoice in invoices:
                self.invoices_list_view.controls.append(
                    self.create_invoice_card(invoice)
                )
        
        self.page.update()
    
    def get_invoice_items(self, invoice_number: str) -> List[Dict]:
        """Récupère les articles d'une facture depuis sale_items"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT si.*, s.invoice_number 
                    FROM sale_items si
                    JOIN sales s ON si.sale_id = s.id
                    WHERE s.invoice_number = ?
                """, (invoice_number,))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            print(f"Erreur get_invoice_items: {e}")
            return []
    
    def get_returnable_items_count(self, invoice_number: str) -> int:
        """Compte les produits retournables sur une facture"""
        items = self.get_invoice_items(invoice_number)
        return sum(1 for item in items 
                   if item.get('quantity', 0) > item.get('returned_quantity', 0))
    
    def create_invoice_card(self, invoice: Dict) -> ft.Card:
        """Crée une carte pour une facture"""
        invoice_number = invoice.get('invoice_number', 'N/A')
        customer_name = invoice.get('customer_name', 'Client')
        total_amount = self._safe_float(invoice.get('total_amount', 0))
        sale_date = self._format_date(invoice.get('sale_date', ''))
        is_modified = invoice.get('is_modified', 0)
        
        # Compter les produits retournables
        returnable_items = self.get_returnable_items_count(invoice_number)
        
        return ft.Card(
            content=ft.Container(
                padding=12,
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Icon(
                                    ft.Icons.RECEIPT,
                                    size=24,
                                    color=ft.Colors.ORANGE if is_modified else ft.Colors.BLUE_700,
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Text(
                                            invoice_number,
                                            size=14,
                                            weight=ft.FontWeight.BOLD,
                                        ),
                                        ft.Text(
                                            f"{sale_date} • {customer_name}",
                                            size=11,
                                            color=ft.Colors.GREY_600,
                                        ),
                                    ],
                                    expand=True,
                                ),
                                ft.Text(
                                    self._format_money(total_amount),
                                    size=14,
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.GREEN_700,
                                ),
                            ],
                        ),
                        ft.Divider(height=5, thickness=0.5),
                        ft.Row(
                            controls=[
                                ft.ElevatedButton(
                                    content=ft.Text("Détails"),
                                    icon=ft.Icons.VISIBILITY,
                                    on_click=lambda e, inv=invoice: self.view_invoice_details(inv),
                                ),
                                ft.ElevatedButton(
                                    content=ft.Text("Retour"),
                                    icon=ft.Icons.UNDO,
                                    on_click=lambda e, inv=invoice: self.show_return_dialog(inv),
                                    disabled=(returnable_items == 0),
                                ),
                                ft.ElevatedButton(
                                    content=ft.Text("Échange"),
                                    icon=ft.Icons.SWAP_HORIZ,
                                    on_click=lambda e, inv=invoice: self.show_exchange_dialog(inv),
                                    disabled=(returnable_items == 0),
                                ),
                                ft.ElevatedButton(
                                    content=ft.Text("Imprimer"),
                                    icon=ft.Icons.PRINT,
                                    on_click=lambda e, inv=invoice: self.print_invoice(inv),
                                ),
                            ],
                            spacing=8,
                            wrap=True,
                        ),
                        ft.Row(
                            controls=[
                                ft.Text(
                                    "⚠️ Facture modifiée" if is_modified else "",
                                    size=10,
                                    color=ft.Colors.ORANGE,
                                ),
                            ],
                        ) if is_modified else ft.Container(),
                        # Indicateur hors-ligne
                        ft.Row(
                            controls=[
                                ft.Icon(ft.Icons.CLOUD_QUEUE, size=12, color=ft.Colors.GREY_500),
                                ft.Text(
                                    "Modification locale (sync différée)" if not self._is_online() else "",
                                    size=9,
                                    color=ft.Colors.GREY_500,
                                ),
                            ],
                        ) if not self._is_online() and is_modified else ft.Container(),
                    ],
                    spacing=8,
                ),
            ),
            margin=5,
        )
    
    def get_invoice_with_items(self, invoice_number: str) -> Optional[Dict]:
        """Récupère une facture avec ses articles"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT id, invoice_number, customer_name, total_price as total_amount,
                           sale_date, payment_method, is_modified, branch_id
                    FROM sales
                    WHERE invoice_number = ?
                """, (invoice_number,))
                
                row = cursor.fetchone()
                if not row:
                    return None
                
                columns = [description[0] for description in cursor.description]
                invoice = dict(zip(columns, row))
                
                invoice['items'] = self.get_invoice_items(invoice_number)
                
                return invoice
        except Exception as e:
            print(f"Erreur get_invoice_with_items: {e}")
            return None
    
    def view_invoice_details(self, invoice: Dict):
        """Affiche les détails d'une facture"""
        invoice_number = invoice.get('invoice_number')
        
        invoice_data = self.get_invoice_with_items(invoice_number)
        if not invoice_data:
            self.show_error("Impossible de charger les détails de la facture")
            return
        
        items = invoice_data.get('items', [])
        
        # Créer les lignes de produits
        items_list = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, height=300)
        
        for item in items:
            is_returned = item.get('is_returned', 0)
            exchange_product = item.get('exchange_product_name')
            returned_qty = item.get('returned_quantity', 0)
            
            item_container = ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Text(item.get('product_name', 'Produit'), weight=ft.FontWeight.BOLD, expand=True),
                                ft.Text(f"{item.get('quantity', 0)} x {self._format_money(item.get('unit_price', 0))}", size=12),
                                ft.Text(self._format_money(item.get('total_price', 0)), weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_700),
                            ],
                        ),
                    ] + ([
                        ft.Row(
                            controls=[
                                ft.Icon(ft.Icons.SWAP_HORIZ, size=14, color=ft.Colors.PURPLE),
                                ft.Text(
                                    f"Échangé: {exchange_product} (Qté: {item.get('exchange_quantity', 0)})",
                                    size=11,
                                    color=ft.Colors.PURPLE,
                                ),
                            ],
                        )
                    ] if exchange_product else []) + ([
                        ft.Row(
                            controls=[
                                ft.Icon(ft.Icons.UNDO, size=14, color=ft.Colors.ORANGE),
                                ft.Text(
                                    f"Retourné: {returned_qty} unités",
                                    size=11,
                                    color=ft.Colors.ORANGE,
                                ),
                            ],
                        )
                    ] if is_returned and not exchange_product else []),
                    spacing=4,
                ),
                padding=8,
                bgcolor=ft.Colors.GREY_50,
                border_radius=8,
            )
            items_list.controls.append(item_container)
        
        dialog = ft.AlertDialog(
            title=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.RECEIPT, color=ft.Colors.BLUE_700),
                    ft.Text(
                        f"Facture {invoice_data.get('invoice_number')}",
                        size=18,
                        weight=ft.FontWeight.BOLD,
                        expand=True,
                    ),
                ],
                spacing=10,
            ),
            content=ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Text("Client:", weight=ft.FontWeight.BOLD, width=80),
                                ft.Text(invoice_data.get('customer_name', 'Client comptant'), expand=True),
                            ],
                        ),
                        ft.Row(
                            controls=[
                                ft.Text("Date:", weight=ft.FontWeight.BOLD, width=80),
                                ft.Text(self._format_date(invoice_data.get('sale_date', '')), expand=True),
                            ],
                        ),
                        ft.Row(
                            controls=[
                                ft.Text("Paiement:", weight=ft.FontWeight.BOLD, width=80),
                                ft.Text("Espèces" if invoice_data.get('payment_method') == 'cash' else "Carte", expand=True),
                            ],
                        ),
                        ft.Divider(),
                        ft.Text("Produits:", weight=ft.FontWeight.BOLD),
                        items_list,
                        ft.Divider(),
                        ft.Row(
                            controls=[
                                ft.Text("Total:", weight=ft.FontWeight.BOLD, size=16),
                                ft.Text(
                                    self._format_money(invoice_data.get('total_amount', 0)),
                                    size=16,
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.GREEN_700,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                    ],
                    spacing=10,
                ),
                width=500,
                height=500,
            ),
            actions=[
                ft.TextButton("Fermer", on_click=lambda e: self.close_dialog(dialog)),
                ft.ElevatedButton(
                    content=ft.Text("Duplicata"),
                    icon=ft.Icons.CONTENT_COPY,
                    on_click=lambda e: (self.close_dialog(dialog), self.print_duplicate(invoice_data)),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()
    
    def close_dialog(self, dialog):
        dialog.open = False
        self.page.update()
    
    def show_return_dialog(self, invoice: Dict):
        """Affiche le dialogue de retour"""
        invoice_number = invoice.get('invoice_number')
        customer_name = invoice.get('customer_name')
        
        items = self.get_invoice_items(invoice_number)
        
        if not items:
            self.show_error("Aucun produit trouvé sur cette facture")
            return
        
        # Filtrer les articles retournables
        returnable_items = [
            (i, item) for i, item in enumerate(items)
            if item.get('quantity', 0) > item.get('returned_quantity', 0)
        ]
        
        if not returnable_items:
            self.show_error("Aucun produit retournable sur cette facture")
            return
        
        product_dropdown = ft.Dropdown(
            label="Produit à retourner",
            options=[
                ft.DropdownOption(
                    key=str(i),
                    text=f"{item.get('product_name')} - Qté vendue: {item.get('quantity')} - Retourné: {item.get('returned_quantity', 0)}"
                )
                for i, item in returnable_items
            ],
            expand=True,
        )
        
        quantity_field = ft.TextField(
            label="Quantité à retourner",
            keyboard_type=ft.KeyboardType.NUMBER,
            value="1",
        )
        
        reason_field = ft.TextField(
            label="Motif du retour",
            multiline=True,
            max_lines=3,
        )
        
        def confirm_return(e):
            if not product_dropdown.value:
                self.show_error("Sélectionnez un produit")
                return
            
            idx = self._safe_int(product_dropdown.value)
            selected_item = None
            for i, item in returnable_items:
                if i == idx:
                    selected_item = item
                    break
            
            if not selected_item:
                self.show_error("Produit invalide")
                return
            
            qty = self._safe_int(quantity_field.value, 0)
            if qty <= 0:
                self.show_error("Quantité invalide")
                return
            
            max_returnable = selected_item.get('quantity', 0) - selected_item.get('returned_quantity', 0)
            if qty > max_returnable:
                self.show_error(f"Quantité supérieure au stock vendu (max: {max_returnable})")
                return
            
            # Traiter le retour
            try:
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()
                    
                    # Mettre à jour sale_items
                    new_returned_qty = selected_item.get('returned_quantity', 0) + qty
                    cursor.execute("""
                        UPDATE sale_items 
                        SET returned_quantity = ?, is_returned = 1,
                            return_date = datetime('now')
                        WHERE id = ?
                    """, (new_returned_qty, selected_item.get('id')))
                    
                    # Restocker le produit
                    cursor.execute("""
                        UPDATE products 
                        SET quantity = quantity + ? 
                        WHERE server_id = ?
                    """, (qty, selected_item.get('product_id')))
                    
                    # Enregistrer dans l'historique des retours
                    cursor.execute("""
                        INSERT INTO returns_history 
                        (sale_id, invoice_number, product_id, product_name, quantity, 
                         unit_price, total_price, reason, return_type, branch_id, 
                         customer_name, return_date, is_synced)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)
                    """, (
                        selected_item.get('sale_id'),
                        invoice_number,
                        selected_item.get('product_id'),
                        selected_item.get('product_name'),
                        qty,
                        selected_item.get('unit_price'),
                        qty * selected_item.get('unit_price', 0),
                        reason_field.value or "Retour produit",
                        'return',
                        self._branch_id(),
                        customer_name,
                        0  # is_synced = False (sera sync plus tard si online)
                    ))
                    
                    # Marquer la facture comme modifiée
                    cursor.execute("""
                        UPDATE sales 
                        SET is_modified = 1,
                            modification_date = datetime('now'),
                            modification_reason = ?
                        WHERE invoice_number = ?
                    """, ('Retour de produit', invoice_number))
                    
                    conn.commit()
                
                # Avertissement si offline
                if not self._is_online():
                    self.show_warning("Retour enregistré localement. Synchronisation automatique au retour en ligne.")
                else:
                    self.show_success(f"Retour effectué: {qty} x {selected_item.get('product_name')}")
                
                dialog.open = False
                self.load_invoices()
                self.load_history()
                
            except Exception as err:
                self.show_error(f"Erreur lors du retour: {str(err)}")
        
        dialog = ft.AlertDialog(
            title=ft.Text(f"Retour de produit - {invoice_number}"),
            content=ft.Container(
                content=ft.Column(
                    controls=[
                        product_dropdown,
                        quantity_field,
                        reason_field,
                    ],
                    spacing=15,
                ),
                width=400,
                padding=20,
            ),
            actions=[
                ft.TextButton("Annuler", on_click=lambda e: self.close_dialog(dialog)),
                ft.ElevatedButton(
                    content=ft.Text("Confirmer le retour"),
                    on_click=confirm_return,
                    bgcolor=ft.Colors.ORANGE
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()
    
    def show_exchange_dialog(self, invoice: Dict):
        """Affiche le dialogue d'échange"""
        invoice_number = invoice.get('invoice_number')
        customer_name = invoice.get('customer_name')
        
        items = self.get_invoice_items(invoice_number)
        branch_id = self._branch_id()
        
        if not items:
            self.show_error("Aucun produit trouvé sur cette facture")
            return
        
        # Filtrer les articles échangeables
        exchangeable_items = [
            (i, item) for i, item in enumerate(items)
            if item.get('quantity', 0) > item.get('returned_quantity', 0)
        ]
        
        if not exchangeable_items:
            self.show_error("Aucun produit échangeable sur cette facture")
            return
        
        # Variables pour stocker les produits disponibles
        available_products = []
        
        # Produit à échanger
        old_product_dropdown = ft.Dropdown(
            label="Produit à échanger",
            options=[
                ft.DropdownOption(
                    key=str(i),
                    text=f"{item.get('product_name')} - Qté vendue: {item.get('quantity')}"
                )
                for i, item in exchangeable_items
            ],
            expand=True,
        )
        
        quantity_field = ft.TextField(
            label="Quantité à échanger",
            keyboard_type=ft.KeyboardType.NUMBER,
            value="1",
        )
        
        # Nouveau produit
        new_product_search = ft.TextField(
            label="Rechercher un produit",
            prefix_icon=ft.Icons.SEARCH,
            expand=True,
        )
        
        new_product_dropdown = ft.Dropdown(
            label="Nouveau produit",
            options=[],
            expand=True,
        )
        
        new_product_price = ft.TextField(
            label="Prix unitaire",
            keyboard_type=ft.KeyboardType.NUMBER,
            read_only=True,
        )
        
        exchange_quantity = ft.TextField(
            label="Quantité échangée",
            keyboard_type=ft.KeyboardType.NUMBER,
            value="1",
        )
        
        difference_label = ft.Text("", size=14, weight=ft.FontWeight.BOLD)
        
        def search_new_products(e):
            term = new_product_search.value
            if not term or len(term) < 2:
                return
            
            try:
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT server_id, name, quantity, selling_price
                        FROM products
                        WHERE branch_id = ? AND name LIKE ? AND is_deleted = 0
                        LIMIT 20
                    """, (branch_id, f"%{term}%"))
                    
                    columns = [description[0] for description in cursor.description]
                    products = [dict(zip(columns, row)) for row in cursor.fetchall()]
                    
                    available_products.clear()
                    available_products.extend(products)
                    
                    options = []
                    for p in products:
                        options.append(ft.DropdownOption(
                            key=str(p.get('server_id')),
                            text=f"{p.get('name')} - Stock: {p.get('quantity', 0)}"
                        ))
                    
                    new_product_dropdown.options = options
                    self.page.update()
            except Exception as ex:
                print(f"Erreur recherche: {ex}")
        
        def on_new_product_change(e):
            if new_product_dropdown.value:
                for p in available_products:
                    if str(p.get('server_id')) == new_product_dropdown.value:
                        price = p.get('selling_price', 0)
                        new_product_price.value = str(int(price) if price.is_integer() else price)
                        break
            update_difference()
        
        def update_difference(e=None):
            try:
                old_qty = self._safe_int(quantity_field.value, 0)
                new_qty = self._safe_int(exchange_quantity.value, 0)
                
                # Trouver l'ancien prix
                old_price = 0
                if old_product_dropdown.value:
                    idx = self._safe_int(old_product_dropdown.value)
                    for i, item in exchangeable_items:
                        if i == idx:
                            old_price = item.get('unit_price', 0)
                            break
                
                new_price = self._safe_float(new_product_price.value, 0)
                
                old_total = old_qty * old_price
                new_total = new_qty * new_price
                
                if new_total > old_total:
                    difference_label.value = f"À payer: {self._format_money(new_total - old_total)}"
                    difference_label.color = ft.Colors.RED
                elif new_total < old_total:
                    difference_label.value = f"À rembourser: {self._format_money(old_total - new_total)}"
                    difference_label.color = ft.Colors.GREEN
                else:
                    difference_label.value = "Montant égal"
                    difference_label.color = ft.Colors.BLUE
                    
            except Exception as ex:
                difference_label.value = ""
            
            self.page.update()
        
        quantity_field.on_change = update_difference
        exchange_quantity.on_change = update_difference
        new_product_price.on_change = update_difference
        new_product_dropdown.on_change = on_new_product_change
        new_product_search.on_change = search_new_products
        
        def confirm_exchange(e):
            if not old_product_dropdown.value:
                self.show_error("Sélectionnez un produit à échanger")
                return
            
            if not new_product_dropdown.value:
                self.show_error("Sélectionnez un nouveau produit")
                return
            
            idx = self._safe_int(old_product_dropdown.value)
            selected_item = None
            for i, item in exchangeable_items:
                if i == idx:
                    selected_item = item
                    break
            
            if not selected_item:
                self.show_error("Produit invalide")
                return
            
            old_qty = self._safe_int(quantity_field.value, 0)
            if old_qty <= 0:
                self.show_error("Quantité invalide")
                return
            
            max_exchangeable = selected_item.get('quantity', 0) - selected_item.get('returned_quantity', 0)
            if old_qty > max_exchangeable:
                self.show_error(f"Quantité supérieure au stock vendu (max: {max_exchangeable})")
                return
            
            new_qty = self._safe_int(exchange_quantity.value, 1)
            new_price = self._safe_float(new_product_price.value, 0)
            
            # Trouver le nom du nouveau produit
            new_product_name = ""
            new_product_id = None
            for p in available_products:
                if str(p.get('server_id')) == new_product_dropdown.value:
                    new_product_name = p.get('name', '')
                    new_product_id = p.get('server_id')
                    break
            
            # Vérifier le stock du nouveau produit
            try:
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT quantity FROM products WHERE server_id = ? AND branch_id = ?",
                        (new_product_id, branch_id)
                    )
                    row = cursor.fetchone()
                    current_stock = row[0] if row else 0
                    
                    if new_qty > current_stock:
                        self.show_error(f"Stock insuffisant pour {new_product_name} (disponible: {current_stock})")
                        return
            except Exception as ex:
                print(f"Erreur vérification stock: {ex}")
            
            # Traiter l'échange
            try:
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()
                    
                    # Mettre à jour sale_items
                    new_returned_qty = selected_item.get('returned_quantity', 0) + old_qty
                    cursor.execute("""
                        UPDATE sale_items 
                        SET returned_quantity = ?,
                            exchange_product_id = ?,
                            exchange_product_name = ?,
                            exchange_quantity = ?,
                            exchange_unit_price = ?,
                            is_returned = 1,
                            return_date = datetime('now')
                        WHERE id = ?
                    """, (
                        new_returned_qty,
                        new_product_id,
                        new_product_name,
                        new_qty,
                        new_price,
                        selected_item.get('id')
                    ))
                    
                    # Restocker l'ancien produit
                    cursor.execute("""
                        UPDATE products 
                        SET quantity = quantity + ? 
                        WHERE server_id = ?
                    """, (old_qty, selected_item.get('product_id')))
                    
                    # Déstocker le nouveau produit
                    cursor.execute("""
                        UPDATE products 
                        SET quantity = quantity - ? 
                        WHERE server_id = ?
                    """, (new_qty, new_product_id))
                    
                    # Enregistrer dans l'historique des retours
                    cursor.execute("""
                        INSERT INTO returns_history 
                        (sale_id, invoice_number, product_id, product_name, quantity, 
                         unit_price, total_price, reason, return_type, branch_id, 
                         customer_name, return_date, is_synced,
                         exchange_product_name, exchange_quantity, exchange_unit_price)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?, ?, ?)
                    """, (
                        selected_item.get('sale_id'),
                        invoice_number,
                        selected_item.get('product_id'),
                        selected_item.get('product_name'),
                        old_qty,
                        selected_item.get('unit_price'),
                        old_qty * selected_item.get('unit_price', 0),
                        "Échange de produit",
                        'exchange',
                        branch_id,
                        customer_name,
                        0,  # is_synced = False
                        new_product_name,
                        new_qty,
                        new_price,
                    ))
                    
                    # Marquer la facture comme modifiée
                    cursor.execute("""
                        UPDATE sales 
                        SET is_modified = 1,
                            modification_date = datetime('now'),
                            modification_reason = ?
                        WHERE invoice_number = ?
                    """, ('Échange de produit', invoice_number))
                    
                    conn.commit()
                
                # Avertissement si offline
                if not self._is_online():
                    self.show_warning("Échange enregistré localement. Synchronisation automatique au retour en ligne.")
                else:
                    self.show_success(f"Échange effectué: {selected_item.get('product_name')} → {new_product_name}")
                
                dialog.open = False
                self.load_invoices()
                self.load_history()
                
            except Exception as err:
                self.show_error(f"Erreur lors de l'échange: {str(err)}")
        
        dialog = ft.AlertDialog(
            title=ft.Text(f"Échange de produit - {invoice_number}"),
            content=ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("Produit à échanger:", weight=ft.FontWeight.BOLD),
                        old_product_dropdown,
                        quantity_field,
                        ft.Divider(),
                        ft.Text("Nouveau produit:", weight=ft.FontWeight.BOLD),
                        new_product_search,
                        new_product_dropdown,
                        ft.Row(
                            controls=[exchange_quantity, new_product_price],
                            spacing=10,
                        ),
                        ft.Divider(),
                        difference_label,
                    ],
                    spacing=15,
                ),
                width=450,
                height=450,
            ),
            actions=[
                ft.TextButton("Annuler", on_click=lambda e: self.close_dialog(dialog)),
                ft.ElevatedButton(
                    content=ft.Text("Confirmer l'échange"),
                    on_click=confirm_exchange,
                    bgcolor=ft.Colors.PURPLE,
                    color=ft.Colors.WHITE
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()
    
    def load_history(self):
        """Charge l'historique des retours et échanges"""
        branch_id = self._branch_id()
        
        if not branch_id:
            return
        
        start_date = self._convert_date_to_iso(self.history_date_from.value) if self.history_date_from and self.history_date_from.value else None
        end_date = self._convert_date_to_iso(self.history_date_to.value) if self.history_date_to and self.history_date_to.value else None
        return_type = self.history_type_filter.value if self.history_type_filter and self.history_type_filter.value != 'all' else None
        
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                query = """
                    SELECT * FROM returns_history
                    WHERE branch_id = ?
                """
                params = [branch_id]
                
                if start_date:
                    query += " AND date(return_date) >= date(?)"
                    params.append(start_date)
                if end_date:
                    query += " AND date(return_date) <= date(?)"
                    params.append(end_date)
                if return_type:
                    query += " AND return_type = ?"
                    params.append(return_type)
                
                query += " ORDER BY return_date DESC"
                
                cursor.execute(query, params)
                columns = [description[0] for description in cursor.description]
                history = [dict(zip(columns, row)) for row in cursor.fetchall()]
            
        except Exception as e:
            print(f"Erreur chargement historique: {e}")
            history = []
        
        self.history_list_view.controls.clear()
        
        if not history:
            self.history_list_view.controls.append(
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Icon(ft.Icons.HISTORY, size=64, color=ft.Colors.GREY_400),
                            ft.Text("Aucun historique trouvé", size=16, color=ft.Colors.GREY_600),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    alignment=ft.Alignment.CENTER,
                    expand=True,
                )
            )
        else:
            for record in history:
                self.history_list_view.controls.append(
                    self.create_history_card(record)
                )
        
        self.page.update()
    
    def create_history_card(self, record: Dict) -> ft.Card:
        """Crée une carte pour l'historique"""
        return_type = record.get('return_type', 'return')
        is_exchange = return_type == 'exchange'
        
        return_date = self._format_date(record.get('return_date', ''))
        
        return ft.Card(
            content=ft.Container(
                padding=12,
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Icon(
                                    ft.Icons.SWAP_HORIZ if is_exchange else ft.Icons.UNDO,
                                    size=24,
                                    color=ft.Colors.PURPLE if is_exchange else ft.Colors.ORANGE,
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Text(
                                            f"{'Échange' if is_exchange else 'Retour'} - {record.get('product_name', 'Produit')}",
                                            size=14,
                                            weight=ft.FontWeight.BOLD,
                                        ),
                                        ft.Text(
                                            f"Facture: {record.get('invoice_number', 'N/A')} • {return_date}",
                                            size=11,
                                            color=ft.Colors.GREY_600,
                                        ),
                                        ft.Text(
                                            f"Client: {record.get('customer_name', 'Client')}",
                                            size=11,
                                            color=ft.Colors.GREY_600,
                                        ),
                                    ],
                                    expand=True,
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Text(
                                            f"Qté: {record.get('quantity', 0)}",
                                            size=12,
                                            weight=ft.FontWeight.BOLD,
                                        ),
                                        ft.Text(
                                            self._format_money(record.get('total_price', 0)),
                                            size=12,
                                            color=ft.Colors.GREEN_700,
                                        ),
                                    ],
                                    horizontal_alignment=ft.CrossAxisAlignment.END,
                                ),
                            ],
                        ),
                    ] + ([
                        ft.Row(
                            controls=[
                                ft.Text(
                                    f"Échangé avec: {record.get('exchange_product_name', 'N/A')} (Qté: {record.get('exchange_quantity', 0)})",
                                    size=11,
                                    color=ft.Colors.PURPLE,
                                ),
                            ],
                        )
                    ] if is_exchange and record.get('exchange_product_name') else []) + [
                        ft.Row(
                            controls=[
                                ft.Text(
                                    f"Motif: {record.get('reason', 'Non spécifié')}",
                                    size=10,
                                    color=ft.Colors.GREY_500,
                                    expand=True,
                                ),
                            ],
                        ),
                        # Indicateur de synchronisation
                        ft.Row(
                            controls=[
                                ft.Icon(
                                    ft.Icons.CLOUD_QUEUE if record.get('is_synced', 0) == 0 else ft.Icons.CLOUD_DONE,
                                    size=12,
                                    color=ft.Colors.GREY_500 if record.get('is_synced', 0) == 0 else ft.Colors.GREEN,
                                ),
                                ft.Text(
                                    "En attente de synchronisation" if record.get('is_synced', 0) == 0 else "Synchronisé",
                                    size=9,
                                    color=ft.Colors.GREY_500 if record.get('is_synced', 0) == 0 else ft.Colors.GREEN,
                                ),
                            ],
                        ) if not self._is_online() or record.get('is_synced', 0) == 0 else ft.Container(),
                    ],
                    spacing=8,
                ),
            ),
            margin=5,
        )
    
    def print_invoice(self, invoice: Dict):
        """Imprime une facture"""
        invoice_number = invoice.get('invoice_number')
        
        invoice_data = self.get_invoice_with_items(invoice_number)
        if invoice_data:
            try:
                from utils.print_manager import PrintManager
                print_manager = PrintManager(self.page, self.db, self.current_user)
                print_manager.print_invoice(invoice_data, invoice_data.get('items', []))
                self.show_success("Impression envoyée")
            except Exception as e:
                self.show_error(f"Erreur d'impression: {str(e)}")
    
    def print_duplicate(self, invoice_data: Dict):
        """Imprime un duplicata de facture"""
        try:
            from utils.print_manager import PrintManager
            print_manager = PrintManager(self.page, self.db, self.current_user)
            invoice_data['is_duplicate'] = True
            print_manager.print_invoice(invoice_data, invoice_data.get('items', []))
            self.show_success("Duplicata envoyé à l'impression")
        except Exception as e:
            self.show_error(f"Erreur d'impression: {str(e)}")
    
    def refresh_data(self):
        """Rafraîchit toutes les données"""
        self.load_invoices()
        if self.current_view == "history":
            self.load_history()
        self.show_success("Données actualisées")
    
    def go_back(self):
        from screens.dashboard_screen import DashboardScreen
        dashboard = DashboardScreen(
            self.page, self.db, self.sync_service,
            self.auth_service, self.current_user
        )
        dashboard.show()