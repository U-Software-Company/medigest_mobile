import flet as ft
from datetime import datetime
import sqlite3
import os
import logging

logger = logging.getLogger(__name__)


class StockReportScreen:
    def __init__(self, page: ft.Page, db, sync_service, auth_service, current_user, connection_manager=None):
        self.page = page
        self.db = db
        self.sync_service = sync_service
        self.auth_service = auth_service
        self.current_user = current_user
        self.connection_manager = connection_manager
        
        self.search_field = None
        self.summary_row = None
        self.products_list_view = None
        self.refresh_button = None
        self.status_text = None
        
        # S'abonner aux changements de connexion
        if self.connection_manager:
            self.connection_manager.register_observer(self._on_connection_changed)
    
    # =========================================================
    # GESTION DE LA CONNEXION
    # =========================================================
    def _on_connection_changed(self, is_online: bool, force_mode):
        """Callback appelé quand l'état de connexion change"""
        if hasattr(self, 'status_text') and self.status_text:
            self._update_connection_status(is_online, force_mode)
    
    def _update_connection_status(self, is_online: bool, force_mode=None):
        """Met à jour l'affichage du statut de connexion"""
        if not hasattr(self, 'status_text') or not self.status_text:
            return
        
        if is_online:
            self.status_text.value = "🟢 En ligne - Données serveur disponibles"
            self.status_text.color = ft.Colors.GREEN
            if hasattr(self, 'refresh_button') and self.refresh_button:
                self.refresh_button.disabled = False
        else:
            self.status_text.value = "🔴 Hors ligne - Affichage des données locales uniquement"
            self.status_text.color = ft.Colors.RED_700
            if hasattr(self, 'refresh_button') and self.refresh_button:
                self.refresh_button.disabled = False
        
        self.page.update()
    
    def is_online(self) -> bool:
        """Vérifie si on est en mode online"""
        if self.connection_manager:
            return self.connection_manager.is_online_mode()
        return self.sync_service and self.sync_service.check_internet_connection()
    
    # =========================================================
    # OUTILS
    # =========================================================
    def _branch_id(self):
        """Récupère l'ID de la branche"""
        branch_id = (self.current_user.get("active_branch_id") or 
                    self.current_user.get("branch_id") or
                    self.current_user.get("current_branch_id"))
        
        if branch_id is None:
            user = self.auth_service.get_current_user()
            if user:
                branch_id = user.get("active_branch_id") or user.get("branch_id")
        
        return branch_id
    
    def _get_product_attr(self, product, attr_name, default=None):
        """Récupère un attribut d'un produit (dictionnaire ou objet)"""
        if isinstance(product, dict):
            return product.get(attr_name, default)
        else:
            return getattr(product, attr_name, default)
    
    def _product_name(self, product):
        name = self._get_product_attr(product, 'name')
        return str(name) if name else "N/A"
    
    def _product_code(self, product):
        code = self._get_product_attr(product, 'code')
        return str(code) if code else "N/A"
    
    def _product_stock(self, product):
        stock = self._get_product_attr(product, 'quantity')
        if stock is None:
            stock = self._get_product_attr(product, 'stock', 0)
        return self._safe_int(stock, 0)
    
    def _product_price(self, product):
        price = self._get_product_attr(product, 'selling_price')
        if price is None:
            price = self._get_product_attr(product, 'price', 0)
        return self._safe_float(price, 0.0)
    
    def _product_id(self, product):
        server_id = self._get_product_attr(product, 'server_id')
        if server_id:
            return server_id
        return self._get_product_attr(product, 'id')
    
    def _safe_int(self, value, default=0):
        try:
            if value is None or value == "":
                return default
            return int(float(value))
        except Exception:
            return default
    
    def _safe_float(self, value, default=0.0):
        try:
            if value is None or value == "":
                return default
            return float(value)
        except Exception:
            return default
    
    def _format_money(self, amount):
        try:
            return f"{float(amount):,.0f} FC"
        except Exception:
            return "0 FC"
    
    def show_snackbar(self, message: str, color):
        snack = ft.SnackBar(
            content=ft.Text(message),
            bgcolor=color,
            duration=3000,
            show_close_icon=True,
        )
        self.page.snack_bar = snack
        snack.open = True
        self.page.update()
    
    def show_error(self, message: str):
        self.show_snackbar(message, ft.Colors.RED)
    
    def show_success(self, message: str):
        self.show_snackbar(message, ft.Colors.GREEN)
    
    def show_info(self, message: str):
        self.show_snackbar(message, ft.Colors.BLUE)
    
    def show_warning(self, message: str):
        self.show_snackbar(message, ft.Colors.ORANGE)
    
    # =========================================================
    # SYNC PRODUITS
    # =========================================================
    def sync_products_from_server(self):
        """Synchronise les produits depuis le serveur"""
        if not self.is_online():
            self.show_warning("Mode hors ligne - Impossible de synchroniser les produits")
            return False
        
        if not self.sync_service:
            self.show_warning("Service de synchronisation non disponible")
            return False
        
        try:
            self.show_info("🔄 Synchronisation des produits en cours...")
            branch_id = self._branch_id()
            
            # Utiliser la méthode améliorée d'import
            result = self.sync_service.import_products_improved(branch_id)
            
            if result.get("success"):
                count = result.get("count", 0)
                self.show_success(f"✅ {count} produits synchronisés depuis le serveur")
                return True
            else:
                error = result.get("error", "Erreur inconnue")
                self.show_error(f"❌ Erreur: {error[:100]}")
                return False
                
        except Exception as e:
            logger.error(f"Erreur sync_products_from_server: {e}")
            self.show_error(f"Erreur: {str(e)[:100]}")
            return False
    
    def get_sold_quantity(self, product_id, branch_id):
        """Récupère la quantité vendue d'un produit"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COALESCE(SUM(quantity), 0) as total
                    FROM sales 
                    WHERE product_id = ? AND branch_id = ?
                """, (str(product_id), str(branch_id)))
                row = cursor.fetchone()
                return self._safe_int(row['total'] if row else 0, 0)
        except Exception as e:
            logger.error(f"Erreur get_sold_quantity: {e}")
            return 0
    
    def get_borrowed_quantity(self, product_id, branch_id):
        """Récupère la quantité empruntée d'un produit"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute("""
                        SELECT COALESCE(SUM(quantity), 0) as total
                        FROM debts 
                        WHERE product_id = ? AND branch_id = ? AND status IN ('pending', 'partial')
                    """, (str(product_id), str(branch_id)))
                    row = cursor.fetchone()
                    if row and 'total' in row.keys():
                        return self._safe_int(row['total'], 0)
                except sqlite3.OperationalError as e:
                    if "no such column: quantity" in str(e):
                        logger.info("La table debts n'a pas de colonne quantity")
                        return 0
                    raise e
                return 0
        except Exception as e:
            logger.error(f"Erreur get_borrowed_quantity: {e}")
            return 0
    
    def get_available_stock(self, stock, sold, borrowed):
        """Calcule le stock disponible restant"""
        return max(0, stock - sold - borrowed)
    
    # =========================================================
    # AFFICHAGE PRINCIPAL
    # =========================================================
    def show(self):
        self.page.clean()
        
        # Statut de connexion
        is_online = self.is_online()
        status_text = "🟢 En ligne" if is_online else "🔴 Hors ligne"
        status_color = ft.Colors.GREEN if is_online else ft.Colors.RED_700
        
        header = ft.Container(
            content=ft.Row([
                ft.IconButton(icon=ft.Icons.ARROW_BACK, on_click=lambda e: self.go_back(), icon_color=ft.Colors.WHITE),
                ft.Text("Rapport de stock", size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                ft.Row([
                    ft.IconButton(
                        icon=ft.Icons.SYNC, 
                        on_click=lambda e: self.refresh_data(), 
                        icon_color=ft.Colors.WHITE, 
                        tooltip="Synchroniser depuis le serveur"
                    ),
                    ft.IconButton(
                        icon=ft.Icons.PICTURE_AS_PDF, 
                        on_click=self.open_pdf_report, 
                        icon_color=ft.Colors.WHITE, 
                        tooltip="Voir rapport PDF"
                    ),
                ]),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=10,
            bgcolor=ft.Colors.GREEN_700,
        )
        
        # Barre de statut
        self.status_text = ft.Text(status_text, size=12, color=status_color)
        
        # ✅ CORRECTION ICI: utiliser content au lieu de text
        self.refresh_button = ft.ElevatedButton(
            content=ft.Text("Actualiser"),
            icon=ft.Icons.REFRESH,
            on_click=lambda e: self.refresh_data(),
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_200),
            height=35,
        )
        
        status_bar = ft.Container(
            content=ft.Row([
                self.status_text,
                ft.Text("•", size=12, color=ft.Colors.GREY_400),
                ft.Text(f"Dernière sync: {self._get_last_sync_time()}", size=11, color=ft.Colors.GREY_600),
                self.refresh_button,
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=ft.Padding.symmetric(horizontal=10, vertical=5),
            bgcolor=ft.Colors.GREY_50,
        )
        
        self.search_field = ft.TextField(
            hint_text="Rechercher un produit (nom, code)...",
            prefix_icon=ft.Icons.SEARCH,
            on_change=self.filter_products,
            expand=True,
            border_radius=30,
            filled=True,
        )
        
        self.summary_row = ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_AROUND,
            wrap=True,
        )
        
        table_header = ft.Container(
            content=ft.Row([
                ft.Container(content=ft.Text("Produit", size=12, weight=ft.FontWeight.BOLD), width=140),
                ft.Container(content=ft.Text("Stock", size=12, weight=ft.FontWeight.BOLD), width=60, alignment=ft.Alignment.CENTER),
                ft.Container(content=ft.Text("Vendu", size=12, weight=ft.FontWeight.BOLD), width=60, alignment=ft.Alignment.CENTER),
                ft.Container(content=ft.Text("Emprunté", size=12, weight=ft.FontWeight.BOLD), width=70, alignment=ft.Alignment.CENTER),
                ft.Container(content=ft.Text("Reste", size=12, weight=ft.FontWeight.BOLD), width=60, alignment=ft.Alignment.CENTER),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=ft.Padding.all(8),
            bgcolor=ft.Colors.GREY_200,
            border_radius=5,
            margin=ft.Margin.only(top=10, left=10, right=10),
        )
        
        self.products_list_view = ft.ListView(expand=True, spacing=5, padding=10)
        
        # Charger les données
        self.load_stock_report()
        
        main_content = ft.Column([
            header,
            status_bar,
            ft.Container(content=self.search_field, padding=10),
            self.summary_row,
            table_header,
            self.products_list_view,
        ], expand=True, spacing=10)
        
        self.page.add(main_content)
        self.page.update()
    
    def _get_last_sync_time(self):
        """Récupère la dernière date de synchronisation"""
        try:
            user = self.auth_service.get_current_user()
            if user and user.get('last_sync'):
                last_sync = user.get('last_sync')
                if isinstance(last_sync, str):
                    try:
                        dt = datetime.fromisoformat(last_sync)
                        return dt.strftime("%d/%m/%Y %H:%M")
                    except:
                        return last_sync[:16]
            return "Jamais"
        except Exception:
            return "Jamais"
    
    def refresh_data(self):
        """Actualise les données - synchronise depuis le serveur puis recharge"""
        def refresh():
            if self.is_online():
                # Désactiver le bouton pendant la synchronisation
                self.refresh_button.disabled = True
                self.refresh_button.content = ft.Text("Synchronisation...")
                self.page.update()
                
                try:
                    # Synchroniser les produits
                    success = self.sync_products_from_server()
                    
                    if success:
                        # Mettre à jour le statut
                        self.status_text.value = "🟢 En ligne - Données synchronisées"
                        self.status_text.color = ft.Colors.GREEN
                        
                        # Recharger l'affichage
                        self.load_stock_report(self.search_field.value if self.search_field else "")
                        self.show_success("Données actualisées avec succès")
                    else:
                        # En cas d'échec, utiliser les données locales
                        self.load_stock_report(self.search_field.value if self.search_field else "")
                        self.show_warning("Synchronisation partielle - Utilisation des données locales")
                        
                except Exception as e:
                    logger.error(f"Erreur refresh: {e}")
                    self.load_stock_report(self.search_field.value if self.search_field else "")
                    self.show_error(f"Erreur: {str(e)[:100]}")
                finally:
                    self.refresh_button.disabled = False
                    self.refresh_button.content = ft.Text("Actualiser")
                    self.page.update()
            else:
                # Mode hors ligne - simplement recharger
                self.load_stock_report(self.search_field.value if self.search_field else "")
                self.show_info("Mode hors ligne - Affichage des données locales")
        
        # Remplacer asyncio.run par un appel direct
        refresh()
    
    def load_stock_report(self, search_term=""):
        """Charger le rapport de stock"""
        branch_id = self._branch_id()
        
        # Récupérer les produits (locaux si offline, ou déjà synchronisés)
        try:
            products = self.db.get_products(branch_id)
            if not products:
                # Essayer d'obtenir les produits via sync service si en ligne
                if self.is_online() and self.sync_service:
                    self.sync_products_from_server()
                    products = self.db.get_products(branch_id)
        except Exception as e:
            logger.error(f"Erreur chargement produits: {e}")
            products = []
        
        # Filtrer
        if search_term:
            search_term_lower = search_term.lower()
            filtered_products = []
            for p in products:
                name = self._product_name(p).lower()
                code = self._product_code(p).lower()
                if search_term_lower in name or search_term_lower in code:
                    filtered_products.append(p)
            products = filtered_products
        
        if not products:
            self.summary_row.controls = [
                self.create_summary_card("Total produits", "0", ft.Icons.INVENTORY, ft.Colors.BLUE),
                self.create_summary_card("Stock faible", "0", ft.Icons.WARNING, ft.Colors.ORANGE),
                self.create_summary_card("Rupture", "0", ft.Icons.ERROR, ft.Colors.RED),
                self.create_summary_card("Plus dispo", "0", ft.Icons.REMOVE_SHOPPING_CART, ft.Colors.PURPLE),
            ]
            self.products_list_view.controls.clear()
            self.products_list_view.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.Icon(ft.Icons.INVENTORY, size=80, color=ft.Colors.GREY_400),
                        ft.Text("Aucun produit trouvé", size=16, color=ft.Colors.GREY_600),
                        ft.Text("Utilisez le bouton Actualiser pour synchroniser", size=12, color=ft.Colors.GREY_500),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
                    alignment=ft.alignment.center,
                    expand=True,
                    padding=50,
                )
            )
            self.page.update()
            return
        
        # Calculer les statistiques
        total_products = len(products)
        low_stock_count = sum(1 for p in products if self._product_stock(p) < 10)
        out_of_stock_count = sum(1 for p in products if self._product_stock(p) == 0)
        
        # Calculer le nombre de produits avec stock disponible <= 0
        products_with_no_available = 0
        for p in products:
            product_id = self._product_id(p)
            stock = self._product_stock(p)
            sold = self.get_sold_quantity(product_id, branch_id)
            borrowed = self.get_borrowed_quantity(product_id, branch_id)
            available = self.get_available_stock(stock, sold, borrowed)
            if available <= 0:
                products_with_no_available += 1
        
        # Mettre à jour le résumé
        self.summary_row.controls = [
            self.create_summary_card("Total produits", str(total_products), ft.Icons.INVENTORY, ft.Colors.BLUE),
            self.create_summary_card("Stock faible", str(low_stock_count), ft.Icons.WARNING, ft.Colors.ORANGE),
            self.create_summary_card("Rupture", str(out_of_stock_count), ft.Icons.ERROR, ft.Colors.RED),
            self.create_summary_card("Plus dispo", str(products_with_no_available), ft.Icons.REMOVE_SHOPPING_CART, ft.Colors.PURPLE),
        ]
        
        # Afficher les produits
        self.products_list_view.controls.clear()
        
        for product in products:
            product_row = self.create_product_row(product)
            self.products_list_view.controls.append(product_row)
        
        self.page.update()
    
    def create_summary_card(self, title, value, icon, color):
        return ft.Container(
            content=ft.Column([
                ft.Icon(icon, color=color, size=24),
                ft.Text(title, size=11, text_align=ft.TextAlign.CENTER),
                ft.Text(value, size=16, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=3),
            padding=8,
            bgcolor=ft.Colors.WHITE,
            border_radius=8,
            shadow=ft.BoxShadow(blur_radius=3, color=ft.Colors.GREY_300),
            width=95,
        )
    
    def create_product_row(self, product):
        """Créer une ligne de produit"""
        product_id = self._product_id(product)
        branch_id = self._branch_id()
        
        stock = self._product_stock(product)
        sold_qty = self.get_sold_quantity(product_id, branch_id)
        borrowed_qty = self.get_borrowed_quantity(product_id, branch_id)
        available = self.get_available_stock(stock, sold_qty, borrowed_qty)
        
        name = self._product_name(product)
        code = self._product_code(product)
        
        # Couleurs
        stock_color = ft.Colors.GREEN if stock > 10 else ft.Colors.ORANGE if stock > 0 else ft.Colors.RED
        available_color = ft.Colors.GREEN if available > 10 else ft.Colors.ORANGE if available > 0 else ft.Colors.RED
        
        return ft.Container(
            content=ft.Row([
                ft.Container(
                    content=ft.Column([
                        ft.Text(name, size=14, weight=ft.FontWeight.BOLD),
                        ft.Text(f"Code: {code}", size=10, color=ft.Colors.GREY_600),
                    ], spacing=2),
                    width=140,
                ),
                ft.Container(
                    content=ft.Text(str(stock), size=14, weight=ft.FontWeight.BOLD, color=stock_color),
                    width=60,
                    alignment=ft.Alignment.CENTER,
                ),
                ft.Container(
                    content=ft.Text(str(sold_qty), size=14, color=ft.Colors.BLUE_700),
                    width=60,
                    alignment=ft.Alignment.CENTER,
                ),
                ft.Container(
                    content=ft.Text(str(borrowed_qty), size=14, color=ft.Colors.ORANGE_700),
                    width=70,
                    alignment=ft.Alignment.CENTER,
                ),
                ft.Container(
                    content=ft.Text(str(available), size=14, weight=ft.FontWeight.BOLD, color=available_color),
                    width=60,
                    alignment=ft.Alignment.CENTER,
                ),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=ft.Padding.all(8),
            border=ft.border.all(0.5, ft.Colors.GREY_300),
            border_radius=5,
            margin=ft.Margin.only(bottom=2),
        )
    
    def filter_products(self, e):
        self.load_stock_report(self.search_field.value if self.search_field else "")
    
    def open_pdf_report(self, e):
        """Ouvre l'écran PDF avec le rapport de stock"""
        try:
            from screens.stock_pdf_screen import StockPdfScreen
            pdf_screen = StockPdfScreen(
                self.page,
                self.db,
                self.sync_service,
                self.auth_service,
                self.current_user,
                self.connection_manager
            )
            pdf_screen.show()
        except ImportError:
            self.show_error("Module PDF non disponible")
    
    def go_back(self):
        from screens.dashboard_screen import DashboardScreen
        dashboard = DashboardScreen(
            self.page, 
            self.db, 
            self.sync_service, 
            self.auth_service, 
            self.current_user,
            self.connection_manager
        )
        dashboard.show()