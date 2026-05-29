# ui/sync_feedback_dialog.py
import flet as ft
from typing import Dict, List, Optional, Callable
from datetime import datetime



class SyncConflictDialog:
    """Dialogue pour informer l'utilisateur des conflits de synchronisation"""
    
    def __init__(self, page: ft.Page, db, sync_service):
        self.page = page
        self.db = db
        self.sync_service = sync_service
        self.callbacks = {}
        
    def show_conflict_resolution(self, conflicts: List[Dict], on_action: Optional[Callable] = None):
        """Affiche les conflits et propose des actions"""
        if on_action:
            self.callbacks['on_action'] = on_action
        
        if not conflicts:
            return
        
        # Si un seul conflit, l'afficher directement
        if len(conflicts) == 1:
            self._show_single_conflict(conflicts[0])
        else:
            self._show_conflict_list(conflicts)
    
    def _show_conflict_list(self, conflicts: List[Dict]):
        """Affiche une liste de conflits"""
        
        # Compter les types de conflits
        partial_count = sum(1 for c in conflicts if c.get('type') == 'partial')
        rejected_count = sum(1 for c in conflicts if c.get('type') == 'rejected')
        
        conflict_items = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO, height=300)
        
        for conflict in conflicts:
            if conflict.get('type') == 'partial':
                icon = ft.Icon(ft.Icons.WARNING_AMBER, color=ft.Colors.ORANGE, size=24)
                title = ft.Text(f"Vente partielle - {conflict.get('product_name', 'Inconnu')}",
                               size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.ORANGE)
                details = ft.Text(
                    f"{conflict.get('accepted_quantity', 0)}/{conflict.get('requested_quantity', 0)} unités acceptées",
                    size=12, color=ft.Colors.GREY_600
                )
            else:
                icon = ft.Icon(ft.Icons.ERROR, color=ft.Colors.RED, size=24)
                title = ft.Text(f"Vente rejetée - {conflict.get('product_name', 'Inconnu')}",
                               size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.RED)
                details = ft.Text(
                    conflict.get('reason', 'Raison inconnue')[:60],
                    size=12, color=ft.Colors.GREY_600
                )
            
            conflict_card = ft.Container(
                content=ft.Row([
                    icon,
                    ft.Column([title, details], expand=True, spacing=2),
                    ft.IconButton(
                        icon=ft.Icons.CHEVRON_RIGHT,
                        on_click=lambda e, c=conflict: self._show_single_conflict(c),
                        tooltip="Voir détails"
                    ),
                ], spacing=10),
                padding=10,
                bgcolor=ft.Colors.GREY_50,
                border_radius=8,
            )
            conflict_items.controls.append(conflict_card)
        
        # Dialogue principal
        dialog = ft.AlertDialog(
            title=ft.Row([
                ft.Icon(ft.Icons.SYNC_PROBLEM, color=ft.Colors.ORANGE),
                ft.Text("Conflits de synchronisation", size=18, weight=ft.FontWeight.BOLD),
            ], spacing=10),
            content=ft.Column([
                ft.Text(
                    f"{len(conflicts)} conflit(s) détecté(s) lors de la synchronisation",
                    size=14,
                ),
                ft.Divider(),
                ft.Row([
                    ft.Container(
                        content=ft.Text(f"⚠️ Partiels: {partial_count}", size=12, color=ft.Colors.ORANGE),
                        padding=5,
                        bgcolor=ft.Colors.ORANGE_50,
                        border_radius=5,
                    ),
                    ft.Container(
                        content=ft.Text(f"❌ Rejetés: {rejected_count}", size=12, color=ft.Colors.RED),
                        padding=5,
                        bgcolor=ft.Colors.RED_50,
                        border_radius=5,
                    ),
                ], spacing=10),
                ft.Divider(),
                conflict_items,
            ], spacing=10, width=500),
            actions=[
                ft.TextButton("Tout fermer", on_click=lambda e: self._close_dialog(dialog)),
                ft.ElevatedButton(
                    "Synchroniser à nouveau",
                    on_click=lambda e: self._retry_sync(dialog),
                    style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()
    
    def _show_single_conflict(self, conflict: Dict):
        """Affiche un dialogue pour un conflit unique"""
        
        conflict_type = conflict.get('type', 'unknown')
        
        if conflict_type == 'partial':
            self._show_partial_sale_dialog(conflict)
        else:
            self._show_rejected_sale_dialog(conflict)
    
    def _show_partial_sale_dialog(self, conflict: Dict):
        """Affiche un dialogue pour une vente partielle"""
        
        product_name = conflict.get('product_name', 'Inconnu')
        requested_qty = conflict.get('requested_quantity', conflict.get('quantity', 0))
        accepted_qty = conflict.get('accepted_quantity', 0)
        rejected_qty = conflict.get('rejected_quantity', requested_qty - accepted_qty)
        reason = conflict.get('reason', 'Stock insuffisant')
        server_stock = conflict.get('server_stock', conflict.get('available_stock', '?'))
        local_stock = conflict.get('local_stock', '?')
        
        message = ft.Column([
            ft.Icon(ft.Icons.WARNING_AMBER, size=48, color=ft.Colors.ORANGE),
            ft.Text("VENTE PARTIELLEMENT ACCEPTÉE", 
                   size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.ORANGE),
            ft.Divider(),
            ft.Container(
                content=ft.Column([
                    ft.Text(f"📦 Produit: {product_name}", size=14),
                    ft.Text(f"📊 Quantité demandée: {requested_qty}", size=14),
                    ft.Text(f"✅ Quantité acceptée: {accepted_qty}", size=14, color=ft.Colors.GREEN),
                    ft.Text(f"❌ Quantité rejetée: {rejected_qty}", size=14, color=ft.Colors.RED),
                ], spacing=5),
                padding=10,
                bgcolor=ft.Colors.GREY_50,
                border_radius=8,
            ),
            ft.Text(f"📝 Raison: {reason}", size=12, color=ft.Colors.GREY_600),
            ft.Divider(),
            ft.Container(
                content=ft.Column([
                    ft.Text("🔍 DÉTAIL DU CONFLIT", size=12, weight=ft.FontWeight.BOLD),
                    ft.Text(f"Stock serveur: {server_stock} unités", size=12),
                    ft.Text(f"Stock connu localement: {local_stock} unités", size=12),
                    ft.Text(
                        "→ Le stock a été modifié entre-temps (vente par un autre vendeur ou réapprovisionnement)",
                        size=11, color=ft.Colors.GREY_500, italic=True,
                    ),
                ], spacing=5),
                padding=10,
                bgcolor=ft.Colors.BLUE_50,
                border_radius=8,
            ),
        ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        
        actions_row = ft.Row([
            ft.TextButton(
                "Voir le stock actuel",
                on_click=lambda e: self._view_product_stock(conflict),
            ),
            ft.ElevatedButton(
                "OK, j'ai compris",
                on_click=lambda e: self._close_current_dialog(),
                style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE),
            ),
        ], alignment=ft.MainAxisAlignment.END, spacing=10)
        
        dialog = ft.AlertDialog(
            title=ft.Text("⚠️ Vente partielle", size=18, weight=ft.FontWeight.BOLD),
            content=ft.Container(content=message, width=450),
            actions=[actions_row],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        self._current_dialog = dialog
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()
    
    def _show_rejected_sale_dialog(self, conflict: Dict):
        """Affiche un dialogue pour une vente rejetée"""
        
        product_name = conflict.get('product_name', 'Inconnu')
        requested_qty = conflict.get('requested_quantity', conflict.get('quantity', 0))
        reason = conflict.get('reason', 'Erreur inconnue')
        
        # Déterminer l'aide contextuelle
        help_text = self._get_rejection_help(conflict)
        
        message = ft.Column([
            ft.Icon(ft.Icons.ERROR, size=48, color=ft.Colors.RED),
            ft.Text("VENTE REJETÉE", 
                   size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.RED),
            ft.Divider(),
            ft.Container(
                content=ft.Column([
                    ft.Text(f"📦 Produit: {product_name}", size=14),
                    ft.Text(f"📊 Quantité demandée: {requested_qty}", size=14),
                ], spacing=5),
                padding=10,
                bgcolor=ft.Colors.GREY_50,
                border_radius=8,
            ),
            ft.Text(f"📝 Raison: {reason}", size=12, color=ft.Colors.GREY_600),
            ft.Divider(),
            ft.Container(
                content=ft.Column([
                    ft.Text("🔍 QUE FAIRE ?", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE),
                    ft.Text(help_text, size=11, color=ft.Colors.GREY_700),
                ], spacing=5),
                padding=10,
                bgcolor=ft.Colors.AMBER_50,
                border_radius=8,
            ),
        ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        
        actions_row = ft.Row([
            ft.TextButton(
                "Voir produits disponibles",
                on_click=lambda e: self._view_available_products(conflict),
            ),
            ft.ElevatedButton(
                "OK",
                on_click=lambda e: self._close_current_dialog(),
                style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE),
            ),
        ], alignment=ft.MainAxisAlignment.END, spacing=10)
        
        dialog = ft.AlertDialog(
            title=ft.Text("❌ Vente rejetée", size=18, weight=ft.FontWeight.BOLD),
            content=ft.Container(content=message, width=450),
            actions=[actions_row],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        self._current_dialog = dialog
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()
    
    def _get_rejection_help(self, conflict: Dict) -> str:
        """Génère une aide contextuelle selon la raison du rejet"""
        reason = conflict.get('reason', '').lower()
        
        if 'n\'existe pas' in reason or 'supprimé' in reason or 'not found' in reason:
            return """
1. Ce produit a peut-être été supprimé par l'administrateur
2. Vérifiez si le produit existe toujours dans le catalogue
3. Mettez à jour votre catalogue local (synchronisation)
4. Si le problème persiste, contactez l'administrateur
            """
        elif 'stock insuffisant' in reason or 'insufficient' in reason:
            return """
1. Ce produit a été vendu entre-temps par un autre vendeur
2. Synchronisez-vous pour mettre à jour votre stock local
3. Vérifiez le stock réel avant de vendre à nouveau ce produit
4. Pour les urgences, utilisez le mode "force" avec prudence
            """
        elif 'authentification' in reason or 'token' in reason:
            return """
1. Votre session a peut-être expiré
2. Déconnectez-vous et reconnectez-vous
3. Vérifiez votre connexion internet
4. Contactez l'administrateur si le problème persiste
            """
        else:
            return """
1. Vérifiez votre connexion internet
2. Réessayez la synchronisation
3. Si le problème persiste, contactez l'administrateur
            """
    
    def _view_product_stock(self, conflict: Dict):
        """Affiche le stock actuel du produit"""
        product_name = conflict.get('product_name', '')
        
        # Rechercher le produit dans la base locale
        if hasattr(self.db, 'search_products'):
            products = self.db.search_products(product_name)
            if products:
                product = products[0] if products else None
                if product:
                    self._show_product_stock_dialog(product, conflict)
                    return
        
        # Si produit non trouvé
        dialog = ft.AlertDialog(
            title=ft.Text("Produit non trouvé"),
            content=ft.Text(f"Le produit '{product_name}' n'a pas été trouvé dans la base locale."),
            actions=[ft.TextButton("Fermer", on_click=lambda e: self._close_dialog(dialog))],
        )
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()
    
    def _show_product_stock_dialog(self, product, conflict: Dict):
        """Affiche les détails du stock d'un produit"""
        
        stock_value = product.stock if hasattr(product, 'stock') else (product.quantity if hasattr(product, 'quantity') else 0)
        
        dialog = ft.AlertDialog(
            title=ft.Text(f"📦 {product.name}", size=16, weight=ft.FontWeight.BOLD),
            content=ft.Column([
                ft.Container(
                    content=ft.Column([
                        ft.Text(f"Code: {product.code}", size=12),
                        ft.Text(f"Prix: {product.selling_price:,.0f} FC", size=12),
                        ft.Divider(),
                        ft.Row([
                            ft.Text("Stock actuel:", size=14),
                            ft.Text(f"{stock_value} unités", 
                                   size=16, weight=ft.FontWeight.BOLD,
                                   color=ft.Colors.RED if stock_value <= (product.min_stock or 0) else ft.Colors.GREEN),
                        ]),
                        ft.Text(f"Stock minimum: {product.min_stock or 0} unités", size=11, color=ft.Colors.GREY_600),
                    ], spacing=8),
                    padding=10,
                ),
            ], width=350),
            actions=[
                ft.TextButton("Fermer", on_click=lambda e: self._close_dialog(dialog)),
                ft.ElevatedButton(
                    "Synchroniser",
                    on_click=lambda e: self._trigger_sync_and_close(dialog),
                ),
            ],
        )
        
        self._close_current_dialog()
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()
    
    def _view_available_products(self, conflict: Dict):
        """Affiche les produits disponibles"""
        from screens.products_screen import ProductScreen
        
        # Fermer le dialogue courant
        self._close_current_dialog()
        
        # Naviguer vers l'écran des produits
        product_screen = ProductScreen(
            self.page, self.db, self.sync_service, None, None
        )
        product_screen.show()
    
    def _trigger_sync_and_close(self, dialog: ft.AlertDialog):
        """Déclenche une synchronisation et ferme le dialogue"""
        self._close_dialog(dialog)
        
        if self.callbacks.get('on_action'):
            self.callbacks['on_action']('retry_sync')
    
    def _retry_sync(self, current_dialog: ft.AlertDialog):
        """Réessaie la synchronisation"""
        self._close_dialog(current_dialog)
        
        if self.callbacks.get('on_action'):
            self.callbacks['on_action']('retry_sync')
    
    def _close_dialog(self, dialog: ft.AlertDialog):
        """Ferme un dialogue"""
        dialog.open = False
        self.page.update()
    
    def _close_current_dialog(self):
        """Ferme le dialogue courant"""
        if hasattr(self, '_current_dialog') and self._current_dialog:
            self._current_dialog.open = False
            self.page.update()
            delattr(self, '_current_dialog')
    
    def show_sync_summary(self, sync_result: Dict):
        """Affiche un résumé de la synchronisation"""
        
        sales_exported = sync_result.get('sales_exported', 0)
        products_imported = sync_result.get('products_imported', 0)
        expenses_exported = sync_result.get('expenses_exported', 0)
        stock_warnings = sync_result.get('stock_warnings', [])
        errors = sync_result.get('errors', [])
        
        has_warnings = len(stock_warnings) > 0
        has_errors = len(errors) > 0
        
        if has_errors:
            icon = ft.Icon(ft.Icons.ERROR, size=48, color=ft.Colors.RED)
            title = "⚠️ Synchronisation avec erreurs"
            title_color = ft.Colors.RED
        elif has_warnings:
            icon = ft.Icon(ft.Icons.WARNING, size=48, color=ft.Colors.ORANGE)
            title = "⚠️ Synchronisation partielle"
            title_color = ft.Colors.ORANGE
        else:
            icon = ft.Icon(ft.Icons.CHECK_CIRCLE, size=48, color=ft.Colors.GREEN)
            title = "✅ Synchronisation réussie"
            title_color = ft.Colors.GREEN
        
        content = ft.Column([
            icon,
            ft.Text(title, size=18, weight=ft.FontWeight.BOLD, color=title_color),
            ft.Divider(),
            ft.Row([
                ft.Container(
                    content=ft.Column([
                        ft.Text("📦 Produits", size=12),
                        ft.Text(str(products_imported), size=20, weight=ft.FontWeight.BOLD),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    expand=True,
                ),
                ft.Container(
                    content=ft.Column([
                        ft.Text("💰 Ventes", size=12),
                        ft.Text(str(sales_exported), size=20, weight=ft.FontWeight.BOLD),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    expand=True,
                ),
                ft.Container(
                    content=ft.Column([
                        ft.Text("📉 Dépenses", size=12),
                        ft.Text(str(expenses_exported), size=20, weight=ft.FontWeight.BOLD),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    expand=True,
                ),
            ]),
        ], spacing=15, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        
        # Ajouter les avertissements de stock
        if stock_warnings:
            warnings_section = ft.Column([
                ft.Divider(),
                ft.Text("⚠️ Avertissements de stock", size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.ORANGE),
            ])
            for warning in stock_warnings[:5]:
                warnings_section.controls.append(
                    ft.Text(
                        f"• {warning.get('product_name')}: {warning.get('available_stock', 0)}/{warning.get('requested_quantity', 0)} unités",
                        size=12, color=ft.Colors.GREY_700
                    )
                )
            if len(stock_warnings) > 5:
                warnings_section.controls.append(
                    ft.Text(f"... et {len(stock_warnings) - 5} autres", size=11, color=ft.Colors.GREY_500)
                )
            content.controls.append(warnings_section)
        
        # Ajouter les erreurs
        if errors:
            errors_section = ft.Column([
                ft.Divider(),
                ft.Text("❌ Erreurs", size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.RED),
            ])
            for error in errors[:3]:
                errors_section.controls.append(
                    ft.Text(f"• {error.get('error', 'Erreur inconnue')[:80]}", size=11, color=ft.Colors.RED_400)
                )
            if len(errors) > 3:
                errors_section.controls.append(
                    ft.Text(f"... et {len(errors) - 3} autres", size=11, color=ft.Colors.GREY_500)
                )
            content.controls.append(errors_section)
        
        # Ajouter le timestamp
        sync_date = sync_result.get('sync_date', datetime.now().isoformat())
        content.controls.append(
            ft.Text(f"Synchronisation du {sync_date[:19]}", size=10, color=ft.Colors.GREY_500)
        )
        
        dialog = ft.AlertDialog(
            title=None,
            content=ft.Container(content=content, width=400),
            actions=[
                ft.TextButton(
                    "Fermer",
                    on_click=lambda e: self._close_dialog(dialog),
                ),
                ft.ElevatedButton(
                    "Voir les conflits" if (stock_warnings or errors) else "OK",
                    on_click=lambda e: self._handle_summary_action(dialog, stock_warnings, errors),
                    style=ft.ButtonStyle(
                        bgcolor=ft.Colors.BLUE_700 if (stock_warnings or errors) else ft.Colors.GREEN_700,
                        color=ft.Colors.WHITE,
                    ),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        self._current_dialog = dialog
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()
    
    def _handle_summary_action(self, dialog: ft.AlertDialog, stock_warnings: List, errors: List):
        """Gère l'action après le résumé"""
        self._close_dialog(dialog)
        
        if stock_warnings or errors:
            # Convertir les warnings en format de conflit
            conflicts = []
            for warning in stock_warnings:
                conflicts.append({
                    'type': 'partial',
                    'product_name': warning.get('product_name'),
                    'requested_quantity': warning.get('requested_quantity', 0),
                    'accepted_quantity': warning.get('available_stock', 0),
                    'rejected_quantity': warning.get('requested_quantity', 0) - warning.get('available_stock', 0),
                    'reason': warning.get('reason', 'Stock insuffisant'),
                    'server_stock': warning.get('available_stock', 0),
                })
            
            if conflicts:
                self.show_conflict_resolution(conflicts)

    def show_fifo_summary(self, sync_result: Dict):
        """Affiche un résumé du traitement FIFO"""
        
        # Récupérer les données en gérant les deux formats possibles (liste ou entier)
        fifo_trace = sync_result.get('fifo_trace', [])
        
        # Gérer le cas où partial_sales peut être un entier (count) ou une liste
        partial_sales_raw = sync_result.get('partial_sales', [])
        if isinstance(partial_sales_raw, int):
            partial_sales = []
            partial_count = partial_sales_raw
        else:
            partial_sales = partial_sales_raw
            partial_count = len(partial_sales)
        
        # Gérer le cas où rejected_sales peut être un entier (count) ou une liste
        rejected_sales_raw = sync_result.get('rejected_sales', [])
        if isinstance(rejected_sales_raw, int):
            rejected_sales = []
            rejected_count = rejected_sales_raw
        else:
            rejected_sales = rejected_sales_raw
            rejected_count = len(rejected_sales)
        
        # Gérer le cas où version_conflicts peut être un entier ou une liste
        version_conflicts_raw = sync_result.get('version_conflicts', [])
        if isinstance(version_conflicts_raw, int):
            version_conflicts = []
            version_conflicts_count = version_conflicts_raw
        else:
            version_conflicts = version_conflicts_raw
            version_conflicts_count = len(version_conflicts)
        
        # Récupérer les compteurs
        sales_exported = sync_result.get('sales_exported', 0)
        if isinstance(sales_exported, list):
            sales_exported = len(sales_exported)
        
        # Déterminer les avertissements et erreurs
        has_warnings = partial_count > 0 or version_conflicts_count > 0
        has_errors = rejected_count > 0
        
        # Construire le contenu
        content_controls = []
        
        # En-tête
        if has_errors:
            icon = ft.Icon(ft.Icons.ERROR, size=48, color=ft.Colors.RED)
            title = "⚠️ Synchronisation avec conflits"
            title_color = ft.Colors.RED
        elif has_warnings:
            icon = ft.Icon(ft.Icons.WARNING, size=48, color=ft.Colors.ORANGE)
            title = "⚠️ Synchronisation partielle"
            title_color = ft.Colors.ORANGE
        else:
            icon = ft.Icon(ft.Icons.CHECK_CIRCLE, size=48, color=ft.Colors.GREEN)
            title = "✅ Synchronisation réussie"
            title_color = ft.Colors.GREEN
        
        content_controls.extend([
            ft.Row([icon], alignment=ft.MainAxisAlignment.CENTER),
            ft.Text(title, size=18, weight=ft.FontWeight.BOLD, color=title_color),
            ft.Divider(),
        ])
        
        # Statistiques FIFO
        content_controls.append(
            ft.Text("📊 Traitement FIFO (First-In-First-Out)", 
                size=14, weight=ft.FontWeight.BOLD)
        )
        
        stats_row = ft.Row([
            ft.Container(
                content=ft.Column([
                    ft.Text("✅ Complètes", size=11),
                    ft.Text(str(sales_exported), 
                        size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                expand=True, padding=10, bgcolor=ft.Colors.GREEN_50, border_radius=8,
            ),
            ft.Container(
                content=ft.Column([
                    ft.Text("⚠️ Partielles", size=11),
                    ft.Text(str(partial_count), 
                        size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.ORANGE),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                expand=True, padding=10, bgcolor=ft.Colors.ORANGE_50, border_radius=8,
            ),
            ft.Container(
                content=ft.Column([
                    ft.Text("❌ Rejetées", size=11),
                    ft.Text(str(rejected_count), 
                        size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.RED),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                expand=True, padding=10, bgcolor=ft.Colors.RED_50, border_radius=8,
            ),
        ])
        content_controls.append(stats_row)
        
        # Trace FIFO par produit
        if fifo_trace and isinstance(fifo_trace, list) and len(fifo_trace) > 0:
            content_controls.append(ft.Divider())
            content_controls.append(
                ft.Text("📦 Détail du traitement FIFO par produit", 
                    size=13, weight=ft.FontWeight.BOLD)
            )
            
            for trace in fifo_trace[:5]:
                if isinstance(trace, dict):
                    product_container = ft.Container(
                        content=ft.Column([
                            ft.Text(f"🏷️ {trace.get('product_name', 'Inconnu')}", size=12, weight=ft.FontWeight.BOLD),
                            ft.Text(f"Stock serveur initial: {trace.get('initial_stock', 0)} unités", size=11),
                            ft.Text(f"Ventes en attente: {trace.get('sales_count', 0)} (total demandé: {trace.get('total_requested', 0)})", size=11),
                            ft.ProgressBar(value=min(1.0, trace.get('initial_stock', 0) / max(1, trace.get('total_requested', 1))), 
                                        height=5, color=ft.Colors.BLUE),
                        ], spacing=3),
                        padding=8, bgcolor=ft.Colors.GREY_50, border_radius=8, margin=ft.Margin.only(bottom=5)
                    )
                    content_controls.append(product_container)
            
            if len(fifo_trace) > 5:
                content_controls.append(
                    ft.Text(f"... et {len(fifo_trace) - 5} autres produits", 
                        size=11, color=ft.Colors.GREY_500)
                )
        
        # Ventes partielles
        if partial_sales and isinstance(partial_sales, list) and len(partial_sales) > 0:
            content_controls.append(ft.Divider())
            content_controls.append(
                ft.Text("⚠️ Ventes partiellement acceptées", 
                    size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.ORANGE)
            )
            
            for sale in partial_sales[:5]:
                if isinstance(sale, dict):
                    partial_card = ft.Container(
                        content=ft.Column([
                            ft.Text(f"📦 {sale.get('product_name', 'Inconnu')}", size=12, weight=ft.FontWeight.BOLD),
                            ft.Text(f"Demandé: {sale.get('requested_quantity', 0)} | Accepté: {sale.get('accepted_quantity', 0)} | Rejeté: {sale.get('rejected_quantity', 0)}", size=11),
                            ft.Text(f"📝 {sale.get('reason', '')[:80]}", size=10, color=ft.Colors.GREY_600),
                            ft.Text(f"Stock serveur: {sale.get('server_stock', '?')} | Stock local connu: {sale.get('local_stock', '?')}", 
                                size=10, color=ft.Colors.BLUE_600),
                        ], spacing=3),
                        padding=8, bgcolor=ft.Colors.ORANGE_50, border_radius=8, margin=ft.Margin.only(bottom=5)
                    )
                    content_controls.append(partial_card)
        
        # Ventes rejetées
        if rejected_sales and isinstance(rejected_sales, list) and len(rejected_sales) > 0:
            content_controls.append(ft.Divider())
            content_controls.append(
                ft.Text("❌ Ventes rejetées", 
                    size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.RED)
            )
            
            for sale in rejected_sales[:5]:
                if isinstance(sale, dict):
                    rejected_card = ft.Container(
                        content=ft.Column([
                            ft.Text(f"📦 {sale.get('product_name', 'Inconnu')}", size=12, weight=ft.FontWeight.BOLD),
                            ft.Text(f"Quantité demandée: {sale.get('requested_quantity', 0)}", size=11),
                            ft.Text(f"📝 {sale.get('reason', '')[:100]}", size=10, color=ft.Colors.RED_400),
                        ], spacing=3),
                        padding=8, bgcolor=ft.Colors.RED_50, border_radius=8, margin=ft.Margin.only(bottom=5)
                    )
                    content_controls.append(rejected_card)
        
        # Conflits de version
        if version_conflicts and isinstance(version_conflicts, list) and len(version_conflicts) > 0:
            content_controls.append(ft.Divider())
            content_controls.append(
                ft.Text("🔄 Conflits de version résolus", 
                    size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE)
            )
            
            for conflict in version_conflicts[:3]:
                if isinstance(conflict, dict):
                    conflict_card = ft.Container(
                        content=ft.Column([
                            ft.Text(f"🏷️ {conflict.get('product_name', 'Inconnu')}", size=12, weight=ft.FontWeight.BOLD),
                            ft.Text(f"Version locale: v{conflict.get('local_version', 0)} | Version serveur: v{conflict.get('server_version', 0)}", size=10),
                            ft.Text(f"Quantité locale: {conflict.get('local_quantity', 0)} | Quantité serveur: {conflict.get('server_quantity', 0)}", size=10),
                            ft.Text(f"✅ Résolution: {conflict.get('resolution', 'serveur gagnant')}", size=10, color=ft.Colors.GREEN),
                        ], spacing=3),
                        padding=8, bgcolor=ft.Colors.BLUE_50, border_radius=8, margin=ft.Margin.only(bottom=5)
                    )
                    content_controls.append(conflict_card)
        
        # Footer
        content_controls.append(ft.Divider())
        sync_date = sync_result.get('sync_date', datetime.now().isoformat())
        content_controls.append(
            ft.Text(f"Synchronisation du {str(sync_date)[:19]}", 
                size=10, color=ft.Colors.GREY_500)
        )
        
        dialog = ft.AlertDialog(
            title=ft.Text("Résumé de la synchronisation", size=18, weight=ft.FontWeight.BOLD),
            content=ft.Container(
                content=ft.Column(content_controls, spacing=10, scroll=ft.ScrollMode.AUTO),
                width=500, height=500
            ),
            actions=[
                ft.TextButton("Fermer", on_click=lambda e: self._close_dialog(dialog)),
                ft.ElevatedButton("Voir les produits", on_click=lambda e: self._view_products_with_conflicts()),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()