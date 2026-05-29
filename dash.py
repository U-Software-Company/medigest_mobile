# dashboard_screen.py - Version avec sidebar masquable/démasquable (corrigée pour mobile)

import flet as ft
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional


class DashboardScreen:
    def __init__(self, page: ft.Page, db, sync_service, auth_service, current_user, notification_manager=None):
        self.page = page
        self.db = db
        self.sync_service = sync_service
        self.auth_service = auth_service
        self.current_user = current_user
        self.notification_manager = notification_manager
        
        # État actif du menu
        self.active_menu = "dashboard"
        
        # État du sidebar (masqué ou visible) - UNIQUEMENT pour desktop/tablette
        self.sidebar_visible = True
        self.sidebar_width = 260
        
        # Composants UI persistants
        self.main_container = None
        self.stats_grid_container = None
        self.mobile_drawer = None
        self.sidebar = None
        
        # Flag pour éviter les reconstructions multiples
        self._is_initialized = False
        
        # Gestionnaire de redimensionnement
        self.page.on_resize = self.on_resize

    # ================= UTILITAIRES =================

    def show_snackbar(self, message: str, color, duration=3000):
        """Affiche un snackbar"""
        snack = ft.SnackBar(
            content=ft.Text(message),
            bgcolor=color,
            duration=duration,
            show_close_icon=True,
        )
        self.page.snack_bar = snack
        snack.open = True
        self.page.update()

    def is_mobile(self):
        """Détecte si l'appareil est mobile (largeur < 600px)"""
        return (self.page.width or 0) < 600

    def is_tablet(self):
        """Détecte si l'appareil est une tablette (600px - 1024px)"""
        width = self.page.width or 0
        return 600 <= width < 1024

    def on_resize(self, e):
        """Met à jour le layout lors du redimensionnement"""
        if self._is_initialized:
            self.update_layout()

    def _extract_numeric_value(self, value) -> float:
        """Extrait une valeur numérique d'une chaîne formatée"""
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            clean_value = value.replace("FC", "").strip().replace(",", "").replace(" ", "")
            try:
                return float(clean_value) if clean_value else 0.0
            except:
                return 0.0
        return 0.0

    def _get_product_attr(self, product, attr_name, default=None):
        """Récupère un attribut d'un produit (dictionnaire ou objet)"""
        if isinstance(product, dict):
            return product.get(attr_name, default)
        else:
            return getattr(product, attr_name, default)

    # ================= DONNÉES =================

    def get_today_sales_value(self) -> float:
        """Récupère le montant des ventes du jour"""
        branch_id = self.current_user.get('active_branch_id') or self.current_user.get('branch_id')
        try:
            if hasattr(self.db, 'get_today_sales'):
                return self.db.get_today_sales(branch_id)
            return 0.0
        except Exception as e:
            print(f"Erreur récupération ventes jour: {e}")
            return 0.0

    def get_today_expenses(self) -> float:
        """Récupère le montant des dépenses du jour"""
        branch_id = self.current_user.get('active_branch_id') or self.current_user.get('branch_id')
        try:
            if hasattr(self.db, 'get_total_expenses'):
                return self.db.get_total_expenses(branch_id, "today")
            return 0.0
        except Exception as e:
            print(f"Erreur récupération dépenses jour: {e}")
            return 0.0

    def get_week_expenses(self) -> float:
        """Récupère le montant des dépenses de la semaine"""
        branch_id = self.current_user.get('active_branch_id') or self.current_user.get('branch_id')
        try:
            if hasattr(self.db, 'get_total_expenses'):
                return self.db.get_total_expenses(branch_id, "week")
            return 0.0
        except Exception as e:
            print(f"Erreur récupération dépenses semaine: {e}")
            return 0.0

    def get_month_expenses(self) -> float:
        """Récupère le montant des dépenses du mois"""
        branch_id = self.current_user.get('active_branch_id') or self.current_user.get('branch_id')
        try:
            if hasattr(self.db, 'get_total_expenses'):
                return self.db.get_total_expenses(branch_id, "month")
            return 0.0
        except Exception as e:
            print(f"Erreur récupération dépenses mois: {e}")
            return 0.0

    def get_today_debts(self) -> float:
        """Récupère le montant des dettes créées aujourd'hui"""
        branch_id = self.current_user.get('active_branch_id') or self.current_user.get('branch_id')
        try:
            today = date.today().isoformat()
            debts = self.db.get_pending_debts(branch_id) if hasattr(self.db, 'get_pending_debts') else []
            total = 0
            for debt in debts:
                created_at = debt.created_at if hasattr(debt, 'created_at') else debt.get('created_at', '')
                if created_at and created_at.startswith(today):
                    remaining = debt.remaining_amount if hasattr(debt, 'remaining_amount') else debt.get('remaining_amount', 0)
                    total += float(remaining)
            return total
        except Exception as e:
            print(f"Erreur récupération dettes jour: {e}")
            return 0.0

    def get_week_debts(self) -> float:
        """Récupère le montant des dettes créées cette semaine"""
        branch_id = self.current_user.get('active_branch_id') or self.current_user.get('branch_id')
        try:
            week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
            debts = self.db.get_pending_debts(branch_id) if hasattr(self.db, 'get_pending_debts') else []
            total = 0
            for debt in debts:
                created_at = debt.created_at if hasattr(debt, 'created_at') else debt.get('created_at', '')
                if created_at and created_at >= week_start:
                    remaining = debt.remaining_amount if hasattr(debt, 'remaining_amount') else debt.get('remaining_amount', 0)
                    total += float(remaining)
            return total
        except Exception as e:
            print(f"Erreur récupération dettes semaine: {e}")
            return 0.0

    def get_month_debts(self) -> float:
        """Récupère le montant des dettes créées ce mois-ci"""
        branch_id = self.current_user.get('active_branch_id') or self.current_user.get('branch_id')
        try:
            month_start = date.today().replace(day=1).isoformat()
            debts = self.db.get_pending_debts(branch_id) if hasattr(self.db, 'get_pending_debts') else []
            total = 0
            for debt in debts:
                created_at = debt.created_at if hasattr(debt, 'created_at') else debt.get('created_at', '')
                if created_at and created_at >= month_start:
                    remaining = debt.remaining_amount if hasattr(debt, 'remaining_amount') else debt.get('remaining_amount', 0)
                    total += float(remaining)
            return total
        except Exception as e:
            print(f"Erreur récupération dettes mois: {e}")
            return 0.0

    def get_expiring_products(self) -> tuple:
        """Récupère les produits expirés et proches de péremption"""
        branch_id = self.current_user.get('active_branch_id') or self.current_user.get('branch_id')
        products = self.db.get_products(branch_id)
        
        expired_products = []
        expiring_soon_products = []
        
        for product in products:
            expiry_date = self._get_product_attr(product, 'expiry_date')
            if not expiry_date:
                expiry_date = self._get_product_attr(product, 'expiration_date')
            
            if not expiry_date:
                continue
                
            try:
                if isinstance(expiry_date, str):
                    if "T" in expiry_date:
                        expiry_date = expiry_date.split("T")[0]
                    expiry = datetime.strptime(expiry_date, "%Y-%m-%d").date()
                else:
                    expiry = expiry_date
                    
                today = date.today()
                days_left = (expiry - today).days
                
                product_id = self._get_product_attr(product, 'server_id')
                if not product_id:
                    product_id = self._get_product_attr(product, 'id')
                
                product_name = self._get_product_attr(product, 'name', "Produit inconnu")
                product_code = self._get_product_attr(product, 'code', "N/A")
                product_quantity = self._get_product_attr(product, 'quantity')
                if product_quantity is None:
                    product_quantity = self._get_product_attr(product, 'stock', 0)
                product_price = self._get_product_attr(product, 'selling_price')
                if product_price is None:
                    product_price = self._get_product_attr(product, 'price', 0)
                product_category = self._get_product_attr(product, 'category', "")
                
                product_info = {
                    "id": str(product_id) if product_id else None,
                    "name": product_name,
                    "code": product_code,
                    "expiry_date": expiry,
                    "days_left": days_left,
                    "quantity": product_quantity,
                    "selling_price": product_price,
                    "category": product_category,
                }
                
                if days_left < 0:
                    product_info["status"] = "expired"
                    product_info["status_text"] = f"Expiré depuis {-days_left} jours"
                    product_info["status_color"] = ft.Colors.RED_700
                    expired_products.append(product_info)
                elif days_left <= 30:
                    product_info["status"] = "expiring"
                    product_info["days_left"] = days_left
                    product_info["status_text"] = f"Expire dans {days_left} jours"
                    product_info["status_color"] = ft.Colors.ORANGE if days_left > 7 else ft.Colors.RED
                    expiring_soon_products.append(product_info)
                    
            except Exception as e:
                product_name = self._get_product_attr(product, 'name', "Inconnu")
                print(f"Erreur vérification expiration pour {product_name}: {e}")
                
        expired_products.sort(key=lambda x: x["days_left"])
        expiring_soon_products.sort(key=lambda x: x["days_left"])
        
        return expired_products, expiring_soon_products

    def get_expiring_count(self) -> int:
        """Récupère le nombre de produits expirés et proches de péremption"""
        expired, expiring = self.get_expiring_products()
        return len(expired) + len(expiring)

    def get_low_stock_products(self) -> List[Dict]:
        """Récupère les produits en rupture de stock (stock <= 0)"""
        branch_id = self.current_user.get('active_branch_id') or self.current_user.get('branch_id')
        try:
            products = self.db.get_products(branch_id)
            low_stock = []
            for product in products:
                quantity = self._get_product_attr(product, 'quantity')
                if quantity is None:
                    quantity = self._get_product_attr(product, 'stock', 0)
                
                if quantity <= 0:
                    low_stock.append({
                        "id": self._get_product_attr(product, 'server_id') or self._get_product_attr(product, 'id'),
                        "name": self._get_product_attr(product, 'name', "Inconnu"),
                        "code": self._get_product_attr(product, 'code', "N/A"),
                        "quantity": quantity,
                        "selling_price": self._get_product_attr(product, 'selling_price', 0),
                        "category": self._get_product_attr(product, 'category', ""),
                    })
            return low_stock
        except Exception as e:
            print(f"Erreur récupération rupture stock: {e}")
            return []

    def get_never_sold_products(self) -> List[Dict]:
        """Récupère les produits qui n'ont jamais été vendus"""
        branch_id = self.current_user.get('active_branch_id') or self.current_user.get('branch_id')
        try:
            if hasattr(self.db, 'get_never_sold_products'):
                return self.db.get_never_sold_products(branch_id)
            
            products = self.db.get_products(branch_id)
            sold_product_ids = set()
            
            if hasattr(self.db, 'get_sales'):
                sales = self.db.get_sales(branch_id)
            else:
                sales = []
            
            for sale in sales:
                product_id = sale.product_id if hasattr(sale, 'product_id') else sale.get('product_id')
                if product_id:
                    sold_product_ids.add(str(product_id))
            
            never_sold = []
            for product in products:
                product_id = str(self._get_product_attr(product, 'server_id') or self._get_product_attr(product, 'id', ''))
                if product_id and product_id not in sold_product_ids:
                    quantity = self._get_product_attr(product, 'quantity')
                    if quantity is None:
                        quantity = self._get_product_attr(product, 'stock', 0)
                    
                    never_sold.append({
                        "id": product_id,
                        "name": self._get_product_attr(product, 'name', "Inconnu"),
                        "code": self._get_product_attr(product, 'code', "N/A"),
                        "quantity": quantity,
                        "selling_price": self._get_product_attr(product, 'selling_price', 0),
                        "category": self._get_product_attr(product, 'category', ""),
                    })
            
            return never_sold
        except Exception as e:
            print(f"Erreur récupération produits jamais vendus: {e}")
            return []

    # ================= CARTES STATISTIQUES =================

    def create_stat_card(self, title: str, value, icon, color, detail_type: str = None):
        """Créer une carte statistique individuelle cliquable"""
        
        def on_card_click(e):
            if detail_type:
                self.show_details(detail_type)
            else:
                self.show_snackbar(f"Informations: {title}", ft.Colors.BLUE)
        
        return ft.Container(
            content=ft.Column([
                ft.Icon(icon, color=color, size=28),
                ft.Text(title, size=12 if self.is_mobile() else 14, text_align=ft.TextAlign.CENTER),
                ft.Text(str(value), size=14 if self.is_mobile() else 16, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=5),
            padding=10,
            bgcolor=ft.Colors.WHITE,
            border_radius=12,
            shadow=ft.BoxShadow(blur_radius=5, color=ft.Colors.GREY_300),
            on_click=on_card_click,
            ink=True,
        )

    def refresh_stats_grid(self):
        """Rafraîchit uniquement la grille des statistiques"""
        if self.stats_grid_container:
            self.stats_grid_container.content = self.create_stats_grid()
            self.page.update()

    def create_stats_grid(self):
        """Crée la grille des statistiques responsive"""
        # Récupérer les données
        today_sales = self.get_today_sales_value()
        today_expenses = self.get_today_expenses()
        week_expenses = self.get_week_expenses()
        month_expenses = self.get_month_expenses()
        today_debts = self.get_today_debts()
        week_debts = self.get_week_debts()
        month_debts = self.get_month_debts()
        expiring_count = self.get_expiring_count()
        low_stock_count = len(self.get_low_stock_products())
        never_sold_count = len(self.get_never_sold_products())
        
        print(f"📊 Dashboard Stats: Ventes jour={today_sales}, Dépenses jour={today_expenses}, "
              f"Dettes jour={today_debts}, Péremptions={expiring_count}, "
              f"Rupture stock={low_stock_count}, Jamais vendus={never_sold_count}")
        
        # Formater les valeurs
        format_fc = lambda v: f"{v:,.0f} FC" if v >= 0 else "0 FC"
        
        stats = [
            ("Vente aujourd'hui", format_fc(today_sales), ft.Icons.TODAY, ft.Colors.GREEN, "today_sales"),
            ("Dépenses aujourd'hui", format_fc(today_expenses), ft.Icons.MONEY_OFF, ft.Colors.RED, "today_expenses"),
            ("Dépenses semaine", format_fc(week_expenses), ft.Icons.WEEKEND, ft.Colors.ORANGE, "week_expenses"),
            ("Dépenses mois", format_fc(month_expenses), ft.Icons.CALENDAR_MONTH, ft.Colors.RED_700, "month_expenses"),
            ("Dettes aujourd'hui", format_fc(today_debts), ft.Icons.ACCOUNT_BALANCE_WALLET, ft.Colors.PURPLE, "today_debts"),
            ("Dettes semaine", format_fc(week_debts), ft.Icons.ACCOUNT_BALANCE_WALLET, ft.Colors.PURPLE_400, "week_debts"),
            ("Dettes mois", format_fc(month_debts), ft.Icons.ACCOUNT_BALANCE_WALLET, ft.Colors.PURPLE_700, "month_debts"),
            ("Péremptions", str(expiring_count), ft.Icons.WARNING_AMBER, ft.Colors.ORANGE, "expiring"),
            ("Rupture stock", str(low_stock_count), ft.Icons.WARNING, ft.Colors.RED, "low_stock"),
            ("Jamais vendus", str(never_sold_count), ft.Icons.INVENTORY, ft.Colors.BLUE, "never_sold"),
        ]
        
        # Utilisation de ResponsiveRow pour les cartes
        return ft.ResponsiveRow(
            controls=[
                ft.Container(
                    content=self.create_stat_card(title, value, icon, color, detail_type),
                    col={"xs": 12, "sm": 6, "md": 4, "lg": 3, "xl": 2},
                    padding=5,
                )
                for title, value, icon, color, detail_type in stats
            ],
            spacing=10,
            run_spacing=10,
        )

    # ================= AFFICHAGE DES DÉTAILS =================

    def show_details(self, detail_type: str):
        """Affiche les détails pour une carte spécifique"""
        from screens.details_screen import DetailsScreen
        
        if detail_type == "today_sales":
            details_screen = DetailsScreen(
                self.page, self.db, self.sync_service, self.auth_service, 
                self.current_user, self.notification_manager,
                title="Ventes d'aujourd'hui",
                detail_type="sales",
                data={"total": self.get_today_sales_value(), "period": "today"}
            )
        elif detail_type == "today_expenses":
            expenses = self.get_expenses_for_period("today")
            details_screen = DetailsScreen(
                self.page, self.db, self.sync_service, self.auth_service,
                self.current_user, self.notification_manager,
                title="Dépenses d'aujourd'hui",
                detail_type="expenses",
                data={"items": expenses, "total": self.get_today_expenses(), "period": "today"}
            )
        elif detail_type == "week_expenses":
            expenses = self.get_expenses_for_period("week")
            details_screen = DetailsScreen(
                self.page, self.db, self.sync_service, self.auth_service,
                self.current_user, self.notification_manager,
                title="Dépenses de la semaine",
                detail_type="expenses",
                data={"items": expenses, "total": self.get_week_expenses(), "period": "week"}
            )
        elif detail_type == "month_expenses":
            expenses = self.get_expenses_for_period("month")
            details_screen = DetailsScreen(
                self.page, self.db, self.sync_service, self.auth_service,
                self.current_user, self.notification_manager,
                title="Dépenses du mois",
                detail_type="expenses",
                data={"items": expenses, "total": self.get_month_expenses(), "period": "month"}
            )
        elif detail_type == "today_debts":
            debts = self.get_debts_for_period("today")
            details_screen = DetailsScreen(
                self.page, self.db, self.sync_service, self.auth_service,
                self.current_user, self.notification_manager,
                title="Dettes d'aujourd'hui",
                detail_type="debts",
                data={"items": debts, "total": self.get_today_debts(), "period": "today"}
            )
        elif detail_type == "week_debts":
            debts = self.get_debts_for_period("week")
            details_screen = DetailsScreen(
                self.page, self.db, self.sync_service, self.auth_service,
                self.current_user, self.notification_manager,
                title="Dettes de la semaine",
                detail_type="debts",
                data={"items": debts, "total": self.get_week_debts(), "period": "week"}
            )
        elif detail_type == "month_debts":
            debts = self.get_debts_for_period("month")
            details_screen = DetailsScreen(
                self.page, self.db, self.sync_service, self.auth_service,
                self.current_user, self.notification_manager,
                title="Dettes du mois",
                detail_type="debts",
                data={"items": debts, "total": self.get_month_debts(), "period": "month"}
            )
        elif detail_type == "expiring":
            expired, expiring = self.get_expiring_products()
            details_screen = DetailsScreen(
                self.page, self.db, self.sync_service, self.auth_service,
                self.current_user, self.notification_manager,
                title="Produits expirés et proches de péremption",
                detail_type="expiring",
                data={"expired": expired, "expiring": expiring}
            )
        elif detail_type == "low_stock":
            products = self.get_low_stock_products()
            details_screen = DetailsScreen(
                self.page, self.db, self.sync_service, self.auth_service,
                self.current_user, self.notification_manager,
                title="Produits en rupture de stock",
                detail_type="low_stock",
                data={"items": products, "count": len(products)}
            )
        elif detail_type == "never_sold":
            products = self.get_never_sold_products()
            details_screen = DetailsScreen(
                self.page, self.db, self.sync_service, self.auth_service,
                self.current_user, self.notification_manager,
                title="Produits jamais vendus",
                detail_type="never_sold",
                data={"items": products, "count": len(products)}
            )
        else:
            self.show_snackbar("Détails non disponibles", ft.Colors.ORANGE)
            return
        
        details_screen.show()

    def get_expenses_for_period(self, period: str) -> List[Dict]:
        """Récupère les dépenses pour une période donnée"""
        branch_id = self.current_user.get('active_branch_id') or self.current_user.get('branch_id')
        
        if hasattr(self.db, 'get_expenses'):
            expenses = self.db.get_expenses(branch_id)
        else:
            expenses = []
        
        today = date.today()
        if period == "today":
            start_date = today.isoformat()
        elif period == "week":
            start_date = (today - timedelta(days=today.weekday())).isoformat()
        else:
            start_date = today.replace(day=1).isoformat()
        
        filtered_expenses = []
        for expense in expenses:
            expense_date = expense.expense_date if hasattr(expense, 'expense_date') else expense.get('expense_date', '')
            if expense_date and expense_date >= start_date:
                filtered_expenses.append({
                    "id": expense.id if hasattr(expense, 'id') else expense.get('id'),
                    "description": expense.description if hasattr(expense, 'description') else expense.get('description', ''),
                    "amount": float(expense.amount if hasattr(expense, 'amount') else expense.get('amount', 0)),
                    "category": expense.category if hasattr(expense, 'category') else expense.get('category', ''),
                    "expense_date": expense_date,
                })
        
        return filtered_expenses

    def get_debts_for_period(self, period: str) -> List[Dict]:
        """Récupère les dettes pour une période donnée"""
        branch_id = self.current_user.get('active_branch_id') or self.current_user.get('branch_id')
        debts = self.db.get_pending_debts(branch_id) if hasattr(self.db, 'get_pending_debts') else []
        
        today = date.today()
        if period == "today":
            start_date = today.isoformat()
        elif period == "week":
            start_date = (today - timedelta(days=today.weekday())).isoformat()
        else:
            start_date = today.replace(day=1).isoformat()
        
        filtered_debts = []
        for debt in debts:
            created_at = debt.created_at if hasattr(debt, 'created_at') else debt.get('created_at', '')
            if created_at and created_at >= start_date:
                filtered_debts.append({
                    "id": debt.id if hasattr(debt, 'id') else debt.get('id'),
                    "customer_name": debt.customer_name if hasattr(debt, 'customer_name') else debt.get('customer_name', 'Client'),
                    "amount": float(debt.amount if hasattr(debt, 'amount') else debt.get('amount', 0)),
                    "remaining_amount": float(debt.remaining_amount if hasattr(debt, 'remaining_amount') else debt.get('remaining_amount', 0)),
                    "due_date": debt.due_date if hasattr(debt, 'due_date') else debt.get('due_date', ''),
                    "created_at": created_at,
                })
        
        return filtered_debts

    # ================= MENU LATÉRAL (DESKTOP/TABLETTE) =================

    def menu_item(self, icon, text, action, key):
        """Crée un élément de menu"""
        active = self.active_menu == key
        
        menu_container = ft.Container(
            bgcolor=ft.Colors.BLUE_100 if active else None,
            border_radius=10,
            margin=ft.margin.only(bottom=5),
            content=ft.ListTile(
                leading=ft.Icon(icon, color=ft.Colors.BLUE_800 if active else ft.Colors.BLUE_GREY_700),
                title=ft.Text(text, color=ft.Colors.BLUE_800 if active else ft.Colors.BLUE_GREY_700),
                on_click=lambda e, a=action, k=key: self._navigate(e, a, k),
            ),
        )
        
        return menu_container

    def _navigate(self, e, action, key):
        """Navigation avec gestion du drawer mobile"""
        # Mettre à jour le menu actif
        self.active_menu = key
        
        # Fermer le drawer si ouvert sur mobile
        if self.is_mobile() and self.mobile_drawer:
            self.mobile_drawer.open = False
            self.page.update()
        
        # Appeler l'action de navigation
        action(e)

    def toggle_sidebar(self, e):
        """Affiche ou masque le sidebar (UNIQUEMENT pour desktop/tablette)"""
        if not self.is_mobile():
            self.sidebar_visible = not self.sidebar_visible
            self.update_layout()

    def create_sidebar(self):
        """Crée le menu latéral pour tablette et desktop (UNIQUEMENT)"""
        return ft.Container(
            width=self.sidebar_width if self.sidebar_visible else 0,
            bgcolor=ft.Colors.BLUE_50,
            padding=10 if self.sidebar_visible else 0,
            animate=ft.Animation(300, ft.AnimationCurve.EASE_IN_OUT),
            visible=not self.is_mobile(),  # invisible sur mobile
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("MediGest", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_800, expand=True),
                            ft.IconButton(
                                icon=ft.Icons.CHEVRON_LEFT,
                                icon_color=ft.Colors.BLUE_800,
                                on_click=self.toggle_sidebar,
                                tooltip="Masquer le menu",
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Divider(height=20, color=ft.Colors.BLUE_200),
                    ft.Container(
                        content=ft.Column(
                            [
                                self.menu_item(ft.Icons.DASHBOARD, "Tableau de bord", self.show_dashboard, "dashboard"),
                                self.menu_item(ft.Icons.SHOPPING_CART, "Vente", self.go_to_sale, "sale"),
                                self.menu_item(ft.Icons.HISTORY, "Historique", self.go_to_history, "history"),
                                self.menu_item(ft.Icons.INVENTORY, "Produits", self.go_to_products, "products"),
                                self.menu_item(ft.Icons.PAYMENT, "Trésorerie", self.go_to_cash_report, "cash"),
                                self.menu_item(ft.Icons.MONEY_OFF, "Dépenses", self.go_to_expenses, "expenses"),
                                self.menu_item(ft.Icons.ACCOUNT_BALANCE_WALLET, "Dettes", self.go_to_debts, "debts"),
                                self.menu_item(ft.Icons.SWAP_HORIZ, "Factures", self.go_to_invoice, "invoice"),
                                self.menu_item(ft.Icons.ASSESSMENT, "Rapport stock", self.go_to_stock_report, "stock"),
                                self.menu_item(ft.Icons.SUBSCRIPTIONS, "Abonnement", self.go_to_abonnement, "abo"),
                                ft.Divider(height=20, color=ft.Colors.BLUE_200),
                                self.menu_item(ft.Icons.SYNC, "Synchronisation", self.go_to_sync, "sync"),
                                self.menu_item(ft.Icons.STORE, "Changer succursale", self.switch_branch, "branch"),
                                self.menu_item(ft.Icons.LOGOUT, "Déconnexion", self.logout, "logout"),
                            ],
                            spacing=5,
                        ),
                        expand=True,
                    ),
                ],
                scroll=ft.ScrollMode.AUTO,
                expand=True,
                spacing=5,
            ),
        )

    # ================= HEADER =================

    def create_header(self):
        """Crée l'en-tête avec informations utilisateur et actions"""
        # Bouton pour afficher/masquer le sidebar (visible uniquement sur desktop/tablette)
        sidebar_toggle_button = ft.IconButton(
            icon=ft.Icons.MENU_OPEN if self.sidebar_visible else ft.Icons.MENU,
            icon_color=ft.Colors.WHITE,
            on_click=self.toggle_sidebar,
            tooltip="Afficher/Masquer le menu",
            visible=not self.is_mobile(),
        )
        
        # Menu burger pour mobile
        mobile_menu_button = ft.IconButton(
            icon=ft.Icons.MENU,
            icon_color=ft.Colors.WHITE,
            on_click=self.toggle_mobile_menu,
            visible=self.is_mobile(),
        )
        
        return ft.Container(
            bgcolor=ft.Colors.BLUE_700,
            padding=ft.Padding.symmetric(horizontal=15, vertical=12),
            content=ft.Row(
                [
                    ft.Row(
                        [
                            sidebar_toggle_button,
                            mobile_menu_button,
                        ],
                        spacing=5,
                    ),
                    
                    # Infos utilisateur
                    ft.Column(
                        [
                            ft.Text(
                                f"Bonjour, {self.current_user.get('full_name', 'Utilisateur')}",
                                color=ft.Colors.WHITE,
                                size=14 if self.is_mobile() else 16,
                                weight=ft.FontWeight.BOLD,
                            ),
                            ft.Text(
                                self.current_user.get('branch_name', 'N/A'),
                                color=ft.Colors.WHITE_70,
                                size=11 if self.is_mobile() else 12,
                            ),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    
                    # Actions
                    ft.Row(
                        [
                            ft.IconButton(
                                icon=ft.Icons.SYNC,
                                icon_color=ft.Colors.WHITE,
                                on_click=self.sync_data,
                                tooltip="Synchroniser",
                                icon_size=20 if self.is_mobile() else 24,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.LOGOUT,
                                icon_color=ft.Colors.WHITE,
                                on_click=self.logout,
                                tooltip="Déconnexion",
                                icon_size=20 if self.is_mobile() else 24,
                            ),
                        ],
                        spacing=5,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def toggle_mobile_menu(self, e):
        """Affiche/masque le menu mobile dans un drawer"""
        # Supprimer l'ancien drawer s'il existe (évite les doublons)
        if self.mobile_drawer and self.mobile_drawer in self.page.overlay:
            self.page.overlay.remove(self.mobile_drawer)
            self.mobile_drawer = None
        
        # Créer un nouveau drawer
        drawer_controls = [
            ft.Container(height=20),
            ft.Text("MediGest", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_800),
            ft.Divider(height=20),
        ]
        
        # Ajouter tous les éléments du menu
        menu_items = [
            (ft.Icons.DASHBOARD, "Tableau de bord", self.show_dashboard, "dashboard"),
            (ft.Icons.SHOPPING_CART, "Vente", self.go_to_sale, "sale"),
            (ft.Icons.HISTORY, "Historique", self.go_to_history, "history"),
            (ft.Icons.INVENTORY, "Produits", self.go_to_products, "products"),
            (ft.Icons.ADD_SHOPPING_CART, "Ajouter produit", self.go_to_add_product, "add_product"),
            (ft.Icons.MERGE_TYPE, "Gérer doublons", self.go_to_duplicates, "duplicates"),
            (ft.Icons.PAYMENT, "Trésorerie", self.go_to_cash_report, "cash"),
            (ft.Icons.MONEY_OFF, "Dépenses", self.go_to_expenses, "expenses"),
            (ft.Icons.ACCOUNT_BALANCE_WALLET, "Dettes", self.go_to_debts, "debts"),
            (ft.Icons.SWAP_HORIZ, "Factures", self.go_to_invoice, "invoice"),
            (ft.Icons.ASSESSMENT, "Rapport stock", self.go_to_stock_report, "stock"),
            (ft.Icons.SUBSCRIPTIONS, "Abonnement", self.go_to_abonnement, "abo"),
            (ft.Icons.SYNC, "Synchronisation", self.go_to_sync, "sync"),
            (ft.Icons.STORE, "Changer succursale", self.switch_branch, "branch"),
            (ft.Icons.LOGOUT, "Déconnexion", self.logout, "logout"),
            
        ]
        
        for icon, text, action, key in menu_items:
            active = self.active_menu == key
            drawer_controls.append(
                ft.Container(
                    bgcolor=ft.Colors.BLUE_100 if active else None,
                    border_radius=10,
                    margin=ft.Margin.only(bottom=5),
                    content=ft.ListTile(
                        leading=ft.Icon(icon, color=ft.Colors.BLUE_800 if active else ft.Colors.BLUE_GREY_700),
                        title=ft.Text(text, color=ft.Colors.BLUE_800 if active else ft.Colors.BLUE_GREY_700),
                        on_click=lambda e, a=action, k=key: self._navigate(e, a, k),
                    ),
                )
            )
        
        self.mobile_drawer = ft.NavigationDrawer(
            controls=drawer_controls,
            on_dismiss=lambda e: self._on_drawer_dismiss(),
        )
        self.page.overlay.append(self.mobile_drawer)
        self.mobile_drawer.open = True
        self.page.update()
    
    def _on_drawer_dismiss(self):
        """Callback quand le drawer est fermé"""
        if self.mobile_drawer:
            self.mobile_drawer.open = False
            self.page.update()

    # ================= CONTENU PRINCIPAL =================

    def create_main_content(self):
        """Crée le contenu principal du dashboard"""
        self.stats_grid_container = ft.Container(
            content=self.create_stats_grid(),
            expand=True,
        )
        
        return ft.Container(
            expand=True,
            padding=ft.Padding.all(15 if not self.is_mobile() else 10),
            content=ft.Column(
                [
                    ft.Text(
                        "Tableau de bord",
                        size=20 if not self.is_mobile() else 18,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.BLUE_GREY_800,
                    ),
                    ft.Container(height=10),
                    self.stats_grid_container,
                ],
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                spacing=10,
            ),
        )

    # ================= AFFICHAGE PRINCIPAL =================

    def show_dashboard(self, e=None):
        """Affiche le dashboard avec layout responsive"""
        self.active_menu = "dashboard"
        
        if not self._is_initialized:
            self.init_layout()
            self._is_initialized = True
        else:
            self.update_layout()
        
        # Mettre à jour le badge de notification si disponible
        if self.notification_manager:
            self.notification_manager.update_notification_badge()

    def init_layout(self):
        """Initialise le layout pour la première fois"""
        self.page.clean()
        self.page.bgcolor = ft.Colors.GREY_50
        self.page.padding = 0
        self.page.spacing = 0
        
        # Contenu sécurisé
        safe_content = ft.SafeArea(
            content=ft.Column(
                [
                    self.create_header(),
                    self.create_main_content(),
                ],
                expand=True,
                spacing=0,
            ),
            expand=True,
        )
        
        # Layout responsive
        if self.is_mobile():
            # Sur mobile : pas de sidebar, seulement le contenu
            self.main_container = safe_content
        else:
            # Sur desktop/tablette : sidebar + contenu
            self.main_container = ft.Row(
                [
                    self.create_sidebar(),
                    ft.VerticalDivider(width=1, color=ft.Colors.GREY_300, visible=self.sidebar_visible),
                    ft.Container(expand=True, content=safe_content),
                ],
                expand=True,
                spacing=0,
            )
        
        self.page.add(self.main_container)
        self.page.update()

    def update_layout(self):
        """Met à jour le layout lors du redimensionnement ou du toggle sidebar"""
        if not self._is_initialized:
            return
        
        self.page.controls.clear()
        
        # Contenu sécurisé
        safe_content = ft.SafeArea(
            content=ft.Column(
                [
                    self.create_header(),
                    self.create_main_content(),
                ],
                expand=True,
                spacing=0,
            ),
            expand=True,
        )
        
        # Layout responsive
        if self.is_mobile():
            # Sur mobile : pas de sidebar
            new_layout = safe_content
        else:
            # Sur desktop/tablette : sidebar + contenu
            new_layout = ft.Row(
                [
                    self.create_sidebar(),
                    ft.VerticalDivider(width=1, color=ft.Colors.GREY_300, visible=self.sidebar_visible),
                    ft.Container(expand=True, content=safe_content),
                ],
                expand=True,
                spacing=0,
            )
        
        self.page.add(new_layout)
        self.main_container = new_layout
        self.page.update()

    def show(self, e=None):
        """Alias pour show_dashboard pour la compatibilité"""
        self.show_dashboard(e)

    def refresh_data(self, e=None):
        """Rafraîchit les données du dashboard"""
        self.refresh_stats_grid()

    # ================= MÉTHODES DE NAVIGATION =================

    def sync_data(self, e):
        """Synchroniser les données avec le serveur"""
        def sync_in_background():
            try:
                result = self.sync_service.sync_all()
                if result and result.get('error'):
                    self.show_snackbar(f"⚠️ {result.get('error')}", ft.Colors.ORANGE)
                else:
                    products = result.get('products_imported', 0) if result else 0
                    sales = result.get('sales_exported', 0) if result else 0
                    expenses = result.get('expenses_exported', 0) if result else 0
                    self.show_snackbar(f"✅ Sync: {products} produits, {sales} ventes, {expenses} dépenses", ft.Colors.GREEN, 4000)
                    self.refresh_stats_grid()
            except Exception as err:
                self.show_snackbar(f"Erreur de synchronisation: {str(err)}", ft.Colors.RED)
        
        self.show_snackbar("Synchronisation en cours...", ft.Colors.BLUE)
        sync_in_background()

    def go_to_sync(self, e):
        """Ouvre l'écran de synchronisation"""
        from screens.sync_screen import SyncScreen
        sync_screen = SyncScreen(
            self.page, self.db, self.sync_service, 
            self.auth_service, self.current_user, self.notification_manager
        )
        sync_screen.show()

    def go_to_sale(self, e):
        from screens.sale_screen import SaleScreen
        sale_screen = SaleScreen(self.page, self.db, self.sync_service, self.auth_service, self.current_user)
        sale_screen.show()

    def go_to_history(self, e):
        from screens.history_screen import HistoryScreen
        history_screen = HistoryScreen(self.page, self.db, self.sync_service, self.auth_service, self.current_user)
        history_screen.show()

    def go_to_products(self, e):
        from screens.products_screen import ProductsScreen
        products_screen = ProductsScreen(self.page, self.db, self.sync_service, self.auth_service, self.current_user)
        products_screen.show()

    def go_to_cash_report(self, e):
        from screens.cash_report_screen import CashReportScreen
        cash_report = CashReportScreen(self.page, self.db, self.sync_service, self.auth_service, self.current_user)
        cash_report.show()

    def go_to_expenses(self, e):
        from screens.expense_screen import ExpenseScreen
        expense_screen = ExpenseScreen(self.page, self.db, self.sync_service, self.auth_service, self.current_user)
        expense_screen.show()

    def go_to_debts(self, e):
        from screens.debt_screen import DebtScreen
        debt_screen = DebtScreen(self.page, self.db, self.sync_service, self.auth_service, self.current_user)
        debt_screen.show()

    def go_to_stock_report(self, e):
        from screens.stock_report_screen import StockReportScreen
        stock_report = StockReportScreen(self.page, self.db, self.sync_service, self.auth_service, self.current_user)
        stock_report.show()

    def go_to_invoice(self, e):
        from screens.invoice_screen import InvoiceScreen
        invoice = InvoiceScreen(self.page, self.db, self.sync_service, self.auth_service, self.current_user)
        invoice.show()

    def go_to_abonnement(self, e):
        from screens.abonnement_screen import AbonnementScreen
        abonnement_screen = AbonnementScreen(
            self.page, self.db, self.sync_service, 
            self.auth_service, self.current_user,
            self.notification_manager
        )
        abonnement_screen.show()

    def switch_branch(self, e):
        from screens.branch_switch_screen import BranchSwitchScreen
        branch_switch = BranchSwitchScreen(self.page, self.db, self.sync_service, self.auth_service, self.current_user)
        branch_switch.show()

    def logout(self, e):
        """Déconnecter l'utilisateur"""
        # Nettoyer le drawer avant déconnexion
        if self.mobile_drawer:
            if self.mobile_drawer in self.page.overlay:
                self.page.overlay.remove(self.mobile_drawer)
            self.mobile_drawer = None
        
        self.auth_service.logout()
        from screens.login_screen import LoginScreen
        login = LoginScreen(self.page, self.db, self.sync_service, self.auth_service)
        login.show()