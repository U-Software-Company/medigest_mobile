# screens/stock_adjust_screen.py
"""
Écran d'ajustement de stock
Permet d'ajouter ou de retirer du stock pour un produit
"""

import flet as ft
from datetime import datetime
from typing import Dict, Optional, Callable
import threading
import logging

logger = logging.getLogger(__name__)


class StockAdjustScreen:
    """
    Écran d'ajustement de stock pour un produit.
    - Ajouter du stock (entrée)
    - Retirer du stock (sortie)
    - Correction de stock (fixer une quantité)
    - Sauvegarde locale et synchronisation serveur
    """
    
    def __init__(self, page: ft.Page, db, sync_service, auth_service, current_user,
                 product, notification_manager=None, on_updated: Optional[Callable] = None):
        """
        Args:
            page: Page Flet
            db: DatabaseManager
            sync_service: SyncService
            auth_service: AuthService
            current_user: Utilisateur courant
            product: Produit à ajuster (objet ou dictionnaire)
            notification_manager: Gestionnaire de notifications
            on_updated: Callback appelé après ajustement réussi
        """
        self.page = page
        self.db = db
        self.sync_service = sync_service
        self.auth_service = auth_service
        self.current_user = current_user
        self.product = product
        self.notification_manager = notification_manager
        self.on_updated = on_updated
        
        # États
        self.is_submitting = False
        self._is_online = self._check_online_status()
        self.adjustment_type = "add"  # "add", "remove", "set"
        
        # Stocker l'ID du produit
        self.product_id = self._get_product_attr(product, 'server_id') or self._get_product_attr(product, 'id')
        self.product_name = self._get_product_attr(product, 'name', 'Produit')
        self.current_stock = self._get_product_attr(product, 'quantity') or self._get_product_attr(product, 'stock', 0)
        
        # Champs du formulaire
        self.adjustment_type_segmented = None
        self.quantity_field = None
        self.reason_field = None
        self.current_stock_text = None
        self.new_stock_text = None
        
        # Indicateur de connexion
        self.connection_indicator = None
        self.progress_text = None
        self.submit_button = None
        
        # Flag pour éviter les doubles soumissions
        self._syncing = False
    
    # ==================== UTILITAIRES ====================
    
    def _check_online_status(self) -> bool:
        """Vérifie si on est en ligne"""
        try:
            if self.sync_service:
                return self.sync_service.check_internet_connection()
        except Exception as e:
            logger.error(f"Erreur vérification connexion: {e}")
        return False
    
    def _get_product_attr(self, product, attr_name: str, default=None):
        """Récupère un attribut d'un produit (dictionnaire ou objet)"""
        if product is None:
            return default
        if isinstance(product, dict):
            return product.get(attr_name, default)
        else:
            return getattr(product, attr_name, default)
    
    def _get_branch_id(self) -> Optional[str]:
        """Récupère l'ID de la branche de l'utilisateur"""
        if self.current_user:
            return (self.current_user.get('active_branch_id') or 
                   self.current_user.get('branch_id'))
        return None
    
    def _safe_int(self, value, default=0) -> int:
        """Convertit en int de manière sécurisée"""
        if value is None:
            return default
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return default
    
    def show_snackbar(self, message: str, color: str = ft.Colors.BLUE, duration: int = 3000):
        """Affiche un snackbar"""
        snack = ft.SnackBar(
            content=ft.Text(message, size=14),
            bgcolor=color,
            duration=duration,
            show_close_icon=True,
        )
        self.page.snack_bar = snack
        snack.open = True
        self.page.update()
    
    # ==================== INDICATEUR DE CONNEXION ====================
    
    def create_connection_indicator(self) -> ft.Container:
        """Crée l'indicateur de connexion"""
        status = self._get_connection_status()
        
        self.connection_indicator = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(status["icon"], color=status["color"], size=16),
                    ft.Text(status["text"], size=11, color=status["color"], weight=ft.FontWeight.BOLD),
                ],
                spacing=4,
            ),
            bgcolor=ft.Colors.WHITE,
            padding=ft.Padding.symmetric(horizontal=8, vertical=4),
            border_radius=15,
            tooltip=status["tooltip"],
        )
        return self.connection_indicator
    
    def _get_connection_status(self) -> Dict:
        """Retourne le statut de connexion à afficher"""
        if self._is_online:
            return {
                "color": ft.Colors.GREEN,
                "text": "Online",
                "icon": ft.Icons.WIFI,
                "tooltip": "Mode connecté - Synchronisation automatique"
            }
        else:
            return {
                "color": ft.Colors.RED,
                "text": "Offline",
                "icon": ft.Icons.WIFI_OFF,
                "tooltip": "Mode hors-ligne - Sauvegarde locale uniquement"
            }
    
    def update_connection_indicator(self):
        """Met à jour l'indicateur de connexion"""
        if self.connection_indicator:
            status = self._get_connection_status()
            self.connection_indicator.content = ft.Row(
                [
                    ft.Icon(status["icon"], color=status["color"], size=16),
                    ft.Text(status["text"], size=11, color=status["color"], weight=ft.FontWeight.BOLD),
                ],
                spacing=4,
            )
            self.connection_indicator.tooltip = status["tooltip"]
            self.page.update()
    
    # ==================== AJUSTEMENT STOCK LOCAL ====================
    
    def _get_headers(self) -> Optional[Dict]:
        """Récupère les headers d'authentification"""
        if self.auth_service:
            user = self.auth_service.get_current_user()
            if user and user.get('token'):
                return {
                    "Authorization": f"Bearer {user.get('token')}",
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                }
        return None
    
    def update_local_stock(self, adjustment_type: str, quantity: int, reason: str) -> bool:
        """
        Met à jour le stock localement.
        
        Args:
            adjustment_type: "add", "remove", ou "set"
            quantity: Quantité à ajouter/retirer ou nouvelle quantité
            reason: Raison de l'ajustement
        
        Returns:
            True si mise à jour réussie
        """
        try:
            from database.models import Product
            
            # Récupérer le produit existant
            existing_product = None
            if hasattr(self.product, 'server_id'):
                existing_product = self.product
            else:
                existing_product = self.db.get_product_by_id(self.product_id)
            
            if not existing_product:
                logger.error(f"Produit non trouvé: {self.product_id}")
                return False
            
            # Calculer la nouvelle quantité
            old_quantity = existing_product.quantity if hasattr(existing_product, 'quantity') else existing_product.stock
            
            if adjustment_type == "add":
                new_quantity = old_quantity + quantity
            elif adjustment_type == "remove":
                if quantity > old_quantity:
                    self.show_snackbar(f"❌ Impossible de retirer {quantity} unités, stock actuel: {old_quantity}", ft.Colors.RED)
                    return False
                new_quantity = old_quantity - quantity
            else:  # set
                new_quantity = quantity
            
            # Mettre à jour l'objet produit
            existing_product.quantity = new_quantity
            if hasattr(existing_product, 'stock'):
                existing_product.stock = new_quantity
            
            # Incrémenter la version du stock
            if hasattr(existing_product, 'stock_version'):
                existing_product.stock_version = getattr(existing_product, 'stock_version', 1) + 1
            
            existing_product.updated_at = datetime.now().isoformat()
            
            # Sauvegarder
            saved = self.db.save_products([existing_product])
            
            if saved > 0:
                # Enregistrer l'historique d'ajustement
                self._save_adjustment_history(adjustment_type, quantity, new_quantity, old_quantity, reason)
                
                logger.info(f"Stock ajusté: {self.product_name} - {adjustment_type} {quantity} -> nouveau stock: {new_quantity}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Erreur mise à jour stock local: {e}")
            return False
    
    def _save_adjustment_history(self, adjustment_type: str, quantity: int, new_quantity: int, old_quantity: int, reason: str):
        """Sauvegarde l'historique d'ajustement de stock"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Créer la table si elle n'existe pas
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS stock_adjustments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        product_id TEXT NOT NULL,
                        product_name TEXT NOT NULL,
                        adjustment_type TEXT NOT NULL,
                        old_quantity INTEGER NOT NULL,
                        quantity INTEGER NOT NULL,
                        new_quantity INTEGER NOT NULL,
                        reason TEXT,
                        branch_id TEXT,
                        user_id TEXT,
                        user_name TEXT,
                        adjusted_at TEXT NOT NULL,
                        is_synced INTEGER DEFAULT 0
                    )
                """)
                
                # Insérer l'historique
                cursor.execute("""
                    INSERT INTO stock_adjustments 
                    (product_id, product_name, adjustment_type, old_quantity, quantity, 
                     new_quantity, reason, branch_id, user_id, user_name, adjusted_at, is_synced)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    self.product_id,
                    self.product_name,
                    adjustment_type,
                    old_quantity,
                    quantity,
                    new_quantity,
                    reason,
                    self._get_branch_id(),
                    self.current_user.get('id') if self.current_user else None,
                    self.current_user.get('full_name', self.current_user.get('username', 'Utilisateur')) if self.current_user else None,
                    datetime.now().isoformat(),
                    0
                ))
                
                conn.commit()
                logger.info(f"Historique d'ajustement enregistré pour {self.product_name}")
                
        except Exception as e:
            logger.error(f"Erreur sauvegarde historique ajustement: {e}")
    
    # ==================== SYNCHRONISATION AVEC SERVEUR ====================
    
    def sync_stock_to_server(self, adjustment_type: str, quantity: int, new_quantity: int, reason: str) -> Dict:
        """
        Synchronise l'ajustement de stock avec le serveur.
        
        Returns:
            Dict avec 'success' (bool) et 'error' (str)
        """
        try:
            headers = self._get_headers()
            if not headers:
                return {"success": False, "error": "Non authentifié"}
            
            # Préparer les données pour le serveur
            payload = {
                "quantity": new_quantity,
                "stock_adjustment": {
                    "type": adjustment_type,
                    "quantity": quantity,
                    "reason": reason,
                    "old_quantity": self.current_stock,
                    "new_quantity": new_quantity,
                    "adjusted_at": datetime.now().isoformat()
                }
            }
            
            response = self.sync_service.session.put(
                f"{self.sync_service.api_url}/stock/{self.product_id}",
                headers=headers,
                json=payload,
                timeout=60
            )
            
            if response.status_code in [200, 201]:
                return {"success": True}
            else:
                error_msg = f"Erreur serveur: {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg = error_data.get('detail', error_msg)
                except:
                    pass
                return {"success": False, "error": error_msg}
                
        except Exception as e:
            logger.error(f"Erreur synchronisation stock serveur: {e}")
            return {"success": False, "error": str(e)}
    
    # ==================== AJUSTEMENT PRINCIPAL ====================
    
    def on_adjustment_type_change(self, e):
        """Change le type d'ajustement"""
        self.adjustment_type = e.control.value
        self.update_ui_for_adjustment_type()
    
    def update_ui_for_adjustment_type(self):
        """Met à jour l'interface selon le type d'ajustement"""
        if self.adjustment_type == "add":
            if self.quantity_field:
                self.quantity_field.label = "Quantité à ajouter"
                self.quantity_field.hint_text = "Nombre d'unités à ajouter au stock"
                self.quantity_field.prefix_icon = ft.Icons.ADD_CIRCLE
        elif self.adjustment_type == "remove":
            if self.quantity_field:
                self.quantity_field.label = "Quantité à retirer"
                self.quantity_field.hint_text = "Nombre d'unités à retirer du stock"
                self.quantity_field.prefix_icon = ft.Icons.REMOVE_CIRCLE
        else:  # set
            if self.quantity_field:
                self.quantity_field.label = "Nouvelle quantité"
                self.quantity_field.hint_text = "Quantité totale après ajustement"
                self.quantity_field.prefix_icon = ft.Icons.EDIT
        
        # Mettre à jour l'aperçu
        self.update_stock_preview()
        self.page.update()
    
    def update_stock_preview(self, e=None):
        """Met à jour l'aperçu du nouveau stock"""
        if not self.quantity_field or not self.new_stock_text:
            return
        
        quantity = self._safe_int(self.quantity_field.value, 0)
        current = self.current_stock
        
        if self.adjustment_type == "add":
            new_stock = current + quantity
        elif self.adjustment_type == "remove":
            new_stock = max(0, current - quantity)
        else:  # set
            new_stock = quantity
        
        self.new_stock_text.value = f"{new_stock:,} unités"
        self.new_stock_text.color = ft.Colors.GREEN_700 if new_stock >= 0 else ft.Colors.RED
        self.page.update()
    
    def submit_adjustment(self, e):
        """Soumet l'ajustement de stock"""
        if self.is_submitting:
            self.show_snackbar("Traitement en cours...", ft.Colors.ORANGE)
            return
        
        # Récupérer les valeurs
        quantity = self._safe_int(self.quantity_field.value if self.quantity_field else 0)
        reason = self.reason_field.value.strip() if self.reason_field else ""
        
        # Validation
        if quantity <= 0 and self.adjustment_type != "set":
            self.show_snackbar("❌ La quantité doit être supérieure à 0", ft.Colors.RED)
            return
        
        if self.adjustment_type == "set" and quantity < 0:
            self.show_snackbar("❌ La quantité ne peut pas être négative", ft.Colors.RED)
            return
        
        if not reason:
            self.show_snackbar("❌ Veuillez indiquer une raison pour l'ajustement", ft.Colors.RED)
            return
        
        self.is_submitting = True
        self._update_submit_button_state(True)
        
        def save_task():
            try:
                # Calculer la nouvelle quantité
                if self.adjustment_type == "add":
                    new_quantity = self.current_stock + quantity
                elif self.adjustment_type == "remove":
                    if quantity > self.current_stock:
                        self.page.run_thread(lambda: self.show_snackbar(
                            f"❌ Stock insuffisant: {self.current_stock} unités disponibles", 
                            ft.Colors.RED
                        ))
                        self.page.run_thread(lambda: self._reset_submit_state())
                        return
                    new_quantity = self.current_stock - quantity
                else:  # set
                    new_quantity = quantity
                
                sync_success = False
                
                # Si en ligne, d'abord synchroniser avec le serveur
                if self._is_online:
                    self._update_progress_text("Synchronisation avec le serveur...")
                    result = self.sync_stock_to_server(self.adjustment_type, quantity, new_quantity, reason)
                    
                    if result.get("success"):
                        sync_success = True
                        self._update_progress_text("✅ Stock synchronisé avec le serveur")
                    else:
                        error = result.get("error", "Erreur inconnue")
                        logger.warning(f"Échec synchronisation serveur: {error}")
                        self._update_progress_text(f"⚠️ Sauvegarde locale seulement: {error[:50]}")
                
                # Mettre à jour localement
                self._update_progress_text("Mise à jour locale...")
                if self.update_local_stock(self.adjustment_type, quantity, reason):
                    self._update_progress_text("✅ Stock mis à jour localement")
                    
                    # Afficher le message de succès
                    if self.adjustment_type == "add":
                        action_text = f"ajouté {quantity} unité(s)"
                    elif self.adjustment_type == "remove":
                        action_text = f"retiré {quantity} unité(s)"
                    else:
                        action_text = f"fixé à {quantity} unité(s)"
                    
                    sync_msg = " (synchronisé)" if sync_success else " (mode hors-ligne)"
                    self.show_snackbar(
                        f"✅ Stock de '{self.product_name}' {action_text}{sync_msg}",
                        ft.Colors.GREEN
                    )
                    
                    # Callback
                    if self.on_updated:
                        self.page.run_thread(self.on_updated)
                    
                    # Retour à l'écran précédent après un court délai
                    import time
                    time.sleep(1.5)
                    self.page.run_thread(self.go_back)
                else:
                    self.show_snackbar("❌ Erreur lors de la mise à jour locale", ft.Colors.RED)
                
            except Exception as e:
                logger.error(f"Erreur lors de l'ajustement: {e}")
                self.show_snackbar(f"❌ Erreur: {str(e)}", ft.Colors.RED)
            finally:
                self._reset_submit_state()
        
        # Démarrer le thread
        threading.Thread(target=save_task, daemon=True).start()
    
    def _reset_submit_state(self):
        """Réinitialise l'état de soumission"""
        self.is_submitting = False
        self.page.run_thread(lambda: self._update_submit_button_state(False))
        self.page.run_thread(lambda: self._update_progress_text(""))
    
    def _update_submit_button_state(self, is_loading: bool):
        """Met à jour l'état du bouton de soumission"""
        if self.submit_button:
            if is_loading:
                self.submit_button.content = ft.Row(
                    [
                        ft.ProgressRing(width=20, height=20, stroke_width=2),
                        ft.Text("Traitement...", size=14),
                    ],
                    spacing=8,
                    alignment=ft.MainAxisAlignment.CENTER,
                )
                self.submit_button.disabled = True
            else:
                self.submit_button.content = ft.Row(
                    [
                        ft.Icon(ft.Icons.SAVE, size=18),
                        ft.Text("Valider l'ajustement", size=14, weight=ft.FontWeight.BOLD),
                    ],
                    spacing=8,
                    alignment=ft.MainAxisAlignment.CENTER,
                )
                self.submit_button.disabled = False
            self.page.update()
    
    def _update_progress_text(self, text: str):
        """Met à jour le texte de progression"""
        if self.progress_text:
            self.progress_text.value = text
            self.progress_text.visible = bool(text)
            self.page.update()
    
    # ==================== CONSTRUCTION DE L'INTERFACE ====================
    
    def build_header(self) -> ft.Container:
        """Construit l'en-tête de l'écran"""
        connection_indicator = self.create_connection_indicator()
        
        return ft.Container(
            content=ft.Row(
                [
                    ft.IconButton(
                        icon=ft.Icons.ARROW_BACK,
                        on_click=lambda e: self.go_back(),
                        icon_color=ft.Colors.WHITE,
                        tooltip="Retour",
                    ),
                    ft.Text(
                        "Ajustement de stock",
                        size=22,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.WHITE,
                        expand=True,
                    ),
                    connection_indicator,
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=15, vertical=12),
            bgcolor=ft.Colors.BLUE_700,
        )
    
    def build_form(self) -> ft.Column:
        """Construit le formulaire d'ajustement de stock"""
        
        # Informations produit
        product_info = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.MEDICATION, size=30, color=ft.Colors.BLUE_700),
                    ft.Column(
                        [
                            ft.Text(self.product_name, size=18, weight=ft.FontWeight.BOLD),
                            ft.Text(f"ID: {self.product_id}", size=11, color=ft.Colors.GREY_500),
                        ],
                        spacing=2,
                    ),
                ],
                spacing=12,
            ),
            padding=15,
            bgcolor=ft.Colors.BLUE_50,
            border_radius=12,
        )
        
        # Stock actuel
        self.current_stock_text = ft.Text(
            f"{self.current_stock:,} unités",
            size=24,
            weight=ft.FontWeight.BOLD,
            color=ft.Colors.BLUE_700,
        )
        
        current_stock_container = ft.Container(
            content=ft.Column(
                [
                    ft.Text("Stock actuel", size=12, color=ft.Colors.GREY_600),
                    self.current_stock_text,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=4,
            ),
            padding=15,
            bgcolor=ft.Colors.WHITE,
            border=ft.border.all(1, ft.Colors.GREY_200),
            border_radius=12,
            expand=True,
        )
        
        # Type d'ajustement (segmented button)
        self.adjustment_type_segmented = ft.SegmentedButton(
            selected={self.adjustment_type},
            on_change=self.on_adjustment_type_change,
            segments=[
                ft.Segment(
                    value="add",
                    label=ft.Text("Ajouter", size=12),
                    icon=ft.Icon(ft.Icons.ADD_CIRCLE_OUTLINE, size=16),
                ),
                ft.Segment(
                    value="remove",
                    label=ft.Text("Retirer", size=12),
                    icon=ft.Icon(ft.Icons.REMOVE_CIRCLE_OUTLINE, size=16),
                ),
                ft.Segment(
                    value="set",
                    label=ft.Text("Fixer", size=12),
                    icon=ft.Icon(ft.Icons.EDIT, size=16),
                ),
            ],
            style=ft.ButtonStyle(
                color={
                    ft.ControlState.SELECTED: ft.Colors.WHITE,
                    ft.ControlState.DEFAULT: ft.Colors.BLUE_700,
                },
                bgcolor={
                    ft.ControlState.SELECTED: ft.Colors.BLUE_700,
                    ft.ControlState.DEFAULT: ft.Colors.WHITE,
                },
                side={
                    ft.ControlState.SELECTED: ft.BorderSide(0, ft.Colors.BLUE_700),
                    ft.ControlState.DEFAULT: ft.BorderSide(1, ft.Colors.BLUE_200),
                },
            ),
        )        
        # Quantité
        self.quantity_field = ft.TextField(
            label="Quantité à ajouter",
            hint_text="Nombre d'unités",
            keyboard_type=ft.KeyboardType.NUMBER,
            prefix_icon=ft.Icons.ADD_CIRCLE,
            expand=True,
            border_radius=10,
            on_change=self.update_stock_preview,
        )
        
        # Nouveau stock (aperçu)
        self.new_stock_text = ft.Text(f"{self.current_stock:,} unités", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_700)
        
        new_stock_container = ft.Container(
            content=ft.Column(
                [
                    ft.Text("Nouveau stock", size=12, color=ft.Colors.GREY_600),
                    self.new_stock_text,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=4,
            ),
            padding=15,
            bgcolor=ft.Colors.GREEN_50,
            border=ft.border.all(1, ft.Colors.GREEN_200),
            border_radius=12,
            expand=True,
        )
        
        # Raison
        self.reason_field = ft.TextField(
            label="Raison de l'ajustement",
            hint_text="Ex: Réapprovisionnement, Inventaire, Casse, Péremption...",
            prefix_icon=ft.Icons.INFO,
            multiline=True,
            min_lines=2,
            max_lines=3,
            expand=True,
            border_radius=10,
        )
        
        # Exemples de raisons rapides
        def set_quick_reason(reason: str):
            self.reason_field.value = reason
            self.page.update()
        
        quick_reasons = ft.Row(
            [
                ft.TextButton(
                    "📦 Réapprovisionnement",
                    on_click=lambda e: set_quick_reason("Réapprovisionnement de stock"),
                    style=ft.ButtonStyle(
                        padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                        shape=ft.RoundedRectangleBorder(radius=15),
                    ),
                ),
                ft.TextButton(
                    "📋 Inventaire",
                    on_click=lambda e: set_quick_reason("Ajustement suite à inventaire physique"),
                    style=ft.ButtonStyle(
                        padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                        shape=ft.RoundedRectangleBorder(radius=15),
                    ),
                ),
                ft.TextButton(
                    "⚡ Casse/Péremption",
                    on_click=lambda e: set_quick_reason("Retrait pour casse ou péremption"),
                    style=ft.ButtonStyle(
                        padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                        shape=ft.RoundedRectangleBorder(radius=15),
                    ),
                ),
            ],
            spacing=8,
            wrap=True,
        )
        
        # Stock et nouveau stock côte à côte
        stock_row = ft.Row(
            [current_stock_container, new_stock_container],
            spacing=15,
            expand=True,
        )
        
        # Bouton de soumission
        self.progress_text = ft.Text("", size=12, color=ft.Colors.BLUE_700, visible=False)
        
        self.submit_button = ft.ElevatedButton(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.SAVE, size=18),
                    ft.Text("Valider l'ajustement", size=14, weight=ft.FontWeight.BOLD),
                ],
                spacing=8,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            on_click=self.submit_adjustment,
            style=ft.ButtonStyle(
                bgcolor=ft.Colors.GREEN_700,
                color=ft.Colors.WHITE,
                padding=ft.Padding.symmetric(horizontal=30, vertical=15),
                shape=ft.RoundedRectangleBorder(radius=10),
            ),
            width=300,
        )
        
        # Assemblage
        return ft.Column(
            [
                product_info,
                ft.Divider(height=1),
                ft.Container(height=10),
                ft.Text("Type d'ajustement", size=14, weight=ft.FontWeight.BOLD),
                ft.Container(height=5),
                self.adjustment_type_segmented,
                ft.Container(height=15),
                ft.Text("Quantité", size=14, weight=ft.FontWeight.BOLD),
                self.quantity_field,
                ft.Container(height=10),
                stock_row,
                ft.Container(height=15),
                ft.Text("Raison", size=14, weight=ft.FontWeight.BOLD),
                quick_reasons,
                ft.Container(height=5),
                self.reason_field,
                ft.Container(height=20),
                ft.Container(
                    content=ft.Column(
                        [
                            self.progress_text,
                            ft.Row(
                                [self.submit_button],
                                alignment=ft.MainAxisAlignment.CENTER,
                            ),
                        ],
                        spacing=10,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=ft.Padding.symmetric(vertical=10),
                ),
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
        )
    
    def show(self):
        """Affiche l'écran d'ajustement de stock"""
        self.page.clean()
        self.page.scroll = ft.ScrollMode.AUTO
        self.page.padding = 0
        self.page.bgcolor = ft.Colors.GREY_100
        
        # Mettre à jour le statut de connexion
        self._is_online = self._check_online_status()
        
        # Construire l'interface
        main_content = ft.Column(
            [
                self.build_header(),
                ft.Container(
                    content=self.build_form(),
                    expand=True,
                    padding=15,
                ),
            ],
            expand=True,
            spacing=0,
        )
        
        self.page.add(main_content)
        self.page.update()
        
        # Focus sur le champ quantité
        if self.quantity_field:
            self.quantity_field.focus()
    
    def go_back(self):
        """Retourne à l'écran précédent"""
        from screens.products_screen import ProductsScreen
        
        products_screen = ProductsScreen(
            self.page, self.db, self.sync_service,
            self.auth_service, self.current_user
        )
        products_screen.show()