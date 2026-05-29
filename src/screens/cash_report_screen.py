import flet as ft
from datetime import datetime, timedelta
import io
import os
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
import threading
import logging

logger = logging.getLogger(__name__)


class CashReportScreen:
    """Écran de rapport de trésorerie avec support online/offline"""
    
    def __init__(self, page: ft.Page, db, sync_service, auth_service, current_user):
        self.page = page
        self.db = db
        self.sync_service = sync_service
        self.auth_service = auth_service
        self.current_user = current_user

        # Récupérer le ConnectionManager
        from services.connection_manager import ConnectionManager
        self.connection_manager = ConnectionManager()
        self._is_online = self.connection_manager.is_online_mode()
        self._is_header_initialized = False

        self.start_date: datetime | None = None
        self.end_date: datetime | None = None

        self.period_text: ft.Text | None = None
        self.summary_grid: ft.GridView | None = None
        self.details_section: ft.Column | None = None

        self.start_date_picker: ft.DatePicker | None = None
        self.end_date_picker: ft.DatePicker | None = None
        self.start_date_text: ft.Text | None = None
        self.end_date_text: ft.Text | None = None
        
        # Indicateur de connexion
        self.connection_indicator: ft.Container | None = None
        
        # S'abonner aux changements de connexion
        self._setup_connection_observer()

    # ==================== GESTION CONNEXION ====================
    
    def _setup_connection_observer(self):
        """S'abonne aux changements de statut de connexion"""
        def on_connection_changed(is_online: bool, force_mode: bool):
            self._is_online = is_online
            logger.info(f"📡 CashReportScreen: Statut connexion changé - online={is_online}")
            
            if self._is_header_initialized and self.connection_indicator:
                self.update_connection_indicator()
                self.page.update()
        
        self.connection_manager.register_observer(on_connection_changed)
    
    def update_connection_indicator(self):
        """Met à jour l'indicateur de connexion"""
        if not self.connection_indicator:
            return
        
        status = self.connection_manager.get_display_status()
        
        if status["color"] == "green":
            color = ft.Colors.GREEN
            icon = ft.Icons.WIFI
        elif status["color"] == "blue":
            color = ft.Colors.BLUE
            icon = ft.Icons.WIFI
        elif status["color"] == "orange":
            color = ft.Colors.ORANGE
            icon = ft.Icons.WIFI_OFF
        else:
            color = ft.Colors.RED
            icon = ft.Icons.WIFI_OFF
        
        self.connection_indicator.content = ft.Row(
            [
                ft.Icon(icon, color=color, size=16),
                ft.Text(status["text"], size=11, color=color, weight=ft.FontWeight.BOLD),
            ],
            spacing=4,
        )
        self.connection_indicator.tooltip = status["tooltip"]
    
    def create_connection_indicator(self):
        """Crée l'indicateur de connexion pour le header"""
        status = self.connection_manager.get_display_status()
        
        if status["color"] == "green":
            color = ft.Colors.GREEN
            icon = ft.Icons.WIFI
        elif status["color"] == "blue":
            color = ft.Colors.BLUE
            icon = ft.Icons.WIFI
        elif status["color"] == "orange":
            color = ft.Colors.ORANGE
            icon = ft.Icons.WIFI_OFF
        else:
            color = ft.Colors.RED
            icon = ft.Icons.WIFI_OFF
        
        self.connection_indicator = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(icon, color=color, size=16),
                    ft.Text(status["text"], size=11, color=color, weight=ft.FontWeight.BOLD),
                ],
                spacing=4,
            ),
            bgcolor=ft.Colors.WHITE,
            padding=ft.Padding.symmetric(horizontal=8, vertical=4),
            border_radius=15,
        )
        return self.connection_indicator

    # =========================================================
    # OUTILS
    # =========================================================
    def _branch_id(self):
        return (
            self.current_user.get("active_branch_id")
            or self.current_user.get("branch_id")
        )

    def _branch_name(self) -> str:
        return self.current_user.get("branch_name", "N/A")

    def _safe_number(self, value, default: float = 0.0) -> float:
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def _format_amount(self, value) -> str:
        amount = self._safe_number(value, 0)
        return f"{amount:,.0f} FC"

    def _show_snackbar(self, message: str, color=ft.Colors.BLUE) -> None:
        self.page.snack_bar = ft.SnackBar(
            content=ft.Text(message, color=ft.Colors.WHITE),
            bgcolor=color,
            open=True,
        )
        self.page.update()

    # =========================================================
    # CHARGEMENT DES DONNÉES (ASYNC POUR ONLINE)
    # =========================================================
    def load_report(self, start_date: datetime | None = None, end_date: datetime | None = None):
        """Charge les données du rapport (online = depuis serveur, offline = depuis local)"""
        if start_date is None:
            start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        if end_date is None:
            end_date = datetime.now().replace(hour=23, minute=59, second=59, microsecond=999999)

        self.start_date = start_date
        self.end_date = end_date

        if self.period_text:
            self.period_text.value = (
                f"Période : du {start_date.strftime('%d/%m/%Y %H:%M')} "
                f"au {end_date.strftime('%d/%m/%Y %H:%M')}"
            )

        # Afficher l'indicateur de chargement
        self._show_loading(True)
        
        def load():
            try:
                if self._is_online:
                    # Mode online: charger depuis le serveur
                    data = self._load_from_server(start_date, end_date)
                else:
                    # Mode offline: charger depuis la base locale
                    data = self._load_from_local(start_date, end_date)
                
                # Mettre à jour l'UI
                self.page.run_thread(lambda: self._update_ui_with_data(data))
                
            except Exception as e:
                logger.error(f"Erreur chargement rapport: {e}")
                self.page.run_thread(lambda: self._show_snackbar(f"Erreur: {str(e)}", ft.Colors.RED))
            finally:
                self.page.run_thread(lambda: self._show_loading(False))
        
        threading.Thread(target=load, daemon=True).start()
    
    def _load_from_server(self, start_date: datetime, end_date: datetime) -> dict:
        """Charge les données depuis le serveur via l'API"""
        try:
            from services.connection_manager import ConnectionManager
            cm = ConnectionManager()
            
            # Vérifier les conditions pour le mode online
            if not cm.is_online_mode():
                logger.info("Mode offline, utilisation des données locales")
                return self._load_from_local(start_date, end_date)
            
            if self.sync_service is None:
                logger.warning("sync_service est None, fallback vers local")
                return self._load_from_local(start_date, end_date)
            
            headers = self.sync_service._get_headers()
            if not headers:
                return self._load_from_local(start_date, end_date)
            
            user = self.sync_service.auth_service.get_current_user()
            branch_id = self._branch_id() or user.get('branch_id')
            
            params = {
                "branch_id": branch_id,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "include_details": True
            }
            
            response = self.sync_service.session.get(
                f"{self.sync_service.api_url}/sales/stats",
                headers=headers,
                params=params,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'sales': data.get('sales', []),
                    'expenses': data.get('expenses', []),
                    'returns_exchanges': data.get('returns', []),
                    'source': 'server'
                }
            else:
                logger.warning(f"Erreur serveur: {response.status_code}, fallback local")
                return self._load_from_local(start_date, end_date)
                
        except Exception as e:
            logger.error(f"Erreur _load_from_server: {e}")
            return self._load_from_local(start_date, end_date)
    
    def _load_from_local(self, start_date: datetime, end_date: datetime) -> dict:
        """Charge les données depuis la base locale"""
        branch_id_str = str(self._branch_id()) if self._branch_id() is not None else None
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Vérifier si la table returns_history existe
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='returns_history'")
            returns_table_exists = cursor.fetchone() is not None
            
            # Ventes
            if branch_id_str:
                cursor.execute(
                    """
                    SELECT 
                        id, sale_date, product_name, quantity, unit_price, 
                        total_price, customer_name, invoice_number
                    FROM sales
                    WHERE sale_date BETWEEN ? AND ?
                    AND branch_id = ?
                    ORDER BY sale_date DESC
                    """,
                    (start_date.isoformat(), end_date.isoformat(), branch_id_str),
                )
            else:
                cursor.execute(
                    """
                    SELECT 
                        id, sale_date, product_name, quantity, unit_price, 
                        total_price, customer_name, invoice_number
                    FROM sales
                    WHERE sale_date BETWEEN ? AND ?
                    ORDER BY sale_date DESC
                    """,
                    (start_date.isoformat(), end_date.isoformat()),
                )
            sales = cursor.fetchall()
            
            # Dépenses
            if branch_id_str:
                cursor.execute(
                    """
                    SELECT id, expense_date, description, amount, category
                    FROM expenses
                    WHERE expense_date BETWEEN ? AND ?
                    AND branch_id = ?
                    ORDER BY expense_date DESC
                    """,
                    (start_date.isoformat(), end_date.isoformat(), branch_id_str),
                )
            else:
                cursor.execute(
                    """
                    SELECT id, expense_date, description, amount, category
                    FROM expenses
                    WHERE expense_date BETWEEN ? AND ?
                    ORDER BY expense_date DESC
                    """,
                    (start_date.isoformat(), end_date.isoformat()),
                )
            expenses = cursor.fetchall()
            
            # Retours et échanges
            returns_exchanges = []
            if returns_table_exists:
                if branch_id_str:
                    cursor.execute(
                        """
                        SELECT id, return_date, product_name, quantity, total_price, 
                               return_type, reason, exchange_product_name
                        FROM returns_history
                        WHERE return_date BETWEEN ? AND ?
                        AND branch_id = ?
                        ORDER BY return_date DESC
                        """,
                        (start_date.isoformat(), end_date.isoformat(), branch_id_str),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT id, return_date, product_name, quantity, total_price, 
                               return_type, reason, exchange_product_name
                        FROM returns_history
                        WHERE return_date BETWEEN ? AND ?
                        ORDER BY return_date DESC
                        """,
                        (start_date.isoformat(), end_date.isoformat()),
                    )
                returns_exchanges = cursor.fetchall()
            
            return {
                'sales': sales,
                'expenses': expenses,
                'returns_exchanges': returns_exchanges,
                'source': 'local'
            }
    
    def _update_ui_with_data(self, data: dict):
        """Met à jour l'UI avec les données chargées"""
        sales = data['sales']
        expenses = data['expenses']
        returns_exchanges = data['returns_exchanges']
        source = data.get('source', 'local')
        
        # Calculer les totaux
        total_sales = 0
        for sale in sales:
            total_sales += self._safe_number(sale[5] if len(sale) > 5 else 0)  # total_price
        
        total_expenses = 0
        for expense in expenses:
            total_expenses += self._safe_number(expense[3] if len(expense) > 3 else 0)  # amount
        
        total_returns = 0
        total_exchanges = 0
        for ret_ex in returns_exchanges:
            value = self._safe_number(ret_ex[4] if len(ret_ex) > 4 else 0)
            return_type = ret_ex[5] if len(ret_ex) > 5 else ''
            if return_type == 'return':
                total_returns += value
            else:
                total_exchanges += value
        
        # Afficher un badge source si online
        source_badge = None
        if source == 'server':
            source_badge = ft.Container(
                content=ft.Text("Données serveur", size=10, color=ft.Colors.GREEN),
                bgcolor=ft.Colors.GREEN_50,
                border_radius=10,
                padding=ft.Padding.symmetric(horizontal=8, vertical=2),
            )
        
        # Créer les cartes récapitulatives
        self.create_summary_cards(total_sales, len(sales), total_expenses, total_returns, total_exchanges)
        
        # Afficher le badge source dans la période
        if source_badge and self.period_text and self.period_text.parent:
            # Ajouter le badge à côté de la période
            pass
        
        # Afficher les détails
        self.display_details(sales, expenses, returns_exchanges)
        
        # Mettre à jour l'affichage du mode
        self._update_mode_display(source)
        
        self.page.update()
    
    def _update_mode_display(self, source: str):
        """Met à jour l'affichage du mode (online/offline)"""
        if not self._is_header_initialized:
            return
        
        mode_text = "Online" if source == 'server' else "Offline (données locales)"
        mode_color = ft.Colors.GREEN if source == 'server' else ft.Colors.ORANGE
        
        # Chercher ou créer l'indicateur de mode
        # (Cette partie peut être adaptée selon votre UI)
    
    def _show_loading(self, show: bool):
        """Affiche ou masque l'indicateur de chargement"""
        # À implémenter selon votre UI
        pass

    def create_summary_cards(self, total_sales, transaction_count, total_expenses, total_returns, total_exchanges):
        """Crée les cartes récapitulatives"""
        if not self.summary_grid:
            return

        self.summary_grid.controls.clear()

        avg_ticket = total_sales / transaction_count if transaction_count > 0 else 0

        cards_data = [
            ("Total ventes", self._format_amount(total_sales), ft.Icons.ATTACH_MONEY, ft.Colors.GREEN),
            ("Transactions", str(transaction_count), ft.Icons.RECEIPT, ft.Colors.BLUE),
            ("Dépenses", self._format_amount(total_expenses), ft.Icons.MONEY_OFF, ft.Colors.RED),
            ("Retours", self._format_amount(total_returns), ft.Icons.REMOVE_SHOPPING_CART, ft.Colors.ORANGE),
            ("Échanges", self._format_amount(total_exchanges), ft.Icons.SWAP_HORIZ, ft.Colors.PURPLE),
            ("Ticket moyen", self._format_amount(avg_ticket), ft.Icons.CALCULATE, ft.Colors.BLUE_GREY),
        ]

        for title, value, icon, color in cards_data:
            card = ft.Container(
                bgcolor=ft.Colors.WHITE,
                border_radius=16,
                padding=12,
                content=ft.Column(
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=8,
                    controls=[
                        ft.Icon(icon, color=color, size=30),
                        ft.Text(
                            title,
                            size=12,
                            text_align=ft.TextAlign.CENTER,
                            color=ft.Colors.GREY_800,
                            weight=ft.FontWeight.W_500,
                        ),
                        ft.Text(
                            value,
                            size=16,
                            text_align=ft.TextAlign.CENTER,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.BLUE_GREY_900,
                        ),
                    ],
                ),
            )
            self.summary_grid.controls.append(card)

    def display_details(self, sales, expenses, returns_exchanges):
        """Affiche les détails du rapport"""
        if not self.details_section:
            return

        self.details_section.controls.clear()

        has_daily_sales = bool(sales)
        has_expenses = any(self._safe_number(exp[3]) > 0 for exp in expenses) if expenses else False
        has_returns = bool(returns_exchanges)

        # SECTION VENTES PAR JOUR
        if has_daily_sales:
            self.details_section.controls.append(
                ft.Container(
                    padding=ft.Padding.only(left=4, right=4, bottom=4),
                    content=ft.Text(
                        "Ventes par jour",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.BLUE_GREY_900,
                    ),
                )
            )

            # Grouper par jour
            sales_by_day = {}
            for sale in sales:
                try:
                    sale_date = sale[1]  # sale_date
                    if sale_date:
                        if isinstance(sale_date, str):
                            day_key = sale_date.split('T')[0]
                            day_name = datetime.fromisoformat(day_key).strftime("%d/%m/%Y")
                        else:
                            day_key = sale_date.strftime("%Y-%m-%d")
                            day_name = sale_date.strftime("%d/%m/%Y")
                    else:
                        continue
                except:
                    continue
                
                amount = self._safe_number(sale[5] if len(sale) > 5 else 0)
                
                if day_key not in sales_by_day:
                    sales_by_day[day_key] = {'count': 0, 'amount': 0, 'name': day_name}
                sales_by_day[day_key]['count'] += 1
                sales_by_day[day_key]['amount'] += amount

            for day_data in sales_by_day.values():
                self.details_section.controls.append(
                    ft.Card(
                        margin=ft.Margin.symmetric(horizontal=2, vertical=4),
                        content=ft.Container(
                            padding=12,
                            content=ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                controls=[
                                    ft.Column(
                                        expand=True,
                                        spacing=4,
                                        controls=[
                                            ft.Text(
                                                day_data['name'],
                                                size=14,
                                                weight=ft.FontWeight.BOLD,
                                                color=ft.Colors.BLUE_GREY_900,
                                            ),
                                            ft.Text(
                                                f"{day_data['count']} transaction(s)",
                                                size=12,
                                                color=ft.Colors.GREY_700,
                                            ),
                                        ],
                                    ),
                                    ft.Text(
                                        self._format_amount(day_data['amount']),
                                        size=16,
                                        weight=ft.FontWeight.BOLD,
                                        color=ft.Colors.GREEN_700,
                                    ),
                                ],
                            ),
                        ),
                    )
                )

        # SECTION RETOURS ET ÉCHANGES
        if has_returns:
            if has_daily_sales:
                self.details_section.controls.append(ft.Divider(height=20))
            
            self.details_section.controls.append(
                ft.Container(
                    padding=ft.Padding.only(left=4, right=4, bottom=4),
                    content=ft.Text(
                        "Retours et échanges",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.BLUE_GREY_900,
                    ),
                )
            )

            for ret_ex in returns_exchanges[:50]:
                try:
                    return_date = ret_ex[1]  # return_date
                    if return_date:
                        if isinstance(return_date, str):
                            return_date = datetime.fromisoformat(return_date.split('T')[0]).strftime("%d/%m/%Y")
                        else:
                            return_date = return_date.strftime("%d/%m/%Y")
                    else:
                        return_date = "N/A"
                except:
                    return_date = "N/A"
                
                return_type = "RETOUR" if (len(ret_ex) > 5 and ret_ex[5] == 'return') else "ÉCHANGE"
                product_name = ret_ex[2] if len(ret_ex) > 2 and ret_ex[2] else "Produit"
                quantity = self._safe_number(ret_ex[3] if len(ret_ex) > 3 else 0)
                total = self._safe_number(ret_ex[4] if len(ret_ex) > 4 else 0)
                reason = ret_ex[6] if len(ret_ex) > 6 and ret_ex[6] else "-"
                
                type_color = ft.Colors.RED_700 if return_type == "RETOUR" else ft.Colors.PURPLE_700
                type_icon = ft.Icons.REMOVE_SHOPPING_CART if return_type == "RETOUR" else ft.Icons.SWAP_HORIZ
                
                self.details_section.controls.append(
                    ft.Card(
                        margin=ft.Margin.symmetric(horizontal=2, vertical=4),
                        content=ft.Container(
                            padding=12,
                            content=ft.Column(
                                spacing=6,
                                controls=[
                                    ft.Row(
                                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                        controls=[
                                            ft.Text(
                                                f"{return_date} - {return_type}",
                                                size=14,
                                                weight=ft.FontWeight.BOLD,
                                                color=type_color,
                                            ),
                                            ft.Icon(type_icon, color=type_color, size=20),
                                        ],
                                    ),
                                    ft.Text(
                                        f"{product_name} x{quantity:,.0f} = {total:,.0f} FC",
                                        size=12,
                                    ),
                                    ft.Text(
                                        f"Motif: {reason[:50]}",
                                        size=11,
                                        color=ft.Colors.GREY_700,
                                    ),
                                ],
                            ),
                        ),
                    )
                )

        # SECTION DÉPENSES
        if has_expenses:
            if has_daily_sales or has_returns:
                self.details_section.controls.append(ft.Divider(height=20))
            
            self.details_section.controls.append(
                ft.Container(
                    padding=ft.Padding.only(left=4, right=4, bottom=4),
                    content=ft.Text(
                        "Dépenses",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.BLUE_GREY_900,
                    ),
                )
            )

            # Grouper par catégorie
            expenses_by_cat = {}
            for expense in expenses:
                amount = self._safe_number(expense[3] if len(expense) > 3 else 0)
                if amount <= 0:
                    continue
                category = expense[4] if len(expense) > 4 and expense[4] else "Non catégorisé"
                
                if category not in expenses_by_cat:
                    expenses_by_cat[category] = {'count': 0, 'amount': 0}
                expenses_by_cat[category]['count'] += 1
                expenses_by_cat[category]['amount'] += amount

            for category, data in expenses_by_cat.items():
                self.details_section.controls.append(
                    ft.Card(
                        margin=ft.Margin.symmetric(horizontal=2, vertical=4),
                        content=ft.Container(
                            padding=12,
                            content=ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                controls=[
                                    ft.Column(
                                        expand=True,
                                        spacing=4,
                                        controls=[
                                            ft.Text(
                                                category,
                                                size=14,
                                                weight=ft.FontWeight.BOLD,
                                                color=ft.Colors.BLUE_GREY_900,
                                            ),
                                            ft.Text(
                                                f"{data['count']} dépense(s)",
                                                size=12,
                                                color=ft.Colors.GREY_700,
                                            ),
                                        ],
                                    ),
                                    ft.Text(
                                        self._format_amount(data['amount']),
                                        size=16,
                                        weight=ft.FontWeight.BOLD,
                                        color=ft.Colors.RED_700,
                                    ),
                                ],
                            ),
                        ),
                    )
                )

        if not has_daily_sales and not has_expenses and not has_returns:
            self.details_section.controls.append(
                ft.Container(
                    padding=30,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=12,
                        controls=[
                            ft.Icon(ft.Icons.ANALYTICS, size=72, color=ft.Colors.GREY_400),
                            ft.Text(
                                "Aucune donnée sur cette période",
                                size=16,
                                color=ft.Colors.GREY_700,
                            ),
                        ],
                    ),
                )
            )

    # =========================================================
    # FILTRES
    # =========================================================
    def filter_today(self):
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        end_today = today + timedelta(days=1) - timedelta(microseconds=1)
        self.load_report(today, end_today)

    def filter_week(self):
        today = datetime.now()
        start_of_week = today - timedelta(days=today.weekday())
        start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_week = start_of_week + timedelta(days=7) - timedelta(microseconds=1)
        self.load_report(start_of_week, end_of_week)

    def filter_month(self):
        today = datetime.now()
        start_of_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        if today.month == 12:
            next_month = today.replace(year=today.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            next_month = today.replace(month=today.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)

        end_of_month = next_month - timedelta(microseconds=1)
        self.load_report(start_of_month, end_of_month)

    def show_custom_filter(self, e):
        self.start_date_text = ft.Text("Date de début : non choisie", color=ft.Colors.GREY_700)
        self.end_date_text = ft.Text("Date de fin : non choisie", color=ft.Colors.GREY_700)

        def on_start_change(evt):
            if self.start_date_text:
                value = evt.control.value
                self.start_date_text.value = (
                    f"Date de début : {value.strftime('%d/%m/%Y')}"
                    if value
                    else "Date de début : non choisie"
                )
                self.page.update()

        def on_end_change(evt):
            if self.end_date_text:
                value = evt.control.value
                self.end_date_text.value = (
                    f"Date de fin : {value.strftime('%d/%m/%Y')}"
                    if value
                    else "Date de fin : non choisie"
                )
                self.page.update()

        self.start_date_picker = ft.DatePicker(
            first_date=datetime(2020, 1, 1),
            last_date=datetime.now(),
            on_change=on_start_change,
        )
        self.end_date_picker = ft.DatePicker(
            first_date=datetime(2020, 1, 1),
            last_date=datetime.now(),
            on_change=on_end_change,
        )

        def apply_filter(ev):
            start_value = self.start_date_picker.value if self.start_date_picker else None
            end_value = self.end_date_picker.value if self.end_date_picker else None

            if not start_value or not end_value:
                self._show_snackbar("Choisis d'abord les deux dates", ft.Colors.RED)
                return

            start_date = datetime(
                start_value.year, start_value.month, start_value.day, 0, 0, 0, 0
            )
            end_date = datetime(
                end_value.year, end_value.month, end_value.day, 23, 59, 59, 999999
            )

            if end_date < start_date:
                self._show_snackbar("La date de fin doit être après la date de début", ft.Colors.RED)
                return

            dialog.open = False
            self.page.update()
            self.load_report(start_date, end_date)

        dialog = ft.AlertDialog(
            title=ft.Text("Filtrer par période personnalisée"),
            content=ft.Column(
                tight=True,
                spacing=12,
                controls=[
                    self.start_date_text,
                    ft.Button(
                        "Choisir la date de début",
                        icon=ft.Icons.CALENDAR_TODAY,
                        on_click=lambda ev: self.page.open(self.start_date_picker),
                    ),
                    self.end_date_text,
                    ft.Button(
                        "Choisir la date de fin",
                        icon=ft.Icons.CALENDAR_TODAY,
                        on_click=lambda ev: self.page.open(self.end_date_picker),
                    ),
                ],
            ),
            actions=[
                ft.TextButton(
                    "Annuler",
                    on_click=lambda ev: self._close_dialog(dialog),
                ),
                ft.Button(
                    "Appliquer",
                    on_click=apply_filter,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        self.page.dialog = dialog
        dialog.open = True
        self.page.update()

    def _close_dialog(self, dialog: ft.AlertDialog):
        dialog.open = False
        self.page.update()

    # =========================================================
    # AFFICHAGE PRINCIPAL
    # =========================================================
    def show(self):
        self.page.clean()
        self.page.padding = 0
        self.page.bgcolor = ft.Colors.GREY_100
        self.page.scroll = ft.ScrollMode.AUTO

        self.period_text = ft.Text(
            "Période : Aujourd'hui",
            size=14,
            color=ft.Colors.GREY_700,
        )

        self.summary_grid = ft.GridView(
            expand=False,
            runs_count=2,
            max_extent=220,
            child_aspect_ratio=1.15,
            spacing=10,
            run_spacing=10,
            padding=10,
        )

        self.details_section = ft.Column(
            spacing=10,
            expand=False,
        )

        # Indicateur de connexion
        connection_indicator = self.create_connection_indicator()

        content = ft.SafeArea(
            expand=True,
            content=ft.Column(
                expand=True,
                spacing=0,
                controls=[
                    self._build_header(),
                    ft.Container(
                        padding=ft.Padding.symmetric(horizontal=12, vertical=5),
                        content=ft.Row(
                            alignment=ft.MainAxisAlignment.END,
                            controls=[connection_indicator],
                        ),
                    ),
                    ft.Container(
                        padding=10,
                        content=self._build_quick_filters(),
                    ),
                    ft.Container(
                        padding=ft.Padding.only(left=12, right=12, bottom=8),
                        content=self.period_text,
                    ),
                    self.summary_grid,
                    ft.Divider(height=1),
                    ft.Container(
                        padding=ft.Padding.only(left=12, right=12, top=10, bottom=6),
                        content=ft.Text(
                            "Détail des transactions",
                            size=18,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.BLUE_GREY_900,
                        ),
                    ),
                    ft.Container(
                        expand=True,
                        padding=ft.Padding.only(left=8, right=8, bottom=12),
                        content=ft.Column(
                            expand=True,
                            scroll=ft.ScrollMode.AUTO,
                            controls=[self.details_section],
                        ),
                    ),
                ],
            ),
        )

        self.page.add(content)
        self._is_header_initialized = True
        self.filter_today()
        self.page.update()

    def _build_header(self) -> ft.Container:
        return ft.Container(
            bgcolor=ft.Colors.BLUE_700,
            padding=ft.Padding.symmetric(horizontal=8, vertical=10),
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.IconButton(
                        icon=ft.Icons.ARROW_BACK,
                        on_click=lambda e: self.go_back(),
                        icon_color=ft.Colors.WHITE,
                        tooltip="Retour",
                    ),
                    ft.Text(
                        "Rapport de trésorerie",
                        expand=True,
                        size=22,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.WHITE,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.PICTURE_AS_PDF,
                        on_click=self.open_export_screen,
                        tooltip="Exporter PDF",
                        icon_color=ft.Colors.WHITE,
                    ),
                ],
            ),
        )

    def _quick_button(self, label: str, on_click, selected: bool = False) -> ft.Button:
        return ft.Button(
            content=ft.Text(label, size=13, weight=ft.FontWeight.W_500),
            on_click=on_click,
            style=ft.ButtonStyle(
                padding=ft.Padding.symmetric(horizontal=14, vertical=10),
                shape=ft.RoundedRectangleBorder(radius=18),
                bgcolor=ft.Colors.BLUE_700 if selected else ft.Colors.WHITE,
                color=ft.Colors.WHITE if selected else ft.Colors.BLUE_700,
                side=ft.BorderSide(
                    1,
                    ft.Colors.BLUE_700 if selected else ft.Colors.BLUE_100,
                ),
            ),
        )

    def _build_quick_filters(self) -> ft.Row:
        return ft.Row(
            wrap=True,
            spacing=8,
            run_spacing=8,
            controls=[
                self._quick_button("Aujourd'hui", lambda e: self.filter_today(), selected=True),
                self._quick_button("Cette semaine", lambda e: self.filter_week()),
                self._quick_button("Ce mois", lambda e: self.filter_month()),
                self._quick_button("Personnalisé", self.show_custom_filter),
            ],
        )

    # =========================================================
    # EXPORT PDF
    # =========================================================
    def open_export_screen(self, e):
        """Ouvre l'écran d'export PDF séparé"""
        if not self.start_date or not self.end_date:
            self._show_snackbar("Aucune période sélectionnée", ft.Colors.RED)
            return

        export_screen = ExportCashScreen(
            self.page,
            self.db,
            self.start_date,
            self.end_date,
            self._branch_id(),
            self._branch_name(),
            self.current_user
        )
        export_screen.show()

    # =========================================================
    # NAVIGATION
    # =========================================================
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


class ExportCashScreen:
    """Écran d'export PDF du rapport de trésorerie"""
    
    def __init__(self, page: ft.Page, db, start_date: datetime, end_date: datetime, branch_id, branch_name, current_user):
        self.page = page
        self.db = db
        self.start_date = start_date
        self.end_date = end_date
        self.branch_id = branch_id
        self.branch_name = branch_name
        self.current_user = current_user
        
        self.is_generating = False
        self.progress_ring = None
        self.status_text = None
        
    def _safe_number(self, value, default: float = 0.0) -> float:
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def _format_amount(self, value) -> str:
        amount = self._safe_number(value, 0)
        return f"{amount:,.0f} FC"

    def show(self):
        self.page.clean()
        self.page.padding = 0
        self.page.bgcolor = ft.Colors.GREY_100
        self.page.title = "Export PDF - Rapport de trésorerie"
        
        # En-tête
        header = ft.Container(
            bgcolor=ft.Colors.BLUE_700,
            padding=ft.Padding.symmetric(horizontal=8, vertical=10),
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.IconButton(
                        icon=ft.Icons.ARROW_BACK,
                        on_click=lambda e: self.go_back(),
                        icon_color=ft.Colors.WHITE,
                        tooltip="Retour",
                    ),
                    ft.Text(
                        "Export PDF - Rapport de trésorerie",
                        expand=True,
                        size=20,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.WHITE,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.DOWNLOAD,
                        on_click=self.generate_and_download_pdf,
                        icon_color=ft.Colors.WHITE,
                        tooltip="Télécharger PDF",
                    ),
                ],
            ),
        )
        
        # Zone d'aperçu du rapport
        self.preview_text = ft.TextField(
            multiline=True,
            min_lines=20,
            max_lines=30,
            read_only=True,
            expand=True,
            label="Aperçu du rapport",
        )
        
        # Zone de progression
        self.progress_ring = ft.ProgressRing(visible=False)
        self.status_text = ft.Text("", size=12, color=ft.Colors.GREY_700)
        
        progress_row = ft.Row(
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=10,
            controls=[self.progress_ring, self.status_text],
            visible=False,
        )
        
        # Informations sur le rapport
        info_card = ft.Card(
            margin=ft.Margin.all(10),
            content=ft.Container(
                padding=15,
                content=ft.Column(
                    spacing=8,
                    controls=[
                        ft.Text("Informations du rapport", size=16, weight=ft.FontWeight.BOLD),
                        ft.Text(f"Période : du {self.start_date.strftime('%d/%m/%Y %H:%M')} au {self.end_date.strftime('%d/%m/%Y %H:%M')}"),
                        ft.Text(f"Succursale : {self.branch_name}"),
                        ft.Text(f"Généré le : {datetime.now().strftime('%d/%m/%Y à %H:%M:%S')}"),
                    ],
                ),
            ),
        )
        
        # Boutons d'action
        action_row = ft.Row(
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=20,
            controls=[
                ft.Button(
                    "Générer l'aperçu",
                    icon=ft.Icons.PREVIEW,
                    on_click=self.generate_preview,
                    style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE),
                ),
                ft.Button(
                    "Télécharger PDF",
                    icon=ft.Icons.DOWNLOAD,
                    on_click=self.generate_and_download_pdf,
                    style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE),
                ),
            ],
        )
        
        content = ft.Column(
            expand=True,
            controls=[
                header,
                info_card,
                ft.Container(
                    expand=True,
                    padding=10,
                    content=self.preview_text,
                ),
                progress_row,
                ft.Container(
                    padding=10,
                    content=action_row,
                ),
            ],
        )
        
        self.page.add(content)
        self.page.update()
        
        # Générer automatiquement l'aperçu
        self.generate_preview(None)
    
    def get_report_data(self):
        """Récupère toutes les données pour le rapport"""
        branch_id_str = str(self.branch_id) if self.branch_id is not None else None
        
        print(f"DEBUG get_report_data: branch_id = {self.branch_id} (type: {type(self.branch_id)})")
        print(f"DEBUG get_report_data: branch_id_str = {branch_id_str}")
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Vérifier si la table returns_history existe
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='returns_history'")
            returns_table_exists = cursor.fetchone() is not None
            
            # ========== VENTES ==========
            if branch_id_str:
                cursor.execute(
                    """
                    SELECT 
                        id,
                        sale_date, 
                        product_name, 
                        quantity, 
                        unit_price, 
                        total_price, 
                        customer_name, 
                        invoice_number
                    FROM sales
                    WHERE sale_date BETWEEN ? AND ?
                    AND branch_id = ?
                    ORDER BY sale_date DESC
                    """,
                    (self.start_date.isoformat(), self.end_date.isoformat(), branch_id_str),
                )
            else:
                cursor.execute(
                    """
                    SELECT 
                        id,
                        sale_date, 
                        product_name, 
                        quantity, 
                        unit_price, 
                        total_price, 
                        customer_name, 
                        invoice_number
                    FROM sales
                    WHERE sale_date BETWEEN ? AND ?
                    ORDER BY sale_date DESC
                    """,
                    (self.start_date.isoformat(), self.end_date.isoformat()),
                )
            sales = cursor.fetchall()
            print(f"DEBUG get_report_data: sales count = {len(sales) if sales else 0}")
            
            # ========== DÉPENSES ==========
            if branch_id_str:
                cursor.execute(
                    """
                    SELECT 
                        id,
                        expense_date, 
                        description, 
                        amount, 
                        category
                    FROM expenses
                    WHERE expense_date BETWEEN ? AND ?
                    AND branch_id = ?
                    ORDER BY expense_date DESC
                    """,
                    (self.start_date.isoformat(), self.end_date.isoformat(), branch_id_str),
                )
            else:
                cursor.execute(
                    """
                    SELECT 
                        id,
                        expense_date, 
                        description, 
                        amount, 
                        category
                    FROM expenses
                    WHERE expense_date BETWEEN ? AND ?
                    ORDER BY expense_date DESC
                    """,
                    (self.start_date.isoformat(), self.end_date.isoformat()),
                )
            expenses = cursor.fetchall()
            print(f"DEBUG get_report_data: expenses count = {len(expenses) if expenses else 0}")
            
            # ========== RETOURS ET ÉCHANGES ==========
            returns_exchanges = []
            if returns_table_exists:
                if branch_id_str:
                    cursor.execute(
                        """
                        SELECT 
                            id,
                            return_date, 
                            product_name, 
                            quantity, 
                            total_price, 
                            return_type, 
                            reason, 
                            exchange_product_name
                        FROM returns_history
                        WHERE return_date BETWEEN ? AND ?
                        AND branch_id = ?
                        ORDER BY return_date DESC
                        """,
                        (self.start_date.isoformat(), self.end_date.isoformat(), branch_id_str),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT 
                            id,
                            return_date, 
                            product_name, 
                            quantity, 
                            total_price, 
                            return_type, 
                            reason, 
                            exchange_product_name
                        FROM returns_history
                        WHERE return_date BETWEEN ? AND ?
                        ORDER BY return_date DESC
                        """,
                        (self.start_date.isoformat(), self.end_date.isoformat()),
                    )
                returns_exchanges = cursor.fetchall()
                print(f"DEBUG get_report_data: returns_exchanges count = {len(returns_exchanges) if returns_exchanges else 0}")
            else:
                print("DEBUG get_report_data: La table returns_history n'existe pas")
            
            return {
                'sales': sales,
                'expenses': expenses,
                'returns_exchanges': returns_exchanges
            }
    
    def generate_preview(self, e):
        """Génère l'aperçu texte du rapport"""
        data = self.get_report_data()
        report_content = self.format_report_text(data)
        self.preview_text.value = report_content
        self.page.update()
    
    def format_report_text(self, data):
        """Formate le rapport en texte"""
        sales = data['sales']
        expenses = data['expenses']
        returns_exchanges = data['returns_exchanges']
        
        # CORRECTION: Utiliser les bons indices pour accéder aux colonnes
        # Pour sales: index 0=id, 1=sale_date, 2=product_name, 3=quantity, 4=unit_price, 5=total_price, 6=customer_name, 7=invoice_number
        total_sales = 0
        for sale in sales:
            # total_price est à l'index 5
            total_sales += self._safe_number(sale[5] if len(sale) > 5 else 0)
        
        # Pour expenses: index 0=id, 1=expense_date, 2=description, 3=amount, 4=category
        total_expenses = 0
        for expense in expenses:
            # amount est à l'index 3
            total_expenses += self._safe_number(expense[3] if len(expense) > 3 else 0)
        
        # Pour returns_exchanges: index 0=id, 1=return_date, 2=product_name, 3=quantity, 4=total_price, 5=return_type, 6=reason, 7=exchange_product_name
        total_returns = 0
        total_exchanges = 0
        for ret_ex in returns_exchanges:
            value = self._safe_number(ret_ex[4] if len(ret_ex) > 4 else 0)  # total_price à l'index 4
            return_type = ret_ex[5] if len(ret_ex) > 5 else ''  # return_type à l'index 5
            if return_type == 'return':
                total_returns += value
            else:
                total_exchanges += value
        
        report = f"""RAPPORT DE TRÉSORERIE
=====================

Période : du {self.start_date.strftime('%d/%m/%Y %H:%M')} au {self.end_date.strftime('%d/%m/%Y %H:%M')}
Succursale : {self.branch_name}
Généré le : {datetime.now().strftime('%d/%m/%Y à %H:%M:%S')}

RÉSUMÉ
-------
Total des ventes : {self._format_amount(total_sales)}
Total des dépenses : {self._format_amount(total_expenses)}
Total des retours : {self._format_amount(total_returns)}
Total des échanges : {self._format_amount(total_exchanges)}
Nombre de transactions : {len(sales)}

DÉTAIL DES VENTES
-----------------
"""
        for sale in sales:
            try:
                sale_date = sale[1]  # sale_date à l'index 1
                if sale_date:
                    if isinstance(sale_date, str):
                        sale_date = datetime.fromisoformat(sale_date).strftime("%d/%m/%Y %H:%M")
                    else:
                        sale_date = sale_date.strftime("%d/%m/%Y %H:%M")
                else:
                    sale_date = "N/A"
            except:
                sale_date = "N/A"
            
            product_name = sale[2] if len(sale) > 2 and sale[2] else "Produit"  # product_name à l'index 2
            quantity = self._safe_number(sale[3] if len(sale) > 3 else 0)  # quantity à l'index 3
            unit_price = self._safe_number(sale[4] if len(sale) > 4 else 0)  # unit_price à l'index 4
            total = self._safe_number(sale[5] if len(sale) > 5 else 0)  # total_price à l'index 5
            customer = sale[6] if len(sale) > 6 and sale[6] else "Client"  # customer_name à l'index 6
            
            report += f"\n{sale_date} - {customer} - {product_name}: {quantity:,.0f} x {unit_price:,.0f} = {total:,.0f} FC"
        
        report += "\n\nDÉTAIL DES DÉPENSES\n-----------------\n"
        
        for expense in expenses:
            try:
                expense_date = expense[1]  # expense_date à l'index 1
                if expense_date:
                    if isinstance(expense_date, str):
                        expense_date = datetime.fromisoformat(expense_date).strftime("%d/%m/%Y")
                    else:
                        expense_date = expense_date.strftime("%d/%m/%Y")
                else:
                    expense_date = "N/A"
            except:
                expense_date = "N/A"
            
            description = expense[2] if len(expense) > 2 and expense[2] else "Sans description"  # description à l'index 2
            amount = self._safe_number(expense[3] if len(expense) > 3 else 0)  # amount à l'index 3
            category = expense[4] if len(expense) > 4 and expense[4] else "Non catégorisé"  # category à l'index 4
            
            report += f"\n{expense_date} - {description} ({category}) - {amount:,.0f} FC"
        
        report += "\n\nDÉTAIL DES RETOURS ET ÉCHANGES\n-----------------------------\n"
        
        for ret_ex in returns_exchanges:
            try:
                return_date = ret_ex[1]  # return_date à l'index 1
                if return_date:
                    if isinstance(return_date, str):
                        return_date = datetime.fromisoformat(return_date).strftime("%d/%m/%Y")
                    else:
                        return_date = return_date.strftime("%d/%m/%Y")
                else:
                    return_date = "N/A"
            except:
                return_date = "N/A"
            
            product_name = ret_ex[2] if len(ret_ex) > 2 and ret_ex[2] else "Produit"  # product_name à l'index 2
            quantity = self._safe_number(ret_ex[3] if len(ret_ex) > 3 else 0)  # quantity à l'index 3
            total = self._safe_number(ret_ex[4] if len(ret_ex) > 4 else 0)  # total_price à l'index 4
            return_type = "RETOUR" if (len(ret_ex) > 5 and ret_ex[5] == 'return') else "ÉCHANGE"  # return_type à l'index 5
            reason = ret_ex[6] if len(ret_ex) > 6 and ret_ex[6] else "Non spécifié"  # reason à l'index 6
            exchange_product = ret_ex[7] if len(ret_ex) > 7 and ret_ex[7] else ""  # exchange_product_name à l'index 7
            
            if return_type == "RETOUR":
                report += f"\n{return_date} - {return_type}: {product_name} x{quantity:,.0f} = {total:,.0f} FC (Motif: {reason})"
            else:
                report += f"\n{return_date} - {return_type}: {product_name} → {exchange_product} x{quantity:,.0f} (Valeur: {total:,.0f} FC, Motif: {reason})"
        
        if not returns_exchanges:
            report += "\nAucun retour ou échange sur cette période."
        
        return report
    
    def generate_and_download_pdf(self, e):
        """Génère et télécharge le fichier PDF"""
        if self.is_generating:
            return
        
        self.is_generating = True
        self.progress_ring.visible = True
        self.status_text.value = "Génération du PDF en cours..."
        # Trouver la ligne de progression
        for control in self.page.controls:
            if isinstance(control, ft.Row) and control.controls and self.progress_ring in control.controls:
                control.visible = True
                break
        self.page.update()
        
        try:
            # Générer le PDF
            pdf_bytes = self.create_pdf()
            
            # Sauvegarder le fichier
            filename = f"rapport_tresorerie_{self.start_date.strftime('%Y%m%d')}_{self.end_date.strftime('%Y%m%d')}.pdf"
            
            # Ouvrir le dialogue de sauvegarde
            self.save_file_dialog(pdf_bytes, filename)
            
            self.status_text.value = "PDF généré avec succès !"
            self.page.update()
            
        except Exception as ex:
            self.status_text.value = f"Erreur: {str(ex)}"
            self._show_snackbar(f"Erreur lors de la génération: {str(ex)}", ft.Colors.RED)
            import traceback
            traceback.print_exc()
        finally:
            self.is_generating = False
            # Cacher la progression
            for control in self.page.controls:
                if isinstance(control, ft.Row) and control.controls and self.progress_ring in control.controls:
                    control.visible = False
                    break
            self.page.update()
    
    def create_pdf(self):
        """Crée le fichier PDF avec ReportLab"""
        buffer = io.BytesIO()
        
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=15*mm, leftMargin=15*mm, topMargin=20*mm, bottomMargin=15*mm)
        
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], fontSize=16, alignment=TA_CENTER, spaceAfter=20)
        heading_style = ParagraphStyle('CustomHeading', parent=styles['Heading2'], fontSize=12, textColor=colors.HexColor('#1976D2'), spaceAfter=10, spaceBefore=15)
        normal_style = styles['Normal']
        normal_style.fontSize = 9
        
        story = []
        
        # Titre
        story.append(Paragraph("RAPPORT DE TRÉSORERIE", title_style))
        story.append(Spacer(1, 5*mm))
        
        # Informations générales
        info_data = [
            [f"Période: du {self.start_date.strftime('%d/%m/%Y %H:%M')} au {self.end_date.strftime('%d/%m/%Y %H:%M')}"],
            [f"Succursale: {self.branch_name}"],
            [f"Date de génération: {datetime.now().strftime('%d/%m/%Y à %H:%M:%S')}"],
        ]
        info_table = Table(info_data, colWidths=[160*mm])
        info_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        story.append(info_table)
        story.append(Spacer(1, 8*mm))
        
        # Récupérer les données
        data = self.get_report_data()
        sales = data['sales']
        expenses = data['expenses']
        returns_exchanges = data['returns_exchanges']
        
        # Calcul des totaux avec les bons indices
        total_sales = 0
        for sale in sales:
            total_sales += self._safe_number(sale[5] if len(sale) > 5 else 0)
        
        total_expenses = 0
        for expense in expenses:
            total_expenses += self._safe_number(expense[3] if len(expense) > 3 else 0)
        
        total_returns = 0
        total_exchanges = 0
        for ret_ex in returns_exchanges:
            value = self._safe_number(ret_ex[4] if len(ret_ex) > 4 else 0)
            return_type = ret_ex[5] if len(ret_ex) > 5 else ''
            if return_type == 'return':
                total_returns += value
            else:
                total_exchanges += value
        
        # Tableau récapitulatif
        story.append(Paragraph("RÉSUMÉ", heading_style))
        summary_data = [
            ["Total des ventes", f"{total_sales:,.0f} FC"],
            ["Total des dépenses", f"{total_expenses:,.0f} FC"],
            ["Total des retours", f"{total_returns:,.0f} FC"],
            ["Total des échanges", f"{total_exchanges:,.0f} FC"],
            ["Nombre de transactions", str(len(sales))],
        ]
        summary_table = Table(summary_data, colWidths=[100*mm, 50*mm])
        summary_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(summary_table)
        story.append(Spacer(1, 8*mm))
        
        # Détail des ventes
        story.append(Paragraph("DÉTAIL DES VENTES", heading_style))
        if sales and len(sales) > 0:
            sales_table_data = [["Date", "Client", "Produit", "Qté", "Prix unit.", "Total"]]
            for sale in sales[:50]:
                try:
                    sale_date = sale[1]  # sale_date
                    if sale_date:
                        if isinstance(sale_date, str):
                            sale_date = datetime.fromisoformat(sale_date).strftime("%d/%m/%Y")
                        else:
                            sale_date = sale_date.strftime("%d/%m/%Y")
                    else:
                        sale_date = "N/A"
                except:
                    sale_date = "N/A"
                
                sales_table_data.append([
                    sale_date,
                    (sale[6] or "Client")[:20] if len(sale) > 6 else "Client",
                    (sale[2] or "Produit")[:25] if len(sale) > 2 else "Produit",
                    f"{self._safe_number(sale[3] if len(sale) > 3 else 0):,.0f}",
                    f"{self._safe_number(sale[4] if len(sale) > 4 else 0):,.0f}",
                    f"{self._safe_number(sale[5] if len(sale) > 5 else 0):,.0f}"
                ])
            
            if len(sales) > 50:
                sales_table_data.append(["", "", f"... et {len(sales) - 50} autres transactions", "", "", ""])
            
            sales_table = Table(sales_table_data, colWidths=[30*mm, 35*mm, 40*mm, 15*mm, 25*mm, 25*mm])
            sales_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1976D2')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ('ALIGN', (3, 1), (5, -1), 'RIGHT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            story.append(sales_table)
        else:
            story.append(Paragraph("Aucune vente sur cette période.", normal_style))
        
        story.append(Spacer(1, 8*mm))
        
        # Détail des dépenses
        story.append(Paragraph("DÉTAIL DES DÉPENSES", heading_style))
        if expenses and len(expenses) > 0:
            expenses_table_data = [["Date", "Description", "Catégorie", "Montant"]]
            for expense in expenses:
                try:
                    expense_date = expense[1]  # expense_date
                    if expense_date:
                        if isinstance(expense_date, str):
                            expense_date = datetime.fromisoformat(expense_date).strftime("%d/%m/%Y")
                        else:
                            expense_date = expense_date.strftime("%d/%m/%Y")
                    else:
                        expense_date = "N/A"
                except:
                    expense_date = "N/A"
                
                expenses_table_data.append([
                    expense_date,
                    (expense[2] or "Sans description")[:35] if len(expense) > 2 else "Sans description",
                    (expense[4] or "Non catégorisé")[:20] if len(expense) > 4 else "Non catégorisé",
                    f"{self._safe_number(expense[3] if len(expense) > 3 else 0):,.0f} FC"
                ])
            
            expenses_table = Table(expenses_table_data, colWidths=[25*mm, 60*mm, 30*mm, 35*mm])
            expenses_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#d32f2f')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ('ALIGN', (3, 1), (3, -1), 'RIGHT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            story.append(expenses_table)
        else:
            story.append(Paragraph("Aucune dépense sur cette période.", normal_style))
        
        story.append(Spacer(1, 8*mm))
        
        # Détail des retours et échanges
        story.append(Paragraph("DÉTAIL DES RETOURS ET ÉCHANGES", heading_style))
        if returns_exchanges and len(returns_exchanges) > 0:
            returns_table_data = [["Date", "Type", "Produit", "Qté", "Montant", "Motif"]]
            for ret_ex in returns_exchanges:
                try:
                    return_date = ret_ex[1]  # return_date
                    if return_date:
                        if isinstance(return_date, str):
                            return_date = datetime.fromisoformat(return_date).strftime("%d/%m/%Y")
                        else:
                            return_date = return_date.strftime("%d/%m/%Y")
                    else:
                        return_date = "N/A"
                except:
                    return_date = "N/A"
                
                return_type = "RETOUR" if (len(ret_ex) > 5 and ret_ex[5] == 'return') else "ÉCHANGE"
                product = ret_ex[2] if len(ret_ex) > 2 and ret_ex[2] else "Produit"
                if return_type == "ÉCHANGE" and len(ret_ex) > 7 and ret_ex[7]:
                    product = f"{product} → {ret_ex[7]}"
                
                returns_table_data.append([
                    return_date,
                    return_type,
                    product[:30],
                    f"{self._safe_number(ret_ex[3] if len(ret_ex) > 3 else 0):,.0f}",
                    f"{self._safe_number(ret_ex[4] if len(ret_ex) > 4 else 0):,.0f} FC",
                    (ret_ex[6] if len(ret_ex) > 6 and ret_ex[6] else "-")[:25]
                ])
            
            returns_table = Table(returns_table_data, colWidths=[25*mm, 20*mm, 45*mm, 15*mm, 25*mm, 30*mm])
            returns_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#9c27b0')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ('ALIGN', (3, 1), (4, -1), 'RIGHT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            story.append(returns_table)
        else:
            story.append(Paragraph("Aucun retour ou échange sur cette période.", normal_style))
        
        doc.build(story)
        buffer.seek(0)
        return buffer.getvalue()
    
    def save_file_dialog(self, file_bytes: bytes, filename: str):
        """Ouvre un dialogue pour sauvegarder le fichier sur Android"""
        try:
            # Méthode 1: Utiliser la boîte de dialogue de partage Android
            from flet import FilePicker, FilePickerResultEvent
            
            file_picker = ft.FilePicker()
            
            def on_file_picked(e: ft.FilePickerResultEvent):
                if e.path:
                    try:
                        with open(e.path, "wb") as f:
                            f.write(file_bytes)
                        self._show_snackbar(f"PDF sauvegardé : {e.path}", ft.Colors.GREEN)
                    except Exception as ex:
                        self._show_snackbar(f"Erreur: {str(ex)}", ft.Colors.RED)
            
            file_picker.on_result = on_file_picked
            self.page.overlay.append(file_picker)
            self.page.update()
            
            # Sauvegarder le fichier
            file_picker.save_file(file_name=filename)
            
        except Exception as e:
            # Fallback: Sauvegarde directe dans le répertoire de l'application
            self.save_file_directly(file_bytes, filename)

    def save_file_directly(self, file_bytes: bytes, filename: str):
        """Sauvegarde directement le fichier dans le répertoire de l'application"""
        try:
            import os
            from pathlib import Path
            
            # Obtenir le répertoire de l'application
            if hasattr(self.page, 'get_platform') and self.page.get_platform() == "android":
                # Sur Android, utiliser le répertoire de l'application
                download_dir = str(Path.home() / "Downloads")
                if not os.path.exists(download_dir):
                    download_dir = str(Path.home() / "Documents")
            else:
                # Sur desktop, utiliser le répertoire Téléchargements
                download_dir = str(Path.home() / "Downloads")
            
            # Créer le répertoire s'il n'existe pas
            os.makedirs(download_dir, exist_ok=True)
            
            # Chemin complet du fichier
            file_path = os.path.join(download_dir, filename)
            
            # Sauvegarder le fichier
            with open(file_path, "wb") as f:
                f.write(file_bytes)
            
            self._show_snackbar(f"PDF sauvegardé dans: {file_path}", ft.Colors.GREEN)
            
        except Exception as ex:
            self._show_snackbar(f"Erreur sauvegarde: {str(ex)}", ft.Colors.RED)

    def _save_pdf_file(self, e: ft.FilePickerResultEvent, file_bytes: bytes):
        """Sauvegarde le fichier PDF"""
        if e.path:
            try:
                with open(e.path, "wb") as f:
                    f.write(file_bytes)
                self._show_snackbar(f"PDF sauvegardé : {e.path}", ft.Colors.GREEN)
            except Exception as ex:
                self._show_snackbar(f"Erreur lors de la sauvegarde: {str(ex)}", ft.Colors.RED)
    
    def _on_file_saved(self, e: ft.FilePickerResultEvent, file_bytes: bytes):
        """Callback après la sauvegarde du fichier"""
        if e.path:
            try:
                with open(e.path, "wb") as f:
                    f.write(file_bytes)
                self._show_snackbar(f"PDF sauvegardé : {e.path}", ft.Colors.GREEN)
            except Exception as ex:
                self._show_snackbar(f"Erreur lors de la sauvegarde: {str(ex)}", ft.Colors.RED)
    
    def _show_snackbar(self, message: str, color=ft.Colors.BLUE) -> None:
        self.page.snack_bar = ft.SnackBar(
            content=ft.Text(message, color=ft.Colors.WHITE),
            bgcolor=color,
            open=True,
        )
        self.page.update()
    
    def go_back(self):
        """Retour à l'écran du rapport de trésorerie"""
        cash_report = CashReportScreen(
            self.page,
            self.db,
            None,  # sync_service
            None,  # auth_service
            self.current_user,
        )
        cash_report.show()