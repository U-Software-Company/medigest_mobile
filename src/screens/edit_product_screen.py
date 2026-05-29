# screens/edit_product_screen.py
"""
Écran de modification d'un produit - Version Responsive avec mode Online/Offline
Permet de modifier toutes les informations d'un produit existant
Adapté pour mobile, tablette et desktop
"""
import flet as ft
from typing import Optional, Dict, Any
import threading
from services.connection_manager import ConnectionManager
import logging

logger = logging.getLogger(__name__)


class EditProductScreen:
    """Écran de modification d'un produit"""

    def __init__(
        self,
        page: ft.Page,
        db,
        sync_service,
        auth_service,
        current_user,
        product,  # Peut être dict ou objet
        on_updated: Optional[callable] = None,
        notification_manager=None,
    ):
        self.page = page
        self.db = db
        self.sync_service = sync_service
        self.auth_service = auth_service
        self.current_user = current_user
        self.product = product
        self.on_updated = on_updated
        self.notification_manager = notification_manager

        # ========== CONNECTION MANAGER ==========
        self.connection_manager = ConnectionManager()
        self.connection_manager.register_observer(self._on_connection_status_changed)
        self._is_online = self.connection_manager.is_online_mode()

        self.is_header_initialized = False
        self.connection_indicator: Optional[ft.Container] = None

        # Conteneur principal (comme dans config_screen)
        self.container = ft.Container(expand=True, padding=0)

        # ========== CHAMPS DU FORMULAIRE ==========
        self.name_field: Optional[ft.TextField] = None
        self.code_field: Optional[ft.TextField] = None
        self.barcode_field: Optional[ft.TextField] = None
        self.category_field: Optional[ft.TextField] = None
        self.subcategory_field: Optional[ft.TextField] = None
        self.product_type_dropdown: Optional[ft.Dropdown] = None
        self.quantity_field: Optional[ft.TextField] = None
        self.purchase_price_field: Optional[ft.TextField] = None
        self.selling_price_field: Optional[ft.TextField] = None
        self.wholesale_price_field: Optional[ft.TextField] = None
        self.unit_field: Optional[ft.TextField] = None
        self.min_stock_field: Optional[ft.TextField] = None
        self.max_stock_field: Optional[ft.TextField] = None
        self.expiry_date_field: Optional[ft.TextField] = None
        self.date_picker: Optional[ft.DatePicker] = None
        self.supplier_field: Optional[ft.TextField] = None
        self.laboratory_field: Optional[ft.TextField] = None
        self.manufacturer_field: Optional[ft.TextField] = None
        self.location_field: Optional[ft.TextField] = None
        self.lot_number_field: Optional[ft.TextField] = None
        self.tax_rate_field: Optional[ft.TextField] = None
        self.has_tva_switch: Optional[ft.Switch] = None
        self.description_field: Optional[ft.TextField] = None
        self.notes_field: Optional[ft.TextField] = None

        # ========== PERMISSIONS ==========
        self._load_user_permissions()

        # ========== RÉCUPÉRATION DES DONNÉES INITIALES ==========
        self.initial_data = self._extract_product_data()

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

        logger.info(
            f"Permissions EditProduct - admin={self.is_admin}, "
            f"edit_product={self.can_edit_product}, edit_stock={self.can_edit_stock}"
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
        logger.info(f"📡 EditProductScreen: Statut connexion - online={is_online}")

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
        except Exception:
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

    def _extract_product_data(self) -> Dict[str, Any]:
        """Extrait toutes les données du produit pour initialisation"""
        return {
            "id": self._get_product_attr("id"),
            "server_id": self._get_product_attr("server_id") or self._get_product_attr("id"),
            "name": self.safe_str(self._get_product_attr("name")),
            "code": self.safe_str(self._get_product_attr("code")),
            "barcode": self.safe_str(self._get_product_attr("barcode")),
            "category": self.safe_str(self._get_product_attr("category")),
            "subcategory": self.safe_str(self._get_product_attr("subcategory")),
            "product_type": self.safe_str(
                self._get_product_attr("product_type"),
                "medicament"
            ),
            "quantity": self.safe_number(self._get_product_attr("quantity"), 0),
            "stock": self.safe_number(self._get_product_attr("stock"), 0),
            "purchase_price": self.safe_number(self._get_product_attr("purchase_price"), 0),
            "selling_price": self.safe_number(self._get_product_attr("selling_price"), 0),
            "wholesale_price": self.safe_number(self._get_product_attr("wholesale_price"), 0),
            "unit": self.safe_str(self._get_product_attr("unit"), "pièce"),
            "min_stock": self.safe_number(self._get_product_attr("min_stock"), 10),
            "max_stock": self.safe_number(self._get_product_attr("max_stock"), 0),
            "expiry_date": self._get_product_attr("expiry_date"),
            "expiry_status": self._get_product_attr("expiry_status"),
            "supplier": self.safe_str(self._get_product_attr("supplier")),
            "laboratory": self.safe_str(self._get_product_attr("laboratory")),
            "manufacturer": self.safe_str(
                self._get_product_attr("manufacturer") or 
                self._get_product_attr("main_supplier") or
                self._get_product_attr("manufacturer_name")
            ),
            "location": self.safe_str(self._get_product_attr("location")),
            "lot_number": self.safe_str(self._get_product_attr("lot_number")),
            "tax_rate": self.safe_number(self._get_product_attr("tax_rate"), 0),
            "has_tva": self._get_product_attr("has_tva", False),
            "description": self.safe_str(self._get_product_attr("description")),
            "notes": self.safe_str(self._get_product_attr("notes")),
            "is_active": self._get_product_attr("is_active", True),
            "is_deleted": self._get_product_attr("is_deleted", False),
        }

    def _get_quantity(self) -> float:
        """Récupère la quantité actuelle (stock)"""
        # La quantité peut être dans 'quantity' ou 'stock'
        qty = self._get_product_attr("quantity")
        if qty is None:
            qty = self._get_product_attr("stock", 0)
        return self.safe_number(qty, 0)

    # ==================== VALIDATION ====================

    def validate_form(self) -> bool:
        """Valide les champs du formulaire"""
        errors = []

        # Nom requis
        if not self.name_field or not self.name_field.value.strip():
            errors.append("Le nom du produit est requis")
            if self.name_field:
                self.name_field.error_text = "Nom requis"
                self.name_field.update()

        # Prix de vente non négatif
        try:
            selling_price = float(self.selling_price_field.value) if self.selling_price_field else 0
            if selling_price < 0:
                errors.append("Le prix de vente ne peut pas être négatif")
                if self.selling_price_field:
                    self.selling_price_field.error_text = "Prix invalide"
                    self.selling_price_field.update()
        except ValueError:
            errors.append("Format du prix de vente invalide")

        # Prix d'achat non négatif
        try:
            purchase_price = float(self.purchase_price_field.value) if self.purchase_price_field else 0
            if purchase_price < 0:
                errors.append("Le prix d'achat ne peut pas être négatif")
        except ValueError:
            pass

        # Quantité non négative
        if self.quantity_field:
            try:
                quantity = int(float(self.quantity_field.value)) if self.quantity_field.value else 0
                if quantity < 0:
                    errors.append("La quantité ne peut pas être négative")
            except ValueError:
                errors.append("Format de quantité invalide")

        # Stock minimum non négatif
        if self.min_stock_field and self.min_stock_field.value:
            try:
                min_stock = int(float(self.min_stock_field.value))
                if min_stock < 0:
                    errors.append("Le stock minimum ne peut pas être négatif")
            except ValueError:
                pass

        return len(errors) == 0

    # ==================== SAUVEGARDE ====================

    def save_product(self, e=None):
        """Sauvegarde les modifications du produit"""
        if not self.validate_form():
            self.show_snackbar("Veuillez corriger les erreurs", ft.Colors.RED)
            return

        # Récupérer les valeurs du formulaire
        product_id = self.initial_data["server_id"] or self.initial_data["id"]
        if not product_id:
            self.show_snackbar("Impossible d'identifier le produit", ft.Colors.RED)
            return

        # Récupérer la quantité (peut être modifiée par l'utilisateur)
        new_quantity = 0
        if self.quantity_field and self.quantity_field.value:
            try:
                new_quantity = int(float(self.quantity_field.value))
            except ValueError:
                new_quantity = 0

        old_quantity = self.initial_data.get("quantity", 0)
        if old_quantity == 0:
            old_quantity = self.initial_data.get("stock", 0)

        quantity_changed = new_quantity != old_quantity

        # Construire les données mises à jour
        updated_data = {
            "name": self.name_field.value.strip() if self.name_field else "",
            "code": self.code_field.value.strip() if self.code_field else "",
            "barcode": self.barcode_field.value.strip() if self.barcode_field else "",
            "category": self.category_field.value.strip() if self.category_field else "",
            "subcategory": self.subcategory_field.value.strip() if self.subcategory_field else "",
            "product_type": self.product_type_dropdown.value if self.product_type_dropdown else "medicament",
            "quantity": new_quantity,
            "stock": new_quantity,
            "purchase_price": float(self.purchase_price_field.value) if self.purchase_price_field and self.purchase_price_field.value else 0,
            "selling_price": float(self.selling_price_field.value) if self.selling_price_field and self.selling_price_field.value else 0,
            "wholesale_price": float(self.wholesale_price_field.value) if self.wholesale_price_field and self.wholesale_price_field.value else 0,
            "unit": self.unit_field.value.strip() if self.unit_field else "pièce",
            "min_stock": int(float(self.min_stock_field.value)) if self.min_stock_field and self.min_stock_field.value else 10,
            "max_stock": int(float(self.max_stock_field.value)) if self.max_stock_field and self.max_stock_field.value else 0,
            "expiry_date": self.expiry_date_field.value if self.expiry_date_field else None,
            "supplier": self.supplier_field.value.strip() if self.supplier_field else "",
            "laboratory": self.laboratory_field.value.strip() if self.laboratory_field else "",
            "manufacturer": self.manufacturer_field.value.strip() if self.manufacturer_field else "",
            "location": self.location_field.value.strip() if self.location_field else "",
            "lot_number": self.lot_number_field.value.strip() if self.lot_number_field else "",
            "tax_rate": float(self.tax_rate_field.value) if self.tax_rate_field and self.tax_rate_field.value else 0,
            "has_tva": self.has_tva_switch.value if self.has_tva_switch else False,
            "description": self.description_field.value.strip() if self.description_field else "",
            "notes": self.notes_field.value.strip() if self.notes_field else "",
            "updated_at": None,  # Sera défini par la base
        }

        # Calculer le statut d'expiration si date fournie
        if updated_data["expiry_date"]:
            from datetime import datetime
            try:
                expiry_str = updated_data["expiry_date"]
                if "T" in expiry_str:
                    expiry_str = expiry_str.split("T")[0]
                expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d").date()
                today = datetime.now().date()
                days_left = (expiry_date - today).days
                if days_left < 0:
                    updated_data["expiry_status"] = "expired"
                elif days_left <= 30:
                    updated_data["expiry_status"] = "soon"
                else:
                    updated_data["expiry_status"] = "valid"
            except:
                updated_data["expiry_status"] = "unknown"
        else:
            updated_data["expiry_status"] = "unknown"

        def do_save():
            try:
                # Sauvegarder dans la base locale
                if hasattr(self.db, "execute_update"):
                    # Construire la requête UPDATE
                    fields = []
                    params = []

                    for key, value in updated_data.items():
                        if key != "id" and key != "server_id":
                            fields.append(f"{key} = ?")
                            params.append(value)

                    params.append(product_id)
                    query = f"UPDATE products SET {', '.join(fields)} WHERE server_id = ?"
                    success = self.db.execute_update(query, params)
                else:
                    # Fallback: utiliser l'objet Product
                    product = self.db.get_product_by_id(product_id)
                    if product:
                        for key, value in updated_data.items():
                            if hasattr(product, key) and key not in ["id", "server_id"]:
                                setattr(product, key, value)
                        self.db.save_products([product])
                        success = True
                    else:
                        success = False

                if success:
                    # Si la quantité a changé, créer un mouvement de stock
                    if quantity_changed and hasattr(self.db, "execute_query"):
                        movement_query = """
                            INSERT INTO stock_movements 
                            (product_id, quantity_change, reason, created_at, branch_id)
                            VALUES (?, ?, ?, ?, ?)
                        """
                        from datetime import datetime
                        self.db.execute_update(
                            movement_query,
                            (
                                product_id,
                                new_quantity - old_quantity,
                                "Modification manuelle du stock",
                                datetime.now().isoformat(),
                                self.get_branch_id(),
                            ),
                        )

                    self.page.run_thread(lambda: self.show_snackbar("✅ Produit mis à jour", ft.Colors.GREEN))
                    self.page.run_thread(lambda: self.go_back())
                else:
                    self.page.run_thread(lambda: self.show_snackbar("❌ Erreur lors de la mise à jour", ft.Colors.RED))

            except Exception as e:
                logger.error(f"Erreur sauvegarde produit: {e}")
                self.page.run_thread(lambda: self.show_snackbar(f"Erreur: {str(e)}", ft.Colors.RED))

        # Démarrer la sauvegarde dans un thread séparé
        threading.Thread(target=do_save, daemon=True).start()

    # ==================== NAVIGATION ====================

    def go_back(self):
        """Retour à l'écran précédent"""
        if self.on_updated:
            self.on_updated()
        else:
            from screens.details_screen import DetailsScreen

            details_screen = DetailsScreen(
                self.page,
                self.db,
                self.sync_service,
                self.auth_service,
                self.current_user,
                self.product,
                on_updated=self.on_updated,
            )
            details_screen.show()

    # ==================== SÉLECTION DATE ====================

    def show_date_picker(self, e):
        """Affiche le sélecteur de date"""
        from datetime import datetime
        if not self.date_picker:
            self.date_picker = ft.DatePicker(
                on_change=self.on_date_selected,
                first_date=datetime(2020, 1, 1),
                last_date=datetime(2030, 12, 31),
            )
            self.page.overlay.append(self.date_picker)

        current_date = None
        if self.expiry_date_field and self.expiry_date_field.value:
            try:
                date_str = self.expiry_date_field.value
                if "T" in date_str:
                    date_str = date_str.split("T")[0]
                current_date = datetime.strptime(date_str, "%Y-%m-%d")
            except:
                pass

        if current_date:
            self.date_picker.value = current_date

        self.date_picker.open = True
        self.page.update()

    def on_date_selected(self, e):
        """Callback quand une date est sélectionnée"""
        if self.date_picker and self.date_picker.value and self.expiry_date_field:
            self.expiry_date_field.value = self.date_picker.value.strftime("%Y-%m-%d")
            self.expiry_date_field.update()

    # ==================== AFFICHAGE ====================

    def show(self) -> None:
        """Affiche l'écran de modification du produit - Style identique à ConfigScreen"""
        # Nettoyer la page et préparer le conteneur (comme ConfigScreen)
        self.page.clean()
        self.page.scroll = ft.ScrollMode.AUTO
        self.page.padding = 0
        # NE PAS définir bgcolor - laisser par défaut comme ConfigScreen

        # Recharger les permissions
        self._load_user_permissions()

        # Vérifier les permissions
        if not (self.can_edit_product or self.is_admin):
            self.page.add(
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Icon(ft.Icons.LOCK, size=64, color=ft.Colors.RED_400),
                            ft.Text(
                                "Vous n'avez pas les permissions nécessaires pour modifier ce produit",
                                size=16,
                                color=ft.Colors.GREY_700,
                                text_align=ft.TextAlign.CENTER,
                            ),
                            ft.Button(
                                "Retour",
                                on_click=lambda e: self.go_back(),
                                bgcolor=ft.Colors.BLUE_700,
                                color=ft.Colors.WHITE,
                            ),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=20,
                    ),
                    expand=True,
                    alignment=ft.Alignment.CENTER,
                )
            )
            return

        # Construire le formulaire
        self.build_form()

        # Header
        product_name = self.initial_data.get("name", "Produit")
        header = self.build_header(product_name)

        # Construire le contenu principal (exactement comme ConfigScreen)
        main_content = ft.Column(
            [
                header,
                ft.Container(
                    content=ft.ListView(
                        [
                            self.build_form_content(),
                            self.build_action_buttons(),
                            ft.Container(height=20),
                        ],
                        spacing=15,
                        expand=True,
                    ),
                    expand=True,
                    padding=ft.Padding.all(15),
                ),
            ],
            spacing=0,
            expand=True,
        )

        # Ajouter au conteneur avec SafeArea (comme ConfigScreen)
        self.container.content = ft.SafeArea(
            content=main_content,
            expand=True,
        )

        self.page.add(self.container)
        self.is_header_initialized = True
        self.page.update()

    def build_header(self, title: str) -> ft.Container:
        """Construit l'en-tête de l'écran"""
        connection_indicator = self.create_connection_indicator()

        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.IconButton(
                        icon=ft.Icons.ARROW_BACK,
                        on_click=lambda e: self.go_back(),
                        icon_color=ft.Colors.WHITE,
                        tooltip="Retour",
                    ),
                    ft.Text("Modifier", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                    ft.Text(title, size=14, color=ft.Colors.WHITE_70, expand=True),
                    connection_indicator,
                ],
                alignment=ft.MainAxisAlignment.START,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=8, vertical=10),
            bgcolor=ft.Colors.BLUE_700,
        )

    def build_form(self):
        """Initialise tous les champs du formulaire"""
        data = self.initial_data
        quantity = self._get_quantity()

        # Informations de base
        self.name_field = ft.TextField(
            label="Nom du produit",
            value=data["name"],
            hint_text="Ex: Paracétamol 500mg",
            expand=True,
            border_radius=8,
            filled=True,
            bgcolor=ft.Colors.WHITE,
        )

        self.code_field = ft.TextField(
            label="Code produit",
            value=data["code"],
            hint_text="Code unique",
            expand=True,
            border_radius=8,
            filled=True,
            bgcolor=ft.Colors.WHITE,
        )

        self.barcode_field = ft.TextField(
            label="Code-barres",
            value=data["barcode"],
            hint_text="Code-barres EAN13",
            expand=True,
            border_radius=8,
            filled=True,
            bgcolor=ft.Colors.WHITE,
        )

        # Catégorie
        self.category_field = ft.TextField(
            label="Catégorie",
            value=data["category"],
            hint_text="Ex: Médicaments, Parapharmacie...",
            expand=True,
            border_radius=8,
            filled=True,
            bgcolor=ft.Colors.WHITE,
        )

        self.subcategory_field = ft.TextField(
            label="Sous-catégorie (optionnel)",
            value=data["subcategory"],
            hint_text="Ex: Antalgiques, Antibiotiques...",
            expand=True,
            border_radius=8,
            filled=True,
            bgcolor=ft.Colors.WHITE,
        )

        self.product_type_dropdown = ft.Dropdown(
            label="Type de produit",
            value=data["product_type"],
            options=[
                ft.dropdown.Option("medicament", "Médicament"),
                ft.dropdown.Option("parapharmacie", "Parapharmacie"),
                ft.dropdown.Option("materiel", "Matériel médical"),
                ft.dropdown.Option("autre", "Autre"),
            ],
            expand=True,
            border_radius=8,
            filled=True,
            bgcolor=ft.Colors.WHITE,
        )

        # Stock et prix
        self.quantity_field = ft.TextField(
            label="Quantité en stock",
            value=str(int(quantity)) if quantity.is_integer() else str(quantity),
            hint_text="Nombre d'unités",
            expand=True,
            border_radius=8,
            filled=True,
            bgcolor=ft.Colors.WHITE,
            keyboard_type=ft.KeyboardType.NUMBER,
        )

        self.unit_field = ft.TextField(
            label="Unité de vente",
            value=data["unit"],
            hint_text="pièce, boîte, sachet...",
            expand=True,
            border_radius=8,
            filled=True,
            bgcolor=ft.Colors.WHITE,
        )

        self.purchase_price_field = ft.TextField(
            label="Prix d'achat (HT)",
            value=str(data["purchase_price"]) if data["purchase_price"] else "0",
            prefix_icon="FC",
            hint_text="0",
            expand=True,
            border_radius=8,
            filled=True,
            bgcolor=ft.Colors.WHITE,
            keyboard_type=ft.KeyboardType.NUMBER,
        )

        self.selling_price_field = ft.TextField(
            label="Prix de vente (TTC)",
            value=str(data["selling_price"]) if data["selling_price"] else "0",
            prefix_icon="FC",
            hint_text="0",
            expand=True,
            border_radius=8,
            filled=True,
            bgcolor=ft.Colors.WHITE,
            keyboard_type=ft.KeyboardType.NUMBER,
        )

        self.wholesale_price_field = ft.TextField(
            label="Prix de gros (optionnel)",
            value=str(data["wholesale_price"]) if data["wholesale_price"] else "",
            prefix_icon="FC",
            hint_text="Prix pour ventes en gros",
            expand=True,
            border_radius=8,
            filled=True,
            bgcolor=ft.Colors.WHITE,
            keyboard_type=ft.KeyboardType.NUMBER,
        )

        self.min_stock_field = ft.TextField(
            label="Seuil d'alerte",
            value=str(int(data["min_stock"])) if data["min_stock"] else "10",
            hint_text="Stock minimum",
            expand=True,
            border_radius=8,
            filled=True,
            bgcolor=ft.Colors.WHITE,
            keyboard_type=ft.KeyboardType.NUMBER,
        )

        self.max_stock_field = ft.TextField(
            label="Stock maximum (optionnel)",
            value=str(int(data["max_stock"])) if data["max_stock"] else "",
            hint_text="Capacité maximale",
            expand=True,
            border_radius=8,
            filled=True,
            bgcolor=ft.Colors.WHITE,
            keyboard_type=ft.KeyboardType.NUMBER,
        )

        # Date d'expiration
        expiry_display = ""
        if data["expiry_date"]:
            expiry_display = data["expiry_date"]
            if "T" in expiry_display:
                expiry_display = expiry_display.split("T")[0]

        self.expiry_date_field = ft.TextField(
            label="Date d'expiration",
            value=expiry_display,
            hint_text="YYYY-MM-DD",
            expand=True,
            border_radius=8,
            filled=True,
            bgcolor=ft.Colors.WHITE,
            read_only=True,
            suffix=ft.IconButton(icon=ft.Icons.CALENDAR_TODAY, on_click=self.show_date_picker),
        )

        # Fournisseur
        self.supplier_field = ft.TextField(
            label="Fournisseur",
            value=data["supplier"],
            hint_text="Nom du fournisseur principal",
            expand=True,
            border_radius=8,
            filled=True,
            bgcolor=ft.Colors.WHITE,
        )

        self.laboratory_field = ft.TextField(
            label="Laboratoire",
            value=data["laboratory"],
            hint_text="Laboratoire fabricant",
            expand=True,
            border_radius=8,
            filled=True,
            bgcolor=ft.Colors.WHITE,
        )

        self.manufacturer_field = ft.TextField(
            label="Fabricant",
            value=data["manufacturer"],
            hint_text="Nom du fabricant",
            expand=True,
            border_radius=8,
            filled=True,
            bgcolor=ft.Colors.WHITE,
        )

        # Localisation et lot
        self.location_field = ft.TextField(
            label="Emplacement",
            value=data["location"],
            hint_text="Rayon, étagère...",
            expand=True,
            border_radius=8,
            filled=True,
            bgcolor=ft.Colors.WHITE,
        )

        self.lot_number_field = ft.TextField(
            label="Numéro de lot",
            value=data["lot_number"],
            hint_text="Lot de fabrication",
            expand=True,
            border_radius=8,
            filled=True,
            bgcolor=ft.Colors.WHITE,
        )

        # TVA
        self.has_tva_switch = ft.Switch(
            value=data["has_tva"], 
            label="Produit assujetti à la TVA"
        )
        self.tax_rate_field = ft.TextField(
            label="Taux de TVA (%)",
            value=str(data["tax_rate"]) if data["tax_rate"] else "0",
            hint_text="Ex: 16, 18",
            expand=True,
            border_radius=8,
            filled=True,
            bgcolor=ft.Colors.WHITE,
            keyboard_type=ft.KeyboardType.NUMBER,
            disabled=not data["has_tva"],
        )

        def on_tva_change(e):
            self.tax_rate_field.disabled = not self.has_tva_switch.value
            self.page.update()

        self.has_tva_switch.on_change = on_tva_change

        # Description et notes
        self.description_field = ft.TextField(
            label="Description",
            value=data["description"],
            hint_text="Description détaillée du produit",
            multiline=True,
            min_lines=2,
            max_lines=5,
            expand=True,
            border_radius=8,
            filled=True,
            bgcolor=ft.Colors.WHITE,
        )

        self.notes_field = ft.TextField(
            label="Notes (optionnel)",
            value=data["notes"],
            hint_text="Informations complémentaires",
            multiline=True,
            min_lines=2,
            max_lines=3,
            expand=True,
            border_radius=8,
            filled=True,
            bgcolor=ft.Colors.WHITE,
        )

    def build_form_content(self) -> ft.Column:
        """Construit le contenu du formulaire - tous les conteneurs avec fond blanc"""
        return ft.Column(
            controls=[
                # Section 1: Informations de base
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Text(
                                "Informations générales",
                                size=16,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.BLUE_700,
                            ),
                            ft.Divider(height=1, color=ft.Colors.GREY_300),
                            ft.Row(controls=[self.name_field], wrap=True),
                            ft.Row(
                                controls=[self.code_field, self.barcode_field],
                                wrap=True,
                                spacing=10,
                            ),
                            ft.Row(
                                controls=[self.category_field, self.subcategory_field],
                                wrap=True,
                                spacing=10,
                            ),
                            ft.Row(controls=[self.product_type_dropdown], wrap=True),
                        ],
                        spacing=12,
                    ),
                    padding=12,
                    bgcolor=ft.Colors.WHITE,
                    border_radius=12,
                ),

                # Section 2: Stock et prix
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Text(
                                "Stock & Prix",
                                size=16,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.GREEN_700,
                            ),
                            ft.Divider(height=1, color=ft.Colors.GREY_300),
                            ft.Row(
                                controls=[self.quantity_field, self.unit_field],
                                wrap=True,
                                spacing=10,
                            ),
                            ft.Row(
                                controls=[
                                    ft.Container(content=self.purchase_price_field, expand=2),
                                    ft.Container(content=self.selling_price_field, expand=3),
                                ],
                                spacing=10,
                            ),
                            ft.Row(controls=[self.wholesale_price_field], wrap=True),
                            ft.Row(
                                controls=[self.min_stock_field, self.max_stock_field],
                                wrap=True,
                                spacing=10,
                            ),
                        ],
                        spacing=12,
                    ),
                    padding=12,
                    bgcolor=ft.Colors.WHITE,
                    border_radius=12,
                ),

                # Section 3: Dates
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Text(
                                "Date d'expiration",
                                size=16,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.ORANGE_700,
                            ),
                            ft.Divider(height=1, color=ft.Colors.GREY_300),
                            ft.Row(controls=[self.expiry_date_field], wrap=True),
                        ],
                        spacing=12,
                    ),
                    padding=12,
                    bgcolor=ft.Colors.WHITE,
                    border_radius=12,
                ),

                # Section 4: Fournisseur
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Text(
                                "Fournisseur & Fabrication",
                                size=16,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.INDIGO_700,
                            ),
                            ft.Divider(height=1, color=ft.Colors.GREY_300),
                            ft.Row(controls=[self.supplier_field], wrap=True),
                            ft.Row(
                                controls=[self.laboratory_field, self.manufacturer_field],
                                wrap=True,
                                spacing=10,
                            ),
                        ],
                        spacing=12,
                    ),
                    padding=12,
                    bgcolor=ft.Colors.WHITE,
                    border_radius=12,
                ),

                # Section 5: Localisation
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Text(
                                "Localisation & Lot",
                                size=16,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.PURPLE_700,
                            ),
                            ft.Divider(height=1, color=ft.Colors.GREY_300),
                            ft.Row(
                                controls=[self.location_field, self.lot_number_field],
                                wrap=True,
                                spacing=10,
                            ),
                        ],
                        spacing=12,
                    ),
                    padding=12,
                    bgcolor=ft.Colors.WHITE,
                    border_radius=12,
                ),

                # Section 6: TVA
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Text(
                                "Taxes",
                                size=16,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.RED_700,
                            ),
                            ft.Divider(height=1, color=ft.Colors.GREY_300),
                            ft.Row(controls=[self.has_tva_switch], wrap=True),
                            ft.Row(controls=[self.tax_rate_field], wrap=True),
                        ],
                        spacing=12,
                    ),
                    padding=12,
                    bgcolor=ft.Colors.WHITE,
                    border_radius=12,
                ),

                # Section 7: Description
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Text(
                                "Description",
                                size=16,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.BLUE_GREY_700,
                            ),
                            ft.Divider(height=1, color=ft.Colors.GREY_300),
                            ft.Row(controls=[self.description_field], wrap=True),
                            ft.Row(controls=[self.notes_field], wrap=True),
                        ],
                        spacing=12,
                    ),
                    padding=12,
                    bgcolor=ft.Colors.WHITE,
                    border_radius=12,
                ),
            ],
            spacing=15,
        )

    def build_action_buttons(self) -> ft.Container:
        """Construit les boutons d'action (Annuler / Enregistrer)"""
        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Button(
                        "Annuler",
                        on_click=lambda e: self.go_back(),
                        style=ft.ButtonStyle(
                            bgcolor=ft.Colors.GREY_300,
                            color=ft.Colors.GREY_800,
                            padding=12,
                            shape=ft.RoundedRectangleBorder(radius=8),
                        ),
                        expand=True,
                    ),
                    ft.Button(
                        "Enregistrer",
                        on_click=self.save_product,
                        style=ft.ButtonStyle(
                            bgcolor=ft.Colors.GREEN_700,
                            color=ft.Colors.WHITE,
                            padding=12,
                            shape=ft.RoundedRectangleBorder(radius=8),
                        ),
                        expand=True,
                    ),
                ],
                spacing=12,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=12, vertical=16),
            bgcolor=ft.Colors.WHITE,
        )