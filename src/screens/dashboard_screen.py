# dashboard_screen.py - Version avec sidebar selon le rôle

import flet as ft
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional
import threading
import time
import logging

from services.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)


class DashboardScreen:
    def __init__(self, page: ft.Page, db, sync_service, auth_service, current_user, notification_manager=None):
        from services.permission_manager import PermissionManager
        self.page = page
        self.db = db
        self.sync_service = sync_service
        self.auth_service = auth_service
        self.current_user = current_user
        self.notification_manager = notification_manager
        
        # ========== CONNECTION MANAGER (SINGLETON) ==========
        self.connection_manager = ConnectionManager()
        
        if sync_service is not None:
            self.connection_manager.set_sync_service(sync_service)
        
        self.connection_manager.register_observer(self._on_connection_status_changed)
        
        # État actif du menu
        self.active_menu = "dashboard"
        
        # État du sidebar (pour desktop/tablette ET mobile)
        self.sidebar_visible = True
        self.sidebar_width = 260
        
        # Pour mobile : sidebar en overlay
        self.mobile_sidebar_overlay = None
        self.mobile_sidebar_container = None
        
        # Composants UI persistants
        self.main_container = None
        self.stats_grid_container = None
        self.sidebar = None
        
        # Flag pour éviter les reconstructions multiples
        self._is_initialized = False
        
        # Thread de vérification internet
        self._stop_checking = False
        self._status_check_thread = None
        
        # Composants UI pour le mode
        self.mode_button = None
        self.internet_status_icon = None
        self.status_text = None
        
        # 🔔 Composant de notification
        self.notification_button_container = None
        
        # Flag pour mise à jour en attente
        self._pending_status_update = None
        
        # User popup menu
        self.user_popup_menu = None
        self.user_avatar_button = None
        
        # Gestionnaire de redimensionnement
        self.page.on_resize = self.on_resize
        
        self._checking_started = False
        self.permission_manager = PermissionManager(db, auth_service)

    # ================= GESTION INTERNET =================
    
    def _on_connection_status_changed(self, is_online: bool, force_mode: Optional[bool]):
        """Callback appelé quand le statut de connexion change"""
        logger.info(f"📡 Dashboard: Statut connexion changé - online={is_online}, force={force_mode}")
        
        self._pending_status_update = (is_online, force_mode)
        
        if hasattr(self, 'mode_button') and self.mode_button is not None and \
           hasattr(self, 'internet_status_icon') and self.internet_status_icon is not None:
            self.update_mode_display()
            if self.page:
                self.page.update()
        else:
            logger.debug("Dashboard: Composants UI non encore initialisés, mise à jour différée")
    
    def check_real_internet_status(self) -> bool:
        """Vérifie le vrai statut de la connexion internet"""
        if self.sync_service is None:
            logger.warning("sync_service est None, impossible de vérifier internet")
            return False
        
        try:
            return self.sync_service.check_internet_connection()
        except AttributeError as e:
            logger.error(f"sync_service n'a pas check_internet_connection: {e}")
            return False
        except Exception as e:
            logger.error(f"Erreur check_real_internet_status: {e}")
            return False

    def start_internet_checking(self, interval_seconds: int = 10):
        """Démarre la vérification périodique de l'internet en arrière-plan"""
        if self._checking_started:
            return
        
        if self.sync_service is None:
            logger.warning("sync_service non disponible, vérification internet différée")
            return
        
        self._checking_started = True
        
        try:
            if self.connection_manager.get_force_mode() is None:
                new_status = self.check_real_internet_status()
                if hasattr(self.connection_manager, '_actual_internet_status'):
                    self.connection_manager._actual_internet_status = new_status
        except Exception as e:
            logger.error(f"Erreur vérification initiale: {e}")
        
        def check_loop():
            while not self._stop_checking:
                try:
                    if self.connection_manager.get_force_mode() is None:
                        new_status = self.check_real_internet_status()
                        if hasattr(self.connection_manager, '_actual_internet_status'):
                            if new_status != self.connection_manager._actual_internet_status:
                                self.connection_manager._actual_internet_status = new_status
                                self.connection_manager._notify_observers()
                except Exception as e:
                    logger.error(f"Erreur vérification internet: {e}")
                
                for _ in range(interval_seconds):
                    if self._stop_checking:
                        break
                    time.sleep(1)
        
        self._stop_checking = False
        self._status_check_thread = threading.Thread(target=check_loop, daemon=True)
        self._status_check_thread.start()

    def stop_internet_checking(self):
        """Arrête la vérification périodique"""
        self._stop_checking = True
        if self._status_check_thread:
            self._status_check_thread.join(timeout=2)
    
    def toggle_mode(self, e):
        """Bascule entre les modes via le ConnectionManager"""
        self.connection_manager.toggle_mode()
        status = self.connection_manager.get_display_status()
        self.show_snackbar(f"Mode: {status['text']}", ft.Colors.BLUE, 3000)
        self.update_mode_display()
        if self.notification_manager:
            self.notification_manager.update_notification_badge()
        if self.page:
            self.page.update()
    
    def get_current_mode(self) -> str:
        return self.connection_manager.get_current_mode()
    
    def is_online_mode(self) -> bool:
        return self.connection_manager.is_online_mode()
    
    def get_internet_display_status(self) -> Dict:
        status = self.connection_manager.get_display_status()
        
        color_map = {
            "green": ft.Colors.GREEN,
            "blue": ft.Colors.BLUE,
            "orange": ft.Colors.ORANGE,
            "red": ft.Colors.RED,
        }
        
        icon_map = {
            "🌐": ft.Icons.WIFI,
            "🔌": ft.Icons.WIFI,
            "✈️": ft.Icons.WIFI_OFF,
            "📡": ft.Icons.WIFI_OFF,
        }
        
        return {
            "color": color_map.get(status["color"], ft.Colors.GREY),
            "text": status["text"],
            "icon": icon_map.get(status["icon"], ft.Icons.WIFI_OFF),
            "tooltip": status["tooltip"]
        }

    def update_mode_display(self):
        """Met à jour l'affichage du bouton de mode"""
        if not hasattr(self, 'mode_button') or self.mode_button is None:
            return
        if not hasattr(self, 'internet_status_icon') or self.internet_status_icon is None:
            return
        
        try:
            status = self.get_internet_display_status()
            force_mode = self.connection_manager.get_force_mode()
            mode = self.get_current_mode()
            
            self.internet_status_icon.name = status["icon"]
            self.internet_status_icon.color = status["color"]
            self.internet_status_icon.tooltip = status["tooltip"]
            
            if force_mode is None:
                button_text = f"{'📱' if self.is_mobile() else '🌐'} {mode.upper()[:3] if self.is_mobile() else mode.upper()}"
                button_bg = ft.Colors.GREEN_700 if mode == "online" else ft.Colors.RED_700
            elif force_mode is True:
                button_text = "🔌 ON" if self.is_mobile() else "🔌 ONLINE (Forcé)"
                button_bg = ft.Colors.BLUE_700
            else:
                button_text = "✈️ OFF" if self.is_mobile() else "✈️ OFFLINE (Forcé)"
                button_bg = ft.Colors.ORANGE_700
            
            self.mode_button.content = ft.Text(button_text, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD, size=11)
            self.mode_button.bgcolor = button_bg
            
        except Exception as e:
            logger.error(f"Erreur dans update_mode_display: {e}")

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
        """Détecte si l'appareil est mobile (largeur < 768px)"""
        return (self.page.width or 0) < 768

    def is_tablet(self):
        """Détecte si l'appareil est une tablette (768px - 1024px)"""
        width = self.page.width or 0
        return 768 <= width < 1024

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
            logger.error(f"Erreur récupération ventes jour: {e}")
            return 0.0

    def get_today_expenses(self) -> float:
        """Récupère le montant des dépenses du jour"""
        branch_id = self.current_user.get('active_branch_id') or self.current_user.get('branch_id')
        try:
            if hasattr(self.db, 'get_total_expenses'):
                return self.db.get_total_expenses(branch_id, "today")
            return 0.0
        except Exception as e:
            logger.error(f"Erreur récupération dépenses jour: {e}")
            return 0.0

    def get_week_expenses(self) -> float:
        """Récupère le montant des dépenses de la semaine"""
        branch_id = self.current_user.get('active_branch_id') or self.current_user.get('branch_id')
        try:
            if hasattr(self.db, 'get_total_expenses'):
                return self.db.get_total_expenses(branch_id, "week")
            return 0.0
        except Exception as e:
            logger.error(f"Erreur récupération dépenses semaine: {e}")
            return 0.0

    def get_month_expenses(self) -> float:
        """Récupère le montant des dépenses du mois"""
        branch_id = self.current_user.get('active_branch_id') or self.current_user.get('branch_id')
        try:
            if hasattr(self.db, 'get_total_expenses'):
                return self.db.get_total_expenses(branch_id, "month")
            return 0.0
        except Exception as e:
            logger.error(f"Erreur récupération dépenses mois: {e}")
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
            logger.error(f"Erreur récupération dettes jour: {e}")
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
            logger.error(f"Erreur récupération dettes semaine: {e}")
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
            logger.error(f"Erreur récupération dettes mois: {e}")
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
                logger.error(f"Erreur vérification expiration pour {product_name}: {e}")
                
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
            logger.error(f"Erreur récupération rupture stock: {e}")
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
            logger.error(f"Erreur récupération produits jamais vendus: {e}")
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
    
    def get_user_role(self) -> str:
        """Récupère le rôle de l'utilisateur actuel"""
        role = self.current_user.get('role', '') if self.current_user else ''
        if not role and self.auth_service:
            role = self.auth_service.get_user_role()
        return role.lower() if role else 'cashier'
    
    def is_admin_or_manager(self) -> bool:
        """Vérifie si l'utilisateur a des droits admin ou gérant"""
        role = self.get_user_role()
        return role in ['admin', 'ADMIN','administrateur', 'gerant']
    
    def is_cashier(self) -> bool:
        """Vérifie si l'utilisateur est vendeur"""
        role = self.get_user_role()
        return role in ['cashier', 'vendeur', 'VENDEUR']


    def refresh_stats_grid(self):
        """Rafraîchit uniquement la grille des statistiques"""
        if self.stats_grid_container:
            self.stats_grid_container.content = self.create_stats_grid()
            self.page.update()

    def create_stats_grid(self):
        """Crée la grille des statistiques responsive selon le rôle"""
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
        
        logger.info(f"📊 Dashboard Stats: Rôle={self.get_user_role()}, "
                   f"Ventes jour={today_sales}, Dépenses jour={today_expenses}, "
                   f"Dettes jour={today_debts}, Péremptions={expiring_count}, "
                   f"Rupture stock={low_stock_count}, Jamais vendus={never_sold_count}")
        
        format_fc = lambda v: f"{v:,.0f} FC" if v >= 0 else "0 FC"
        
        # Définir toutes les cartes possibles
        all_stats = [
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
        
        # Filtrer les cartes selon le rôle
        if self.is_admin_or_manager():
            # Admin ou gérant → toutes les cartes
            stats_to_show = all_stats
            logger.info("👑 Mode ADMIN/GERANT: Affichage de toutes les cartes")
        else:
            # Vendeur (cashier) → uniquement péremptions et rupture stock
            stats_to_show = [
                ("Péremptions", str(expiring_count), ft.Icons.WARNING_AMBER, ft.Colors.ORANGE, "expiring"),
                ("Rupture stock", str(low_stock_count), ft.Icons.WARNING, ft.Colors.RED, "low_stock"),
            ]
            logger.info("💳 Mode VENDEUR: Affichage uniquement des cartes Péremptions et Rupture stock")
        
        # Ajuster le nombre de colonnes pour les vendeurs (2 cartes sur xs)
        if not self.is_admin_or_manager():
            return ft.ResponsiveRow(
                controls=[
                    ft.Container(
                        content=self.create_stat_card(title, value, icon, color, detail_type),
                        col={"xs": 12, "sm": 6, "md": 6, "lg": 4, "xl": 3},
                        padding=5,
                    )
                    for title, value, icon, color, detail_type in stats_to_show
                ],
                spacing=10,
                run_spacing=10,
            )
        else:
            return ft.ResponsiveRow(
                controls=[
                    ft.Container(
                        content=self.create_stat_card(title, value, icon, color, detail_type),
                        col={"xs": 12, "sm": 6, "md": 4, "lg": 3, "xl": 2},
                        padding=5,
                    )
                    for title, value, icon, color, detail_type in stats_to_show
                ],
                spacing=10,
                run_spacing=10,
            )

    # ================= AFFICHAGE DES DÉTAILS =================

    def show_details(self, detail_type: str):
        """Affiche les détails pour une carte spécifique (vérifie les permissions)"""
        from screens.dashboard_details_screen import DashboardDetailsScreen
        
        # Vérifier si l'utilisateur a accès à ce détail
        if not self.is_admin_or_manager():
            # Pour les vendeurs, autoriser uniquement expiring et low_stock
            if detail_type not in ["expiring", "low_stock"]:
                self.show_snackbar("🔒 Accès non autorisé pour votre rôle", ft.Colors.RED, 3000)
                return
        
        if detail_type == "today_sales":
            details_screen = DashboardDetailsScreen(
                self.page, self.db, self.sync_service, self.auth_service, 
                self.current_user, self.notification_manager,
                title="Ventes d'aujourd'hui",
                detail_type="sales",
                data={"total": self.get_today_sales_value(), "period": "today"}
            )
        elif detail_type == "today_expenses":
            expenses = self.get_expenses_for_period("today")
            details_screen = DashboardDetailsScreen(
                self.page, self.db, self.sync_service, self.auth_service,
                self.current_user, self.notification_manager,
                title="Dépenses d'aujourd'hui",
                detail_type="expenses",
                data={"items": expenses, "total": self.get_today_expenses(), "period": "today"}
            )
        elif detail_type == "week_expenses":
            expenses = self.get_expenses_for_period("week")
            details_screen = DashboardDetailsScreen(
                self.page, self.db, self.sync_service, self.auth_service,
                self.current_user, self.notification_manager,
                title="Dépenses de la semaine",
                detail_type="expenses",
                data={"items": expenses, "total": self.get_week_expenses(), "period": "week"}
            )
        elif detail_type == "month_expenses":
            expenses = self.get_expenses_for_period("month")
            details_screen = DashboardDetailsScreen(
                self.page, self.db, self.sync_service, self.auth_service,
                self.current_user, self.notification_manager,
                title="Dépenses du mois",
                detail_type="expenses",
                data={"items": expenses, "total": self.get_month_expenses(), "period": "month"}
            )
        elif detail_type == "today_debts":
            debts = self.get_debts_for_period("today")
            details_screen = DashboardDetailsScreen(
                self.page, self.db, self.sync_service, self.auth_service,
                self.current_user, self.notification_manager,
                title="Dettes d'aujourd'hui",
                detail_type="debts",
                data={"items": debts, "total": self.get_today_debts(), "period": "today"}
            )
        elif detail_type == "week_debts":
            debts = self.get_debts_for_period("week")
            details_screen = DashboardDetailsScreen(
                self.page, self.db, self.sync_service, self.auth_service,
                self.current_user, self.notification_manager,
                title="Dettes de la semaine",
                detail_type="debts",
                data={"items": debts, "total": self.get_week_debts(), "period": "week"}
            )
        elif detail_type == "month_debts":
            debts = self.get_debts_for_period("month")
            details_screen = DashboardDetailsScreen(
                self.page, self.db, self.sync_service, self.auth_service,
                self.current_user, self.notification_manager,
                title="Dettes du mois",
                detail_type="debts",
                data={"items": debts, "total": self.get_month_debts(), "period": "month"}
            )
        elif detail_type == "expiring":
            expired, expiring = self.get_expiring_products()
            details_screen = DashboardDetailsScreen(
                self.page, self.db, self.sync_service, self.auth_service,
                self.current_user, self.notification_manager,
                title="Produits expirés et proches de péremption",
                detail_type="expiring",
                data={"expired": expired, "expiring": expiring}
            )
        elif detail_type == "low_stock":
            products = self.get_low_stock_products()
            details_screen = DashboardDetailsScreen(
                self.page, self.db, self.sync_service, self.auth_service,
                self.current_user, self.notification_manager,
                title="Produits en rupture de stock",
                detail_type="low_stock",
                data={"items": products, "count": len(products)}
            )
        elif detail_type == "never_sold":
            products = self.get_never_sold_products()
            details_screen = DashboardDetailsScreen(
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

    # ================= MENU LATÉRAL (AVEC PERMISSIONS) =================

    def get_menu_items_by_role(self) -> List[Dict]:
        """
        Retourne la liste des éléments de menu en fonction du rôle de l'utilisateur.
        """
        # Récupérer le rôle depuis l'utilisateur ou l'objet auth_service
        role = self.current_user.get('role', '') if self.current_user else ''
        if not role:
            role = self.auth_service.get_user_role()
        
        logger.info(f"📋 Construction du menu pour le rôle: {role}")
        
        # Menu de base (visible par tous)
        base_menu = [
            {"key": "dashboard", "label": "Tableau de bord", "icon": "DASHBOARD", "action": "dashboard"},
            {"key": "sale", "label": "Vente", "icon": "SHOPPING_CART", "action": "sale"},
            {"key": "history", "label": "Historique", "icon": "HISTORY", "action": "history"},
        ]
        
        # Menu pour les gestionnaires (gerant, admin)
        manager_menu = [
            {"key": "products", "label": "Produits", "icon": "INVENTORY", "action": "products"},
            {"key": "cash", "label": "Trésorerie", "icon": "PAYMENT", "action": "cash"},
            {"key": "expenses", "label": "Dépenses", "icon": "MONEY_OFF", "action": "expenses"},
            {"key": "debts", "label": "Dettes", "icon": "ACCOUNT_BALANCE_WALLET", "action": "debts"},
            {"key": "invoice", "label": "Factures", "icon": "SWAP_HORIZ", "action": "invoice"},
            {"key": "stock", "label": "Rapport stock", "icon": "ASSESSMENT", "action": "stock"},
            {"key": "sync", "label": "Synchronisation", "icon": "SYNC", "action": "sync"},
        ]
        
        # Menu admin uniquement
        admin_menu = [
            {"key": "users", "label": "Utilisateurs", "icon": "PEOPLE", "action": "users"},
            {"key": "permissions", "label": "Permissions", "icon": "SECURITY", "action": "permissions"},
            {"key": "config", "label": "Configuration", "icon": "SETTINGS", "action": "config"},
            {"key": "export", "label": "Export", "icon": "DOWNLOAD", "action": "export"},
        ]
        
        # ✅ NOUVEAU: Menu pour les vendeurs (cashier/seller)
        # On retire "inventory" et "branch", on ajoute "expenses" et "debts"
        cashier_menu = [
            {"key": "expenses", "label": "Dépenses", "icon": "MONEY_OFF", "action": "expenses"},
            {"key": "debts", "label": "Dettes", "icon": "ACCOUNT_BALANCE_WALLET", "action": "debts"},
        ]
        
        # Construction du menu selon le rôle
        if role in ['admin', 'ADMIN', 'Administrateur']:
            # Admin voit tout
            final_menu = base_menu + manager_menu + admin_menu + cashier_menu
        elif role == 'gerant':
            # Gérant voit tout sauf les menus admin
            final_menu = base_menu + manager_menu + cashier_menu
        elif role in ['cashier', 'vendeur', 'VENDEUR', 'seller', 'SELLER']:
            # ✅ Vendeur voit: dashboard, vente, historique, dépenses, dettes
            # PLUS: synchronisation et abonnement
            final_menu = base_menu + cashier_menu
            logger.info("💳 Mode VENDEUR: Menu = Tableau de bord, Vente, Historique, Dépenses, Dettes")
        elif role == 'viewer':
            # Lecture seule: tableau de bord, historique, rapports
            final_menu = [
                {"key": "dashboard", "label": "Tableau de bord", "icon": "DASHBOARD", "action": "dashboard"},
                {"key": "history", "label": "Historique", "icon": "HISTORY", "action": "history"},
                {"key": "stock", "label": "Rapport stock", "icon": "ASSESSMENT", "action": "stock"},
            ]
        else:
            # Rôle par défaut (cashier)
            final_menu = base_menu + cashier_menu
        
        # ✅ Pour les vendeurs, on n'ajoute PAS "Changer succursale"
        # Pour les autres rôles, on ajoute "Changer succursale" sauf viewers
        if role not in ['cashier', 'vendeur', 'VENDEUR', 'seller', 'SELLER', 'viewer']:
            final_menu.append({"key": "branch", "label": "Changer succursale", "icon": "STORE", "action": "branch"})
        
        # Ajouter "Synchronisation" pour tous sauf viewers (et déjà dans manager_menu)
        if role not in ['viewer']:
            if "sync" not in [m["key"] for m in final_menu]:
                final_menu.append({"key": "sync", "label": "Synchronisation", "icon": "SYNC", "action": "sync"})
        
        # Ajouter "Abonnement" pour tous
        final_menu.append({"key": "abo", "label": "Abonnement", "icon": "SUBSCRIPTIONS", "action": "abo"})
        
        logger.info(f"📋 Menu construit: {len(final_menu)} éléments")
        return final_menu

    def menu_item(self, icon, text, action, key):
        """Crée un élément de menu"""
        active = self.active_menu == key
        
        menu_container = ft.Container(
            bgcolor=ft.Colors.BLUE_100 if active else None,
            border_radius=10,
            margin=ft.Margin.only(bottom=5),
            content=ft.ListTile(
                leading=ft.Icon(icon, color=ft.Colors.BLUE_800 if active else ft.Colors.BLUE_GREY_700),
                title=ft.Text(text, color=ft.Colors.BLUE_800 if active else ft.Colors.BLUE_GREY_700),
                on_click=lambda e, a=action, k=key: self._navigate(e, a, k),
            ),
        )
        
        return menu_container

    def _navigate(self, e, action, key):
        """Navigation avec fermeture du sidebar mobile"""
        self.active_menu = key
        
        # Fermer le sidebar mobile s'il est ouvert
        if self.is_mobile() and hasattr(self, 'mobile_sidebar_overlay') and self.mobile_sidebar_overlay:
            self.close_mobile_sidebar()
        
        # Exécuter l'action
        if callable(action):
            action(e)
        else:
            # Si action est une chaîne, appeler la méthode correspondante
            method_map = {
                "dashboard": self.show_dashboard,
                "sale": self.go_to_sale,
                "history": self.go_to_history,
                "products": self.go_to_products,
                "cash": self.go_to_cash_report,
                "expenses": self.go_to_expenses,
                "debts": self.go_to_debts,
                "invoice": self.go_to_invoice,
                "stock": self.go_to_stock_report,
                "inventory": self.go_to_inventory,
                "abo": self.go_to_abonnement,
                "sync": self.go_to_sync,
                "branch": self.switch_branch,
                "users": self.go_to_user_management,
                "permissions": self.go_to_permissions,
                "config": self.open_config,
                "export": self.go_to_export,
            }
            if action in method_map:
                method_map[action](e)

    def toggle_sidebar(self, e):
        """Affiche ou masque le sidebar"""
        if self.is_mobile():
            if self.mobile_sidebar_overlay and self.mobile_sidebar_overlay in self.page.overlay:
                self.close_mobile_sidebar()
            else:
                self.show_mobile_sidebar()
        else:
            self.sidebar_visible = not self.sidebar_visible
            self.update_layout()
    
    
    def show_mobile_sidebar(self):
        """Affiche le sidebar mobile en overlay"""
        if self.mobile_sidebar_overlay and self.mobile_sidebar_overlay in self.page.overlay:
            return
        
        self.mobile_sidebar_overlay = ft.Container(
            content=self.create_mobile_sidebar_content(),
            left=0,
            top=0,
            width=self.sidebar_width,
            height=float('inf'),
            bgcolor=ft.Colors.BLUE_50,
            shadow=ft.BoxShadow(blur_radius=10, spread_radius=2),
            animate_position=ft.Animation(300, ft.AnimationCurve.EASE_IN_OUT),
        )
        
        self.page.overlay.append(self.mobile_sidebar_overlay)
        self.page.update()
    
    def create_mobile_sidebar_content(self):
        """Crée le contenu du sidebar mobile avec scroll et bouton masquer"""
        menu_items = self.get_menu_items_by_role()
        
        menu_controls = []
        for item in menu_items:
            action_map = {
                "dashboard": self.show_dashboard,
                "sale": self.go_to_sale,
                "history": self.go_to_history,
                "products": self.go_to_products,
                "cash": self.go_to_cash_report,
                "expenses": self.go_to_expenses,
                "debts": self.go_to_debts,
                "invoice": self.go_to_invoice,
                "stock": self.go_to_stock_report,
                "inventory": self.go_to_inventory,
                "abo": self.go_to_abonnement,
                "sync": self.go_to_sync,
                "branch": self.switch_branch,
                "users": self.go_to_user_management,
                "permissions": self.go_to_permissions,
                "config": self.open_config,
                "export": self.go_to_export,
            }
            
            action = action_map.get(item["key"])
            if not action:
                continue
            
            menu_controls.append(
                self.menu_item(
                    getattr(ft.Icons, item["icon"], ft.Icons.CIRCLE),
                    item["label"],
                    action,
                    item["key"]
                )
            )
        
        # Ajouter déconnexion
        menu_controls.append(ft.Divider(height=10, color=ft.Colors.BLUE_200))
        menu_controls.append(
            self.menu_item(ft.Icons.LOGOUT, "Déconnexion", self.logout, "logout")
        )
        
        return ft.Column(
            [
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Text("MediGest", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_800, expand=True),
                            ft.IconButton(
                                icon=ft.Icons.CLOSE,
                                icon_color=ft.Colors.RED,
                                on_click=self.close_mobile_sidebar,
                                tooltip="Masquer le menu",
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    padding=ft.Padding.all(12),
                    bgcolor=ft.Colors.BLUE_100,
                ),
                ft.Divider(height=1, color=ft.Colors.BLUE_200),
                ft.Container(
                    content=ft.Column(menu_controls, spacing=5),
                    expand=True,
                    padding=ft.Padding.symmetric(horizontal=10, vertical=10),
                    # ✅ scroll retiré d'ici
                ),
            ],
            spacing=0,
            expand=True,
            scroll=ft.ScrollMode.AUTO,  # ✅ scroll sur le Column principal
        )
    
    def close_mobile_sidebar(self, e=None):
        """Ferme le sidebar mobile"""
        if self.mobile_sidebar_overlay and self.mobile_sidebar_overlay in self.page.overlay:
            self.page.overlay.remove(self.mobile_sidebar_overlay)
            self.mobile_sidebar_overlay = None
            self.page.update()

    def create_sidebar(self):
        """Crée le menu latéral avec filtrage par rôle"""
        menu_items = self.get_menu_items_by_role()
        
        menu_controls = []
        for item in menu_items:
            # Déterminer l'action en fonction de la clé
            action_map = {
                "dashboard": self.show_dashboard,
                "sale": self.go_to_sale,
                "history": self.go_to_history,
                "products": self.go_to_products,
                "cash": self.go_to_cash_report,
                "expenses": self.go_to_expenses,
                "debts": self.go_to_debts,
                "invoice": self.go_to_invoice,
                "stock": self.go_to_stock_report,
                "inventory": self.go_to_inventory,
                "abo": self.go_to_abonnement,
                "sync": self.go_to_sync,
                "branch": self.switch_branch,
                "users": self.go_to_user_management,
                "permissions": self.go_to_permissions,
                "config": self.open_config,
                "export": self.go_to_export,
            }
            
            action = action_map.get(item["key"])
            if not action:
                continue
            
            menu_controls.append(
                self.menu_item(
                    getattr(ft.Icons, item["icon"], ft.Icons.CIRCLE),
                    item["label"],
                    action,
                    item["key"]
                )
            )
        
        # Ajouter déconnexion
        menu_controls.append(ft.Divider(height=20, color=ft.Colors.BLUE_200))
        menu_controls.append(
            self.menu_item(ft.Icons.LOGOUT, "Déconnexion", self.logout, "logout")
        )
        
        # ✅ CORRECTION: scroll sur Column, pas sur Container
        return ft.Container(
            width=self.sidebar_width if self.sidebar_visible else 0,
            bgcolor=ft.Colors.BLUE_50,
            padding=10 if self.sidebar_visible else 0,
            animate=ft.Animation(300, ft.AnimationCurve.EASE_IN_OUT),
            visible=not self.is_mobile(),
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("MediGest", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_800, expand=True),
                            ft.IconButton(
                                icon=ft.Icons.CHEVRON_LEFT if self.sidebar_visible else ft.Icons.MENU,
                                icon_color=ft.Colors.BLUE_800,
                                on_click=self.toggle_sidebar,
                                tooltip="Masquer le menu",
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Divider(height=20, color=ft.Colors.BLUE_200),
                    ft.Container(
                        content=ft.Column(menu_controls, spacing=5),
                        expand=True,
                        # ✅ scroll retiré d'ici
                    ),
                ],
                scroll=ft.ScrollMode.AUTO,  # ✅ scroll sur Column
                expand=True,
                spacing=5,
            ),
        )

    # ================= MÉTHODES DE NAVIGATION =================

    def go_to_user_management(self, e):
        """Ouvre l'écran de gestion des utilisateurs"""
        try:
            from screens.user_management_screen import UserManagementScreen
            user_mgmt = UserManagementScreen(
                self.page, self.db, self.sync_service, 
                self.auth_service, self.current_user, self.notification_manager
            )
            user_mgmt.show()
        except ImportError:
            self.show_snackbar("👥 Gestion des utilisateurs - Fonctionnalité à venir", ft.Colors.ORANGE, 3000)
    
    def go_to_permissions(self, e):
        """Ouvre l'écran de gestion des permissions (admin uniquement)"""
        try:
            from screens.permission_screen import PermissionScreen
            perm_screen = PermissionScreen(
                self.page, self.db, self.sync_service,
                self.auth_service, self.current_user, self.notification_manager,
                on_back=self.show_dashboard
            )
            perm_screen.show()
        except PermissionError as err:
            self.show_snackbar(str(err), ft.Colors.RED)
    
    def go_to_export(self, e):
        """Ouvre l'écran d'exportation"""
        try:
            from screens.export_screen import ExportScreen
            export_screen = ExportScreen(
                self.page, self.db, self.sync_service,
                self.auth_service, self.current_user, self.notification_manager
            )
            export_screen.show()
        except ImportError:
            self.show_snackbar("📤 Écran d'exportation - Fonctionnalité à venir", ft.Colors.ORANGE, 3000)
    
    def go_to_inventory(self, e):
        """Ouvre l'écran d'inventaire"""
        try:
            from screens.inventory_screen import InventoryScreen
            inventory_screen = InventoryScreen(
                self.page, self.db, self.sync_service,
                self.auth_service, self.current_user, self.notification_manager
            )
            inventory_screen.show()
        except ImportError:
            self.show_snackbar("📋 Écran d'inventaire - Fonctionnalité à venir", ft.Colors.ORANGE, 3000)

    # ================= HEADER =================

    def create_notification_button(self):
        """Crée le bouton de notification avec badge"""
        if not self.notification_manager:
            return None
        
        container = self.notification_manager.create_notification_button()
        
        def on_notification_update(_):
            if self.page:
                self.page.update()
        
        self.notification_manager.add_observer(on_notification_update)
        
        return container

    def get_user_initial(self) -> str:
        """Récupère l'initiale de l'utilisateur pour l'avatar"""
        full_name = self.current_user.get('full_name', 'U')
        if full_name and len(full_name) > 0:
            return full_name[0].upper()
        return 'U'

    def create_header(self):
        """Crée l'en-tête avec informations utilisateur"""
        
        status = self.get_internet_display_status()
        force_mode = self.connection_manager.get_force_mode()
        mode = self.get_current_mode()
        
        self.internet_status_icon = ft.Icon(
            status["icon"],
            color=status["color"],
            size=16,
            tooltip=status["tooltip"],
        )
        
        if force_mode is None:
            button_text = f"{'📱' if self.is_mobile() else '🌐'} {mode.upper()[:3] if self.is_mobile() else mode.upper()}"
            button_bg = ft.Colors.GREEN_700 if mode == "online" else ft.Colors.RED_700
        elif force_mode is True:
            button_text = "🔌 ON" if self.is_mobile() else "🔌 ONLINE (Forcé)"
            button_bg = ft.Colors.BLUE_700
        else:
            button_text = "✈️ OFF" if self.is_mobile() else "✈️ OFFLINE (Forcé)"
            button_bg = ft.Colors.ORANGE_700
        
        self.mode_button = ft.Button(
            content=ft.Text(button_text, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD, size=11),
            bgcolor=button_bg,
            on_click=self.toggle_mode,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=20),
                padding=ft.Padding.symmetric(horizontal=8, vertical=5),
            ),
            tooltip="Changer le mode",
        )
        
        sidebar_toggle_button = ft.IconButton(
            icon=ft.Icons.MENU,
            icon_color=ft.Colors.WHITE,
            on_click=self.toggle_sidebar,
            tooltip="Afficher le menu",
        )
        
        # Menu utilisateur
        user_initial = self.get_user_initial()
        user_name = self.current_user.get('full_name', 'Utilisateur')
        branch_name = self.current_user.get('branch_name', 'N/A')
        user_role = self.current_user.get('role', 'cashier')
        
        # Traduire le rôle pour l'affichage
        role_display = {
            'admin': '👑 Administrateur',
            'gerant': '📊 Gérant',
            'cashier': '💳 Vendeur',
            'viewer': '👁️ Lecture seule'
        }.get(user_role, '👤 Utilisateur')
        
        user_menu_items = [
            ft.PopupMenuItem(
                content=ft.Container(
                    content=ft.Column([
                        ft.Text(user_name, weight=ft.FontWeight.BOLD, size=14),
                        ft.Text(branch_name, size=12, color=ft.Colors.GREY_700),
                        ft.Text(role_display, size=10, color=ft.Colors.BLUE_700),
                    ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=ft.Padding.all(10),
                ),
                height=75,
            ),
            ft.PopupMenuItem(),
            ft.PopupMenuItem(
                content=ft.Row([
                    ft.Icon(ft.Icons.SYNC, size=18, color=ft.Colors.BLUE),
                    ft.Text("Synchroniser", size=13),
                ], spacing=10),
                on_click=self.sync_data,
            ),
            ft.PopupMenuItem(
                content=ft.Row([
                    ft.Icon(ft.Icons.LOGOUT, size=18, color=ft.Colors.RED),
                    ft.Text("Déconnexion", size=13),
                ], spacing=10),
                on_click=self.logout,
            ),
        ]
        
        # Ajouter configuration si admin ou gerant
        if user_role in ['admin', 'gerant']:
            user_menu_items.insert(-1, ft.PopupMenuItem(
                content=ft.Row([
                    ft.Icon(ft.Icons.SETTINGS, size=18, color=ft.Colors.ORANGE),
                    ft.Text("Configuration", size=13),
                ], spacing=10),
                on_click=self.open_config,
            ))
        
        user_menu_button = ft.PopupMenuButton(
            content=ft.CircleAvatar(
                content=ft.Text(user_initial, size=16, weight=ft.FontWeight.BOLD),
                bgcolor=ft.Colors.BLUE_300,
                color=ft.Colors.WHITE,
                radius=18,
            ),
            items=user_menu_items,
        )
        
        config_button = ft.IconButton(
            icon=ft.Icons.SETTINGS,
            icon_color=ft.Colors.WHITE,
            on_click=self.open_config,
            tooltip="Configuration",
            visible=user_role in ['admin', 'gerant'],  # Seulement pour admin/gerant
        )
        
        notification_button = None
        if self.notification_manager:
            notification_button = self.create_notification_button()
        
        action_buttons = []
        
        if self.is_mobile():
            action_buttons = [
                self.mode_button,
            ]
            if config_button.visible:
                action_buttons.append(config_button)
            if notification_button:
                action_buttons.append(notification_button)
            action_buttons.append(user_menu_button)
        else:
            action_buttons = [
                ft.Container(
                    content=ft.Row(
                        [
                            self.internet_status_icon,
                            ft.Text(status["text"], size=11, color=status["color"], weight=ft.FontWeight.BOLD),
                        ],
                        spacing=3,
                    ),
                    bgcolor=ft.Colors.WHITE,
                    padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                    border_radius=15,
                ),
                self.mode_button,
            ]
            if config_button.visible:
                action_buttons.append(config_button)
            if notification_button:
                action_buttons.append(notification_button)
            action_buttons.extend([
                ft.IconButton(
                    icon=ft.Icons.SYNC,
                    icon_color=ft.Colors.WHITE,
                    on_click=self.sync_data,
                    tooltip="Synchroniser",
                ),
                user_menu_button,
            ])
        
        header = ft.Container(
            bgcolor=ft.Colors.BLUE_700,
            padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            content=ft.Row(
                [
                    sidebar_toggle_button,
                    ft.Container(
                        content=ft.Text("MediGest", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                        visible=not self.is_mobile(),
                        expand=not self.is_mobile(),
                    ),
                    ft.Row(action_buttons, spacing=6, tight=True),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )
        
        if self._pending_status_update:
            self.update_mode_display()
            self._pending_status_update = None
        
        return header

    # ================= CONTENU PRINCIPAL =================

    def create_main_content(self):
        """Crée le contenu principal du dashboard"""
        self.stats_grid_container = ft.Container(
            content=self.create_stats_grid(),
            expand=True,
        )
        
        force_mode = self.connection_manager.get_force_mode()
        is_vendeur = self.is_cashier()
        
        # Message personnalisé pour les vendeurs
        vendeur_message = None
        if is_vendeur:
            vendeur_message = ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.INFO, color=ft.Colors.BLUE, size=14),
                        ft.Text(
                            "👤 Vue vendeur: Affichage des alertes de péremption et rupture de stock uniquement",
                            size=11,
                            color=ft.Colors.BLUE_GREY_600,
                        ),
                    ],
                    spacing=5,
                ),
                margin=ft.Margin.only(bottom=8),
                padding=ft.Padding.symmetric(horizontal=10, vertical=5),
                bgcolor=ft.Colors.BLUE_50,
                border_radius=8,
            )
        
        return ft.Container(
            expand=True,
            padding=ft.Padding.all(12 if self.is_mobile() else 15),
            content=ft.Column(
                [
                    ft.Text(
                        "Tableau de bord",
                        size=18 if self.is_mobile() else 20,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.BLUE_GREY_800,
                    ),
                    ft.Container(height=4),
                    vendeur_message if vendeur_message else ft.Container(height=0),
                    ft.Container(height=4 if vendeur_message else 0),
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.WARNING_AMBER, color=ft.Colors.ORANGE, size=14),
                                ft.Text(
                                    "Mode forcé activé",
                                    size=11,
                                    color=ft.Colors.ORANGE,
                                ),
                            ],
                            spacing=5,
                        ),
                        visible=force_mode is not None,
                        margin=ft.Margin.only(bottom=8),
                    ),
                    self.stats_grid_container,
                ],
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                spacing=8,
            ),
        )

    # ================= AFFICHAGE PRINCIPAL =================

    def show_dashboard(self, e=None):
        """Affiche le dashboard avec layout responsive"""
        self.active_menu = "dashboard"
        
        # Rafraîchir le rôle de l'utilisateur depuis la base
        self.current_user = self.auth_service.get_current_user()
        
        if not self._is_initialized:
            self.init_layout()
            self._is_initialized = True
        else:
            self.update_layout()
        
        if self.notification_manager:
            self.notification_manager.update_notification_badge()

    def init_layout(self):
        """Initialise le layout pour la première fois"""
        self.page.clean()
        self.page.bgcolor = ft.Colors.GREY_50
        self.page.padding = 0
        self.page.spacing = 0
        
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
        
        if self.is_mobile():
            self.main_container = safe_content
        else:
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
        
        self.start_internet_checking()

    def update_layout(self):
        """Met à jour le layout lors du redimensionnement ou du toggle sidebar"""
        if not self._is_initialized:
            return
        
        self.page.controls.clear()
        
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
        
        if self.is_mobile():
            new_layout = safe_content
        else:
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
        """Alias pour show_dashboard"""
        self.show_dashboard(e)

    def refresh_data(self, e=None):
        """Rafraîchit les données du dashboard"""
        self.refresh_stats_grid()

    def __del__(self):
        """Nettoyage lors de la destruction"""
        self.stop_internet_checking()
        if hasattr(self, 'mobile_sidebar_overlay') and self.mobile_sidebar_overlay:
            try:
                if self.mobile_sidebar_overlay in self.page.overlay:
                    self.page.overlay.remove(self.mobile_sidebar_overlay)
            except:
                pass

    # ================= SYNC ET NAVIGATION =================

    def sync_data(self, e):
        """Synchroniser les données avec le serveur"""
        if not self.is_online_mode():
            self.show_snackbar("⚠️ Mode OFFLINE activé - Impossible de synchroniser", ft.Colors.ORANGE, 4000)
            return
        
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
                self.show_snackbar(f"Erreur: {str(err)}", ft.Colors.RED)
        
        self.show_snackbar("Synchronisation en cours...", ft.Colors.BLUE)
        threading.Thread(target=sync_in_background, daemon=True).start()

    def go_to_sync(self, e):
        """Ouvre l'écran de synchronisation"""
        from screens.sync_screen import SyncScreen
        
        sync_screen = SyncScreen(
            page=self.page,
            db_manager=self.db,
            sync_service=self.sync_service,
            auth_service=self.auth_service,
            on_back=lambda: self.show_dashboard()  # Callback pour revenir au dashboard
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
    
    def open_config(self, e):
        """Ouvre l'écran de configuration"""
        from screens.config_screen import ConfigScreen
        
        self.config_screen = ConfigScreen(
            page=self.page,
            db_manager=self.db,
            auth_service=self.auth_service,
            sync_service=self.sync_service,
            on_config_changed=self.on_config_changed,
            on_back=self.close_config,
            notification_manager=self.notification_manager
        )
        
        self.config_screen.show()

    def close_config(self):
        """Ferme l'écran de configuration et revient au dashboard"""
        if hasattr(self, 'config_screen') and self.config_screen:
            self.config_screen = None
        
        # Rafraîchir l'utilisateur au cas où le rôle a changé
        self.current_user = self.auth_service.get_current_user()
        self.show_dashboard()

    def on_config_changed(self, new_config):
        """Callback quand la configuration change"""
        logger.info(f"Configuration mise à jour: {new_config}")
        self.page.theme_mode = ft.ThemeMode.DARK if new_config.get('dark_theme') else ft.ThemeMode.LIGHT
        if hasattr(self, 'mode_button'):
            self.update_mode_display()
        self.page.update()

    def logout(self, e):
        """Déconnecter l'utilisateur"""
        self.stop_internet_checking()
        
        if hasattr(self, 'mobile_sidebar_overlay') and self.mobile_sidebar_overlay:
            try:
                if self.mobile_sidebar_overlay in self.page.overlay:
                    self.page.overlay.remove(self.mobile_sidebar_overlay)
            except:
                pass
            self.mobile_sidebar_overlay = None
        
        # Déconnexion via auth_service
        self.auth_service.logout()
        
        # Rediriger vers l'écran de login
        from screens.login_screen import LoginScreen
        login = LoginScreen(self.page, self.db, self.sync_service, self.auth_service)
        login.show()