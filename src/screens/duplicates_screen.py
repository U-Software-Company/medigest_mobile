# screens/duplicates_screen.py
"""
Écran de gestion des doublons de produits
Permet de fusionner, supprimer ou corriger les produits en doublon
"""

import flet as ft
from typing import List, Dict, Optional
import threading
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class DuplicatesScreen:
    """
    Écran de gestion des produits en doublon.
    - Détection automatique des doublons
    - Fusion de produits
    - Suppression des doublons
    - Correction des informations
    """
    
    def __init__(self, page: ft.Page, db, sync_service, auth_service, current_user, notification_manager=None):
        self.page = page
        self.db = db
        self.sync_service = sync_service
        self.auth_service = auth_service
        self.current_user = current_user
        self.notification_manager = notification_manager
        
        # État
        self.duplicate_groups = []
        self.selected_products = {}
        self.is_processing = False
        
        # Composants UI
        self.duplicates_list = None
        self.progress_bar = None
        self.status_text = None
    
    def show_snackbar(self, message: str, color: str = ft.Colors.BLUE, duration: int = 3000):
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
    
    def get_branch_id(self) -> Optional[str]:
        """Récupère l'ID de la branche"""
        if self.current_user:
            return (self.current_user.get('active_branch_id') or 
                   self.current_user.get('branch_id'))
        return None
    
    def detect_duplicates(self) -> List[Dict]:
        """
        Détecte les produits en doublon.
        
        Returns:
            Liste de groupes de produits doublons
        """
        branch_id = self.get_branch_id()
        products = self.db.get_products(branch_id) or []
        
        # Index par nom, code, code-barres
        by_name = {}
        by_code = {}
        by_barcode = {}
        
        for product in products:
            name = self._get_product_attr(product, 'name', '').lower().strip()
            code = self._get_product_attr(product, 'code', '').lower().strip()
            barcode = self._get_product_attr(product, 'barcode', '').lower().strip()
            
            if name:
                if name not in by_name:
                    by_name[name] = []
                by_name[name].append(product)
            
            if code:
                if code not in by_code:
                    by_code[code] = []
                by_code[code].append(product)
            
            if barcode:
                if barcode not in by_barcode:
                    by_barcode[barcode] = []
                by_barcode[barcode].append(product)
        
        # Regrouper les doublons
        duplicate_groups = []
        processed_ids = set()
        
        # Par nom
        for name, group in by_name.items():
            if len(group) > 1:
                group_ids = [self._get_product_id(p) for p in group]
                if not any(pid in processed_ids for pid in group_ids):
                    duplicate_groups.append({
                        'type': 'name',
                        'value': name,
                        'products': group,
                        'count': len(group)
                    })
                    for pid in group_ids:
                        processed_ids.add(pid)
        
        # Par code
        for code, group in by_code.items():
            if len(group) > 1:
                group_ids = [self._get_product_id(p) for p in group]
                if not any(pid in processed_ids for pid in group_ids):
                    duplicate_groups.append({
                        'type': 'code',
                        'value': code,
                        'products': group,
                        'count': len(group)
                    })
                    for pid in group_ids:
                        processed_ids.add(pid)
        
        # Par code-barres
        for barcode, group in by_barcode.items():
            if len(group) > 1:
                group_ids = [self._get_product_id(p) for p in group]
                if not any(pid in processed_ids for pid in group_ids):
                    duplicate_groups.append({
                        'type': 'barcode',
                        'value': barcode,
                        'products': group,
                        'count': len(group)
                    })
                    for pid in group_ids:
                        processed_ids.add(pid)
        
        return duplicate_groups
    
    def _get_product_attr(self, product, attr_name: str, default=None):
        """Récupère un attribut d'un produit"""
        if isinstance(product, dict):
            return product.get(attr_name, default)
        else:
            return getattr(product, attr_name, default)
    
    def _get_product_id(self, product) -> str:
        """Récupère l'ID d'un produit"""
        return self._get_product_attr(product, 'server_id') or self._get_product_attr(product, 'id')
    
    def refresh_duplicates(self):
        """Rafraîchit la liste des doublons"""
        self.duplicate_groups = self.detect_duplicates()
        self.display_duplicates()
    
    def display_duplicates(self):
        """Affiche la liste des groupes de doublons"""
        if not self.duplicates_list:
            return
        
        self.duplicates_list.controls.clear()
        
        if not self.duplicate_groups:
            self.duplicates_list.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(ft.Icons.CHECK_CIRCLE, size=50, color=ft.Colors.GREEN),
                            ft.Text("Aucun produit en doublon détecté", size=16, weight=ft.FontWeight.BOLD),
                            ft.Text("Votre inventaire est propre !", size=13, color=ft.Colors.GREY_600),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=10,
                    ),
                    padding=30,
                    alignment=ft.alignment.center,
                )
            )
        else:
            for group in self.duplicate_groups:
                self.duplicates_list.controls.append(
                    self.create_duplicate_group_card(group)
                )
        
        self.page.update()
    
    def create_duplicate_group_card(self, group: Dict) -> ft.Card:
        """Crée une carte pour un groupe de doublons"""
        
        # Style selon le type
        type_colors = {
            'name': (ft.Colors.ORANGE, ft.Icons.PRODUCT),
            'code': (ft.Colors.BLUE, ft.Icons.CODE),
            'barcode': (ft.Colors.PURPLE, ft.Icons.BARCODE_READER),
        }
        color, icon = type_colors.get(group['type'], (ft.Colors.GREY, ft.Icons.WARNING))
        
        # En-tête du groupe
        header = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(icon, color=color, size=20),
                    ft.Text(
                        f"Doublon par {group['type']}: '{group['value']}'",
                        size=14,
                        weight=ft.FontWeight.BOLD,
                        color=color,
                    ),
                    ft.Container(expand=True),
                    ft.Container(
                        content=ft.Text(f"{group['count']} produits", size=12),
                        bgcolor=color,
                        padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                        border_radius=10,
                    ),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.all(10),
            bgcolor=ft.Colors.GREY_100,
            border_radius=ft.Border_radius.only(top_left=12, top_right=12),
        )
        
        # Liste des produits du groupe
        products_list = ft.Column(spacing=5)
        
        for product in group['products']:
            product_id = self._get_product_id(product)
            name = self._get_product_attr(product, 'name', 'Inconnu')
            code = self._get_product_attr(product, 'code', '-')
            barcode = self._get_product_attr(product, 'barcode', '-')
            quantity = self._get_product_attr(product, 'quantity', 0)
            price = self._get_product_attr(product, 'selling_price', 0)
            
            # Case à cocher pour sélection
            checkbox = ft.Checkbox(
                value=product_id in self.selected_products,
                on_change=lambda e, pid=product_id: self.toggle_product_selection(pid, e.control.value),
            )
            
            product_row = ft.Container(
                content=ft.Row(
                    [
                        checkbox,
                        ft.Column(
                            [
                                ft.Text(name, size=14, weight=ft.FontWeight.W_500),
                                ft.Text(f"Code: {code} | Barre: {barcode}", size=11, color=ft.Colors.GREY_600),
                                ft.Text(f"Stock: {quantity} | Prix: {price:,.0f} FC", size=11),
                            ],
                            expand=True,
                            spacing=2,
                        ),
                        ft.PopupMenuButton(
                            icon=ft.Icons.MORE_VERT,
                            items=[
                                ft.PopupMenuItem(
                                    text="Voir détails",
                                    on_click=lambda e, p=product: self.view_product_details(p),
                                ),
                                ft.PopupMenuItem(
                                    text="Modifier",
                                    on_click=lambda e, p=product: self.edit_product(p),
                                ),
                                ft.PopupMenuItem(
                                    text="Supprimer",
                                    on_click=lambda e, p=product: self.delete_product(p),
                                ),
                            ],
                        ),
                    ],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                bgcolor=ft.Colors.WHITE,
                border=ft.border.all(0.5, ft.Colors.GREY_200),
                border_radius=8,
            )
            products_list.controls.append(product_row)
        
        # Boutons d'action pour le groupe
        action_buttons = ft.Row(
            [
                ft.TextButton(
                    "Tout sélectionner",
                    on_click=lambda e, g=group: self.select_all_in_group(g, True),
                    icon=ft.Icons.SELECT_ALL,
                ),
                ft.TextButton(
                    "Tout désélectionner",
                    on_click=lambda e, g=group: self.select_all_in_group(g, False),
                    icon=ft.Icons.DESELECT,
                ),
                ft.Button(
                    "Fusionner sélection",
                    on_click=lambda e, g=group: self.merge_selected_products(g),
                    icon=ft.Icons.MERGE_TYPE,
                    color=ft.Colors.WHITE,
                    bgcolor=ft.Colors.BLUE_700,
                    style=ft.ButtonStyle(padding=10),
                ),
            ],
            spacing=10,
            wrap=True,
        )
        
        footer = ft.Container(
            content=action_buttons,
            padding=ft.Padding.all(10),
            bgcolor=ft.Colors.GREY_50,
            border_radius=ft.Border_radius.only(bottom_left=12, bottom_right=12),
        )
        
        return ft.Card(
            content=ft.Column(
                [
                    header,
                    products_list,
                    footer,
                ],
                spacing=0,
                tight=True,
            ),
            margin=ft.Margin.only(bottom=15),
            elevation=2,
        )
    
    def toggle_product_selection(self, product_id: str, is_selected: bool):
        """Active/désactive la sélection d'un produit"""
        if is_selected:
            self.selected_products[product_id] = True
        else:
            self.selected_products.pop(product_id, None)
    
    def select_all_in_group(self, group: Dict, select: bool):
        """Sélectionne/désélectionne tous les produits d'un groupe"""
        for product in group['products']:
            product_id = self._get_product_id(product)
            if select:
                self.selected_products[product_id] = True
            else:
                self.selected_products.pop(product_id, None)
        self.display_duplicates()
    
    def merge_selected_products(self, group: Dict):
        """Fusionne les produits sélectionnés"""
        # Récupérer les produits sélectionnés dans ce groupe
        selected = []
        for product in group['products']:
            product_id = self._get_product_id(product)
            if product_id in self.selected_products:
                selected.append(product)
        
        if len(selected) < 2:
            self.show_snackbar("Veuillez sélectionner au moins 2 produits à fusionner", ft.Colors.ORANGE)
            return
        
        # Afficher le dialogue de fusion
        self.show_merge_dialog(selected, group)
    
    def show_merge_dialog(self, products: List, group: Dict):
        """Affiche le dialogue de fusion des produits"""
        
        # Le premier produit sera le maître (on garde ses infos)
        master_product = products[0]
        master_id = self._get_product_id(master_product)
        master_name = self._get_product_attr(master_product, 'name', 'Produit')
        
        # Options de fusion
        keep_stock_from = ft.Dropdown(
            label="Garder le stock de",
            options=[
                ft.dropdown.Option(str(i), f"Produit {i+1}: {self._get_product_attr(p, 'name', '')[:30]}")
                for i, p in enumerate(products)
            ],
            value="0",
            width=200,
        )
        
        keep_price_from = ft.Dropdown(
            label="Garder le prix de",
            options=[
                ft.dropdown.Option(str(i), f"Produit {i+1}: {self._get_product_attr(p, 'selling_price', 0):,.0f} FC")
                for i, p in enumerate(products)
            ],
            value="1",
            width=200,
        )
        
        keep_name_from = ft.Dropdown(
            label="Garder le nom de",
            options=[
                ft.dropdown.Option(str(i), f"Produit {i+1}: {self._get_product_attr(p, 'name', '')[:30]}")
                for i, p in enumerate(products)
            ],
            value="0",
            width=200,
        )
        
        # Mode de fusion
        merge_mode = ft.Dropdown(
            label="Mode de fusion",
            options=[
                ft.dropdown.Option("sum", "Additionner les stocks"),
                ft.dropdown.Option("max", "Prendre le stock maximum"),
                ft.dropdown.Option("min", "Prendre le stock minimum"),
                ft.dropdown.Option("average", "Moyenne des stocks"),
            ],
            value="sum",
            width=200,
        )
        
        def on_confirm(e):
            # Fermer le dialogue
            if hasattr(self, 'merge_dialog') and self.merge_dialog:
                self.merge_dialog.open = False
                self.page.update()
            
            # Effectuer la fusion
            self.execute_merge(products, {
                'keep_stock_from': int(keep_stock_from.value),
                'keep_price_from': int(keep_price_from.value),
                'keep_name_from': int(keep_name_from.value),
                'merge_mode': merge_mode.value,
            })
        
        def on_cancel(e):
            if hasattr(self, 'merge_dialog') and self.merge_dialog:
                self.merge_dialog.open = False
                self.page.update()
        
        self.merge_dialog = ft.AlertDialog(
            title=ft.Text("Fusion de produits", size=18, weight=ft.FontWeight.BOLD),
            content=ft.Column(
                [
                    ft.Text(f"Vous allez fusionner {len(products)} produits en un seul.", size=14),
                    ft.Divider(),
                    ft.Text("Produits à fusionner:", weight=ft.FontWeight.BOLD),
                    ft.Column(
                        [ft.Text(f"• {self._get_product_attr(p, 'name', '')} (stock: {self._get_product_attr(p, 'quantity', 0)})") 
                         for p in products],
                        spacing=5,
                    ),
                    ft.Divider(),
                    ft.Row([keep_name_from], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Row([keep_stock_from, merge_mode], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Row([keep_price_from], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Text("⚠️ Cette action est irréversible. Les produits fusionnés seront supprimés.",
                           size=11, color=ft.Colors.RED),
                ],
                spacing=10,
                width=500,
                height=400,
                scroll=ft.ScrollMode.AUTO,
            ),
            actions=[
                ft.TextButton("Annuler", on_click=on_cancel),
                ft.Button("Fusionner", on_click=on_confirm, bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        self.page.dialog = self.merge_dialog
        self.merge_dialog.open = True
        self.page.update()
    
    def execute_merge(self, products: List, options: Dict):
        """Exécute la fusion des produits"""
        if self.is_processing:
            return
        
        self.is_processing = True
        self.show_snackbar("Fusion en cours...", ft.Colors.BLUE)
        
        def merge_task():
            try:
                master = products[options['keep_name_from']]
                stock_source = products[options['keep_stock_from']]
                price_source = products[options['keep_price_from']]
                
                # Calculer le stock final
                if options['merge_mode'] == 'sum':
                    final_quantity = sum(self._get_product_attr(p, 'quantity', 0) for p in products)
                elif options['merge_mode'] == 'max':
                    final_quantity = max(self._get_product_attr(p, 'quantity', 0) for p in products)
                elif options['merge_mode'] == 'min':
                    final_quantity = min(self._get_product_attr(p, 'quantity', 0) for p in products)
                else:  # average
                    final_quantity = sum(self._get_product_attr(p, 'quantity', 0) for p in products) // len(products)
                
                # Mettre à jour le produit maître
                master_id = self._get_product_id(master)
                master_name = self._get_product_attr(master, 'name')
                master_code = self._get_product_attr(master, 'code')
                master_barcode = self._get_product_attr(master, 'barcode')
                
                final_price = self._get_product_attr(price_source, 'selling_price', 0)
                final_purchase_price = self._get_product_attr(price_source, 'purchase_price', 0)
                
                # Créer l'objet produit mis à jour
                from database.models import Product
                
                updated_product = Product(
                    server_id=master_id,
                    name=master_name,
                    code=master_code,
                    barcode=master_barcode,
                    selling_price=final_price,
                    purchase_price=final_purchase_price,
                    quantity=final_quantity,
                    stock=final_quantity,
                    category=self._get_product_attr(master, 'category', ''),
                    branch_id=self.get_branch_id(),
                    updated_at=datetime.now().isoformat(),
                )
                
                # Sauvegarder le produit mis à jour
                self.db.save_products([updated_product])
                
                # Supprimer les autres produits (sauf le maître)
                for product in products:
                    product_id = self._get_product_id(product)
                    if product_id != master_id:
                        # Marquer comme supprimé
                        if hasattr(product, 'is_deleted'):
                            product.is_deleted = True
                            self.db.save_products([product])
                        elif isinstance(product, dict):
                            product['is_deleted'] = True
                            # Créer un objet Product pour sauvegarde
                            del_prod = Product(
                                server_id=product_id,
                                name=self._get_product_attr(product, 'name', ''),
                                is_deleted=True,
                                branch_id=self.get_branch_id(),
                                updated_at=datetime.now().isoformat(),
                            )
                            self.db.save_products([del_prod])
                
                # Rafraîchir
                self.selected_products.clear()
                self.refresh_duplicates()
                
                self.show_snackbar(
                    f"✅ Fusion réussie: {len(products)} produits fusionnés en '{master_name}'",
                    ft.Colors.GREEN
                )
                
            except Exception as e:
                logger.error(f"Erreur lors de la fusion: {e}")
                self.show_snackbar(f"Erreur: {str(e)}", ft.Colors.RED)
            finally:
                self.is_processing = False
        
        threading.Thread(target=merge_task, daemon=True).start()
    
    def view_product_details(self, product):
        """Affiche les détails d'un produit"""
        name = self._get_product_attr(product, 'name', 'Produit')
        code = self._get_product_attr(product, 'code', '-')
        barcode = self._get_product_attr(product, 'barcode', '-')
        quantity = self._get_product_attr(product, 'quantity', 0)
        price = self._get_product_attr(product, 'selling_price', 0)
        purchase_price = self._get_product_attr(product, 'purchase_price', 0)
        category = self._get_product_attr(product, 'category', '-')
        unit = self._get_product_attr(product, 'unit', 'pièce')
        location = self._get_product_attr(product, 'location', '-')
        supplier = self._get_product_attr(product, 'supplier', '-')
        batch = self._get_product_attr(product, 'batch_number', '-')
        
        content = ft.Column(
            [
                ft.Text(f"📦 {name}", size=16, weight=ft.FontWeight.BOLD),
                ft.Divider(),
                ft.Row([ft.Text("Code:", weight=ft.FontWeight.BOLD), ft.Text(code)], spacing=10),
                ft.Row([ft.Text("Code-barres:", weight=ft.FontWeight.BOLD), ft.Text(barcode)], spacing=10),
                ft.Row([ft.Text("Catégorie:", weight=ft.FontWeight.BOLD), ft.Text(category)], spacing=10),
                ft.Row([ft.Text("Unité:", weight=ft.FontWeight.BOLD), ft.Text(unit)], spacing=10),
                ft.Row([ft.Text("Stock:", weight=ft.FontWeight.BOLD), ft.Text(str(quantity))], spacing=10),
                ft.Row([ft.Text("Prix vente:", weight=ft.FontWeight.BOLD), ft.Text(f"{price:,.0f} FC")], spacing=10),
                ft.Row([ft.Text("Prix achat:", weight=ft.FontWeight.BOLD), ft.Text(f"{purchase_price:,.0f} FC")], spacing=10),
                ft.Row([ft.Text("Emplacement:", weight=ft.FontWeight.BOLD), ft.Text(location)], spacing=10),
                ft.Row([ft.Text("Fournisseur:", weight=ft.FontWeight.BOLD), ft.Text(supplier)], spacing=10),
                ft.Row([ft.Text("Lot:", weight=ft.FontWeight.BOLD), ft.Text(batch)], spacing=10),
            ],
            spacing=8,
            width=400,
            height=400,
            scroll=ft.ScrollMode.AUTO,
        )
        
        dialog = ft.AlertDialog(
            title=ft.Text("Détails du produit"),
            content=content,
            actions=[ft.TextButton("Fermer", on_click=lambda e: self.close_dialog(dialog))],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()
    
    def edit_product(self, product):
        """Ouvre l'écran de modification du produit"""
        from screens.edit_product_screen import EditProductScreen
        
        edit_screen = EditProductScreen(
            self.page, self.db, self.sync_service,
            self.auth_service, self.current_user,
            product, self.notification_manager,
            on_updated=lambda: self.refresh_duplicates()
        )
        edit_screen.show()
    
    def delete_product(self, product):
        """Supprime un produit après confirmation"""
        product_name = self._get_product_attr(product, 'name', 'ce produit')
        product_id = self._get_product_id(product)
        
        def confirm_delete(e):
            self.page.dialog.open = False
            self.page.update()
            
            # Supprimer le produit
            if hasattr(product, 'is_deleted'):
                product.is_deleted = True
                self.db.save_products([product])
            elif isinstance(product, dict):
                from database.models import Product
                del_prod = Product(
                    server_id=product_id,
                    name=product_name,
                    is_deleted=True,
                    branch_id=self.get_branch_id(),
                    updated_at=datetime.now().isoformat(),
                )
                self.db.save_products([del_prod])
            
            # Rafraîchir
            self.refresh_duplicates()
            self.show_snackbar(f"✅ Produit '{product_name}' supprimé", ft.Colors.GREEN)
        
        dialog = ft.AlertDialog(
            title=ft.Text("Confirmation de suppression"),
            content=ft.Text(f"Voulez-vous vraiment supprimer '{product_name}' ?"),
            actions=[
                ft.TextButton("Annuler", on_click=lambda e: self.close_dialog(dialog)),
                ft.Button("Supprimer", on_click=confirm_delete, bgcolor=ft.Colors.RED, color=ft.Colors.WHITE),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()
    
    def close_dialog(self, dialog):
        """Ferme un dialogue"""
        dialog.open = False
        self.page.update()
    
    def build_header(self) -> ft.Container:
        """Construit l'en-tête"""
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
                        "Gestion des doublons",
                        size=22,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.WHITE,
                        expand=True,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.REFRESH,
                        on_click=lambda e: self.refresh_duplicates(),
                        tooltip="Rafraîchir",
                        icon_color=ft.Colors.WHITE,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=15, vertical=12),
            bgcolor=ft.Colors.BLUE_700,
        )
    
    def show(self):
        """Affiche l'écran de gestion des doublons"""
        self.page.clean()
        self.page.scroll = ft.ScrollMode.AUTO
        self.page.padding = 0
        self.page.bgcolor = ft.Colors.GREY_100
        
        # Initialiser la liste
        self.duplicates_list = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO)
        
        # Détecter les doublons
        self.refresh_duplicates()
        
        # Construction de l'interface
        main_content = ft.Column(
            [
                self.build_header(),
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(
                                "Produits en double détectés",
                                size=18,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.BLUE_800,
                            ),
                            ft.Text(
                                "Sélectionnez les produits à fusionner pour nettoyer votre inventaire.",
                                size=13,
                                color=ft.Colors.GREY_600,
                            ),
                            ft.Divider(),
                            self.duplicates_list,
                        ],
                        spacing=15,
                        expand=True,
                    ),
                    padding=15,
                    expand=True,
                ),
            ],
            expand=True,
            spacing=0,
        )
        
        self.page.add(main_content)
        self.page.update()
    
    def go_back(self):
        """Retourne à l'écran précédent"""
        from screens.products_screen import ProductsScreen
        
        products_screen = ProductsScreen(
            self.page, self.db, self.sync_service,
            self.auth_service, self.current_user
        )
        products_screen.show()