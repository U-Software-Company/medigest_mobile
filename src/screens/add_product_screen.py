# screens/add_product_screen.py
"""
Écran d'ajout de produits - Version complète
Gère la création de produits avec vérification des doublons,
enregistrement local et synchronisation automatique avec le serveur.
"""

import flet as ft
from datetime import datetime, date
from typing import Dict, Optional, List, Callable
import threading
import logging
import re

logger = logging.getLogger(__name__)


class AddProductScreen:
    """
    Écran d'ajout/création de produits.
    - Vérification des doublons (nom, code, code-barres)
    - Enregistrement local si pas d'internet
    - Synchronisation automatique quand internet revient
    - Modification de quantité/prix si produit existe déjà
    """
    
    def __init__(self, page: ft.Page, db, sync_service, auth_service, current_user,
                 on_product_added: Optional[Callable] = None):
        """
        Args:
            page: Page Flet
            db: DatabaseManager
            sync_service: SyncService
            auth_service: AuthService
            current_user: Utilisateur courant
            on_product_added: Callback appelé après ajout réussi
        """
        self.page = page
        self.db = db
        self.sync_service = sync_service
        self.auth_service = auth_service
        self.current_user = current_user
        self.on_product_added = on_product_added
        
        # États
        self.is_submitting = False
        self._is_online = self._check_online_status()
        
        # Champs du formulaire
        self.name_field = None
        self.code_field = None
        self.barcode_field = None
        self.category_field = None
        self.quantity_field = None
        self.purchase_price_field = None
        self.selling_price_field = None
        self.expiry_date_field = None
        self.location_field = None
        self.supplier_field = None
        self.batch_number_field = None
        self.description_field = None
        self.unit_field = None
        self.min_stock_field = None
        self.max_stock_field = None
        
        # Indicateur de connexion
        self.connection_indicator = None
        
        # Dialogues
        self.duplicate_dialog = None
        
        # Cache des produits existants pour vérification rapide
        self.existing_products_cache = []
        self._refresh_product_cache()
        
        # Flag pour éviter les appels multiples
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
    
    def _refresh_product_cache(self):
        """Rafraîchit le cache des produits existants"""
        try:
            branch_id = self._get_branch_id()
            self.existing_products_cache = self.db.get_products(branch_id) or []
            logger.info(f"Cache produits rafraîchi: {len(self.existing_products_cache)} produits")
        except Exception as e:
            logger.error(f"Erreur rafraîchissement cache: {e}")
            self.existing_products_cache = []
    
    def _get_branch_id(self) -> Optional[str]:
        """Récupère l'ID de la branche de l'utilisateur"""
        if self.current_user:
            return (self.current_user.get('active_branch_id') or 
                   self.current_user.get('branch_id'))
        return None
    
    def _get_pharmacy_id(self) -> Optional[str]:
        """Récupère l'ID de la pharmacie"""
        if self.current_user:
            return self.current_user.get('pharmacy_id')
        return None
    
    def _get_tenant_id(self) -> Optional[str]:
        """Récupère le tenant_id"""
        if self.current_user:
            return self.current_user.get('tenant_id')
        return None
    
    def _safe_str(self, value, default='') -> str:
        """Convertit en string de manière sécurisée"""
        if value is None:
            return default
        return str(value).strip()
    
    def _safe_int(self, value, default=0) -> int:
        """Convertit en int de manière sécurisée"""
        if value is None:
            return default
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return default
    
    def _safe_float(self, value, default=0.0) -> float:
        """Convertit en float de manière sécurisée"""
        if value is None:
            return default
        try:
            return float(value)
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
    
    # ==================== VÉRIFICATION DES DOUBLONS ====================
    
    def check_duplicate_product(self, name: str, code: str = None, barcode: str = None) -> Dict:
        """
        Vérifie si un produit existe déjà.
        
        Returns:
            Dict avec 'exists' (bool) et 'product' (le produit existant si trouvé)
        """
        name_lower = name.lower().strip()
        code_lower = code.lower().strip() if code else None
        barcode_lower = barcode.lower().strip() if barcode else None
        
        for product in self.existing_products_cache:
            # Vérifier par nom
            product_name = self._get_product_attr(product, 'name', '').lower().strip()
            if product_name == name_lower:
                return {"exists": True, "product": product, "match_by": "name"}
            
            # Vérifier par code
            if code_lower:
                product_code = self._get_product_attr(product, 'code', '').lower().strip()
                if product_code and product_code == code_lower:
                    return {"exists": True, "product": product, "match_by": "code"}
            
            # Vérifier par code-barres
            if barcode_lower:
                product_barcode = self._get_product_attr(product, 'barcode', '').lower().strip()
                if product_barcode and product_barcode == barcode_lower:
                    return {"exists": True, "product": product, "match_by": "barcode"}
        
        return {"exists": False, "product": None, "match_by": None}
    
    def _get_product_attr(self, product, attr_name: str, default=None):
        """Récupère un attribut d'un produit (dictionnaire ou objet)"""
        if isinstance(product, dict):
            return product.get(attr_name, default)
        else:
            return getattr(product, attr_name, default)
    
    # ==================== CRÉATION DE PRODUIT LOCAL ====================
    
    def create_local_product(self, product_data: Dict) -> object:
        """Crée un objet Product local"""
        from database.models import Product
        
        branch_id = self._get_branch_id()
        pharmacy_id = self._get_pharmacy_id()
        tenant_id = self._get_tenant_id()
        
        # Générer un ID temporaire si pas d'internet
        import uuid
        temp_id = str(uuid.uuid4())
        
        product = Product(
            server_id=product_data.get('server_id', temp_id),
            name=product_data.get('name', ''),
            code=product_data.get('code', ''),
            barcode=product_data.get('barcode', ''),
            selling_price=product_data.get('selling_price', 0),
            purchase_price=product_data.get('purchase_price', 0),
            quantity=product_data.get('quantity', 0),
            stock=product_data.get('quantity', 0),
            synced_quantity=product_data.get('quantity', 0) if self._is_online else 0,
            category=product_data.get('category', ''),
            unit=product_data.get('unit', 'pièce'),
            min_stock=product_data.get('min_stock', 0),
            max_stock=product_data.get('max_stock', 0),
            expiry_date=product_data.get('expiry_date'),
            location=product_data.get('location', ''),
            supplier=product_data.get('supplier', ''),
            batch_number=product_data.get('batch_number', ''),
            description=product_data.get('description', ''),
            branch_id=branch_id,
            pharmacy_id=pharmacy_id,
            tenant_id=tenant_id,
            is_active=True,
            is_deleted=False,
            stock_version=1,
            last_sync_at=datetime.now().isoformat() if self._is_online else None,
            updated_at=datetime.now().isoformat(),
            created_at=datetime.now().isoformat(),
        )
        
        return product
    
    def save_product_locally(self, product) -> bool:
        """Sauvegarde le produit dans la base locale"""
        try:
            saved_count = self.db.save_products([product])
            if saved_count > 0:
                logger.info(f"Produit sauvegardé localement: {product.name}")
                return True
            return False
        except Exception as e:
            logger.error(f"Erreur sauvegarde locale: {e}")
            return False
    
    # ==================== SYNCHRONISATION AVEC SERVEUR ====================
    
    def sync_product_to_server(self, product_data: Dict) -> Dict:
        """
        Envoie le produit au serveur.
        
        Returns:
            Dict avec 'success' (bool), 'server_id' (str), 'error' (str)
        """
        try:
            headers = self._get_headers()
            if not headers:
                return {"success": False, "error": "Non authentifié"}
            
            branch_id = self._get_branch_id()
            
            # Préparer les données pour le serveur
            payload = {
                "name": product_data.get('name', ''),
                "code": product_data.get('code', ''),
                "barcode": product_data.get('barcode', ''),
                "selling_price": product_data.get('selling_price', 0),
                "purchase_price": product_data.get('purchase_price', 0),
                "quantity": product_data.get('quantity', 0),
                "category": product_data.get('category', ''),
                "unit": product_data.get('unit', 'pièce'),
                "min_stock": product_data.get('min_stock', 0),
                "max_stock": product_data.get('max_stock', 0),
                "expiry_date": product_data.get('expiry_date'),
                "location": product_data.get('location', ''),
                "supplier": product_data.get('supplier', ''),
                "batch_number": product_data.get('batch_number', ''),
                "description": product_data.get('description', ''),
                "branch_id": branch_id,
            }
            
            # Nettoyer les champs None
            payload = {k: v for k, v in payload.items() if v is not None}
            
            response = self.sync_service.session.post(
                f"{self.sync_service.api_url}/stock",
                headers=headers,
                json=payload,
                timeout=60
            )
            
            if response.status_code in [200, 201]:
                data = response.json()
                server_id = data.get('id') or data.get('product', {}).get('id')
                return {"success": True, "server_id": server_id}
            else:
                error_msg = f"Erreur serveur: {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg = error_data.get('detail', error_msg)
                except:
                    pass
                return {"success": False, "error": error_msg}
                
        except Exception as e:
            logger.error(f"Erreur synchronisation serveur: {e}")
            return {"success": False, "error": str(e)}
    
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
    
    # ==================== DIALOGUE DE MODIFICATION ====================
    
    def show_modify_existing_product_dialog(self, existing_product: Dict, new_data: Dict):
        """
        Affiche un dialogue pour modifier un produit existant.
        
        Args:
            existing_product: Produit existant
            new_data: Nouvelles données saisies par l'utilisateur
        """
        product_name = self._get_product_attr(existing_product, 'name', 'Produit')
        existing_qty = self._get_product_attr(existing_product, 'quantity', 0)
        existing_price = self._get_product_attr(existing_product, 'selling_price', 0)
        
        new_qty = new_data.get('quantity', 0)
        new_price = new_data.get('selling_price', 0)
        
        # Conteneurs pour les champs modifiables
        qty_field = ft.TextField(
            label="Nouvelle quantité",
            value=str(existing_qty + new_qty),
            keyboard_type=ft.KeyboardType.NUMBER,
            prefix_icon=ft.Icons.INVENTORY,
            hint_text=f"Stock actuel: {existing_qty}",
        )
        
        price_field = ft.TextField(
            label="Nouveau prix de vente",
            value=str(new_price if new_price > 0 else existing_price),
            keyboard_type=ft.KeyboardType.NUMBER,
            prefix_icon=ft.Icons.MONETIZATION_ON,
            hint_text=f"Prix actuel: {existing_price:,.0f} FC",
        )
        
        def on_confirm(e):
            # Récupérer les valeurs modifiées
            final_qty = self._safe_int(qty_field.value, existing_qty + new_qty)
            final_price = self._safe_float(price_field.value, existing_price)
            
            # Fermer le dialogue
            if self.duplicate_dialog:
                self.duplicate_dialog.open = False
                self.page.update()
            
            # Mettre à jour le produit
            self.update_existing_product(existing_product, final_qty, final_price, new_data)
        
        def on_cancel(e):
            if self.duplicate_dialog:
                self.duplicate_dialog.open = False
                self.page.update()
        
        self.duplicate_dialog = ft.AlertDialog(
            title=ft.Text(f"⚠️ Produit déjà existant", size=18, weight=ft.FontWeight.BOLD),
            content=ft.Column(
                [
                    ft.Text(f"Le produit '{product_name}' existe déjà dans votre inventaire.", size=14),
                    ft.Divider(),
                    ft.Text("Voulez-vous modifier les informations du produit ?", size=13, color=ft.Colors.GREY_700),
                    ft.Container(height=10),
                    ft.Text("Quantité à ajouter:", size=12, weight=ft.FontWeight.BOLD),
                    qty_field,
                    ft.Text("Prix de vente:", size=12, weight=ft.FontWeight.BOLD),
                    price_field,
                    ft.Text("⚠️ Les autres informations (catégorie, emplacement, etc.) seront mises à jour.", 
                           size=11, color=ft.Colors.ORANGE),
                ],
                spacing=8,
                tight=True,
                width=400,
            ),
            actions=[
                ft.TextButton("Annuler", on_click=on_cancel),
                ft.Button("Mettre à jour", on_click=on_confirm, bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        self.page.dialog = self.duplicate_dialog
        self.duplicate_dialog.open = True
        self.page.update()
    
    def update_existing_product(self, existing_product, new_quantity: int, new_price: float, new_data: Dict):
        """
        Met à jour un produit existant (quantité et/ou prix)
        """
        try:
            product_id = self._get_product_attr(existing_product, 'server_id')
            if not product_id:
                product_id = self._get_product_attr(existing_product, 'id')
            
            # Récupérer l'objet product
            from database.models import Product
            
            # Obtenir la quantité actuelle
            current_qty = self._get_product_attr(existing_product, 'quantity', 0)
            if hasattr(existing_product, 'quantity'):
                current_qty = existing_product.quantity
            elif isinstance(existing_product, dict):
                current_qty = existing_product.get('quantity', 0)
            
            # Créer ou mettre à jour le produit
            if hasattr(existing_product, 'server_id'):
                # C'est déjà un objet Product
                product = existing_product
                product.quantity = new_quantity
                product.selling_price = new_price
                
                # Mettre à jour les autres champs
                if new_data.get('category'):
                    product.category = new_data.get('category')
                if new_data.get('location'):
                    product.location = new_data.get('location')
                if new_data.get('supplier'):
                    product.supplier = new_data.get('supplier')
                if new_data.get('batch_number'):
                    product.batch_number = new_data.get('batch_number')
                if new_data.get('expiry_date'):
                    product.expiry_date = new_data.get('expiry_date')
                if new_data.get('description'):
                    product.description = new_data.get('description')
                
                product.updated_at = datetime.now().isoformat()
                
                # Sauvegarder
                saved = self.db.save_products([product])
                if saved > 0:
                    self.show_snackbar(
                        f"✅ Produit mis à jour: quantité={new_quantity}, prix={new_price:,.0f} FC",
                        ft.Colors.GREEN
                    )
                else:
                    self.show_snackbar("❌ Erreur lors de la mise à jour", ft.Colors.RED)
            else:
                # C'est un dictionnaire, créer un objet Product mis à jour
                product = self.create_local_product({
                    'server_id': product_id,
                    'name': self._get_product_attr(existing_product, 'name', ''),
                    'code': self._get_product_attr(existing_product, 'code', ''),
                    'barcode': self._get_product_attr(existing_product, 'barcode', ''),
                    'selling_price': new_price,
                    'purchase_price': self._get_product_attr(existing_product, 'purchase_price', 0),
                    'quantity': new_quantity,
                    'category': new_data.get('category') or self._get_product_attr(existing_product, 'category', ''),
                    'unit': self._get_product_attr(existing_product, 'unit', 'pièce'),
                    'min_stock': self._get_product_attr(existing_product, 'min_stock', 0),
                    'max_stock': self._get_product_attr(existing_product, 'max_stock', 0),
                    'expiry_date': new_data.get('expiry_date') or self._get_product_attr(existing_product, 'expiry_date'),
                    'location': new_data.get('location') or self._get_product_attr(existing_product, 'location', ''),
                    'supplier': new_data.get('supplier') or self._get_product_attr(existing_product, 'supplier', ''),
                    'batch_number': new_data.get('batch_number') or self._get_product_attr(existing_product, 'batch_number', ''),
                    'description': new_data.get('description') or self._get_product_attr(existing_product, 'description', ''),
                })
                saved = self.db.save_products([product])
                if saved > 0:
                    self.show_snackbar(
                        f"✅ Produit mis à jour: quantité={new_quantity}, prix={new_price:,.0f} FC",
                        ft.Colors.GREEN
                    )
                else:
                    self.show_snackbar("❌ Erreur lors de la mise à jour", ft.Colors.RED)
            
            # Synchroniser avec le serveur si en ligne
            if self._is_online:
                self.sync_existing_product_to_server(product_id, new_quantity, new_price, new_data)
            
            # Rafraîchir le cache
            self._refresh_product_cache()
            
            # Callback
            if self.on_product_added:
                self.on_product_added()
            
            # Réinitialiser le formulaire
            self.reset_form()
            
        except Exception as e:
            logger.error(f"Erreur mise à jour produit existant: {e}")
            self.show_snackbar(f"Erreur: {str(e)}", ft.Colors.RED)
    
    def sync_existing_product_to_server(self, product_id: str, new_quantity: int, new_price: float, new_data: Dict):
        """Synchronise la mise à jour d'un produit existant vers le serveur"""
        try:
            headers = self._get_headers()
            if not headers:
                return
            
            payload = {
                "quantity": new_quantity,
                "selling_price": new_price,
            }
            
            if new_data.get('category'):
                payload["category"] = new_data.get('category')
            if new_data.get('location'):
                payload["location"] = new_data.get('location')
            if new_data.get('supplier'):
                payload["supplier"] = new_data.get('supplier')
            if new_data.get('expiry_date'):
                payload["expiry_date"] = new_data.get('expiry_date')
            
            response = self.sync_service.session.put(
                f"{self.sync_service.api_url}/stock/{product_id}",
                headers=headers,
                json=payload,
                timeout=60
            )
            
            if response.status_code in [200, 201]:
                logger.info(f"Produit {product_id} mis à jour sur le serveur")
            else:
                logger.warning(f"Échec mise à jour serveur: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Erreur sync mise à jour serveur: {e}")
    
    # ==================== ENREGISTREMENT PRINCIPAL ====================
    
    def submit_product(self, e):
        """Soumet le formulaire de création de produit"""
        if self.is_submitting:
            self.show_snackbar("Traitement en cours...", ft.Colors.ORANGE)
            return
        
        # Récupérer les valeurs du formulaire
        name = self._safe_str(self.name_field.value if self.name_field else "")
        code = self._safe_str(self.code_field.value if self.code_field else "")
        barcode = self._safe_str(self.barcode_field.value if self.barcode_field else "")
        quantity = self._safe_int(self.quantity_field.value if self.quantity_field else 0)
        selling_price = self._safe_float(self.selling_price_field.value if self.selling_price_field else 0)
        purchase_price = self._safe_float(self.purchase_price_field.value if self.purchase_price_field else 0)
        category = self._safe_str(self.category_field.value if self.category_field else "")
        unit = self._safe_str(self.unit_field.value if self.unit_field else "pièce")
        min_stock = self._safe_int(self.min_stock_field.value if self.min_stock_field else 0)
        max_stock = self._safe_int(self.max_stock_field.value if self.max_stock_field else 0)
        location = self._safe_str(self.location_field.value if self.location_field else "")
        supplier = self._safe_str(self.supplier_field.value if self.supplier_field else "")
        batch_number = self._safe_str(self.batch_number_field.value if self.batch_number_field else "")
        description = self._safe_str(self.description_field.value if self.description_field else "")
        
        # Date d'expiration
        expiry_date = None
        if self.expiry_date_field and self.expiry_date_field.value:
            try:
                expiry_date = datetime.strptime(self.expiry_date_field.value, "%Y-%m-%d").date()
            except:
                try:
                    expiry_date = datetime.strptime(self.expiry_date_field.value, "%d/%m/%Y").date()
                except:
                    pass
        
        # Validation
        if not name:
            self.show_snackbar("❌ Le nom du produit est obligatoire", ft.Colors.RED)
            return
        
        if quantity < 0:
            self.show_snackbar("❌ La quantité ne peut pas être négative", ft.Colors.RED)
            return
        
        if selling_price < 0:
            self.show_snackbar("❌ Le prix de vente ne peut pas être négatif", ft.Colors.RED)
            return
        
        # Vérifier les doublons
        duplicate_check = self.check_duplicate_product(name, code, barcode)
        
        if duplicate_check["exists"]:
            # Produit existant - demander modification
            product_data = {
                'name': name,
                'code': code,
                'barcode': barcode,
                'quantity': quantity,
                'selling_price': selling_price,
                'purchase_price': purchase_price,
                'category': category,
                'unit': unit,
                'min_stock': min_stock,
                'max_stock': max_stock,
                'expiry_date': expiry_date.isoformat() if expiry_date else None,
                'location': location,
                'supplier': supplier,
                'batch_number': batch_number,
                'description': description,
            }
            self.show_modify_existing_product_dialog(duplicate_check["product"], product_data)
            return
        
        # Nouveau produit - procéder à l'enregistrement
        self.is_submitting = True
        self._update_submit_button_state(True)
        
        def save_task():
            try:
                product_data = {
                    'name': name,
                    'code': code,
                    'barcode': barcode,
                    'quantity': quantity,
                    'selling_price': selling_price,
                    'purchase_price': purchase_price,
                    'category': category,
                    'unit': unit,
                    'min_stock': min_stock,
                    'max_stock': max_stock,
                    'expiry_date': expiry_date.isoformat() if expiry_date else None,
                    'location': location,
                    'supplier': supplier,
                    'batch_number': batch_number,
                    'description': description,
                }
                
                server_id = None
                sync_success = False
                
                # Si en ligne, d'abord enregistrer sur le serveur
                if self._is_online:
                    self._update_progress_text("Synchronisation avec le serveur...")
                    result = self.sync_product_to_server(product_data)
                    
                    if result.get("success"):
                        server_id = result.get("server_id")
                        sync_success = True
                        product_data['server_id'] = server_id
                        self._update_progress_text("✅ Produit enregistré sur le serveur")
                    else:
                        error = result.get("error", "Erreur inconnue")
                        logger.warning(f"Échec enregistrement serveur: {error}")
                        self._update_progress_text(f"⚠️ Enregistrement local seulement: {error[:50]}")
                        # Continuer avec enregistrement local
                
                # Enregistrer localement
                self._update_progress_text("Enregistrement local...")
                product = self.create_local_product(product_data)
                
                if self.save_product_locally(product):
                    self._update_progress_text("✅ Produit enregistré localement")
                    
                    if self._is_online and not sync_success:
                        # Planifier une synchronisation ultérieure
                        self._schedule_later_sync(product)
                    
                    # Rafraîchir le cache
                    self._refresh_product_cache()
                    
                    # Afficher le message de succès
                    sync_msg = " (synchronisé)" if sync_success else " (mode hors-ligne)"
                    self.show_snackbar(
                        f"✅ Produit '{name}' ajouté avec succès{sync_msg}",
                        ft.Colors.GREEN
                    )
                    
                    # Callback
                    if self.on_product_added:
                        self.page.run_thread(self.on_product_added)
                    
                    # Réinitialiser le formulaire
                    self.page.run_thread(self.reset_form)
                else:
                    self.show_snackbar("❌ Erreur lors de l'enregistrement local", ft.Colors.RED)
                
            except Exception as e:
                logger.error(f"Erreur lors de l'enregistrement: {e}")
                self.show_snackbar(f"❌ Erreur: {str(e)}", ft.Colors.RED)
            finally:
                self.is_submitting = False
                self.page.run_thread(lambda: self._update_submit_button_state(False))
                self.page.run_thread(lambda: self._update_progress_text(""))
        
        # Démarrer le thread
        threading.Thread(target=save_task, daemon=True).start()
    
    def _update_submit_button_state(self, is_loading: bool):
        """Met à jour l'état du bouton de soumission"""
        if hasattr(self, 'submit_button') and self.submit_button:
            if is_loading:
                self.submit_button.content = ft.Row(
                    [
                        ft.ProgressRing(width=20, height=20, stroke_width=2),
                        ft.Text("Enregistrement...", size=14),
                    ],
                    spacing=8,
                    alignment=ft.MainAxisAlignment.CENTER,
                )
                self.submit_button.disabled = True
            else:
                self.submit_button.content = ft.Row(
                    [
                        ft.Icon(ft.Icons.SAVE, size=18),
                        ft.Text("Enregistrer le produit", size=14, weight=ft.FontWeight.BOLD),
                    ],
                    spacing=8,
                    alignment=ft.MainAxisAlignment.CENTER,
                )
                self.submit_button.disabled = False
            self.page.update()
    
    def _update_progress_text(self, text: str):
        """Met à jour le texte de progression"""
        if hasattr(self, 'progress_text') and self.progress_text:
            self.progress_text.value = text
            self.progress_text.visible = bool(text)
            self.page.update()
    
    def _schedule_later_sync(self, product):
        """Planifie une synchronisation ultérieure pour ce produit"""
        # Stocker le produit dans une liste des produits à synchroniser
        # Cette méthode peut être étendue pour utiliser un service de file d'attente
        logger.info(f"Produit '{product.name}' planifié pour synchronisation ultérieure")
        # TODO: Implémenter un système de file d'attente pour les produits non synchronisés
    
    def reset_form(self):
        """Réinitialise le formulaire après enregistrement"""
        if self.name_field:
            self.name_field.value = ""
        if self.code_field:
            self.code_field.value = ""
        if self.barcode_field:
            self.barcode_field.value = ""
        if self.quantity_field:
            self.quantity_field.value = "0"
        if self.selling_price_field:
            self.selling_price_field.value = ""
        if self.purchase_price_field:
            self.purchase_price_field.value = ""
        if self.category_field:
            self.category_field.value = ""
        if self.unit_field:
            self.unit_field.value = "pièce"
        if self.min_stock_field:
            self.min_stock_field.value = "0"
        if self.max_stock_field:
            self.max_stock_field.value = ""
        if self.expiry_date_field:
            self.expiry_date_field.value = ""
        if self.location_field:
            self.location_field.value = ""
        if self.supplier_field:
            self.supplier_field.value = ""
        if self.batch_number_field:
            self.batch_number_field.value = ""
        if self.description_field:
            self.description_field.value = ""
        
        # Focus sur le champ nom
        if self.name_field:
            self.name_field.focus()
        
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
                        "Ajouter un produit",
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
    
    def create_form_section(self, title: str, fields: List[ft.Control], columns: int = 1) -> ft.Container:
        """Crée une section de formulaire avec titre"""
        if columns > 1:
            # Disposition en grille
            rows = []
            for i in range(0, len(fields), columns):
                row = ft.Row(
                    fields[i:i + columns],
                    expand=True,
                    spacing=15,
                )
                rows.append(row)
            content = ft.Column(rows, spacing=15)
        else:
            content = ft.Column(fields, spacing=12)
        
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(title, size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_800),
                    ft.Divider(height=1, color=ft.Colors.GREY_300),
                    content,
                ],
                spacing=10,
            ),
            padding=15,
            bgcolor=ft.Colors.WHITE,
            border_radius=12,
            margin=ft.Margin.only(bottom=15),
            shadow=ft.BoxShadow(blur_radius=5, color=ft.Colors.GREY_200),
        )
    
    def build_form(self) -> ft.Column:
        """Construit le formulaire complet"""
        
        # Section: Informations de base
        self.name_field = ft.TextField(
            label="Nom du produit *",
            hint_text="Ex: Paracétamol 500mg",
            prefix_icon=ft.Icons.MEDICATION,  # Correction: utiliser MEDICATION au lieu de PRODUCT
            expand=True,
            border_radius=10,
            on_submit=self.submit_product,
        )
        
        self.code_field = ft.TextField(
            label="Code produit",
            hint_text="Code unique du produit",
            prefix_icon=ft.Icons.CODE,
            expand=True,
            border_radius=10,
        )
        
        self.barcode_field = ft.TextField(
            label="Code-barres EAN13",
            hint_text="Numéro de code-barres",
            prefix_icon=ft.Icons.BARCODE_READER,
            expand=True,
            border_radius=10,
        )
        
        basic_info_row = ft.Row(
            [self.name_field, self.code_field, self.barcode_field],
            expand=True,
            spacing=15,
            wrap=True,
        )
        
        # Section: Stock et prix
        self.quantity_field = ft.TextField(
            label="Quantité initiale",
            value="0",
            keyboard_type=ft.KeyboardType.NUMBER,
            prefix_icon=ft.Icons.INVENTORY,
            expand=True,
            border_radius=10,
        )
        
        self.selling_price_field = ft.TextField(
            label="Prix de vente (FC)",
            hint_text="0",
            keyboard_type=ft.KeyboardType.NUMBER,
            prefix_icon=ft.Icons.MONETIZATION_ON,
            expand=True,
            border_radius=10,
        )
        
        self.purchase_price_field = ft.TextField(
            label="Prix d'achat (FC)",
            hint_text="0",
            keyboard_type=ft.KeyboardType.NUMBER,
            prefix_icon=ft.Icons.SHOPPING_CART,
            expand=True,
            border_radius=10,
        )
        
        stock_row = ft.Row(
            [self.quantity_field, self.selling_price_field, self.purchase_price_field],
            expand=True,
            spacing=15,
            wrap=True,
        )
        
        # Section: Catégorie et unité
        self.category_field = ft.TextField(
            label="Catégorie",
            hint_text="Ex: Médicaments, Parapharmacie...",
            prefix_icon=ft.Icons.CATEGORY,
            expand=True,
            border_radius=10,
        )
        
        self.unit_field = ft.TextField(
            label="Unité",
            value="pièce",
            hint_text="pièce, boîte, flacon...",
            prefix_icon=ft.Icons.SCALE,
            expand=True,
            border_radius=10,
        )
        
        category_row = ft.Row(
            [self.category_field, self.unit_field],
            expand=True,
            spacing=15,
            wrap=True,
        )
        
        # Section: Seuils
        self.min_stock_field = ft.TextField(
            label="Stock minimum (alerte)",
            value="0",
            keyboard_type=ft.KeyboardType.NUMBER,
            prefix_icon=ft.Icons.WARNING,
            expand=True,
            border_radius=10,
            helper_style="Alerte quand le stock atteint ce niveau",
        )
        
        self.max_stock_field = ft.TextField(
            label="Stock maximum",
            hint_text="Optionnel",
            keyboard_type=ft.KeyboardType.NUMBER,
            prefix_icon=ft.Icons.TRENDING_UP,
            expand=True,
            border_radius=10,
        )
        
        thresholds_row = ft.Row(
            [self.min_stock_field, self.max_stock_field],
            expand=True,
            spacing=15,
            wrap=True,
        )
        
        # Section: Traçabilité
        self.expiry_date_field = ft.TextField(
            label="Date d'expiration",
            hint_text="YYYY-MM-DD",
            prefix_icon=ft.Icons.DATE_RANGE,
            expand=True,
            border_radius=10,
            helper_style="Format: 2025-12-31",
        )
        
        self.batch_number_field = ft.TextField(
            label="Numéro de lot",
            hint_text="Lot du fabricant",
            prefix_icon=ft.Icons.LABEL,
            expand=True,
            border_radius=10,
        )
        
        self.supplier_field = ft.TextField(
            label="Fournisseur",
            hint_text="Nom du fournisseur",
            prefix_icon=ft.Icons.LOCAL_SHIPPING,
            expand=True,
            border_radius=10,
        )
        
        traceability_row = ft.Row(
            [self.expiry_date_field, self.batch_number_field, self.supplier_field],
            expand=True,
            spacing=15,
            wrap=True,
        )
        
        # Section: Emplacement et description
        self.location_field = ft.TextField(
            label="Emplacement",
            hint_text="Ex: Rayon A, étagère 3",
            prefix_icon=ft.Icons.LOCATION_ON,
            expand=True,
            border_radius=10,
        )
        
        self.description_field = ft.TextField(
            label="Description",
            hint_text="Informations complémentaires",
            prefix_icon=ft.Icons.DESCRIPTION,
            multiline=True,
            min_lines=2,
            max_lines=4,
            expand=True,
            border_radius=10,
        )
        
        location_desc_row = ft.Row(
            [self.location_field],
            expand=True,
            spacing=15,
        )
        
        # Bouton de soumission
        self.progress_text = ft.Text("", size=12, color=ft.Colors.BLUE_700, visible=False)
        
        self.submit_button = ft.Button(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.SAVE, size=18),
                    ft.Text("Enregistrer le produit", size=14, weight=ft.FontWeight.BOLD),
                ],
                spacing=8,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            on_click=self.submit_product,
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
                self.create_form_section("📦 Informations de base", [basic_info_row]),
                self.create_form_section("💰 Stock et prix", [stock_row]),
                self.create_form_section("🏷️ Catégorie", [category_row]),
                self.create_form_section("⚙️ Seuils et alertes", [thresholds_row]),
                self.create_form_section("🔍 Traçabilité", [traceability_row]),
                self.create_form_section("📍 Emplacement", [location_desc_row, self.description_field]),
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
                    padding=ft.Padding.symmetric(vertical=20),
                ),
            ],
            spacing=15,
            scroll=ft.ScrollMode.AUTO,
        )
    
    def show(self):
        """Affiche l'écran d'ajout de produit"""
        self.page.clean()
        self.page.scroll = ft.ScrollMode.AUTO
        self.page.padding = 0
        self.page.bgcolor = ft.Colors.GREY_100
        
        # Rafraîchir le cache des produits
        self._refresh_product_cache()
        
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
        
        # Focus sur le champ nom
        if self.name_field:
            self.name_field.focus()
    
    def go_back(self):
        """Retourne à l'écran précédent"""
        from screens.products_screen import ProductsScreen
        
        products_screen = ProductsScreen(
            self.page, self.db, self.sync_service,
            self.auth_service, self.current_user
        )
        products_screen.show()