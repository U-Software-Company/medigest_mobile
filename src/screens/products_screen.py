"""
Écran de gestion des produits - Version Responsive avec mode Online/Offline
Gère l'affichage, la recherche et la synchronisation des produits
Adapté pour mobile, tablette et desktop
"""
import flet as ft
from typing import List, Dict, Optional
import threading
from services.connection_manager import ConnectionManager
import logging

logger = logging.getLogger(__name__)


class ProductsScreen:
    def __init__(self, page: ft.Page, db, sync_service, auth_service, current_user):
        self.page = page
        self.db = db
        self.sync_service = sync_service
        self.auth_service = auth_service
        self.current_user = current_user

        # ========== CONNECTION MANAGER ==========
        self.connection_manager = ConnectionManager()
        self.connection_manager.register_observer(self._on_connection_status_changed)
        self._is_online = self.connection_manager.is_online_mode()
        self._is_header_initialized = False

        self.search_field: ft.TextField | None = None
        self.products_list_view: ft.ListView | None = None
        self.current_category: str | None = None
        self.current_page: int = 1
        self.page_size: int = 50
        self.total_products: int = 0
        self.total_pages: int = 0
        
        # Cache pour éviter de recharger tous les produits à chaque recherche
        self.all_products_cache: list = []
        self.filtered_products_cache: list = []

        self.category_filters_row: ft.Row | None = None
        self.category_buttons: dict[str | None, ft.Button] = {}
        self.pagination_row: ft.Row | None = None
        self.prev_button: ft.IconButton | None = None
        self.next_button: ft.IconButton | None = None
        self.page_info_text: ft.Text | None = None
        
        # Indicateur de connexion
        self.connection_indicator: ft.Container | None = None
        
        # Flag pour éviter les synchronisations multiples
        self._syncing = False
        
        # ========== PERMISSIONS UTILISATEUR ==========
        self._load_user_permissions()

    # ==================== GESTION PERMISSIONS ====================
    
    def _load_user_permissions(self):
        """Charge les permissions de l'utilisateur courant"""
        self.user_role = self.current_user.get('role', '').lower() if self.current_user else ''
        self.is_admin = self.user_role in ['admin', 'super_admin', 'superadmin']
        
        # Permissions spécifiques pour les produits
        self.can_add_product = self._has_permission('can_add_product')
        self.can_edit_product = self._has_permission('can_edit_product')
        self.can_edit_stock = self._has_permission('can_edit_stock')
        self.can_edit_price = self._has_permission('can_edit_price')
        self.can_delete_product = self._has_permission('can_delete_product')
        
        logger.info(f"Permissions chargées - admin={self.is_admin}, edit_product={self.can_edit_product}, edit_stock={self.can_edit_stock}")
    
    def _has_permission(self, permission_key: str) -> bool:
        """Vérifie si l'utilisateur a une permission spécifique"""
        # Admin a toutes les permissions
        if self.is_admin:
            return True
        
        # Vérifier depuis le cache local
        if self.current_user:
            permissions = self.current_user.get('permissions', {})
            if permission_key in permissions:
                return permissions[permission_key]
        
        # Vérifier depuis la base de données
        try:
            branch_id = self.get_branch_id()
            user_id = self.current_user.get('id') if self.current_user else None
            if user_id and branch_id:
                user_perms = self.db.get_user_permissions(user_id, branch_id)
                return user_perms.get(permission_key, False)
        except Exception as e:
            logger.error(f"Erreur vérification permission {permission_key}: {e}")
        
        return False

    # ==================== GESTION STATUT CONNEXION ====================
    
    def _on_connection_status_changed(self, is_online: bool, force_mode: Optional[bool]):
        """Callback appelé quand le statut de connexion change"""
        self._is_online = is_online
        logger.info(f"📡 ProductsScreen: Statut connexion changé - online={is_online}, force={force_mode}")
        
        if self._is_header_initialized and self.connection_indicator:
            self.update_connection_indicator()
            self.page.update()
        
        # Si on passe en mode online, synchroniser les produits
        if is_online and not self._syncing:
            self.sync_products_from_server()
    
    def update_connection_indicator(self):
        """Met à jour l'indicateur de connexion"""
        if not self.connection_indicator:
            return
        
        status = self.connection_manager.get_display_status()
        
        # Déterminer la couleur
        if status["color"] == "green":
            color = ft.Colors.GREEN
            tooltip = "Mode Online - Produits synchronisés avec le serveur"
        elif status["color"] == "blue":
            color = ft.Colors.BLUE
            tooltip = "Mode Online forcé - Synchronisation forcée"
        elif status["color"] == "orange":
            color = ft.Colors.ORANGE
            tooltip = "Mode Offline forcé - Données locales uniquement"
        else:
            color = ft.Colors.RED
            tooltip = "Mode Offline - Données locales uniquement"
        
        # Déterminer l'icône
        icon = ft.Icons.WIFI if status["icon"] in ["🌐", "🔌"] else ft.Icons.WIFI_OFF
        
        self.connection_indicator.content = ft.Row(
            [
                ft.Icon(icon, color=color, size=16),
                ft.Text(status["text"], size=11, color=color, weight=ft.FontWeight.BOLD),
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

    # =========================================================
    # SYNCHRONISATION DES PRODUITS
    # =========================================================
    
    def sync_products_from_server(self):
        """Synchronise les produits depuis le serveur (seulement en mode online)"""
        if not self._is_online:
            logger.info("Mode offline - Synchronisation des produits ignorée")
            return
        
        if self._syncing:
            logger.info("Synchronisation déjà en cours")
            return
        
        def sync_in_background():
            self._syncing = True
            try:
                logger.info("🌐 Début synchronisation des produits depuis le serveur")
                
                # Récupérer le branch_id
                branch_id = self.get_branch_id()
                
                if not branch_id:
                    logger.warning("Impossible de déterminer la branche pour la synchronisation")
                    return
                
                # Importer les produits depuis le serveur
                result = self.sync_service.import_products_improved(branch_id)
                
                if result and result.get("success"):
                    count = result.get("count", 0)
                    logger.info(f"✅ {count} produits synchronisés depuis le serveur")
                    
                    # Recharger le cache local
                    self.load_all_products()
                    
                    # Mettre à jour l'affichage
                    if self._is_header_initialized:
                        self.page.run_thread(lambda: self._update_ui_after_sync(count))
                else:
                    error = result.get("error", "Erreur inconnue")
                    logger.error(f"❌ Erreur synchronisation: {error}")
                    if self._is_header_initialized:
                        self.page.run_thread(lambda: self.show_snackbar(f"Erreur sync: {error}", ft.Colors.RED))
                        
            except Exception as e:
                logger.error(f"Erreur synchronisation produits: {e}")
                if self._is_header_initialized:
                    self.page.run_thread(lambda: self.show_snackbar(f"Erreur: {str(e)}", ft.Colors.RED))
            finally:
                self._syncing = False
        
        # Démarrer la synchronisation en arrière-plan
        threading.Thread(target=sync_in_background, daemon=True).start()
    
    def _update_ui_after_sync(self, count: int):
        """Met à jour l'UI après une synchronisation réussie (appelé depuis run_thread)"""
        self.apply_filters_and_paginate()
        self.display_current_page()
        self.update_pagination_buttons_state()
        
        # Mettre à jour le texte du compteur de produits dans le header
        self._update_product_count_display()
        
        if count > 0:
            self.show_snackbar(f"📦 {count} produits synchronisés", ft.Colors.GREEN)
        else:
            self.show_snackbar("✅ Produits à jour avec le serveur", ft.Colors.BLUE)
    
    def _update_product_count_display(self):
        """Met à jour l'affichage du nombre de produits"""
        # Cette méthode sera appelée après reconstruction de l'UI
        pass

    # =========================================================
    # UTILITAIRES
    # =========================================================
    def show_snackbar(self, message: str, color: str = ft.Colors.BLUE) -> None:
        self.page.snack_bar = ft.SnackBar(
            content=ft.Text(message),
            bgcolor=color,
            open=True,
        )
        self.page.update()

    def get_branch_id(self):
        if not self.current_user:
            return None
        return (
            self.current_user.get("active_branch_id")
            or self.current_user.get("branch_id")
        )

    def safe_str(self, value, default: str = "") -> str:
        if value is None:
            return default
        return str(value)

    def safe_number(self, value, default: float = 0) -> float:
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def format_fc(self, value) -> str:
        amount = self.safe_number(value, 0)
        return f"{amount:,.0f} FC"

    def _get_product_attr(self, product, attr_name, default=None):
        """Récupère un attribut d'un produit (dictionnaire ou objet)"""
        if isinstance(product, dict):
            return product.get(attr_name, default)
        else:
            return getattr(product, attr_name, default)

    def scroll_to_top(self):
        """Scroller vers le haut de la liste"""
        if self.products_list_view:
            try:
                self.products_list_view.controls.clear()
                self.display_current_page()
            except:
                pass

    # =========================================================
    # AFFICHAGE
    # =========================================================
    def show(self) -> None:
        self.page.clean()
        self.page.scroll = ft.ScrollMode.AUTO
        self.page.padding = 0
        self.page.bgcolor = ft.Colors.GREY_100
        
        # Recharger les permissions avant d'afficher
        self._load_user_permissions()

        header = self.build_header()
        self.search_field = self.build_search_field()
        
        # Charger d'abord les produits depuis le cache local
        self.load_all_products()
        
        # Synchroniser avec le serveur si online
        if self._is_online and not self._syncing:
            self.sync_products_from_server()
        
        # Construire les catégories (après chargement)
        self.category_filters_row = self.build_category_filters()
        
        # Créer la liste des produits
        self.products_list_view = ft.ListView(
            expand=True,
            spacing=10,
            padding=10,
            auto_scroll=False,
        )
        
        # Construire la pagination
        self.pagination_row = self.build_pagination_controls()
        
        # Afficher les produits de la page 1
        self.display_current_page()
        
        # Construction de l'interface complète
        main_content = ft.Column(
            controls=[
                header,
                ft.Container(content=self.search_field, padding=10),
                ft.Container(
                    content=ft.Text(
                        "Catégories",
                        size=14,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.GREY_700,
                    ),
                    padding=ft.Padding.only(left=12, right=12, top=5),
                ),
                ft.Container(content=self.category_filters_row, padding=ft.Padding.only(left=10, right=10, bottom=5)),
                ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Text(
                                "Liste des produits",
                                size=18,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.BLUE_GREY_900,
                            ),
                            ft.Text(
                                f"({self.total_products} produits)",
                                size=14,
                                color=ft.Colors.GREY_600,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    padding=ft.Padding.only(left=12, right=12, top=5, bottom=5),
                ),
                ft.Container(
                    content=self.products_list_view,
                    expand=True,
                ),
                ft.Container(
                    content=self.pagination_row,
                    padding=ft.Padding.symmetric(vertical=10, horizontal=12),
                    bgcolor=ft.Colors.WHITE,
                    border=ft.border.only(top=ft.BorderSide(1, ft.Colors.GREY_200)),
                ),
            ],
            expand=True,
            spacing=0,
        )

        self.page.add(main_content)
        self._is_header_initialized = True
        self.page.update()

    def build_header(self) -> ft.Container:
        """Construit l'en-tête avec indicateur de connexion"""
        connection_indicator = self.create_connection_indicator()
        
        # Bouton Ajouter produit si permission
        add_button = None
        if self.can_add_product or self.is_admin:
            add_button = ft.IconButton(
                icon=ft.Icons.ADD,
                on_click=lambda e: self.go_to_add_product(),
                tooltip="Ajouter un produit",
                icon_color=ft.Colors.WHITE,
            )
        
        header_controls = [
            ft.IconButton(
                icon=ft.Icons.ARROW_BACK,
                on_click=lambda e: self.go_back(),
                icon_color=ft.Colors.WHITE,
                tooltip="Retour",
            ),
            ft.Text(
                "Produits",
                size=22,
                weight=ft.FontWeight.BOLD,
                color=ft.Colors.WHITE,
                expand=True,
            ),
            connection_indicator,
        ]
        
        if add_button:
            header_controls.append(add_button)
        
        header_controls.append(
            ft.IconButton(
                icon=ft.Icons.REFRESH,
                on_click=lambda e: self.refresh_products(),
                tooltip="Synchroniser",
                icon_color=ft.Colors.WHITE,
            )
        )
        
        return ft.Container(
            content=ft.Row(
                controls=header_controls,
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=8, vertical=10),
            bgcolor=ft.Colors.BLUE_700,
        )

    def build_search_field(self) -> ft.TextField:
        return ft.TextField(
            hint_text="Rechercher un produit...",
            prefix_icon=ft.Icons.SEARCH,
            on_change=self.on_search_change,
            expand=True,
            border_radius=30,
            filled=True,
            bgcolor=ft.Colors.WHITE,
            border_color=ft.Colors.BLUE_GREY_100,
            content_padding=ft.Padding.symmetric(horizontal=16, vertical=12),
        )

    def build_category_filters(self) -> ft.Row:
        """Construit la barre de filtres par catégorie"""
        categories = self.get_categories_from_cache()
        self.category_buttons.clear()

        row = ft.Row(
            controls=[],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
        )

        # Bouton "Tous"
        all_button = self.build_filter_button("Tous", None, selected=(self.current_category is None))
        self.category_buttons[None] = all_button
        row.controls.append(all_button)

        for category in categories:
            btn = self.build_filter_button(category, category, selected=(self.current_category == category))
            self.category_buttons[category] = btn
            row.controls.append(btn)

        return row

    def build_filter_button(
        self,
        label: str,
        category_value: str | None,
        selected: bool = False,
    ) -> ft.Button:
        return ft.Button(
            content=ft.Text(label, size=13, weight=ft.FontWeight.W_500),
            on_click=lambda e, c=category_value: self.filter_by_category(c),
            style=self.get_filter_button_style(selected),
        )

    def get_filter_button_style(self, selected: bool) -> ft.ButtonStyle:
        return ft.ButtonStyle(
            padding=ft.Padding.symmetric(horizontal=14, vertical=10),
            shape=ft.RoundedRectangleBorder(radius=20),
            bgcolor=ft.Colors.BLUE_700 if selected else ft.Colors.WHITE,
            color=ft.Colors.WHITE if selected else ft.Colors.BLUE_700,
            side=ft.BorderSide(
                1,
                ft.Colors.BLUE_700 if selected else ft.Colors.BLUE_100,
            ),
        )

    def build_pagination_controls(self) -> ft.Row:
        """Construit les contrôles de pagination"""
        self.prev_button = ft.IconButton(
            icon=ft.Icons.CHEVRON_LEFT,
            on_click=lambda e: self.go_to_prev_page(),
            tooltip="Page précédente",
            disabled=(self.current_page <= 1),
        )
        
        self.page_info_text = ft.Text(
            f"Page {self.current_page} / {self.total_pages}",
            size=14,
            weight=ft.FontWeight.W_500,
        )
        
        self.next_button = ft.IconButton(
            icon=ft.Icons.CHEVRON_RIGHT,
            on_click=lambda e: self.go_to_next_page(),
            tooltip="Page suivante",
            disabled=(self.current_page >= self.total_pages),
        )
        
        return ft.Row(
            controls=[
                self.prev_button,
                self.page_info_text,
                self.next_button,
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=20,
        )

    def update_pagination_buttons_state(self) -> None:
        """Met à jour l'état des boutons de pagination"""
        if self.prev_button:
            self.prev_button.disabled = (self.current_page <= 1)
        if self.next_button:
            self.next_button.disabled = (self.current_page >= self.total_pages)
        if self.page_info_text:
            self.page_info_text.value = f"Page {self.current_page} / {self.total_pages}"
        self.page.update()

    # =========================================================
    # DONNÉES
    # =========================================================
    def load_all_products(self) -> None:
        """Charge tous les produits depuis le cache local"""
        branch_id = self.get_branch_id()
        self.all_products_cache = self.db.get_products(branch_id) or []
        logger.info(f"📦 Produits chargés: {len(self.all_products_cache)} produits (branch_id={branch_id})")
        
        # Appliquer le filtre initial
        self.apply_filters_and_paginate()

    def apply_filters_and_paginate(self) -> None:
        """Applique les filtres (recherche et catégorie) puis pagine"""
        if not self.all_products_cache:
            self.filtered_products_cache = []
        else:
            # Filtre par recherche
            search_term = self.search_field.value if self.search_field else ""
            search_value = self.safe_str(search_term).strip().lower()
            
            filtered = self.all_products_cache.copy()
            
            if search_value:
                temp_filtered = []
                for product in filtered:
                    name = self.safe_str(self._get_product_attr(product, "name")).lower()
                    code = self.safe_str(self._get_product_attr(product, "code")).lower()
                    category_name = self.safe_str(self._get_product_attr(product, "category")).lower()
                    
                    if (search_value in name or 
                        search_value in code or 
                        search_value in category_name):
                        temp_filtered.append(product)
                filtered = temp_filtered
            
            # Filtre par catégorie
            if self.current_category:
                filtered = [
                    p for p in filtered
                    if self.safe_str(self._get_product_attr(p, "category")).strip() == self.current_category
                ]
            
            # Trier par nom
            filtered.sort(key=lambda p: self.safe_str(self._get_product_attr(p, "name")).lower())
            
            self.filtered_products_cache = filtered
        
        # Mettre à jour la pagination
        self.total_products = len(self.filtered_products_cache)
        self.total_pages = max(1, (self.total_products + self.page_size - 1) // self.page_size)
        
        logger.info(f"📊 Filtrage: {len(self.filtered_products_cache)} produits affichés sur {len(self.all_products_cache)} total, {self.total_pages} pages")
        
        # Réinitialiser la page si elle dépasse le total
        if self.current_page > self.total_pages:
            self.current_page = self.total_pages
        elif self.current_page < 1:
            self.current_page = 1

    def display_current_page(self) -> None:
        """Affiche les produits de la page courante"""
        if not self.products_list_view:
            return
        
        self.products_list_view.controls.clear()
        
        if not self.filtered_products_cache:
            self.products_list_view.controls.append(self.build_empty_state())
        else:
            # Calculer les indices de début et fin
            start_idx = (self.current_page - 1) * self.page_size
            end_idx = min(start_idx + self.page_size, self.total_products)
            
            logger.info(f"📄 Affichage page {self.current_page}: produits {start_idx+1} à {end_idx}")
            
            # Afficher les produits de la page
            for product in self.filtered_products_cache[start_idx:end_idx]:
                self.products_list_view.controls.append(
                    self.create_product_card(product)
                )
        
        self.page.update()

    def get_categories_from_cache(self) -> list[str]:
        """Récupère les catégories depuis le cache des produits"""
        categories = set()
        for product in self.all_products_cache:
            category = self._get_product_attr(product, "category", "")
            category_str = self.safe_str(category).strip()
            if category_str:
                categories.add(category_str)
        
        return sorted(categories, key=lambda x: x.lower())

    def build_empty_state(self) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Icon(ft.Icons.INVENTORY_2_OUTLINED, size=70, color=ft.Colors.GREY_400),
                    ft.Text(
                        "Aucun produit trouvé",
                        size=16,
                        color=ft.Colors.GREY_700,
                        weight=ft.FontWeight.W_500,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=12,
            ),
            alignment=ft.Alignment.CENTER,
            padding=30,
        )

    # =========================================================
    # PAGINATION
    # =========================================================
    def go_to_prev_page(self) -> None:
        if self.current_page > 1:
            self.current_page -= 1
            self.display_current_page()
            self.update_pagination_buttons_state()

    def go_to_next_page(self) -> None:
        if self.current_page < self.total_pages:
            self.current_page += 1
            self.display_current_page()
            self.update_pagination_buttons_state()

    # =========================================================
    # UI PRODUIT - CARTE AVEC BOUTONS D'ACTION
    # =========================================================
    
    def open_edit_product_screen(self, product):
        """Ouvre l'écran de modification du produit"""
        from screens.edit_product_screen import EditProductScreen
        
        edit_screen = EditProductScreen(
            self.page,
            self.db,
            self.sync_service,
            self.auth_service,
            self.current_user,
            product,
            on_updated=self.on_product_updated,
            notification_manager=None
        )
        # Utiliser run_thread pour les méthodes synchrones
        edit_screen.show()
    
    def open_stock_adjustment_screen(self, product):
        """Ouvre l'écran d'ajustement de stock"""
        from screens.stock_adjust_screen import StockAdjustScreen
        
        adjust_screen = StockAdjustScreen(
            self.page,
            self.db,
            self.sync_service,
            self.auth_service,
            self.current_user,
            product,
            on_updated=self.on_product_updated
        )
        adjust_screen.show()
    
    def open_price_edit_screen(self, product):
        """Ouvre l'écran de modification du prix"""
        from screens.edit_product_screen import EditProductScreen
        
        price_screen = EditProductScreen(
            self.page,
            self.db,
            self.sync_service,
            self.auth_service,
            self.current_user,
            product,
            on_updated=self.on_product_updated
        )
        price_screen.show()
    
    def open_product_details_screen(self, product):
        """Ouvre l'écran des détails du produit"""
        from screens.details_screen import DetailsScreen
        
        details_screen = DetailsScreen(
            self.page,
            self.db,
            self.sync_service,
            self.auth_service,
            self.current_user,
            product
        )
        details_screen.show()
    
    def on_product_updated(self):
        """Callback après modification d'un produit"""
        # Recharger les produits
        self.load_all_products()
        self.apply_filters_and_paginate()
        self.display_current_page()
        self.update_pagination_buttons_state()
        self.show_snackbar("✅ Produit mis à jour", ft.Colors.GREEN)
    
    def create_product_card(self, product) -> ft.Card:
        """Crée une carte produit avec indicateur du mode online/offline et boutons d'action"""
        # Récupérer les attributs du produit
        product_name = self.safe_str(self._get_product_attr(product, "name"), "Produit inconnu")
        product_code = self.safe_str(self._get_product_attr(product, "code"), "N/A")
        product_category = self.safe_str(self._get_product_attr(product, "category"), "Non catégorisé")
        product_id = self._get_product_attr(product, "server_id") or self._get_product_attr(product, "id")

        # Récupérer le prix
        product_price_value = self._get_product_attr(product, "selling_price")
        if product_price_value is None:
            product_price_value = self._get_product_attr(product, "price", 0)
        product_price = self.safe_number(product_price_value, 0)

        # Récupérer le stock
        product_stock_value = self._get_product_attr(product, "quantity")
        if product_stock_value is None:
            product_stock_value = self._get_product_attr(product, "stock", 0)
        product_stock = self.safe_number(product_stock_value, 0)

        # Déterminer le style du stock
        if product_stock > 10:
            stock_color = ft.Colors.GREEN
            stock_text = "En stock"
        elif product_stock > 0:
            stock_color = ft.Colors.ORANGE
            stock_text = "Stock faible"
        else:
            stock_color = ft.Colors.RED
            stock_text = "Rupture"

        progress_value = min(max(product_stock / 100, 0), 1.0)
        
        # Badge offline
        offline_badge = None
        if not self._is_online:
            offline_badge = ft.Container(
                content=ft.Icon(ft.Icons.CLOUD_OFF, size=12, color=ft.Colors.GREY_500),
                padding=ft.Padding.symmetric(horizontal=5),
                tooltip="Données locales (mode hors-ligne)",
            )

        # ========== BOUTONS D'ACTION ==========
        action_buttons = []
        
        # Bouton Détails (toujours visible pour tous les utilisateurs)
        details_button = ft.IconButton(
            icon=ft.Icons.INFO_OUTLINE,
            icon_size=18,
            tooltip="Voir les détails",
            on_click=lambda e, p=product: self.open_product_details_screen(p),
        )
        action_buttons.append(details_button)
        
        # Bouton Modifier (si permission edit_product ou admin)
        if self.can_edit_product or self.is_admin:
            edit_button = ft.IconButton(
                icon=ft.Icons.EDIT,
                icon_size=18,
                tooltip="Modifier le produit",
                on_click=lambda e, p=product: self.open_edit_product_screen(p),
            )
            action_buttons.append(edit_button)
        
        # Bouton Ajouter au stock (si permission edit_stock ou admin)
        if self.can_edit_stock or self.is_admin:
            stock_button = ft.IconButton(
                icon=ft.Icons.ADD_BOX,
                icon_size=18,
                tooltip="Ajouter au stock",
                on_click=lambda e, p=product: self.open_stock_adjustment_screen(p),
            )
            action_buttons.append(stock_button)
        
        # Bouton Modifier le prix (si permission edit_price ou admin)
        if self.can_edit_price or self.is_admin:
            price_button = ft.IconButton(
                icon=ft.Icons.PRICE_CHANGE,
                icon_size=18,
                tooltip="Modifier le prix",
                on_click=lambda e, p=product: self.open_price_edit_screen(p),
            )
            action_buttons.append(price_button)
        
        # Barre d'actions (affichée seulement si des boutons sont disponibles)
        actions_row = ft.Row(
            controls=action_buttons if action_buttons else [],
            spacing=4,
            alignment=ft.MainAxisAlignment.END,
        )
        
        # Badge admin sur le produit (optionnel, pour debug)
        admin_badge = None
        if self.is_admin:
            admin_badge = ft.Container(
                content=ft.Text("ADMIN", size=8, color=ft.Colors.WHITE),
                bgcolor=ft.Colors.PURPLE_400,
                padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                border_radius=10,
            )

        return ft.Card(
            elevation=2,
            margin=ft.Margin.symmetric(horizontal=4, vertical=4),
            content=ft.Container(
                padding=12,
                bgcolor=ft.Colors.WHITE,
                border_radius=16,
                content=ft.Column(
                    spacing=8,
                    controls=[
                        # Ligne principale avec info produit
                        ft.Row(
                            controls=[
                                ft.Container(
                                    expand=True,
                                    content=ft.Column(
                                        spacing=4,
                                        controls=[
                                            ft.Row(
                                                controls=[
                                                    ft.Text(
                                                        product_name,
                                                        size=16,
                                                        weight=ft.FontWeight.BOLD,
                                                        color=ft.Colors.BLUE_GREY_900,
                                                        expand=True,
                                                    ),
                                                    offline_badge if offline_badge else ft.Container(),
                                                    admin_badge if admin_badge else ft.Container(),
                                                ],
                                                spacing=4,
                                            ),
                                            ft.Text(
                                                f"Code : {product_code}",
                                                size=12,
                                                color=ft.Colors.GREY_700,
                                            ),
                                            ft.Text(
                                                product_category,
                                                size=12,
                                                color=ft.Colors.BLUE_700,
                                            ),
                                        ],
                                    ),
                                ),
                                ft.Column(
                                    horizontal_alignment=ft.CrossAxisAlignment.END,
                                    spacing=6,
                                    controls=[
                                        ft.Text(
                                            self.format_fc(product_price),
                                            size=18,
                                            weight=ft.FontWeight.BOLD,
                                            color=ft.Colors.GREEN_700,
                                        ),
                                        ft.Container(
                                            padding=ft.Padding.symmetric(horizontal=8, vertical=5),
                                            border_radius=8,
                                            bgcolor=stock_color,
                                            content=ft.Text(
                                                f"Stock : {int(product_stock) if product_stock.is_integer() else product_stock}",
                                                size=12,
                                                color=ft.Colors.WHITE,
                                                weight=ft.FontWeight.W_500,
                                            ),
                                        ),
                                    ],
                                ),
                            ],
                            vertical_alignment=ft.CrossAxisAlignment.START,
                        ),
                        # Barre de progression du stock
                        ft.ProgressBar(
                            value=progress_value,
                            color=stock_color,
                            bgcolor=ft.Colors.GREY_300,
                            height=6,
                            border_radius=10,
                        ),
                        # Ligne avec statut stock et boutons d'action
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Text(
                                    stock_text,
                                    size=12,
                                    color=stock_color,
                                    weight=ft.FontWeight.W_500,
                                ),
                                actions_row,
                            ],
                        ),
                    ],
                ),
            ),
        )

    # =========================================================
    # ÉVÉNEMENTS ET NAVIGATION
    # =========================================================
    def on_search_change(self, e=None) -> None:
        """Recherche en temps réel"""
        self.current_page = 1
        self.apply_filters_and_paginate()
        self.display_current_page()
        self.update_pagination_buttons_state()

    def filter_by_category(self, category: str | None) -> None:
        self.current_category = category
        self.current_page = 1
        for cat, button in self.category_buttons.items():
            is_selected = (cat == category) or (cat is None and category is None)
            button.style = self.get_filter_button_style(is_selected)
        self.apply_filters_and_paginate()
        self.display_current_page()
        self.update_pagination_buttons_state()

    def refresh_products(self) -> None:
        """Rafraîchit les produits - selon le mode online/offline"""
        if not self._is_online:
            self.show_snackbar("⚠️ Mode OFFLINE - Impossible de synchroniser avec le serveur", ft.Colors.ORANGE)
            return
        
        if self._syncing:
            self.show_snackbar("Synchronisation déjà en cours...", ft.Colors.BLUE)
            return
        
        self.show_snackbar("🔄 Synchronisation des produits...", ft.Colors.BLUE)
        self.sync_products_from_server()

    def go_to_add_product(self) -> None:
        """Navigue vers l'écran d'ajout de produit"""
        from screens.add_product_screen import AddProductScreen
        
        add_screen = AddProductScreen(
            self.page,
            self.db,
            self.sync_service,
            self.auth_service,
            self.current_user,
            on_product_added=self.on_product_updated
        )
        add_screen.show()

    def go_back(self) -> None:
        from screens.dashboard_screen import DashboardScreen

        dashboard = DashboardScreen(
            self.page,
            self.db,
            self.sync_service,
            self.auth_service,
            self.current_user,
        )
        dashboard.show()