"""
Écran de synchronisation style WhatsApp avec Flet - Version Stable
Sans scroll_to_async qui n'existe pas dans cette version de Flet
"""

import flet as ft
from datetime import datetime
import asyncio
from typing import Dict, List, Optional, Callable
import logging

logger = logging.getLogger(__name__)


class SyncMessage:
    """Représente un message de synchronisation"""
    
    def __init__(self, key: str, title: str, icon: str, status: str = "pending", details: str = ""):
        self.key = key
        self.title = title
        self.icon = icon
        self.status = status
        self.details = details
        self.timestamp = datetime.now()
        self.retry_count = 0
        self.result_data = None


class SyncScreen:
    """Écran de synchronisation style WhatsApp"""
    
    SYNC_ITEMS = [
        {"key": "branch", "title": "Branche utilisateur", "icon": "🏢", "priority": 1},
        {"key": "subscription", "title": "Abonnement", "icon": "📅", "priority": 2},
        {"key": "products", "title": "Produits", "icon": "📦", "priority": 3},
        {"key": "sales", "title": "Ventes", "icon": "💰", "priority": 4},
        {"key": "expenses", "title": "Dépenses", "icon": "📉", "priority": 5},
        {"key": "returns", "title": "Retours", "icon": "🔄", "priority": 6},
        {"key": "debts", "title": "Dettes", "icon": "💳", "priority": 7},
    ]
    
    def __init__(
        self, 
        page: ft.Page, 
        db_manager, 
        sync_service, 
        auth_service,
        on_back: Optional[Callable] = None
    ):
        self.page = page
        self.db = db_manager
        self.sync_service = sync_service
        self.auth_service = auth_service
        self.on_back = on_back
        
        self.messages: List[SyncMessage] = []
        self.message_containers: Dict[str, ft.Container] = {}
        self.is_syncing = False
        self.stop_monitoring = False
        self.last_online_status = None
        self._monitor_task = None
        
        self.setup_ui()
        self.start_monitoring()
        self.load_existing_messages()
        
        # Démarrer la vérification initiale
        self.page.run_task(self.check_online_and_sync)
    
    def setup_ui(self):
        """Configure l'interface utilisateur"""
        
        back_button = ft.IconButton(
            icon=ft.Icons.ARROW_BACK,
            icon_color=ft.Colors.GREEN_800,
            on_click=self.go_back,
            tooltip="Retour",
        )
        
        self.header = ft.Container(
            content=ft.Row(
                [
                    back_button,
                    ft.Icon(ft.Icons.SYNC, color=ft.Colors.GREEN_400, size=28),
                    ft.Text("Synchronisation", size=22, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_800),
                    ft.Container(expand=True),
                    ft.Row(
                        [
                            ft.Container(
                                width=12,
                                height=12,
                                bgcolor=ft.Colors.GREY_400,
                                border_radius=6,
                            ),
                            ft.Text("Hors ligne", size=12, color=ft.Colors.GREY_600),
                        ],
                        spacing=5,
                    ),
                ],
                alignment=ft.MainAxisAlignment.START,
                spacing=10,
            ),
            padding=ft.Padding.all(15),
            bgcolor=ft.Colors.WHITE,
            border=ft.Border.all(color=ft.Colors.GREY_200),
        )
        
        self.messages_list = ft.ListView(
            spacing=8,
            padding=ft.Padding.symmetric(horizontal=10, vertical=10),
            expand=True,
        )
        
        self.footer = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.CLOUD_SYNC, color=ft.Colors.BLUE_400, size=20),
                    ft.Text("Prêt", size=12, color=ft.Colors.GREEN_600),
                    ft.Container(expand=True),
                    ft.ProgressRing(width=20, height=20, visible=False),
                    ft.ElevatedButton(
                        "Actualiser tout",
                        icon=ft.Icons.REFRESH,
                        on_click=self.force_full_sync,
                        style=ft.ButtonStyle(
                            color=ft.Colors.WHITE,
                            bgcolor=ft.Colors.GREEN_500,
                        ),
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            padding=ft.Padding.all(12),
            bgcolor=ft.Colors.GREY_50,
            border=ft.Border.all(color=ft.Colors.GREY_200),
        )
        
        self.content = ft.Column(
            [self.header, self.messages_list, self.footer],
            spacing=0,
            expand=True,
        )
        
        self.online_indicator = self.header.content.controls[4].controls[0]
        self.online_label = self.header.content.controls[4].controls[1]
        self.progress_ring = self.footer.content.controls[3]
        self.sync_status_label = self.footer.content.controls[1]
    
    def go_back(self, e):
        """Retourne à l'écran précédent"""
        self.stop_monitoring = True
        if self._monitor_task:
            self._monitor_task.cancel()
        if self.on_back:
            self.on_back()
        else:
            self.page.go("/dashboard")
    
    def update_online_status(self, is_online: bool):
        """Met à jour l'indicateur de connexion"""
        color = ft.Colors.GREEN_400 if is_online else ft.Colors.GREY_400
        text = "En ligne" if is_online else "Hors ligne"
        text_color = ft.Colors.GREEN_600 if is_online else ft.Colors.GREY_600
        
        if hasattr(self, 'online_indicator') and self.online_indicator:
            self.online_indicator.bgcolor = color
        if hasattr(self, 'online_label') and self.online_label:
            self.online_label.value = text
            self.online_label.color = text_color
        
        if hasattr(self, 'sync_status_label') and self.sync_status_label:
            if is_online:
                self.sync_status_label.value = "Connecté"
                self.sync_status_label.color = ft.Colors.GREEN_600
            else:
                self.sync_status_label.value = "Hors ligne - En attente"
                self.sync_status_label.color = ft.Colors.ORANGE_600
        
        self.page.update()
    
    def load_existing_messages(self):
        """Charge les messages existants"""
        for item in self.SYNC_ITEMS:
            message = SyncMessage(
                key=item["key"],
                title=item["title"],
                icon=item["icon"],
                status="pending",
                details="En attente de synchronisation"
            )
            self.messages.append(message)
            self.add_message_widget(message)
    
    def get_status_color(self, status: str) -> str:
        colors = {
            "pending": ft.Colors.GREY_100,
            "syncing": ft.Colors.BLUE_50,
            "success": ft.Colors.GREEN_50,
            "error": ft.Colors.RED_50,
            "partial": ft.Colors.ORANGE_50,
        }
        return colors.get(status, ft.Colors.GREY_100)
    
    def add_message_widget(self, message: SyncMessage):
        """Ajoute un widget de message style WhatsApp"""
        
        content_column = ft.Column(
            [
                ft.Row(
                    [
                        ft.Text(f"{message.icon} ", size=16),
                        ft.Text(message.title, size=14, weight=ft.FontWeight.BOLD),
                        ft.Container(expand=True),
                        ft.Text(message.timestamp.strftime("%H:%M"), size=10, color=ft.Colors.GREY_500),
                    ],
                    alignment=ft.MainAxisAlignment.START,
                ),
                ft.Text(message.details, size=12, color=ft.Colors.GREY_700),
            ],
            spacing=5,
        )
        
        if message.status == "success":
            content_column.controls.append(
                ft.Row([ft.Container(expand=True), ft.Text("✓✓", size=12, color=ft.Colors.GREEN_500)])
            )
        elif message.status == "syncing":
            content_column.controls.append(
                ft.Row([ft.Container(expand=True), ft.Text("⏳ Envoi...", size=11, color=ft.Colors.BLUE_400, italic=True)])
            )
        
        if message.status == "error":
            retry_button = ft.ElevatedButton(
                "Réessayer",
                icon=ft.Icons.REFRESH,
                on_click=lambda e, m=message: self.run_retry_sync_item(m),
                style=ft.ButtonStyle(color=ft.Colors.RED_500, bgcolor=ft.Colors.TRANSPARENT),
                height=30,
            )
            content_column.controls.append(
                ft.Row([ft.Container(expand=True), retry_button], alignment=ft.MainAxisAlignment.END)
            )
        
        bubble = ft.Container(
            content=content_column,
            bgcolor=self.get_status_color(message.status),
            border_radius=ft.BorderRadius.all(12),
            padding=ft.Padding.all(12),
            width=400,
        )
        
        message_container = ft.Container(
            content=bubble,
            margin=ft.Margin.only(left=40 if message.status == "success" else 10, right=10),
            alignment=ft.Alignment.CENTER_RIGHT if message.status == "success" else ft.Alignment.CENTER_LEFT,
        )
        
        self.message_containers[message.key] = message_container
        self.messages_list.controls.append(message_container)
        self.page.update()
    
    def update_message_widget(self, message: SyncMessage):
        """Met à jour un widget de message existant"""
        if message.key not in self.message_containers:
            self.add_message_widget(message)
            return
        
        container = self.message_containers[message.key]
        
        new_content = ft.Column(
            [
                ft.Row(
                    [
                        ft.Text(f"{message.icon} ", size=16),
                        ft.Text(message.title, size=14, weight=ft.FontWeight.BOLD),
                        ft.Container(expand=True),
                        ft.Text(message.timestamp.strftime("%H:%M"), size=10, color=ft.Colors.GREY_500),
                    ],
                    alignment=ft.MainAxisAlignment.START,
                ),
                ft.Text(message.details, size=12, color=ft.Colors.GREY_700),
            ],
            spacing=5,
        )
        
        if message.status == "success":
            new_content.controls.append(
                ft.Row([ft.Container(expand=True), ft.Text("✓✓", size=12, color=ft.Colors.GREEN_500)])
            )
        elif message.status == "syncing":
            new_content.controls.append(
                ft.Row([ft.Container(expand=True), ft.Text("⏳ Envoi...", size=11, color=ft.Colors.BLUE_400, italic=True)])
            )
        
        if message.status == "error":
            retry_btn = ft.ElevatedButton(
                "Réessayer",
                icon=ft.Icons.REFRESH,
                on_click=lambda e, m=message: self.run_retry_sync_item(m),
                style=ft.ButtonStyle(color=ft.Colors.RED_500, bgcolor=ft.Colors.TRANSPARENT),
                height=30,
            )
            new_content.controls.append(ft.Row([ft.Container(expand=True), retry_btn], alignment=ft.MainAxisAlignment.END))
        
        container.content = ft.Container(
            content=new_content,
            bgcolor=self.get_status_color(message.status),
            border_radius=ft.BorderRadius.all(12),
            padding=ft.Padding.all(12),
            width=400,
        )
        container.margin = ft.Margin.only(left=40 if message.status == "success" else 10, right=10)
        container.alignment = ft.Alignment.CENTER_RIGHT if message.status == "success" else ft.Alignment.CENTER_LEFT
        
        # Simple mise à jour sans scroll automatique (évite l'erreur)
        self.page.update()
    
    def start_monitoring(self):
        """Démarre la surveillance de connexion asynchrone"""
        async def monitor():
            while not self.stop_monitoring:
                try:
                    # Vérification asynchrone de la connexion
                    is_online = await self._check_internet_async()
                    
                    self.update_online_status(is_online)
                    
                    if is_online and not self.last_online_status and not self.is_syncing:
                        await asyncio.sleep(2)
                        await self.auto_sync_all()
                    
                    self.last_online_status = is_online
                    await asyncio.sleep(3)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Erreur monitoring: {e}")
                    await asyncio.sleep(5)
        
        self._monitor_task = self.page.run_task(monitor)
    
    async def _check_internet_async(self) -> bool:
        """Vérification asynchrone de la connexion internet"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, 
            self.sync_service.check_internet_connection
        )
    
    async def check_online_and_sync(self):
        """Vérifie la connexion et synchronise si possible"""
        is_online = await self._check_internet_async()
        if is_online and not self.is_syncing:
            await self.auto_sync_all()
    
    async def auto_sync_all(self):
        """Synchronisation automatique asynchrone"""
        if self.is_syncing:
            return
        
        for message in self.messages:
            if message.status == "success":
                message.status = "pending"
                message.details = "En attente de synchronisation"
                message.result_data = None
                self.update_message_widget(message)
        
        await self.start_sync(force=False)
    
    async def force_full_sync(self, e=None):
        """Synchronisation forcée asynchrone"""
        if self.is_syncing:
            self.show_snackbar("Une synchronisation est déjà en cours...", ft.Colors.ORANGE)
            return
        
        def confirm_yes(e):
            for message in self.messages:
                message.status = "pending"
                message.details = "En attente de synchronisation forcée..."
                message.result_data = None
                self.update_message_widget(message)
            self.page.run_task(self.start_sync, True)
            dlg.open = False
            self.page.update()
        
        def confirm_no(e):
            dlg.open = False
            self.page.update()
        
        dlg = ft.AlertDialog(
            title=ft.Text("Synchronisation forcée"),
            content=ft.Text("⚠️ La synchronisation forcée va ignorer les conflits et forcer la mise à jour.\nContinuer ?"),
            actions=[
                ft.TextButton("Oui", on_click=confirm_yes),
                ft.TextButton("Non", on_click=confirm_no),
            ],
        )
        self.page.dialog = dlg
        dlg.open = True
        self.page.update()
    
    async def start_sync(self, force: bool = False):
        """Démarre le processus de synchronisation asynchrone"""
        if self.is_syncing:
            return
        
        self.is_syncing = True
        self.progress_ring.visible = True
        self.sync_status_label.value = "Synchronisation en cours..."
        self.sync_status_label.color = ft.Colors.ORANGE_600
        self.page.update()
        
        await self._sync_worker(force)
    
    async def _sync_worker(self, force: bool = False):
        """Worker de synchronisation asynchrone"""
        try:
            # Vérifier la connexion
            if not await self._check_internet_async():
                await self._sync_finished(False, "Pas de connexion internet")
                return
            
            # 1. Branche
            await self._update_message_status("branch", "syncing", "Synchronisation de la branche...")
            branch_result = await self._sync_branch_async()
            if branch_result.get("success"):
                if branch_result.get("up_to_date") or branch_result.get("message") == "Déjà à jour":
                    await self._update_message_status("branch", "success", "✅ Déjà à jour", branch_result)
                else:
                    await self._update_message_status("branch", "success", "Branche synchronisée", branch_result)
            else:
                await self._update_message_status("branch", "error", branch_result.get("error", "Erreur"))
            
            # 2. Abonnement
            await self._update_message_status("subscription", "syncing", "Vérification de l'abonnement...")
            sub_result = await self._sync_subscription_async()
            if sub_result.get("success"):
                if sub_result.get("up_to_date") or sub_result.get("message") == "Déjà à jour":
                    await self._update_message_status("subscription", "success", "✅ Déjà à jour", sub_result)
                else:
                    await self._update_message_status("subscription", "success", "Abonnement valide", sub_result)
            else:
                await self._update_message_status("subscription", "error", sub_result.get("error", "Erreur"))
            
            # 3. Produits
            await self._update_message_status("products", "syncing", "Import des produits...")
            products_result = await self._sync_products_async(force)
            if products_result.get("success"):
                if products_result.get("up_to_date") or products_result.get("message") == "Déjà à jour":
                    await self._update_message_status("products", "success", "✅ Déjà à jour", products_result)
                else:
                    count = products_result.get("count", 0)
                    await self._update_message_status("products", "success", f"{count} produits importés", products_result)
            else:
                await self._update_message_status("products", "error", products_result.get("error", "Erreur"))
            
            # 4. Ventes
            await self._update_message_status("sales", "syncing", "Export des ventes...")
            sales_result = await self._sync_sales_async(force)
            if sales_result.get("success"):
                if sales_result.get("up_to_date") or sales_result.get("message") == "Déjà à jour":
                    await self._update_message_status("sales", "success", "✅ Déjà à jour", sales_result)
                else:
                    count = sales_result.get("count", 0)
                    await self._update_message_status("sales", "success", f"{count} ventes exportées", sales_result)
            else:
                await self._update_message_status("sales", "error", sales_result.get("error", "Erreur"))
            
            # 5. Dépenses
            await self._update_message_status("expenses", "syncing", "Export des dépenses...")
            expenses_result = await self._sync_expenses_async(force)
            if expenses_result.get("success"):
                if expenses_result.get("up_to_date") or expenses_result.get("message") == "Déjà à jour":
                    await self._update_message_status("expenses", "success", "✅ Déjà à jour", expenses_result)
                else:
                    count = expenses_result.get("count", 0)
                    await self._update_message_status("expenses", "success", f"{count} dépenses exportées", expenses_result)
            else:
                await self._update_message_status("expenses", "error", expenses_result.get("error", "Erreur"))
            
            # 6. Retours
            await self._update_message_status("returns", "syncing", "Export des retours...")
            returns_result = await self._sync_returns_async()
            if returns_result.get("success"):
                if returns_result.get("up_to_date") or returns_result.get("message") == "Déjà à jour":
                    await self._update_message_status("returns", "success", "✅ Déjà à jour", returns_result)
                else:
                    count = returns_result.get("count", 0)
                    await self._update_message_status("returns", "success", f"{count} retours exportés", returns_result)
            else:
                await self._update_message_status("returns", "error", returns_result.get("error", "Erreur"))
            
            # 7. Dettes
            await self._update_message_status("debts", "syncing", "Export des dettes...")
            debts_result = await self._sync_debts_async()
            if debts_result.get("success"):
                if debts_result.get("up_to_date") or debts_result.get("message") == "Déjà à jour":
                    await self._update_message_status("debts", "success", "✅ Déjà à jour", debts_result)
                else:
                    count = debts_result.get("count", 0)
                    await self._update_message_status("debts", "success", f"{count} dettes exportées", debts_result)
            else:
                await self._update_message_status("debts", "error", debts_result.get("error", "Erreur"))
            
            await self._sync_finished(True, "Synchronisation terminée")
            
        except Exception as e:
            logger.error(f"Erreur synchronisation: {e}")
            await self._sync_finished(False, str(e))
    
    async def _update_message_status(self, key: str, status: str, details: str, result_data: Dict = None):
        """Met à jour le statut d'un message de façon asynchrone"""
        for message in self.messages:
            if message.key == key:
                message.status = status
                message.details = details
                if result_data:
                    message.result_data = result_data
                self.update_message_widget(message)
                await asyncio.sleep(0.3)
                return
    
    async def _run_sync_operation(self, func, *args, **kwargs):
        """Exécute une opération de synchronisation dans un thread séparé"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))
    
    async def _sync_branch_async(self) -> Dict:
        """Synchronise la branche de l'utilisateur"""
        try:
            result = await self._run_sync_operation(self.auth_service.sync_user_branch_from_server)
            
            # Si aucune modification n'a été faite
            if result.get('success') and result.get('branch_id'):
                # Vérifier si des changements ont été détectés
                if result.get('changed', False) is False:
                    return {"success": True, "message": "Déjà à jour", "up_to_date": True}
            
            return result if result else {"success": False, "error": "Erreur inconnue"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _sync_subscription_async(self) -> Dict:
        """Synchronise l'abonnement depuis le serveur"""
        try:
            result = await self._run_sync_operation(self.sync_service.import_subscription)
            
            # Vérifier si l'abonnement est déjà à jour (cached)
            if result and result.get('cached', False):
                return {
                    "success": True, 
                    "message": "Déjà à jour", 
                    "up_to_date": True,
                    "cached": True
                }
            
            if not result:
                return {"success": False, "error": "Aucune réponse du serveur"}
            
            if isinstance(result, dict):
                if result.get("success") or result.get("subscription") is not None:
                    # Vérifier si aucune modification
                    if result.get("up_to_date", False):
                        return {"success": True, "message": "Déjà à jour", "up_to_date": True}
                    
                    return {
                        "success": True,
                        "is_active": result.get("is_active", True),
                        "has_subscription": result.get("has_subscription", True),
                        "days_remaining": result.get("days_remaining", 30),
                        "plan_name": result.get("plan_name", "Standard"),
                        "access_mode": result.get("access_mode", "full")
                    }
                elif result.get("error"):
                    return {"success": False, "error": result.get("error")}
            
            # Succès par défaut
            return {
                "success": True,
                "is_active": True,
                "has_subscription": True,
                "days_remaining": 30,
                "plan_name": "Standard"
            }
            
        except Exception as e:
            logger.error(f"Erreur synchronisation abonnement: {e}")
            return {
                "success": True,
                "is_active": True,
                "has_subscription": True,
                "days_remaining": 30,
                "plan_name": "Standard",
                "warning": str(e)
            }

    async def _sync_products_async(self, force: bool = False) -> Dict:
        """Importe les produits depuis le serveur"""
        try:
            user = self.auth_service.get_current_user()
            branch_id = user.get('active_branch_id') or user.get('branch_id')
            
            # D'abord, vérifier combien de produits sont déjà à jour
            local_products_count = 0
            server_products_count = 0
            
            try:
                # Compter les produits locaux
                local_products = self.db.get_all_products(branch_id)
                local_products_count = len(local_products) if local_products else 0
            except:
                pass
            
            result = await self._run_sync_operation(
                self.sync_service.import_products_improved, branch_id
            )
            
            if result and result.get("success"):
                imported_count = result.get("count", 0)
                total_products = result.get("total_products", 0)
                
                # Si aucun produit n'a été importé ET qu'il n'y a pas d'erreur
                if imported_count == 0:
                    # Vérifier si c'est parce que tout est déjà à jour
                    if total_products == 0:
                        return {
                            "success": True, 
                            "message": "Aucun produit trouvé", 
                            "count": 0
                        }
                    elif local_products_count > 0 and total_products == local_products_count:
                        return {
                            "success": True, 
                            "message": "Déjà à jour", 
                            "up_to_date": True,
                            "count": 0
                        }
                
                return {
                    "success": True,
                    "count": imported_count,
                    "total_products": total_products,
                    "message": f"{imported_count} produit(s) importé(s)"
                }
            
            return result if result else {"success": False, "error": "Erreur inconnue"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _sync_sales_async(self, force: bool = False) -> Dict:
        """Exporte les ventes vers le serveur"""
        try:
            # D'abord, vérifier combien de ventes non synchronisées
            pending_count = 0
            try:
                unsynced = self.db.get_unsynced_sales()
                pending_count = len(unsynced) if unsynced else 0
            except:
                pass
            
            if pending_count == 0:
                return {
                    "success": True, 
                    "message": "Déjà à jour", 
                    "up_to_date": True,
                    "count": 0
                }
            
            if force:
                result = await self._run_sync_operation(self.sync_service.export_sales_force_stock, force=True)
            else:
                result = await self._run_sync_operation(self.sync_service.export_sales)
            
            if result:
                exported_count = result.get("count", 0)
                if exported_count == 0 and pending_count > 0:
                    # Il y avait des ventes mais aucune n'a été exportée
                    return {
                        "success": False,
                        "error": result.get("error", "Échec de l'export"),
                        "count": 0,
                        "pending": pending_count
                    }
                return result
            
            return {"success": False, "error": "Erreur inconnue", "count": 0}
        except Exception as e:
            return {"success": False, "error": str(e), "count": 0}

    async def _sync_expenses_async(self, force: bool = False) -> Dict:
        """Exporte les dépenses vers le serveur"""
        try:
            # D'abord, vérifier combien de dépenses non synchronisées
            pending_count = 0
            try:
                unsynced = self.db.get_unsynced_expenses() if hasattr(self.db, 'get_unsynced_expenses') else []
                pending_count = len(unsynced) if unsynced else 0
            except:
                pass
            
            if pending_count == 0:
                return {
                    "success": True, 
                    "message": "Déjà à jour", 
                    "up_to_date": True,
                    "count": 0
                }
            
            result = await self._run_sync_operation(self.sync_service.export_expenses)
            
            if result:
                exported_count = result.get("count", 0)
                if exported_count == 0 and pending_count > 0:
                    return {
                        "success": False,
                        "error": result.get("error", "Échec de l'export"),
                        "count": 0,
                        "pending": pending_count
                    }
                return result
            
            return {"success": False, "error": "Erreur inconnue", "count": 0}
        except Exception as e:
            return {"success": False, "error": str(e), "count": 0}

    async def _sync_returns_async(self) -> Dict:
        """Exporte les retours vers le serveur"""
        try:
            # Vérifier s'il y a des retours à synchroniser
            pending_count = 0
            try:
                unsynced = self.db.get_unsynced_returns() if hasattr(self.db, 'get_unsynced_returns') else []
                pending_count = len(unsynced) if unsynced else 0
            except:
                pass
            
            if pending_count == 0:
                return {
                    "success": True, 
                    "message": "Déjà à jour", 
                    "up_to_date": True,
                    "count": 0
                }
            
            result = await self._run_sync_operation(self.sync_service.export_returns)
            
            if result:
                exported_count = result.get("count", 0)
                if exported_count == 0 and pending_count > 0:
                    return {
                        "success": False,
                        "error": result.get("error", "Échec de l'export"),
                        "count": 0
                    }
                return result
            
            return {"success": False, "error": "Erreur inconnue", "count": 0}
        except Exception as e:
            return {"success": False, "error": str(e), "count": 0}

    async def _sync_debts_async(self) -> Dict:
        """Exporte les dettes vers le serveur"""
        try:
            # Vérifier s'il y a des dettes à synchroniser
            pending_count = 0
            try:
                unsynced = self.db.get_unsynced_debts() if hasattr(self.db, 'get_unsynced_debts') else []
                pending_count = len(unsynced) if unsynced else 0
            except:
                pass
            
            if pending_count == 0:
                return {
                    "success": True, 
                    "message": "Déjà à jour", 
                    "up_to_date": True,
                    "count": 0
                }
            
            result = await self._run_sync_operation(self.sync_service.export_debts)
            
            if result:
                exported_count = result.get("count", 0)
                if exported_count == 0 and pending_count > 0:
                    return {
                        "success": False,
                        "error": result.get("error", "Échec de l'export"),
                        "count": 0
                    }
                return result
            
            return {"success": False, "error": "Erreur inconnue", "count": 0}
        except Exception as e:
            return {"success": False, "error": str(e), "count": 0}
    
    def run_retry_sync_item(self, message: SyncMessage):
        """Wrapper pour appeler retry_sync_item depuis un callback synchrone"""
        self.page.run_task(self.retry_sync_item, message)
    
    async def retry_sync_item(self, message: SyncMessage):
        """Réessaie la synchronisation d'un élément de façon asynchrone"""
        if self.is_syncing:
            return
        
        message.retry_count += 1
        message.status = "syncing"
        message.details = f"Tentative {message.retry_count}..."
        self.update_message_widget(message)
        
        try:
            if not await self._check_internet_async():
                await self._update_message_status(message.key, "error", "Pas de connexion internet")
                return
            
            result = None
            if message.key == "branch":
                result = await self._sync_branch_async()
            elif message.key == "subscription":
                result = await self._sync_subscription_async()
            elif message.key == "products":
                result = await self._sync_products_async(True)
            elif message.key == "sales":
                result = await self._sync_sales_async(True)
            elif message.key == "expenses":
                result = await self._sync_expenses_async(True)
            elif message.key == "returns":
                result = await self._sync_returns_async()
            elif message.key == "debts":
                result = await self._sync_debts_async()
            
            if result and result.get("success"):
                await self._update_message_status(message.key, "success", "Synchronisation réussie", result)
            else:
                error = result.get("error", "Erreur") if result else "Erreur inconnue"
                await self._update_message_status(message.key, "error", error)
                
        except Exception as e:
            await self._update_message_status(message.key, "error", str(e))
    
    async def _sync_finished(self, success: bool, message: str):
        """Termine la synchronisation"""
        self.is_syncing = False
        self.progress_ring.visible = False
        
        if success:
            self.sync_status_label.value = "Synchronisé"
            self.sync_status_label.color = ft.Colors.GREEN_600
            if hasattr(self.auth_service, 'update_last_sync'):
                self.auth_service.update_last_sync(datetime.now().isoformat())
        else:
            self.sync_status_label.value = f"⚠️ {message}"
            self.sync_status_label.color = ft.Colors.ORANGE_600
        
        self.page.update()
        self.show_snackbar(message, ft.Colors.GREEN_600 if success else ft.Colors.RED_600)
    
    def show_snackbar(self, message: str, color: str):
        """Affiche un snackbar"""
        snack_bar = ft.SnackBar(
            content=ft.Text(message),
            bgcolor=color,
            duration=3000,
        )
        self.page.snack_bar = snack_bar
        snack_bar.open = True
        self.page.update()
    
    def show(self):
        """Affiche l'écran de synchronisation"""
        self.page.clean()
        self.page.add(self.content)
        self.page.update()
    
    def on_close(self):
        """Ferme l'écran proprement"""
        self.stop_monitoring = True
        if self._monitor_task:
            self._monitor_task.cancel()