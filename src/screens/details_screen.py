# screens/details_screen.py
"""
Écran de détail d'un produit - Version Responsive avec mode Online/Offline
Affiche toutes les informations d'un produit sélectionné avec gestion des actions
suivant les permissions utilisateur.
"""
import flet as ft
from typing import Optional
import threading
from services.connection_manager import ConnectionManager
import logging

logger = logging.getLogger(__name__)


class DetailsScreen:
    """Écran d'affichage des détails d'un produit"""

    def __init__(
        self,
        page: ft.Page,
        db,
        sync_service,
        auth_service,
        current_user,
        product,  # Peut être dict ou objet
        on_updated: Optional[callable] = None,
    ):
        self.page = page
        self.db = db
        self.sync_service = sync_service
        self.auth_service = auth_service
        self.current_user = current_user
        self.product = product
        self.on_updated = on_updated

        # ========== CONNECTION MANAGER ==========
        self.connection_manager = ConnectionManager()
        self.connection_manager.register_observer(self._on_connection_status_changed)
        self._is_online = self.connection_manager.is_online_mode()

        self.is_header_initialized = False
        self.connection_indicator: Optional[ft.Container] = None

        # ========== PERMISSIONS ==========
        self._load_user_permissions()

    # ==================== GESTION PERMISSIONS ====================

    def _load_user_permissions(self):
        """Charge les permissions de l'utilisateur courant"""
        self.user_role = (
            self.current_user.get("role", "").lower() if self.current_user else ""
        )
        self.is_admin = self.user_role in ["admin", "super_admin", "superadmin"]

        # Permissions spécifiques
        self.can_edit_product = self._has_permission("can_edit_product")
        self.can_edit_stock = self._has_permission("can_edit_stock")
        self.can_edit_price = self._has_permission("can_edit_price")
        self.can_delete_product = self._has_permission("can_delete_product")

        logger.info(
            f"Permissions Détails - admin={self.is_admin}, edit_product={self.can_edit_product}"
        )

    def _has_permission(self, permission_key: str) -> bool:
        """Vérifie si l'utilisateur a une permission spécifique"""
        if self.is_admin:
            return True

        if self.current_user:
            permissions = self.current_user.get("permissions", {})
            if permission_key in permissions:
                return permissions[permission_key]

        try:
            branch_id = self.get_branch_id()
            user_id = self.current_user.get("id") if self.current_user else None
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
        logger.info(f"📡 DetailsScreen: Statut connexion - online={is_online}")

        if self.is_header_initialized and self.connection_indicator:
            self.update_connection_indicator()
            self.page.update()

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

    def create_connection_indicator(self) -> ft.Container:
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

    # ==================== UTILITAIRES ====================

    def show_snackbar(self, message: str, color: str = ft.Colors.BLUE) -> None:
        """Affiche une notification temporaire"""
        self.page.snack_bar = ft.SnackBar(
            content=ft.Text(message), bgcolor=color, open=True
        )
        self.page.update()

    def get_branch_id(self) -> Optional[str]:
        """Récupère l'ID de la branche de l'utilisateur"""
        if not self.current_user:
            return None
        return (
            self.current_user.get("active_branch_id") or self.current_user.get("branch_id")
        )

    def safe_str(self, value, default: str = "") -> str:
        """Convertit une valeur en string de manière sécurisée"""
        if value is None:
            return default
        return str(value)

    def safe_number(self, value, default: float = 0) -> float:
        """Convertit une valeur en nombre de manière sécurisée"""
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def format_fc(self, value) -> str:
        """Formate un nombre en monnaie locale"""
        amount = self.safe_number(value, 0)
        return f"{amount:,.0f} FC"

    def _get_product_attr(self, attr_name: str, default=None):
        """Récupère un attribut du produit (dict ou objet)"""
        if isinstance(self.product, dict):
            return self.product.get(attr_name, default)
        else:
            return getattr(self.product, attr_name, default)

    def format_date(self, date_str: Optional[str]) -> str:
        """Formate une date pour l'affichage"""
        if not date_str:
            return "Non définie"
        try:
            # Gérer différents formats
            if "T" in date_str:
                date_str = date_str.split("T")[0]
            if " " in date_str:
                date_str = date_str.split(" ")[0]
            # Format YYYY-MM-DD -> DD/MM/YYYY
            parts = date_str.split("-")
            if len(parts) == 3:
                return f"{parts[2]}/{parts[1]}/{parts[0]}"
            return date_str
        except:
            return date_str

    def get_expiry_status_info(self, status: Optional[str]) -> dict:
        """Retourne les informations de statut d'expiration"""
        status_map = {
            "expired": {"text": "Expiré", "color": ft.Colors.RED, "icon": ft.Icons.DANGEROUS},
            "critical": {"text": "Critique", "color": ft.Colors.DEEP_ORANGE, "icon": ft.Icons.WARNING},
            "warning": {"text": "Expire bientôt", "color": ft.Colors.ORANGE, "icon": ft.Icons.HOURGLASS_EMPTY},
            "soon": {"text": "Expire bientôt", "color": ft.Colors.ORANGE, "icon": ft.Icons.HOURGLASS_EMPTY},
            "valid": {"text": "Valide", "color": ft.Colors.GREEN, "icon": ft.Icons.CHECK_CIRCLE},
            "unknown": {"text": "Non définie", "color": ft.Colors.GREY, "icon": ft.Icons.HELP},
        }
        return status_map.get(status, status_map["unknown"])

    def get_stock_status_info(self, quantity: float, min_stock: float = 10) -> dict:
        """Retourne les informations de statut de stock"""
        if quantity <= 0:
            return {"text": "Rupture de stock", "color": ft.Colors.RED, "icon": ft.Icons.ERROR}
        elif quantity <= min_stock:
            return {"text": "Stock faible", "color": ft.Colors.ORANGE, "icon": ft.Icons.WARNING_AMBER}
        else:
            return {"text": "En stock", "color": ft.Colors.GREEN, "icon": ft.Icons.CHECK_CIRCLE}

    # ==================== NAVIGATION ====================

    def go_to_edit_product(self):
        """Navigue vers l'écran de modification du produit"""
        from screens.edit_product_screen import EditProductScreen

        edit_screen = EditProductScreen(
            self.page,
            self.db,
            self.sync_service,
            self.auth_service,
            self.current_user,
            self.product,
            on_updated=self.on_product_updated,
            notification_manager=None,
        )
        edit_screen.show()

    def go_to_stock_adjustment(self):
        """Navigue vers l'écran d'ajustement de stock"""
        from screens.stock_adjust_screen import StockAdjustScreen

        adjust_screen = StockAdjustScreen(
            self.page,
            self.db,
            self.sync_service,
            self.auth_service,
            self.current_user,
            self.product,
            on_updated=self.on_product_updated,
        )
        adjust_screen.show()

    def go_to_price_edit(self):
        """Navigue vers l'écran de modification du prix"""
        from screens.edit_product_screen import EditProductScreen

        price_screen = EditProductScreen(
            self.page,
            self.db,
            self.sync_service,
            self.auth_service,
            self.current_user,
            self.product,
            on_updated=self.on_product_updated,
        )
        price_screen.show()

    def on_product_updated(self):
        """Callback après modification du produit"""
        # Recharger les données du produit depuis la base
        product_id = self._get_product_attr("server_id") or self._get_product_attr("id")
        if product_id:
            # Essayer de récupérer le produit mis à jour
            updated_product = self.db.get_product_by_id(product_id)
            if updated_product:
                self.product = updated_product
            elif isinstance(self.product, dict):
                # Recharger depuis la base en dict
                updated_dict = self.db.get_product_by_server_id(product_id)
                if updated_dict:
                    self.product = updated_dict

        # Rafraîchir l'affichage
        self.show()
        if self.on_updated:
            self.on_updated()

    def go_back(self):
        """Retour à l'écran des produits"""
        from screens.products_screen import ProductsScreen

        products_screen = ProductsScreen(
            self.page,
            self.db,
            self.sync_service,
            self.auth_service,
            self.current_user,
        )
        products_screen.show()

    def show_delete_confirmation(self):
        """Affiche une boîte de dialogue de confirmation de suppression"""

        def confirm_delete(e):
            dialog.open = False
            self.page.update()
            self.delete_product()

        def cancel_delete(e):
            dialog.open = False
            self.page.update()

        dialog = ft.AlertDialog(
            title=ft.Text("Supprimer le produit", size=18, weight=ft.FontWeight.BOLD),
            content=ft.Text(
                f"Êtes-vous sûr de vouloir supprimer le produit "
                f'"{self._get_product_attr("name")}" ?\n\n'
                f"Cette action est irréversible.",
                size=14,
            ),
            actions=[
                ft.TextButton("Annuler", on_click=cancel_delete),
                ft.Button(
                    "Supprimer",
                    on_click=confirm_delete,
                    bgcolor=ft.Colors.RED,
                    color=ft.Colors.WHITE,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        self.page.dialog = dialog
        dialog.open = True
        self.page.update()

    def delete_product(self):
        """Supprime le produit (soft delete)"""

        def do_delete():
            try:
                product_id = self._get_product_attr("server_id") or self._get_product_attr("id")
                if not product_id:
                    self.show_snackbar("Impossible d'identifier le produit", ft.Colors.RED)
                    return

                # Mettre à jour le statut is_deleted
                if hasattr(self.db, "execute_update"):
                    success = self.db.execute_update(
                        "UPDATE products SET is_deleted = 1 WHERE server_id = ?",
                        (product_id,),
                    )
                else:
                    # Fallback: marquer comme supprimé via l'objet
                    product = self.db.get_product_by_id(product_id)
                    if product:
                        product.is_deleted = True
                        self.db.save_products([product])
                        success = True
                    else:
                        success = False

                if success:
                    self.show_snackbar("✅ Produit supprimé", ft.Colors.GREEN)
                    self.page.run_thread(lambda: self.go_back())
                else:
                    self.show_snackbar("❌ Erreur lors de la suppression", ft.Colors.RED)

            except Exception as e:
                logger.error(f"Erreur suppression produit: {e}")
                self.page.run_thread(
                    lambda: self.show_snackbar(f"Erreur: {str(e)}", ft.Colors.RED)
                )

        threading.Thread(target=do_delete, daemon=True).start()

    # ==================== AFFICHAGE ====================

    def show(self) -> None:
        """Affiche l'écran de détail du produit"""
        self.page.clean()
        self.page.scroll = ft.ScrollMode.AUTO
        self.page.padding = 0
        self.page.bgcolor = ft.Colors.GREY_100

        # Recharger les permissions
        self._load_user_permissions()

        # Récupérer les informations du produit
        product_name = self.safe_str(self._get_product_attr("name"), "Produit inconnu")
        product_code = self.safe_str(self._get_product_attr("code"), "N/A")
        product_barcode = self.safe_str(self._get_product_attr("barcode"), "N/A")
        product_quantity = self.safe_number(self._get_product_attr("quantity"), 0)
        product_stock = product_quantity
        product_selling_price = self.safe_number(self._get_product_attr("selling_price"), 0)
        product_purchase_price = self.safe_number(self._get_product_attr("purchase_price"), 0)
        product_wholesale_price = self.safe_number(self._get_product_attr("wholesale_price"), 0)
        product_category = self.safe_str(self._get_product_attr("category"), "Non catégorisé")
        product_subcategory = self.safe_str(self._get_product_attr("subcategory"), "")
        product_product_type = self.safe_str(self._get_product_attr("product_type"), "Médicament")
        product_expiry_date = self._get_product_attr("expiry_date")
        product_expiry_status = self._get_product_attr("expiry_status")
        product_supplier = self.safe_str(self._get_product_attr("supplier"), "")
        product_laboratory = self.safe_str(self._get_product_attr("laboratory"), "")
        product_manufacturer = self.safe_str(
            self._get_product_attr("manufacturer") or self._get_product_attr("main_supplier"), ""
        )
        product_description = self.safe_str(self._get_product_attr("description"), "")
        product_min_stock = self.safe_number(self._get_product_attr("min_stock"), 10)
        product_max_stock = self.safe_number(self._get_product_attr("max_stock"), 0)
        product_unit = self.safe_str(self._get_product_attr("unit"), "pièce")
        product_tax_rate = self.safe_number(self._get_product_attr("tax_rate"), 0)
        product_location = self.safe_str(self._get_product_attr("location"), "")
        product_lot_number = self.safe_str(self._get_product_attr("lot_number"), "")
        product_has_tva = self._get_product_attr("has_tva", False)

        # Si le produit a une propriété has_tva (booléen)
        if isinstance(product_has_tva, bool):
            tva_display = f"{product_tax_rate}%" if product_has_tva and product_tax_rate > 0 else "0%"
        else:
            tva_display = f"{product_tax_rate}%" if product_tax_rate > 0 else "Non applicable"

        # Statuts
        stock_info = self.get_stock_status_info(product_stock, product_min_stock)
        expiry_info = self.get_expiry_status_info(product_expiry_status)

        # Calcul de la marge
        if product_purchase_price > 0:
            margin = product_selling_price - product_purchase_price
            margin_percent = (margin / product_purchase_price) * 100
        else:
            margin = 0
            margin_percent = 0

        # Construction du header
        header = self.build_header(product_name)
        connection_indicator = self.create_connection_indicator()

        # Mettre à jour le header avec l'indicateur
        header.content.controls = [
            self.build_back_button(),
            ft.Text(product_name, size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE, expand=True),
            connection_indicator,
            self.build_action_buttons(),
        ]

        # Corps principal
        body = self.build_body(
            product_name,
            product_code,
            product_barcode,
            product_stock,
            product_selling_price,
            product_purchase_price,
            product_wholesale_price,
            product_category,
            product_subcategory,
            product_product_type,
            product_expiry_date,
            product_expiry_status,
            product_supplier,
            product_laboratory,
            product_manufacturer,
            product_description,
            product_min_stock,
            product_max_stock,
            product_unit,
            tva_display,
            product_location,
            product_lot_number,
            stock_info,
            expiry_info,
            margin,
            margin_percent,
        )

        main_content = ft.Column(
            controls=[
                header,
                body,
            ],
            expand=True,
            spacing=0,
        )

        self.page.add(main_content)
        self.is_header_initialized = True
        self.page.update()

    def build_back_button(self) -> ft.IconButton:
        """Crée le bouton de retour"""
        return ft.IconButton(
            icon=ft.Icons.ARROW_BACK,
            on_click=lambda e: self.go_back(),
            icon_color=ft.Colors.WHITE,
            tooltip="Retour à la liste",
        )

    def build_action_buttons(self) -> ft.Row:
        """Crée les boutons d'action dans le header"""
        buttons = []

        # Bouton Modifier (si permission)
        if self.can_edit_product or self.is_admin:
            buttons.append(
                ft.IconButton(
                    icon=ft.Icons.EDIT,
                    on_click=lambda e: self.go_to_edit_product(),
                    icon_color=ft.Colors.WHITE,
                    tooltip="Modifier le produit",
                )
            )

        # Bouton Ajuster le stock (si permission)
        if self.can_edit_stock or self.is_admin:
            buttons.append(
                ft.IconButton(
                    icon=ft.Icons.ADD_BOX,
                    on_click=lambda e: self.go_to_stock_adjustment(),
                    icon_color=ft.Colors.WHITE,
                    tooltip="Ajuster le stock",
                )
            )

        # Bouton Modifier le prix (si permission)
        if self.can_edit_price or self.is_admin:
            buttons.append(
                ft.IconButton(
                    icon=ft.Icons.PRICE_CHANGE,
                    on_click=lambda e: self.go_to_price_edit(),
                    icon_color=ft.Colors.WHITE,
                    tooltip="Modifier le prix",
                )
            )

        # Bouton Supprimer (si permission)
        if self.can_delete_product or self.is_admin:
            buttons.append(
                ft.IconButton(
                    icon=ft.Icons.DELETE_OUTLINE,
                    on_click=lambda e: self.show_delete_confirmation(),
                    icon_color=ft.Colors.RED_200,
                    tooltip="Supprimer le produit",
                )
            )

        return ft.Row(controls=buttons, spacing=4)

    def build_header(self, title: str) -> ft.Container:
        """Construit l'en-tête de l'écran"""
        return ft.Container(
            content=ft.Row(
                controls=[
                    self.build_back_button(),
                    ft.Text(title, size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE, expand=True),
                ],
                alignment=ft.MainAxisAlignment.START,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=8, vertical=10),
            bgcolor=ft.Colors.BLUE_700,
        )

    def build_info_card(
        self,
        title: str,
        icon: str,
        fields: list,
        icon_color: str = ft.Colors.BLUE_700,
    ) -> ft.Card:
        """Construit une carte d'informations générique"""
        return ft.Card(
            elevation=2,
            margin=ft.Margin.symmetric(horizontal=12, vertical=4),
            content=ft.Container(
                padding=12,
                bgcolor=ft.Colors.WHITE,
                content=ft.Column(
                    spacing=10,
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Icon(icon, size=20, color=icon_color),
                                ft.Text(title, size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_GREY_900),
                            ],
                            spacing=8,
                        ),
                        ft.Divider(height=1, color=ft.Colors.GREY_200),
                    ]
                    + fields,
                ),
            ),
        )

    def build_body(
        self,
        name,
        code,
        barcode,
        quantity,
        selling_price,
        purchase_price,
        wholesale_price,
        category,
        subcategory,
        product_type,
        expiry_date,
        expiry_status,
        supplier,
        laboratory,
        manufacturer,
        description,
        min_stock,
        max_stock,
        unit,
        tva_display,
        location,
        lot_number,
        stock_info,
        expiry_info,
        margin,
        margin_percent,
    ) -> ft.Column:
        """Construit le corps de l'écran avec toutes les informations"""

        # ========== Carte principale stock / prix ==========
        main_card = ft.Card(
            elevation=3,
            margin=ft.Margin.symmetric(horizontal=12, vertical=8),
            content=ft.Container(
                padding=16,
                bgcolor=ft.Colors.WHITE,
                content=ft.Row(
                    controls=[
                        # Informations stock
                        ft.Column(
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=4,
                            expand=True,
                            controls=[
                                ft.Container(
                                    width=60,
                                    height=60,
                                    bgcolor=stock_info["color"] + "20",
                                    border_radius=30,
                                    content=ft.Icon(stock_info["icon"], size=30, color=stock_info["color"]),
                                ),
                                ft.Text(
                                    f"{int(quantity) if quantity.is_integer() else quantity} {unit}",
                                    size=24,
                                    weight=ft.FontWeight.BOLD,
                                    color=stock_info["color"],
                                ),
                                ft.Text(
                                    stock_info["text"],
                                    size=12,
                                    color=stock_info["color"],
                                    weight=ft.FontWeight.W_500,
                                ),
                                ft.Text(
                                    f"Seuil min: {min_stock} {unit}",
                                    size=11,
                                    color=ft.Colors.GREY_600,
                                ),
                                ft.ProgressBar(
                                    value=min(quantity / max(min_stock, 1), 1.0),
                                    color=stock_info["color"],
                                    bgcolor=ft.Colors.GREY_300,
                                    width=100,
                                    height=4,
                                ),
                            ],
                        ),
                        ft.VerticalDivider(width=1, color=ft.Colors.GREY_300),
                        # Informations prix
                        ft.Column(
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=4,
                            expand=True,
                            controls=[
                                ft.Text(
                                    self.format_fc(selling_price),
                                    size=22,
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.GREEN_700,
                                ),
                                ft.Text("Prix de vente TTC", size=11, color=ft.Colors.GREY_600),
                                ft.Divider(height=5, color=ft.Colors.TRANSPARENT),
                                ft.Text(
                                    self.format_fc(purchase_price),
                                    size=16,
                                    color=ft.Colors.GREY_700,
                                ),
                                ft.Text("Prix d'achat HT", size=11, color=ft.Colors.GREY_500),
                                ft.Divider(height=5, color=ft.Colors.TRANSPARENT),
                                ft.Row(
                                    controls=[
                                        ft.Text(
                                            f"Marge: {self.format_fc(margin)}",
                                            size=12,
                                            color=ft.Colors.BLUE_700 if margin > 0 else ft.Colors.RED,
                                            weight=ft.FontWeight.W_500,
                                        ),
                                        ft.Text(
                                            f"({margin_percent:.1f}%)",
                                            size=11,
                                            color=ft.Colors.GREY_600,
                                        ),
                                    ],
                                    spacing=4,
                                ),
                            ],
                        ),
                        ft.VerticalDivider(width=1, color=ft.Colors.GREY_300),
                        # Informations TVA / unité
                        ft.Column(
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=4,
                            expand=True,
                            controls=[
                                ft.Container(
                                    width=50,
                                    height=50,
                                    bgcolor=ft.Colors.BLUE_50,
                                    border_radius=25,
                                    content=ft.Icon(ft.Icons.SHOPPING_BASKET, size=24, color=ft.Colors.BLUE_700),
                                ),
                                ft.Text(unit, size=14, color=ft.Colors.BLUE_700, weight=ft.FontWeight.BOLD),
                                ft.Text("Unité de vente", size=10, color=ft.Colors.GREY_600),
                                ft.Divider(height=5, color=ft.Colors.TRANSPARENT),
                                ft.Text(tva_display, size=14, weight=ft.FontWeight.BOLD),
                                ft.Text("TVA", size=10, color=ft.Colors.GREY_600),
                            ],
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_EVENLY,
                ),
            ),
        )

        # ========== Informations générales ==========
        general_fields = [
            self.build_info_row("Code produit", code, ft.Icons.INVENTORY, ft.Colors.BLUE_700),
            self.build_info_row("Code-barres", barcode or "Non défini", ft.Icons.QR_CODE_SCANNER, ft.Colors.BLUE_700),
            self.build_info_row("Catégorie", category, ft.Icons.CATEGORY, ft.Colors.GREEN_700),
            ft.Divider(height=1, color=ft.Colors.GREY_200),
            self.build_info_row("Sous-catégorie", subcategory or "Non définie", ft.Icons.LABEL_OUTLINE, ft.Colors.GREEN_700),
            self.build_info_row("Type", product_type, ft.Icons.MEDICATION, ft.Colors.PURPLE_700),
            ft.Divider(height=1, color=ft.Colors.GREY_200),
            self.build_info_row("Emplacement", location or "Non défini", ft.Icons.LOCATION_ON, ft.Colors.ORANGE_700),
            self.build_info_row("Numéro de lot", lot_number or "Non défini", ft.Icons.NUMBERS, ft.Colors.GREY_700),
        ]

        general_card = self.build_info_card(
            "Informations générales",
            ft.Icons.INFO_OUTLINE,
            general_fields,
            ft.Colors.BLUE_700,
        )

        # ========== Fournisseur ==========
        supplier_fields = [
            self.build_info_row("Fournisseur principal", supplier or "Non défini", ft.Icons.LOCAL_SHIPPING, ft.Colors.INDIGO_700),
            ft.Divider(height=1, color=ft.Colors.GREY_200),
            self.build_info_row("Laboratoire", laboratory or "Non défini", ft.Icons.SCIENCE, ft.Colors.PURPLE_700),
            ft.Divider(height=1, color=ft.Colors.GREY_200),
            self.build_info_row("Fabricant", manufacturer or "Non défini", ft.Icons.FACTORY, ft.Colors.GREY_700),
        ]
        if not supplier and not laboratory and not manufacturer:
            supplier_fields = [ft.Text("Aucune information fournisseur", size=12, color=ft.Colors.GREY_500, italic=True)]

        supplier_card = self.build_info_card(
            "Fournisseur & Fabrication",
            ft.Icons.BUSINESS,
            supplier_fields,
            ft.Colors.INDIGO_700,
        )

        # ========== Dates ==========
        expiry_display = self.format_date(expiry_date) if expiry_date else "Non définie"
        expiry_date_fields = [
            ft.Row(
                controls=[
                    ft.Icon(expiry_info["icon"], size=18, color=expiry_info["color"]),
                    ft.Text("Date d'expiration:", size=13, weight=ft.FontWeight.W_500, color=ft.Colors.GREY_700),
                    ft.Text(expiry_display, size=13, color=expiry_info["color"]),
                ],
                spacing=8,
            ),
            ft.Row(
                controls=[
                    ft.Container(width=26),
                    ft.Text(expiry_info["text"], size=11, color=expiry_info["color"]),
                ],
                spacing=0,
            ),
        ]

        expiry_card = ft.Card(
            elevation=2,
            margin=ft.Margin.symmetric(horizontal=12, vertical=4),
            content=ft.Container(
                padding=12,
                bgcolor=expiry_info["color"] + "10",
                content=ft.Column(spacing=6, controls=expiry_date_fields),
            ),
        )

        # ========== Description ==========
        description_card = None
        if description:
            description_card = ft.Card(
                elevation=2,
                margin=ft.Margin.symmetric(horizontal=12, vertical=4),
                content=ft.Container(
                    padding=12,
                    bgcolor=ft.Colors.WHITE,
                    content=ft.Column(
                        spacing=8,
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.DESCRIPTION, size=18, color=ft.Colors.BLUE_700),
                                    ft.Text("Description", size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_GREY_900),
                                ],
                                spacing=6,
                            ),
                            ft.Divider(height=1, color=ft.Colors.GREY_200),
                            ft.Text(description, size=12, color=ft.Colors.GREY_800),
                        ],
                    ),
                ),
            )

        # ========== Assemblage ==========
        return ft.Column(
            controls=[
                main_card,
                general_card,
                supplier_card,
                expiry_card,
                description_card if description_card else ft.Container(),
                ft.Container(height=20),  # Espacement en bas
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def build_info_row(self, label: str, value: str, icon: str, icon_color: str) -> ft.Row:
        """Construit une ligne d'information icône + label + valeur"""
        return ft.Row(
            controls=[
                ft.Icon(icon, size=16, color=icon_color),
                ft.Text(label + ":", size=13, weight=ft.FontWeight.W_500, color=ft.Colors.GREY_700),
                ft.Text(value, size=13, color=ft.Colors.GREY_800, expand=True),
            ],
            spacing=8,
        )