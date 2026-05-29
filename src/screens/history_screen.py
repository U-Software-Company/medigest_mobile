import flet as ft
from datetime import datetime, timedelta
import sqlite3

class HistoryScreen:
    def __init__(self, page: ft.Page, db, sync_service, auth_service, current_user):
        self.page = page
        self.db = db
        self.sync_service = sync_service
        self.auth_service = auth_service
        self.current_user = current_user
        self.start_date = None
        self.end_date = None
        self.history_list_view = None
    
    def show_snackbar(self, message: str, color: str):
        """Afficher une snackbar"""
        snack = ft.SnackBar(content=ft.Text(message), bgcolor=color)
        self.page.snack_bar = snack
        snack.open = True
        self.page.update()
    
    def show(self):
        self.page.clean()
        
        # Header - CORRIGÉ
        header = ft.Container(
            content=ft.Row([
                ft.IconButton(icon=ft.Icons.ARROW_BACK, on_click=lambda e: self.go_back(), icon_color=ft.Colors.WHITE),
                ft.Text("Historique des ventes", size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                ft.IconButton(icon=ft.Icons.FILTER_LIST, on_click=self.show_filter_dialog, tooltip="Filtrer", icon_color=ft.Colors.WHITE),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=10,
            bgcolor=ft.Colors.BLUE_700,
        )
        
        # Filtres rapides
        quick_filters = ft.Row([
            ft.Button("Aujourd'hui", on_click=lambda e: self.filter_today(), style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_200)),
            ft.Button("Cette semaine", on_click=lambda e: self.filter_week(), style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_200)),
            ft.Button("Ce mois", on_click=lambda e: self.filter_month(), style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_200)),
        ], alignment=ft.MainAxisAlignment.SPACE_AROUND)
        
        # Période sélectionnée
        self.period_text = ft.Text("Période: Aujourd'hui", size=12, color=ft.Colors.GREY_600)
        
        # Résumé - CORRIGÉ : mise à jour dynamique
        self.total_sales_text = ft.Text("0 FC", size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_700)
        self.transaction_count_text = ft.Text("0", size=14, weight=ft.FontWeight.BOLD)
        
        self.summary_card = ft.Container(
            content=ft.Column([
                ft.Text("Résumé", size=16, weight=ft.FontWeight.BOLD),
                ft.Row([
                    ft.Text("Total ventes:", size=14),
                    self.total_sales_text,
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([
                    ft.Text("Nombre de transactions:", size=14),
                    self.transaction_count_text,
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ]),
            padding=10,
            bgcolor=ft.Colors.GREY_100,
            border_radius=10,
            margin=10,
        )
        
        # Liste de l'historique
        self.history_list_view = ft.ListView(expand=True, spacing=10, padding=10)
        
        # Charger l'historique par défaut (aujourd'hui)
        self.filter_today()
        
        # Layout principal
        main_content = ft.Column([
            header,
            quick_filters,
            self.period_text,
            self.summary_card,
            ft.Text("Transactions", size=16, weight=ft.FontWeight.BOLD),
            ft.Container(height=5),
            self.history_list_view,
        ], expand=True, spacing=10)
        
        self.page.add(main_content)
        self.page.update()
    
    def load_history(self, start_date=None, end_date=None):
        """Charger l'historique des ventes"""
        branch_id = self.current_user.get('active_branch_id') or self.current_user.get('branch_id')
        
        if not start_date:
            start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        if not end_date:
            end_date = datetime.now().replace(hour=23, minute=59, second=59, microsecond=999999)
        
        self.start_date = start_date
        self.end_date = end_date
        
        # Mettre à jour l'affichage de la période
        self.period_text.value = f"Période: du {start_date.strftime('%d/%m/%Y')} au {end_date.strftime('%d/%m/%Y')}"
        
        # Récupérer les ventes de la période - CORRECTION: utiliser 'sales' au lieu de 'local_sales'
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Vérifier si branch_id existe
                if branch_id:
                    cursor.execute("""
                        SELECT s.*, p.name as product_name, p.code as product_code
                        FROM sales s
                        LEFT JOIN products p ON s.product_id = p.server_id
                        WHERE datetime(s.sale_date) BETWEEN datetime(?) AND datetime(?)
                        AND s.branch_id = ?
                        ORDER BY datetime(s.sale_date) DESC
                    """, (start_date.isoformat(), end_date.isoformat(), branch_id))
                else:
                    cursor.execute("""
                        SELECT s.*, p.name as product_name, p.code as product_code
                        FROM sales s
                        LEFT JOIN products p ON s.product_id = p.server_id
                        WHERE datetime(s.sale_date) BETWEEN datetime(?) AND datetime(?)
                        ORDER BY datetime(s.sale_date) DESC
                    """, (start_date.isoformat(), end_date.isoformat()))
                
                columns = [description[0] for description in cursor.description]
                sales = [dict(zip(columns, row)) for row in cursor.fetchall()]
            
        except sqlite3.OperationalError as e:
            # Si la table 'sales' n'existe pas encore, essayer 'local_sales' (compatibilité)
            print(f"Erreur avec table sales: {e}, tentative avec local_sales...")
            try:
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()
                    
                    if branch_id:
                        cursor.execute("""
                            SELECT ls.*, p.name as product_name, p.code as product_code
                            FROM sales ls
                            LEFT JOIN products p ON ls.product_id = p.server_id
                            WHERE datetime(ls.sale_date) BETWEEN datetime(?) AND datetime(?)
                            AND ls.branch_id = ?
                            ORDER BY datetime(ls.sale_date) DESC
                        """, (start_date.isoformat(), end_date.isoformat(), branch_id))
                    else:
                        cursor.execute("""
                            SELECT ls.*, p.name as product_name, p.code as product_code
                            FROM sales ls
                            LEFT JOIN products p ON ls.product_id = p.server_id
                            WHERE datetime(ls.sale_date) BETWEEN datetime(?) AND datetime(?)
                            ORDER BY datetime(ls.sale_date) DESC
                        """, (start_date.isoformat(), end_date.isoformat()))
                    
                    columns = [description[0] for description in cursor.description]
                    sales = [dict(zip(columns, row)) for row in cursor.fetchall()]
            except Exception as e2:
                print(f"Erreur également avec local_sales: {e2}")
                sales = []
        
        except Exception as e:
            print(f"Erreur lors du chargement de l'historique: {e}")
            sales = []
        
        # Mettre à jour le résumé
        total_sales = sum(float(sale.get('total_price', 0)) for sale in sales)
        transaction_count = len(sales)
        
        self.total_sales_text.value = f"{total_sales:,.0f} FC"
        self.transaction_count_text.value = str(transaction_count)
        
        # Afficher les ventes
        self.history_list_view.controls.clear()
        
        if not sales:
            self.history_list_view.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.Icon(ft.Icons.HISTORY, size=80, color=ft.Colors.GREY_400),
                        ft.Text("Aucune transaction sur cette période", size=16, color=ft.Colors.GREY_600),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=20),
                    alignment=ft.Alignment.CENTER,
                    expand=True,
                )
            )
        else:
            # Grouper par date
            sales_by_date = {}
            for sale in sales:
                sale_date = sale.get('sale_date', '')
                # Gérer différents formats de date
                if sale_date:
                    if 'T' in sale_date:
                        date_key = sale_date.split('T')[0]
                    elif ' ' in sale_date:
                        date_key = sale_date.split(' ')[0]
                    else:
                        date_key = sale_date
                else:
                    date_key = datetime.now().isoformat().split('T')[0]
                
                if date_key not in sales_by_date:
                    sales_by_date[date_key] = []
                sales_by_date[date_key].append(sale)
            
            # Afficher par date
            for date_key, date_sales in sorted(sales_by_date.items(), reverse=True):
                try:
                    date_obj = datetime.strptime(date_key, '%Y-%m-%d')
                    date_header = ft.Container(
                        content=ft.Row([
                            ft.Text(date_obj.strftime("%A %d %B %Y"), size=16, weight=ft.FontWeight.BOLD),
                            ft.Text(f"{sum(float(s.get('total_price', 0)) for s in date_sales):,.0f} FC", size=14, color=ft.Colors.GREEN_700),
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        padding=10,
                        bgcolor=ft.Colors.GREY_200,
                        border_radius=5,
                    )
                    self.history_list_view.controls.append(date_header)
                except ValueError:
                    # Si le format de date est différent, afficher la date brute
                    date_header = ft.Container(
                        content=ft.Row([
                            ft.Text(date_key, size=16, weight=ft.FontWeight.BOLD),
                            ft.Text(f"{sum(float(s.get('total_price', 0)) for s in date_sales):,.0f} FC", size=14, color=ft.Colors.GREEN_700),
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        padding=10,
                        bgcolor=ft.Colors.GREY_200,
                        border_radius=5,
                    )
                    self.history_list_view.controls.append(date_header)
                
                for sale in date_sales:
                    sale_card = self.create_sale_card(sale)
                    self.history_list_view.controls.append(sale_card)
        
        # Mettre à jour l'interface
        self.page.update()
    
    def create_sale_card(self, sale):
        """Créer une carte de transaction"""
        try:
            sale_date = sale.get('sale_date', datetime.now().isoformat())
            sale_time = datetime.fromisoformat(sale_date).strftime("%H:%M")
        except:
            sale_time = "00:00"
        
        product_name = sale.get('product_name', sale.get('product_name', f"Produit #{sale.get('product_id', '?')}"))
        quantity = sale.get('quantity', 1)
        unit_price = sale.get('unit_price', 0)
        total_price = sale.get('total_price', 0)
        customer_name = sale.get('customer_name', 'Client comptant')
        
        return ft.Card(
            content=ft.Container(
                content=ft.Row([
                    ft.Column([
                        ft.Text(product_name, size=14, weight=ft.FontWeight.BOLD),
                        ft.Text(f"{quantity} x {unit_price:,.0f} FC", size=12, color=ft.Colors.GREY_600),
                        ft.Text(f"Client: {customer_name}", size=12, color=ft.Colors.GREY_600),
                    ], expand=True),
                    ft.Column([
                        ft.Text(f"{total_price:,.0f} FC", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_700),
                        ft.Text(sale_time, size=12, color=ft.Colors.GREY_600),
                    ], horizontal_alignment=ft.CrossAxisAlignment.END),
                ]),
                padding=10,
            ),
            margin=5,
        )
    
    def filter_today(self):
        """Filtrer pour aujourd'hui"""
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today + timedelta(days=1)
        self.load_history(today, tomorrow)
    
    def filter_week(self):
        """Filtrer pour cette semaine (lundi à dimanche)"""
        today = datetime.now()
        start_of_week = today - timedelta(days=today.weekday())
        start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_week = start_of_week + timedelta(days=7)
        self.load_history(start_of_week, end_of_week)
    
    def filter_month(self):
        """Filtrer pour ce mois"""
        today = datetime.now()
        start_of_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if today.month == 12:
            end_of_month = today.replace(year=today.year+1, month=1, day=1)
        else:
            end_of_month = today.replace(month=today.month+1, day=1)
        self.load_history(start_of_month, end_of_month)
    
    def show_filter_dialog(self, e):
        """Afficher le dialogue de filtre personnalisé"""
        start_date_picker = ft.DatePicker()
        end_date_picker = ft.DatePicker()
        
        self.page.overlay.append(start_date_picker)
        self.page.overlay.append(end_date_picker)
        
        def apply_filter(e):
            if start_date_picker.value and end_date_picker.value:
                start_date = datetime.fromordinal(start_date_picker.value.toordinal())
                end_date = datetime.fromordinal(end_date_picker.value.toordinal()) + timedelta(days=1)
                self.load_history(start_date, end_date)
                dialog.open = False
                self.page.update()
        
        dialog = ft.AlertDialog(
            title=ft.Text("Filtrer par période"),
            content=ft.Column([
                ft.Text("Date de début:"),
                ft.Button(
                    "Choisir date",
                    on_click=lambda e: start_date_picker.pick_date(),
                ),
                ft.Text("Date de fin:"),
                ft.Button(
                    "Choisir date",
                    on_click=lambda e: end_date_picker.pick_date(),
                ),
            ], tight=True, spacing=10),
            actions=[
                ft.TextButton("Annuler", on_click=lambda e: setattr(dialog, 'open', False)),
                ft.Button("Appliquer", on_click=apply_filter),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()
    
    def go_back(self):
        from screens.dashboard_screen import DashboardScreen
        dashboard = DashboardScreen(self.page, self.db, self.sync_service, self.auth_service, self.current_user)
        dashboard.show()