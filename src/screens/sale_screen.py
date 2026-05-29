# sale_screen.py - Version avec synchronisation automatique des produits
# Met à jour les produits depuis le serveur toutes les minutes en mode online

import flet as ft
from datetime import datetime, timedelta
from .cart_manager import CartManager
from utils.print_manager import PrintManager 
from services.connection_manager import ConnectionManager
from typing import Optional, Dict, List
import logging
import requests
import threading

logger = logging.getLogger(__name__)


class SaleScreen:
    def __init__(self, page: ft.Page, db, sync_service, auth_service, current_user):
        self.page = page
        self.db = db
        self.sync_service = sync_service
        self.auth_service = auth_service
        self.current_user = current_user

        self.search_field = None
        self.cart_button = None
        self.products_list_view = None
        self.products_list = []
        self.cart_count = 0
        self.cart_manager = CartManager(db)
        self._is_header_initialized = False
        
        # ========== CONFIGURATION ==========
        self.auto_generate_receipt = True
        self.sale_confirmation_required = True
        
        # ========== SYNC AUTO PRODUITS (initialiser AVANT l'observateur) ==========
        self._syncing_products = False
        self._auto_sync_timer = None  # ✅ Initialisation ici
        self._auto_sync_interval = 60  # 60 secondes (1 minute)
        self._last_sync_time = None
        
        # Cache des produits avec leurs prix/stocks
        self.products_cache = []  # Cache local des produits
        self.products_cache_timestamp = None
        self.products_cache_ttl = 30  # 30 secondes de validité du cache
        
        # Composants UI
        self.connection_indicator = None
        self._is_online = False  # Valeur par défaut
        
        # ========== CONNECTION MANAGER ==========
        self.connection_manager = ConnectionManager()
        # Mettre à jour _is_online APRÈS avoir initialisé tous les attributs
        self._is_online = self.connection_manager.is_online_mode()
        self.connection_manager.register_observer(self._on_connection_status_changed)
        
        # Dialog de confirmation de vente
        self.confirmation_dialog = None
        self.pending_product = None
        
        # Charger la configuration
        self._load_configuration()
        
        # Démarrer la synchronisation automatique si online
        self._start_auto_sync()

    # ==================== CHARGEMENT CONFIGURATION ====================
    
    def _load_configuration(self):
        """Charge la configuration depuis la base de données"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS app_config (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        updated_at TEXT
                    )
                """)
                conn.commit()
                
                cursor.execute(
                    "SELECT value FROM app_config WHERE key = 'auto_invoice'"
                )
                row = cursor.fetchone()
                if row:
                    self.auto_generate_receipt = row[0].lower() == 'true'
                else:
                    self._save_configuration('auto_invoice', 'true')
                    self.auto_generate_receipt = True
                
                cursor.execute(
                    "SELECT value FROM app_config WHERE key = 'confirm_before_sale'"
                )
                row = cursor.fetchone()
                if row:
                    self.sale_confirmation_required = row[0].lower() == 'true'
                else:
                    self._save_configuration('confirm_before_sale', 'true')
                    self.sale_confirmation_required = True
                
                logger.info(f"📋 Configuration chargée: auto_generate_receipt={self.auto_generate_receipt}, "
                        f"sale_confirmation_required={self.sale_confirmation_required}")
                
        except Exception as e:
            logger.error(f"Erreur chargement configuration: {e}")
            self.auto_generate_receipt = True
            self.sale_confirmation_required = True

    def _save_configuration(self, key: str, value: str):
        """Sauvegarde une configuration dans la base de données"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO app_config (key, value, updated_at)
                    VALUES (?, ?, ?)
                """, (key, value, datetime.now().isoformat()))
                conn.commit()
        except Exception as e:
            logger.error(f"Erreur sauvegarde configuration {key}: {e}")

    # ==================== SYNCHRONISATION AUTO PRODUITS ====================
    
    def _start_auto_sync(self):
        """Démarre la synchronisation automatique des produits"""
        if self._auto_sync_timer:
            self._stop_auto_sync()
        
        if self._is_online:
            logger.info(f"🔄 Démarrage synchronisation auto des produits ({self._auto_sync_interval}s)")
            self._schedule_auto_sync()
    
    def _schedule_auto_sync(self):
        """Planifie la prochaine synchronisation"""
        if self._auto_sync_timer:
            self._auto_sync_timer.cancel()
        
        self._auto_sync_timer = threading.Timer(self._auto_sync_interval, self._auto_sync_products)
        self._auto_sync_timer.daemon = True
        self._auto_sync_timer.start()
    
    def _stop_auto_sync(self):
        """Arrête la synchronisation automatique"""
        if self._auto_sync_timer:
            self._auto_sync_timer.cancel()
            self._auto_sync_timer = None
        self._syncing_products = False
        logger.info("⏹️ Synchronisation auto des produits arrêtée")
    
    def _auto_sync_products(self):
        """Synchronisation automatique en arrière-plan"""
        if not self._is_online:
            self._schedule_auto_sync()
            return
        
        if self._syncing_products:
            logger.debug("Synchronisation auto déjà en cours")
            self._schedule_auto_sync()
            return
        
        if not self._is_header_initialized:
            self._schedule_auto_sync()
            return
        
        def sync_in_background():
            self._syncing_products = True
            try:
                logger.info("🔄 Synchronisation auto des produits en cours...")
                
                branch_id = self._branch_id()
                if not branch_id:
                    logger.warning("Impossible de déterminer la branche")
                    self._schedule_auto_sync()
                    return
                
                # Importer les produits depuis le serveur
                result = self.sync_service.import_products_improved(branch_id)
                
                if result and result.get("success"):
                    count = result.get("count", 0)
                    self._last_sync_time = datetime.now()
                    logger.info(f"✅ Sync auto: {count} produits mis à jour")
                    
                    if count > 0 and self._is_header_initialized:
                        # Invalider le cache
                        self.products_cache = []
                        self.products_cache_timestamp = None
                        # Recharger les produits
                        self.page.run_thread(self._refresh_products_ui)
                else:
                    error = result.get("error", "Erreur inconnue")
                    logger.warning(f"⚠️ Sync auto: {error}")
                    
            except Exception as e:
                logger.error(f"Erreur sync auto produits: {e}")
            finally:
                self._syncing_products = False
                # Planifier la prochaine synchronisation
                self._schedule_auto_sync()
        
        threading.Thread(target=sync_in_background, daemon=True).start()
    
    def _refresh_products_ui(self):
        """Rafraîchit l'UI des produits après sync auto"""
        if not self._is_header_initialized:
            return
        
        def update_ui():
            # Sauvegarder le terme de recherche actuel
            current_search = self.search_field.value if self.search_field else ""
            
            # Recharger les produits depuis la base locale
            self.products_list = self._load_products_from_db(current_search)
            
            # Mettre à jour l'affichage
            self._update_products_display()
            
            # Afficher une notification discrète
            self._show_auto_sync_notification()
        
        self.page.run_thread(update_ui)
    
    def _show_auto_sync_notification(self):
        """Affiche une notification discrète pour la sync auto"""
        if self.page and self._is_header_initialized:
            try:
                # Snackbar discret
                snack = ft.SnackBar(
                    content=ft.Text("🔄 Produits mis à jour"),
                    bgcolor=ft.Colors.GREEN_700,
                    duration=1500,
                )
                self.page.snack_bar = snack
                snack.open = True
                self.page.update()
            except:
                pass
    
    def _load_products_from_db(self, search_term: str = "") -> List:
        """
        Charge les produits depuis la base locale avec filtrage par autocomplétion.
        
        La recherche s'effectue automatiquement dès la première lettre saisie.
        Les résultats sont triés par ordre alphabétique.
        La recherche accepte jusqu'à 50 caractères.
        """
        branch_id = self._branch_id()
        
        # Récupérer les produits
        if branch_id:
            products = self.db.get_products(branch_id)
        else:
            products = self.db.get_products()
        
        # Vérifier si on a des données actuelles (moins de 30s)
        now = datetime.now()
        if (self.products_cache and self.products_cache_timestamp and 
            (now - self.products_cache_timestamp).total_seconds() < self.products_cache_ttl):
            products = self.products_cache
        else:
            self.products_cache = products
            self.products_cache_timestamp = now
        
        # Appliquer la recherche avec autocomplétion
        if search_term:
            # Tronquer le terme de recherche à 50 caractères maximum
            term = search_term.strip().lower()[:50]
            filtered = []
            for product in products:
                name = self._product_name(product).lower()
                code = self._product_code(product).lower()
                # Recherche par autocomplétion : le nom ou le code commence par le terme saisi
                if name.startswith(term) or code.startswith(term):
                    filtered.append(product)
            products = filtered
        
        # Trier par nom alphabétiquement
        products.sort(key=lambda p: self._product_name(p).lower())
        
        return products
    
    def _update_products_display(self):
        """Met à jour l'affichage des produits"""
        if not self.products_list_view:
            return
        
        self.products_list_view.controls.clear()
        
        if not self.products_list:
            self.products_list_view.controls.append(
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Icon(ft.Icons.INVENTORY_2_OUTLINED, size=60, color=ft.Colors.GREY_400),
                            ft.Text("Aucun produit trouvé", color=ft.Colors.GREY_600),
                            ft.Text("Essayez de synchroniser", size=12, color=ft.Colors.GREY_500),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=10,
                    ),
                    padding=20,
                    alignment=ft.Alignment.CENTER,
                )
            )
        else:
            for product in self.products_list[:80]:
                self.products_list_view.controls.append(self.create_product_card(product))
        
        if self._is_header_initialized:
            self.page.update()

    # ==================== GESTION STATUT CONNEXION ====================
    
    def _on_connection_status_changed(self, is_online: bool, force_mode: Optional[bool]):
        """Callback appelé quand le statut de connexion change"""
        self._is_online = is_online
        logger.info(f"📡 SaleScreen: Statut connexion changé - online={is_online}")
        
        def update_ui():
            if self._is_header_initialized and self.connection_indicator:
                self.update_connection_indicator()
                try:
                    self.page.update()
                except:
                    pass
        
        self.page.run_thread(update_ui)
        
        status = self.connection_manager.get_display_status()
        self.show_success_dialog("Mode", f"Mode: {status['text']}")
        
        # Gérer la synchronisation auto
        if is_online:
            if not hasattr(self, '_auto_sync_timer'):
                self._auto_sync_timer = None
            self._start_auto_sync()
            # Synchroniser immédiatement les produits
            self.refresh_products_from_server()
        else:
            self._stop_auto_sync()
        
    def update_connection_indicator(self):
        """Met à jour l'indicateur de connexion dans le header"""
        if not self.connection_indicator:
            return
        
        status = self.connection_manager.get_display_status()
        
        if status["color"] == "green":
            color = ft.Colors.GREEN
            tooltip = "Mode Online - Produits synchronisés automatiquement"
        elif status["color"] == "blue":
            color = ft.Colors.BLUE
            tooltip = "Mode Online forcé"
        elif status["color"] == "orange":
            color = ft.Colors.ORANGE
            tooltip = "Mode Offline forcé - Données locales uniquement"
        else:
            color = ft.Colors.RED
            tooltip = "Mode Offline - Données locales uniquement"
        
        icon = ft.Icons.WIFI if status["icon"] in ["🌐", "🔌"] else ft.Icons.WIFI_OFF
        
        # Ajouter l'heure de dernière sync
        last_sync_text = ""
        if self._last_sync_time:
            seconds_ago = int((datetime.now() - self._last_sync_time).total_seconds())
            if seconds_ago < 60:
                last_sync_text = f" (il y a {seconds_ago}s)"
            elif seconds_ago < 3600:
                last_sync_text = f" (il y a {seconds_ago//60}min)"
        
        self.connection_indicator.content = ft.Row(
            [
                ft.Icon(icon, color=color, size=16),
                ft.Text(f"{status['text']}{last_sync_text}", size=11, color=color, weight=ft.FontWeight.BOLD),
            ],
            spacing=4,
        )
        self.connection_indicator.tooltip = tooltip
    
    def create_connection_indicator(self):
        """Crée l'indicateur de connexion pour le header"""
        status = self.connection_manager.get_display_status()
        
        if status["color"] == "green":
            color = ft.Colors.GREEN
        elif status["color"] == "blue":
            color = ft.Colors.BLUE
        elif status["color"] == "orange":
            color = ft.Colors.ORANGE
        else:
            color = ft.Colors.RED
        
        icon = ft.Icons.WIFI if status["icon"] in ["🌐", "🔌"] else ft.Icons.WIFI_OFF
        
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

    # ==================== SYNCHRONISATION MANUELLE ====================
    
    def refresh_products_from_server(self):
        """Synchronise manuellement les produits depuis le serveur"""
        if not self._is_online:
            self.show_success_dialog("Mode offline", "Impossible de synchroniser en mode hors-ligne")
            return
        
        if self._syncing_products:
            self.show_success_dialog("Synchronisation", "Synchronisation déjà en cours...")
            return
        
        def sync_in_background():
            self._syncing_products = True
            try:
                branch_id = self._branch_id()
                if not branch_id:
                    self.show_success_dialog("Erreur", "Impossible de déterminer la branche")
                    return
                
                # Notification de début
                self.show_success_dialog("Synchronisation", "🔄 Synchronisation des produits...")
                
                result = self.sync_service.import_products_improved(branch_id)
                
                if result and result.get("success"):
                    count = result.get("count", 0)
                    self._last_sync_time = datetime.now()
                    
                    # Invalider le cache
                    self.products_cache = []
                    self.products_cache_timestamp = None
                    
                    # Recharger les produits (UI update)
                    def update_ui():
                        search_term = self.search_field.value if self.search_field else ""
                        self.products_list = self._load_products_from_db(search_term)
                        self._update_products_display()
                    
                    self.page.run_thread(update_ui)
                    
                    if count > 0:
                        self.show_success_dialog(
                            "✅ Synchronisation réussie", 
                            f"{count} produits mis à jour"
                        )
                    else:
                        self.show_success_dialog(
                            "✅ Produits à jour", 
                            "Aucun changement détecté"
                        )
                else:
                    error = result.get("error", "Erreur inconnue")
                    self.show_success_dialog("❌ Erreur", error)
                    
            except Exception as e:
                logger.error(f"Erreur synchronisation: {e}")
                self.show_success_dialog("Erreur", str(e))
            finally:
                self._syncing_products = False
        
        threading.Thread(target=sync_in_background, daemon=True).start()    
    # ==================== DIALOG ====================
    
    def show_success_dialog(self, title: str, message: str, details: dict = None):
        """Affiche un dialog de confirmation - SÉCURISÉ POUR LES THREADS"""
        def _show():
            content_controls = [
                ft.Icon(
                    ft.Icons.CHECK_CIRCLE if "succès" in title or "réussie" in title or "✅" in title else ft.Icons.INFO,
                    size=50,
                    color=ft.Colors.GREEN_700 if "succès" in title or "réussie" in title else ft.Colors.BLUE_700,
                ),
                ft.Text(
                    title.replace("✅", "").strip(),
                    size=20,
                    weight=ft.FontWeight.BOLD,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
                ft.Text(
                    message,
                    size=14,
                    text_align=ft.TextAlign.CENTER,
                ),
            ]
            
            if details:
                content_controls.append(ft.Divider(height=5, color=ft.Colors.TRANSPARENT))
                for key, value in details.items():
                    if value:
                        content_controls.append(
                            ft.Text(
                                f"{key}: {value}",
                                size=12,
                                color=ft.Colors.GREY_700,
                                text_align=ft.TextAlign.CENTER,
                            )
                        )
            
            content_controls.append(ft.Divider(height=10, color=ft.Colors.TRANSPARENT))
            
            dialog = ft.AlertDialog(
                title=ft.Text("", size=0),
                content=ft.Container(
                    content=ft.Column(
                        controls=content_controls,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=8,
                    ),
                    padding=20,
                    width=300,
                ),
                actions=[
                    ft.TextButton(
                        "OK",
                        on_click=lambda e: self._close_dialog(dialog),
                        style=ft.ButtonStyle(color=ft.Colors.GREEN_700),
                    ),
                ],
                actions_alignment=ft.MainAxisAlignment.CENTER,
                shape=ft.RoundedRectangleBorder(radius=20),
            )
            
            self.page.dialog = dialog
            dialog.open = True
            self.page.update()
        
        # Exécuter sur le thread principal
        try:
            if hasattr(self.page, 'run_thread'):
                self.page.run_thread(_show)
            else:
                _show()
        except Exception as e:
            logger.error(f"Erreur affichage dialog: {e}")
    
    def _close_dialog(self, dialog):
        """Ferme un dialog en toute sécurité"""
        def _close():
            dialog.open = False
            self.page.update()
        
        try:
            if hasattr(self.page, 'run_thread'):
                self.page.run_thread(_close)
            else:
                _close()
        except Exception as e:
            logger.error(f"Erreur fermeture dialog: {e}")
    
    # ==================== OUTILS ====================
    
    def _branch_id(self):
        branch_id = (self.current_user.get("active_branch_id") or 
                    self.current_user.get("branch_id") or
                    self.current_user.get("current_branch_id"))
        
        if not branch_id:
            print("⚠️ ATTENTION: Aucun branch_id trouvé")
            return None
        
        return branch_id

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

    def _get_product_attr(self, product, attr_name, default=None):
        if isinstance(product, dict):
            return product.get(attr_name, default)
        else:
            return getattr(product, attr_name, default)

    def _product_id(self, product):
        server_id = self._get_product_attr(product, 'server_id')
        if server_id:
            return str(server_id)
        return str(self._get_product_attr(product, 'id'))

    def _product_name(self, product):
        name = self._get_product_attr(product, 'name')
        return str(name) if name else "Produit inconnu"

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

    def _format_money(self, amount):
        try:
            return f"{float(amount):,.0f} FC"
        except Exception:
            return "0 FC"

    def _get_expiry_status(self, product):
        expiry_date = self._get_product_attr(product, 'expiry_date')
        if not expiry_date:
            expiry_date = self._get_product_attr(product, 'expiration_date')
        
        if not expiry_date:
            return None
        
        try:
            if isinstance(expiry_date, str):
                if "T" in expiry_date:
                    expiry_date = expiry_date.split("T")[0]
                expiry = datetime.strptime(expiry_date, "%Y-%m-%d").date()
            else:
                expiry = expiry_date
            
            today = datetime.now().date()
            
            if expiry < today:
                days_expired = (today - expiry).days
                return {"status": "expired", "text": f"Expiré depuis {days_expired} jours", "color": ft.Colors.RED_700}
            elif expiry == today:
                return {"status": "expires_today", "text": "Expire aujourd'hui", "color": ft.Colors.ORANGE_700}
            elif (expiry - today).days <= 30:
                days_left = (expiry - today).days
                return {"status": "expires_soon", "text": f"Expire dans {days_left} jours", "color": ft.Colors.ORANGE}
            else:
                return {"status": "valid", "text": None, "color": None}
        except Exception:
            return None

    # ==================== NUMÉROS DE FACTURE ====================
    
    def _get_local_sequential_number(self) -> int:
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                today = datetime.now().strftime("%Y%m%d")
                cursor.execute("""
                    SELECT MAX(CAST(SUBSTR(invoice_number, -4) AS INTEGER)) as last_num
                    FROM sales 
                    WHERE invoice_number LIKE 'LOCAL-%' 
                    AND invoice_number LIKE ?
                """, (f'LOCAL-{today}-%',))
                row = cursor.fetchone()
                
                last_num = row[0] if row and row[0] else 0
                next_num = last_num + 1
                
                if next_num > 9999:
                    next_num = 1
                
                return next_num
                
        except Exception as e:
            logger.error(f"Erreur _get_local_sequential_number: {e}")
            return 1
    
    def generate_local_invoice_number(self) -> str:
        today = datetime.now().strftime("%Y%m%d")
        seq_num = self._get_local_sequential_number()
        return f"LOCAL-{today}-{seq_num:04d}"

    # ==================== HEADER / PANIER ====================
    
    def update_cart_badge(self):
        self.cart_count = self.cart_manager.get_count()
        
        if not self.cart_button:
            return
        
        if self.cart_count > 0:
            self.cart_button.content = ft.Stack(
                controls=[
                    ft.IconButton(
                        icon=ft.Icons.SHOPPING_CART,
                        on_click=lambda e: self.show_cart(),
                        icon_size=30,
                        icon_color=ft.Colors.WHITE,
                    ),
                    ft.Container(
                        content=ft.Text(
                            str(self.cart_count),
                            size=10,
                            color=ft.Colors.WHITE,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        bgcolor=ft.Colors.RED,
                        border_radius=20,
                        width=18,
                        height=18,
                        alignment=ft.Alignment.CENTER,
                        right=0,
                        top=0,
                    ),
                ]
            )
        else:
            self.cart_button.content = ft.IconButton(
                icon=ft.Icons.SHOPPING_CART,
                on_click=lambda e: self.show_cart(),
                icon_size=30,
                icon_color=ft.Colors.WHITE,
            )
        
        self.page.update()
    
    # ==================== ÉCRAN PRINCIPAL ====================
    
    def show(self):
        self.page.clean()

        self.cart_button = ft.Container()
        self.update_cart_badge()
        
        connection_indicator = self.create_connection_indicator()
        self._is_header_initialized = True

        header = ft.Container(
            content=ft.Row(
                controls=[
                    ft.IconButton(
                        icon=ft.Icons.ARROW_BACK,
                        on_click=lambda e: self.go_back(),
                        icon_color=ft.Colors.WHITE,
                    ),
                    ft.Text(
                        "Vente",
                        size=24,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.WHITE,
                        expand=True,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    connection_indicator,
                    ft.IconButton(
                        icon=ft.Icons.SYNC,
                        on_click=lambda e: self.refresh_products_from_server(),
                        tooltip="Synchroniser les produits",
                        icon_color=ft.Colors.WHITE,
                    ),
                    self.cart_button,
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=10,
            bgcolor=ft.Colors.BLUE_700,
            border_radius=10,
        )

        # Champ de recherche avec autocomplétion instantanée
        self.search_field = ft.TextField(
            hint_text="Rechercher un produit (autocomplétion automatique)...",
            prefix_icon=ft.Icons.SEARCH,
            on_change=self.search_products,
            expand=True,
            border_radius=30,
            filled=True,
            bgcolor=ft.Colors.WHITE,
            max_length=50,  # ✅ Limite de 50 caractères maximum
            autofocus=True,  # ✅ Focus automatique pour saisie immédiate
            helper_style=ft.TextStyle(size=12, color=ft.Colors.GREY_600),
        )

        self.products_list_view = ft.ListView(
            expand=True,
            spacing=10,
            padding=10,
        )

        # Charger les produits
        self.products_list = self._load_products_from_db("")
        self._update_products_display()

        main_content = ft.Column(
            controls=[
                ft.Container(content=self.search_field, padding=10),
                ft.Container(
                    content=ft.Text(
                        "Produits disponibles",
                        size=18,
                        weight=ft.FontWeight.BOLD,
                    ),
                    padding=ft.Padding.symmetric(horizontal=10),
                ),
                self.products_list_view,
            ],
            expand=True,
            spacing=10,
        )

        self.page.add(
            ft.Container(
                content=ft.Column(
                    controls=[header, main_content],
                    expand=True,
                ),
                expand=True,
                padding=10,
            )
        )
        self.page.update()

    # ==================== PRODUITS ====================
    
    def load_products(self, search_term=""):
        """Charge les produits depuis le cache local avec autocomplétion"""
        self.products_list = self._load_products_from_db(search_term)
        self._update_products_display()

    def create_product_card(self, product):
        product_name = self._product_name(product)
        product_code = self._product_code(product)
        product_stock = self._product_stock(product)
        product_price = self._product_price(product)
        
        expiry_status = self._get_expiry_status(product)
        
        stock_color = ft.Colors.GREEN
        if product_stock <= 0:
            stock_color = ft.Colors.RED
        elif product_stock <= 5:
            stock_color = ft.Colors.ORANGE

        product_info = ft.Column(
            controls=[
                ft.Text(product_name, size=16, weight=ft.FontWeight.BOLD),
                ft.Text(f"Code: {product_code}", size=12, color=ft.Colors.GREY_600),
                ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.INVENTORY, size=14, color=stock_color),
                        ft.Text(f"Stock: {product_stock}", size=12, color=stock_color),
                    ],
                    spacing=4,
                ),
            ],
            spacing=4,
            expand=True,
        )
        
        if expiry_status and expiry_status["text"]:
            product_info.controls.append(
                ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.WARNING, size=14, color=expiry_status["color"]),
                        ft.Text(expiry_status["text"], size=11, color=expiry_status["color"]),
                    ],
                    spacing=4,
                )
            )

        return ft.Card(
            content=ft.Container(
                padding=12,
                content=ft.Row(
                    controls=[
                        product_info,
                        ft.Column(
                            controls=[
                                ft.Text(
                                    self._format_money(product_price),
                                    size=16,
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.GREEN_700,
                                ),
                                ft.Row(
                                    controls=[
                                        ft.IconButton(
                                            icon=ft.Icons.SELL,
                                            icon_size=20,
                                            on_click=lambda e, p=product: self.execute_quick_sale(p),
                                            tooltip="Vente rapide",
                                            disabled=(product_stock <= 0),
                                        ),
                                        ft.IconButton(
                                            icon=ft.Icons.ADD_SHOPPING_CART,
                                            icon_size=20,
                                            on_click=lambda e, p=product: self.add_to_cart(p),
                                            tooltip="Ajouter au panier",
                                            disabled=(product_stock <= 0),
                                        ),
                                    ],
                                    spacing=0,
                                ),
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.END,
                            spacing=4,
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ),
            margin=5,
        )

    # ==================== VENTE ====================
    
    def execute_quick_sale(self, product):
        try:
            product_id = self._product_id(product)
            product_name = self._product_name(product)
            product_stock = self._product_stock(product)
            product_price = self._product_price(product)
            branch_id = self._branch_id()
            
            if not product_id:
                self.show_success_dialog("Erreur", "ID du produit manquant.")
                return
            
            if product_stock <= 0:
                self.show_success_dialog("Stock insuffisant", f"Stock insuffisant pour {product_name}.")
                return
            
            if not branch_id:
                self.show_success_dialog("Erreur", "Aucune succursale sélectionnée.")
                return
            
            if not self.auto_generate_receipt:
                self.show_sale_confirmation_dialog(product)
                return
            
            self._execute_sale_with_quantity(product, 1)
                    
        except Exception as err:
            print(f"❌ Erreur dans execute_quick_sale: {err}")
            import traceback
            traceback.print_exc()
            self.show_success_dialog("Erreur", str(err))
    
    def show_sale_confirmation_dialog(self, product):
        product_name = self._product_name(product)
        product_price = self._product_price(product)
        product_stock = self._product_stock(product)
        
        self.pending_product = product
        
        quantity_input = ft.TextField(
            value="1",
            keyboard_type=ft.KeyboardType.NUMBER,
            text_align=ft.TextAlign.CENTER,
            width=80,
            height=40,
            border_radius=10,
        )
        
        total_price_text = ft.Text(
            self._format_money(product_price),
            size=20,
            weight=ft.FontWeight.BOLD,
            color=ft.Colors.GREEN_700,
        )
        
        def update_total(e):
            try:
                qty = int(quantity_input.value) if quantity_input.value else 1
                if qty < 1:
                    qty = 1
                    quantity_input.value = "1"
                if qty > product_stock:
                    qty = product_stock
                    quantity_input.value = str(product_stock)
                total = qty * product_price
                total_price_text.value = self._format_money(total)
                self.page.update()
            except:
                pass
        
        quantity_input.on_change = update_total
        
        def confirm_sale(e):
            try:
                qty = int(quantity_input.value) if quantity_input.value else 1
                if qty < 1:
                    qty = 1
                if qty > product_stock:
                    qty = product_stock
                
                self._execute_sale_with_quantity(product, qty)
                dialog.open = False
                self.page.update()
            except Exception as err:
                logger.error(f"Erreur confirmation vente: {err}")
        
        dialog = ft.AlertDialog(
            title=ft.Text(
                "Confirmation de vente",
                size=18,
                weight=ft.FontWeight.BOLD,
            ),
            content=ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text(
                            product_name,
                            size=16,
                            weight=ft.FontWeight.BOLD,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Divider(),
                        ft.Row(
                            controls=[
                                ft.Text("Prix unitaire:", size=14),
                                ft.Text(self._format_money(product_price), size=14, weight=ft.FontWeight.BOLD),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Row(
                            controls=[
                                ft.Text("Stock disponible:", size=14),
                                ft.Text(str(product_stock), size=14, color=ft.Colors.GREEN if product_stock > 0 else ft.Colors.RED),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Row(
                            controls=[
                                ft.Text("Quantité:", size=14),
                                quantity_input,
                                ft.IconButton(
                                    icon=ft.Icons.ADD,
                                    icon_size=20,
                                    on_click=lambda e: self._adjust_quantity(quantity_input, 1, product_stock, total_price_text, product_price),
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.REMOVE,
                                    icon_size=20,
                                    on_click=lambda e: self._adjust_quantity(quantity_input, -1, product_stock, total_price_text, product_price),
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Divider(),
                        ft.Row(
                            controls=[
                                ft.Text("TOTAL:", size=16, weight=ft.FontWeight.BOLD),
                                total_price_text,
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                    ],
                    spacing=12,
                ),
                padding=20,
                width=320,
            ),
            actions=[
                ft.TextButton(
                    "ANNULER",
                    on_click=lambda e: self.close_dialog(dialog),
                    style=ft.ButtonStyle(color=ft.Colors.GREY_700),
                ),
                ft.ElevatedButton(
                    "CONFIRMER",
                    on_click=confirm_sale,
                    style=ft.ButtonStyle(
                        bgcolor=ft.Colors.GREEN_700,
                        color=ft.Colors.WHITE,
                    ),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            shape=ft.RoundedRectangleBorder(radius=20),
        )
        
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()
    
    def _adjust_quantity(self, input_field, delta, max_stock, total_text, unit_price):
        try:
            current = int(input_field.value) if input_field.value else 1
            new_value = current + delta
            if new_value < 1:
                new_value = 1
            if new_value > max_stock:
                new_value = max_stock
            input_field.value = str(new_value)
            total = new_value * unit_price
            total_text.value = self._format_money(total)
            self.page.update()
        except:
            pass
    
    def _execute_sale_with_quantity(self, product, qty: int):
        try:
            product_id = self._product_id(product)
            product_name = self._product_name(product)
            product_stock = self._product_stock(product)
            product_price = self._product_price(product)
            branch_id = self._branch_id()
            
            if product_stock < qty:
                self.show_success_dialog("Stock insuffisant", f"Stock insuffisant. Disponible: {product_stock}")
                return
            
            total_price = round(product_price * qty, 2)
            
            # Gestion du numéro de facture
            invoice_number = None
            use_server_invoice = False
            is_online_mode = self._is_online
            
            if is_online_mode:
                print("🌐 Mode ONLINE - Le serveur générera le numéro de facture")
                invoice_number = None
                use_server_invoice = False
            else:
                invoice_number = self.generate_local_invoice_number()
                print(f"✈️ Mode OFFLINE - Numéro facture local: {invoice_number}")
                use_server_invoice = False
            
            sale_data = {
                'product_id': str(product_id),
                'product_name': product_name,
                'quantity': qty,
                'unit_price': product_price,
                'total_price': total_price,
                'sale_date': datetime.now().isoformat(),
                'customer_name': "Client comptant",
                'branch_id': str(branch_id),
                'payment_method': 'cash',
                'seller_id': self.current_user.get('id'),
                'seller_name': self.current_user.get('full_name', 'Vendeur'),
            }
            
            sale_id = None
            is_online_sale = False
            final_invoice_number = None
            
            if is_online_mode:
                print("🌐 Envoi de la vente au serveur...")
                result = self._save_sale_to_server(sale_data)
                
                if result.get("success"):
                    sale_id = result.get("sale_id")
                    is_online_sale = True
                    final_invoice_number = result.get('generated_invoice_number', self.generate_local_invoice_number())
                    print(f"✅ Vente enregistrée sur le serveur: {sale_id} - Facture: {final_invoice_number}")
                    self._update_local_stock_after_server_sale(product_id, qty)
                    
                    self.show_success_dialog(
                        "Vente réussie!",
                        f"{qty} x {product_name}",
                        {
                            "Montant": self._format_money(total_price),
                            "Facture": final_invoice_number,
                            "Mode": "En ligne"
                        }
                    )
                else:
                    error = result.get('error', 'Erreur inconnue')
                    print(f"⚠️ Échec serveur ({error}) - Fallback local")
                    fallback_invoice = self.generate_local_invoice_number()
                    sale_data['invoice_number'] = fallback_invoice
                    sale_id = self._save_sale_to_local(sale_data, product_id, qty)
                    is_online_sale = False
                    final_invoice_number = fallback_invoice
                    
                    self.show_success_dialog(
                        "Vente en mode local",
                        f"{qty} x {product_name}",
                        {
                            "Montant": self._format_money(total_price),
                            "Facture": final_invoice_number,
                            "Mode": "Hors-ligne (serveur indisponible)"
                        }
                    )
            else:
                print("✈️ Mode OFFLINE - Enregistrement local")
                sale_id = self._save_sale_to_local(sale_data, product_id, qty)
                is_online_sale = False
                final_invoice_number = sale_data.get('invoice_number', invoice_number)
                
                if sale_id:
                    self.show_success_dialog(
                        "Vente hors-ligne",
                        f"{qty} x {product_name}",
                        {
                            "Montant": self._format_money(total_price),
                            "Facture": final_invoice_number,
                            "Mode": "Hors-ligne"
                        }
                    )
            
            if sale_id:
                # Recharger les produits pour mettre à jour le stock
                search_term = self.search_field.value if self.search_field else ""
                self.products_list = self._load_products_from_db(search_term)
                self._update_products_display()
                self.update_cart_badge()
                
                if self.auto_generate_receipt:
                    sale_data_display = {
                        'product_name': product_name,
                        'quantity': qty,
                        'unit_price': product_price,
                        'total_price': total_price,
                    }
                    self.show_invoice_dialog(sale_data_display, final_invoice_number, is_online_sale)
                    
        except Exception as err:
            print(f"❌ Erreur dans _execute_sale_with_quantity: {err}")
            import traceback
            traceback.print_exc()
            self.show_success_dialog("Erreur", str(err))
    
    def _save_sale_to_server(self, sale_data: dict) -> dict:
        try:
            headers = self.sync_service._get_headers()
            if not headers:
                return {"success": False, "error": "Non authentifié"}
            
            user = self.auth_service.get_current_user()
            
            payload = {
                "items": [{
                    "product_id": sale_data['product_id'],
                    "quantity": sale_data['quantity'],
                    "discount_percent": 0
                }],
                "customer_name": sale_data['customer_name'],
                "payment_method": sale_data['payment_method'],
                "global_discount": 0,
                "notes": f"Vente synchro",
            }
            
            if sale_data.get('sale_date'):
                payload["sale_date"] = sale_data['sale_date']
            
            pharmacy_id = user.get('pharmacy_id') or sale_data.get('branch_id')
            if pharmacy_id:
                payload["pharmacy_id"] = str(pharmacy_id)
            
            logger.info(f"📤 Envoi vente au serveur: qty={sale_data['quantity']}")
            
            response = self.sync_service.session.post(
                f"{self.sync_service.api_url}/sales",
                headers=headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code in [200, 201]:
                data = response.json()
                sale_id = None
                generated_invoice = None
                if isinstance(data, dict):
                    sale_id = data.get('id')
                    generated_invoice = data.get('invoice_number')
                    if not sale_id and 'sale' in data:
                        sale_id = data['sale'].get('id')
                        generated_invoice = data['sale'].get('invoice_number')
                    if not sale_id:
                        sale_id = data.get('sale_id')
                
                logger.info(f"✅ Vente envoyée au serveur avec succès")
                return {"success": True, "sale_id": sale_id, "generated_invoice_number": generated_invoice}
            else:
                error_detail = response.text
                try:
                    error_json = response.json()
                    error_detail = error_json.get('detail', error_detail)
                except:
                    pass
                logger.error(f"❌ Erreur API: {response.status_code} - {error_detail}")
                return {"success": False, "error": f"HTTP {response.status_code}: {error_detail[:100]}"}
                
        except requests.exceptions.Timeout:
            logger.error("Timeout lors de l'envoi au serveur")
            return {"success": False, "error": "Timeout"}
        except Exception as e:
            logger.error(f"Erreur _save_sale_to_server: {e}")
            return {"success": False, "error": str(e)}
    
    def _save_sale_to_local(self, sale_data: dict, product_id: str, qty: int) -> Optional[int]:
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("SELECT quantity FROM products WHERE server_id = ?", (product_id,))
                row = cursor.fetchone()
                
                if not row or qty > row[0]:
                    return None
                
                cursor.execute("""
                    INSERT INTO sales 
                    (product_id, product_name, quantity, unit_price, total_price, sale_date, 
                    customer_name, branch_id, is_synced, payment_method, invoice_number)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    product_id,
                    sale_data['product_name'],
                    qty,
                    sale_data['unit_price'],
                    sale_data['total_price'],
                    sale_data['sale_date'],
                    sale_data['customer_name'],
                    sale_data['branch_id'],
                    0,
                    sale_data['payment_method'],
                    sale_data.get('invoice_number', self.generate_local_invoice_number())
                ))
                
                sale_id = cursor.lastrowid
                
                cursor.execute(
                    "UPDATE products SET quantity = quantity - ? WHERE server_id = ? AND quantity >= ?",
                    (qty, product_id, qty)
                )
                
                conn.commit()
                
                logger.info(f"✅ Vente locale enregistrée: {sale_id}")
                return sale_id
                
        except Exception as e:
            logger.error(f"❌ Erreur _save_sale_to_local: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _update_local_stock_after_server_sale(self, product_id: str, qty: int):
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE products SET quantity = quantity - ? WHERE server_id = ? AND quantity >= ?",
                    (qty, product_id, qty)
                )
                conn.commit()
        except Exception as e:
            print(f"Erreur mise à jour stock local: {e}")
    
    def show_invoice_dialog(self, sale_data: dict, invoice_number: str, is_online: bool):
        status_text = "✅ Vente en ligne" if is_online else "📱 Vente hors-ligne"
        status_color = ft.Colors.GREEN_700 if is_online else ft.Colors.BLUE_700
        
        dialog = ft.AlertDialog(
            title=ft.Text(
                "🧾 FACTURE",
                size=18,
                weight=ft.FontWeight.BOLD,
                text_align=ft.TextAlign.CENTER,
            ),
            content=ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Container(
                            content=ft.Column(
                                controls=[
                                    ft.Text(
                                        invoice_number,
                                        size=14,
                                        weight=ft.FontWeight.BOLD,
                                        text_align=ft.TextAlign.CENTER,
                                    ),
                                    ft.Text(
                                        datetime.now().strftime("%d/%m/%Y %H:%M"),
                                        size=12,
                                        color=ft.Colors.GREY_600,
                                        text_align=ft.TextAlign.CENTER,
                                    ),
                                ],
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                spacing=4,
                            ),
                            padding=10,
                            bgcolor=ft.Colors.GREY_100,
                            border_radius=10,
                        ),
                        ft.Divider(),
                        ft.Row(
                            controls=[
                                ft.Text(sale_data['product_name'], size=14, expand=True),
                                ft.Text(f"x{sale_data['quantity']}", size=14),
                                ft.Text(
                                    self._format_money(sale_data['total_price']),
                                    size=14,
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.GREEN_700,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Divider(),
                        ft.Row(
                            controls=[
                                ft.Text("TOTAL", size=16, weight=ft.FontWeight.BOLD),
                                ft.Text(
                                    self._format_money(sale_data['total_price']),
                                    size=16,
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.GREEN_700,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
                        ft.Container(
                            content=ft.Text(
                                status_text,
                                size=12,
                                color=status_color,
                                text_align=ft.TextAlign.CENTER,
                            ),
                            padding=ft.Padding.symmetric(vertical=5, horizontal=10),
                            bgcolor=ft.Colors.GREY_100,
                            border_radius=15,
                        ),
                    ],
                    spacing=8,
                ),
                padding=15,
                width=320,
            ),
            actions=[
                ft.TextButton(
                    "IMPRIMER",
                    on_click=lambda e: self._print_invoice_and_close(dialog, sale_data, invoice_number, is_online),
                    style=ft.ButtonStyle(color=ft.Colors.BLUE_700),
                ),
                ft.TextButton(
                    "FERMER",
                    on_click=lambda e: self.close_dialog(dialog),
                    style=ft.ButtonStyle(color=ft.Colors.GREY_700),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            shape=ft.RoundedRectangleBorder(radius=20),
        )
        
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()
    
    def _print_invoice_and_close(self, dialog, sale_data, invoice_number, is_online):
        dialog.open = False
        self.page.update()
        
        print_manager = PrintManager(self.page, self.db, self.current_user)
        print_manager.print_sale({
            'product_name': sale_data['product_name'],
            'quantity': sale_data['quantity'],
            'unit_price': sale_data['unit_price'],
            'total_price': sale_data['total_price'],
            'customer_name': 'Client comptant',
            'sale_date': datetime.now().strftime('%d/%m/%Y %H:%M'),
            'payment_method': 'Espèces',
            'seller_name': self.current_user.get('full_name', 'Vendeur'),
            'branch_name': self.current_user.get('branch_name', 'MédiGest Pro'),
            'invoice_number': invoice_number,
            'is_online': is_online
        })
    
    # ==================== NAVIGATION ====================
    
    def add_to_cart(self, product):
        try:
            product_id = self._product_id(product)
            if not product_id:
                self.show_success_dialog("Erreur", "ID du produit manquant.")
                return

            product_name = self._product_name(product)
            product_stock = self._product_stock(product)
            product_price = self._product_price(product)

            if product_stock <= 0:
                self.show_success_dialog("Stock insuffisant", f"Stock insuffisant pour {product_name}.")
                return
            
            success = self.cart_manager.add_item(
                product_id=str(product_id), 
                product_name=product_name, 
                unit_price=product_price, 
                quantity=1
            )
            
            if success:
                self.update_cart_badge()
                self.show_success_dialog("Ajouté au panier", f"{product_name} ajouté au panier.")
            else:
                self.show_success_dialog("Erreur", "Erreur lors de l'ajout au panier.")

        except Exception as err:
            import traceback
            traceback.print_exc()
            self.show_success_dialog("Erreur", str(err))

    def show_cart(self):
        from screens.cart_screen import CartScreen

        cart_screen = CartScreen(
            self.page,
            self.db,
            self.sync_service,
            self.auth_service,
            self.current_user,
        )
        cart_screen.show()

    def search_products(self, e):
        """
        Fonction de recherche avec autocomplétion instantanée.
        
        - S'exécute à chaque frappe de touche (événement on_change)
        - Le filtrage se fait par préfixe (autocomplétion) sur le nom ou le code produit
        - Les résultats sont triés par ordre alphabétique automatiquement
        - La recherche est limitée à 50 caractères maximum
        - L'affichage se met à jour instantanément
        """
        search_term = self.search_field.value if self.search_field else ""
        # La méthode load_products applique le filtrage et le tri alphabétique
        self.load_products(search_term)

    def go_back(self):
        from screens.dashboard_screen import DashboardScreen

        dashboard = DashboardScreen(
            self.page,
            self.db,
            self.sync_service,
            self.auth_service,
            self.current_user,
            None
        )
        dashboard.show()
    
    def __del__(self):
        """Nettoyage à la destruction"""
        self._stop_auto_sync()