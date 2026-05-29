# utils/subscription_blocker.py
"""
Gestionnaire de blocage d'interface basé sur l'état de l'abonnement.
Version Flet pour application mobile.
"""

from functools import wraps
from typing import Callable, Optional, Any, Tuple
import logging
import threading
from datetime import datetime

import flet as ft

logger = logging.getLogger(__name__)


class SubscriptionBlocker:
    """
    Gestionnaire de blocage d'interface basé sur l'état de l'abonnement.
    Version Flet pour application mobile.
    """
    
    def __init__(self, sync_service, page: ft.Page = None):
        self.sync_service = sync_service
        self.page = page
        self._blocked_until_sync = False
        self._last_check = None
        self._blocker_dialog = None
        self._blocker_view = None
        self._blocker_container = None  # Pour stocker le conteneur du bloqueur
    
    def is_blocked(self, feature: str = None) -> Tuple[bool, Optional[str], Optional[dict]]:
        """
        Vérifie si l'interface doit être bloquée.
        
        Args:
            feature: Fonctionnalité spécifique à vérifier
        
        Returns:
            (est_bloque, block_type, details)
        """
        # ✅ Vérifier que sync_service existe
        if self.sync_service is None:
            logger.warning("sync_service est None dans is_blocked")
            return True, "access_limited", {
                "title": "⚠️ SERVICE INDISPONIBLE",
                "message": "Service de synchronisation non disponible. Veuillez redémarrer l'application.",
                "action": "restart"
            }
        
        # ✅ Vérifier que auth_service existe dans sync_service
        if not hasattr(self.sync_service, 'auth_service') or self.sync_service.auth_service is None:
            logger.warning("auth_service est None dans sync_service")
            return True, "access_limited", {
                "title": "⚠️ AUTHENTIFICATION REQUISE",
                "message": "Service d'authentification non disponible. Veuillez vous reconnecter.",
                "action": "logout"
            }
        
        # Vérifier l'abonnement
        try:
            access = self.sync_service.check_subscription_access(feature)
        except Exception as e:
            logger.error(f"Erreur check_subscription_access: {e}")
            return True, "access_limited", {
                "title": "⚠️ ERREUR DE VÉRIFICATION",
                "message": f"Impossible de vérifier l'abonnement: {str(e)}",
                "action": "sync"
            }
        
        # Vérifier que access n'est pas None
        if access is None or not isinstance(access, dict):
            logger.warning("check_subscription_access a retourné None ou invalide")
            return True, "access_limited", {
                "title": "⚠️ ACCÈS LIMITÉ",
                "message": "Impossible de vérifier l'abonnement. Veuillez synchroniser.",
                "action": "sync"
            }
        
        if not access.get("has_access", False):
            reason = access.get("reason", "Accès non autorisé")
            
            # Si l'abonnement est expiré, bloquer complètement
            if not access.get("is_active", False):
                subscription = access.get("subscription", {})
                days_remaining = subscription.get("days_remaining", 0) if isinstance(subscription, dict) else 0
                return True, "subscription_expired", {
                    "title": "⛔ ABONNEMENT EXPIRÉ",
                    "message": reason,
                    "days_remaining": days_remaining,
                    "action": "sync"
                }
            
            # Si limite de produits atteinte
            if access.get("products_limit_exceeded"):
                limits = access.get("limits", {})
                max_products = limits.get("max_products", "inconnue") if isinstance(limits, dict) else "inconnue"
                usage_data = access.get("usage", {})
                current_products = usage_data.get("current_products", 0) if isinstance(usage_data, dict) else 0
                return True, "products_limit", {
                    "title": "⚠️ LIMITE DE PRODUITS ATTEINTE",
                    "message": f"Vous avez atteint la limite de {max_products} produits.\n\nActuellement: {current_products}/{max_products}",
                    "action": "upgrade"
                }
            
            # Si limite d'utilisateurs atteinte
            if access.get("users_limit_exceeded"):
                limits = access.get("limits", {})
                max_users = limits.get("max_users", "inconnue") if isinstance(limits, dict) else "inconnue"
                usage_data = access.get("usage", {})
                current_users = usage_data.get("current_users", 0) if isinstance(usage_data, dict) else 0
                return True, "users_limit", {
                    "title": "⚠️ LIMITE D'UTILISATEURS ATTEINTE",
                    "message": f"Vous avez atteint la limite de {max_users} utilisateurs.\n\nActuellement: {current_users}/{max_users}",
                    "action": "upgrade"
                }
            
            if reason:
                return True, "access_limited", {
                    "title": "⚠️ ACCÈS LIMITÉ",
                    "message": reason,
                    "action": None
                }
        
        return False, None, None
    
    def require_subscription(self, feature: str = None, on_blocked: Callable = None):
        """Décorateur pour bloquer une fonction si l'abonnement n'est pas actif."""
        def decorator(func: Callable):
            @wraps(func)
            def wrapper(*args, **kwargs):
                is_blocked, block_type, details = self.is_blocked(feature)
                
                if is_blocked:
                    logger.warning(f"Accès bloqué à {func.__name__}: {details.get('title')}")
                    
                    if on_blocked:
                        return on_blocked(block_type, details)
                    
                    # Afficher le dialogue de blocage
                    self.show_blocker_dialog(details)
                    return None
                
                return func(*args, **kwargs)
            return wrapper
        return decorator
    
    def show_blocker(self, page: ft.Page = None):
        """
        Affiche le bloqueur d'abonnement.
        Alias pour show_blocker_screen pour compatibilité.
        """
        if page:
            self.page = page
        
        # Vérifier si l'abonnement est bloqué
        is_blocked, block_type, details = self.is_blocked()
        
        if is_blocked:
            self.show_blocker_screen(details)
        else:
            # Si non bloqué, s'assurer que le bloqueur est caché
            self.hide_blocker(page)
    
    def hide_blocker(self, page: ft.Page = None):
        """
        Cache le bloqueur d'abonnement s'il est affiché.
        
        Args:
            page: Page Flet (optionnel)
        """
        try:
            if page:
                self.page = page
            
            # Fermer le dialogue s'il existe
            if self._blocker_dialog and self._blocker_dialog.open:
                self._blocker_dialog.open = False
                self._blocker_dialog = None
                logger.info("✅ Dialogue de blocage fermé")
            
            # Supprimer le conteneur du bloqueur s'il existe
            if self._blocker_container and self.page:
                try:
                    if self._blocker_container in self.page.controls:
                        self.page.controls.remove(self._blocker_container)
                        logger.info("✅ Conteneur de blocage supprimé")
                except Exception as e:
                    logger.warning(f"Erreur suppression conteneur: {e}")
                self._blocker_container = None
            
            # Nettoyer la vue si elle existe
            if self._blocker_view:
                self._blocker_view = None
            
            if self.page:
                self.page.update()
                
        except Exception as e:
            logger.error(f"Erreur masquage bloqueur: {e}")
    
    def show_blocker_dialog(self, details: dict):
        """Affiche un dialogue de blocage Flet"""
        
        def close_dialog(e):
            if self._blocker_dialog:
                self._blocker_dialog.open = False
                self.page.update()
        
        def do_sync(e):
            # Désactiver le bouton
            sync_button.disabled = True
            progress_ring.visible = True
            status_text.value = "Synchronisation en cours..."
            self.page.update()
            
            # Exécuter la synchronisation dans un thread
            def sync_in_thread():
                try:
                    result = self.sync_service.sync_subscription()
                    
                    def update_ui():
                        if result.get("success") and result.get("is_active"):
                            progress_ring.visible = False
                            status_text.value = "✅ Synchronisation réussie!"
                            status_text.color = ft.Colors.GREEN
                            self.page.update()
                            
                            # Fermer le dialogue
                            close_dialog(None)
                            
                            # Recharger l'interface
                            if hasattr(self.page, 'on_subscription_updated'):
                                try:
                                    callback = self.page.on_subscription_updated
                                    if hasattr(callback, '__call__'):
                                        callback()
                                except Exception as ex:
                                    logger.error(f"Erreur callback: {ex}")
                            elif hasattr(self.page, 'reload_app'):
                                self.page.reload_app()
                            else:
                                # Recharger la page
                                self.page.clean()
                                if hasattr(self.page, 'app') and hasattr(self.page.app, 'reload_app'):
                                    self.page.app.reload_app()
                        else:
                            progress_ring.visible = False
                            sync_button.disabled = False
                            error_msg = result.get("error", "Erreur inconnue")
                            status_text.value = f"❌ Échec: {error_msg}"
                            status_text.color = ft.Colors.RED
                            self.page.update()
                    
                    update_ui()
                    
                except Exception as ex:
                    logger.error(f"Erreur sync: {ex}")
                    def error_ui():
                        progress_ring.visible = False
                        sync_button.disabled = False
                        status_text.value = f"❌ Erreur: {str(ex)}"
                        status_text.color = ft.Colors.RED
                        self.page.update()
                    error_ui()
            
            thread = threading.Thread(target=sync_in_thread, daemon=True)
            thread.start()
        
        # Créer le dialogue
        title = ft.Text(
            details.get("title", "Accès restreint"),
            size=20,
            weight=ft.FontWeight.BOLD,
            color=ft.Colors.RED_600,
            text_align=ft.TextAlign.CENTER
        )
        
        message = ft.Text(
            details.get("message", ""),
            size=14,
            color=ft.Colors.GREY_700,
            text_align=ft.TextAlign.CENTER
        )
        
        info_text = ft.Text(
            "📱 Mode hors ligne\n\n"
            "L'application est en mode lecture seule.\n"
            "Pour retrouver l'accès complet, synchronisez l'application\n"
            "pour mettre à jour les informations de votre abonnement.",
            size=12,
            color=ft.Colors.GREY_500,
            text_align=ft.TextAlign.CENTER
        )
        
        progress_ring = ft.ProgressRing(visible=False)
        status_text = ft.Text("", size=12, color=ft.Colors.BLUE, text_align=ft.TextAlign.CENTER)
        
        sync_button = ft.ElevatedButton(
            content=ft.Row(
                [ft.Icon(ft.Icons.SYNC, size=20), ft.Text("Synchroniser maintenant")],
                spacing=10,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            on_click=do_sync,
            style=ft.ButtonStyle(
                color=ft.Colors.WHITE,
                bgcolor=ft.Colors.BLUE_600,
                padding=15,
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
        )
        
        close_button = ft.OutlinedButton(
            content=ft.Text("Fermer"),
            on_click=close_dialog,
            style=ft.ButtonStyle(
                color=ft.Colors.GREY_700,
                padding=15,
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
        )
        
        dialog_content = ft.Container(
            content=ft.Column(
                [
                    ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, size=60, color=ft.Colors.ORANGE_600),
                    title,
                    ft.Divider(height=20, color=ft.Colors.TRANSPARENT),
                    message,
                    ft.Divider(height=20, color=ft.Colors.TRANSPARENT),
                    info_text,
                    ft.Divider(height=20, color=ft.Colors.TRANSPARENT),
                    ft.Row([progress_ring], alignment=ft.MainAxisAlignment.CENTER),
                    status_text,
                    ft.Divider(height=20, color=ft.Colors.TRANSPARENT),
                    ft.Row([sync_button, close_button], alignment=ft.MainAxisAlignment.SPACE_EVENLY, spacing=20),
                ],
                spacing=5,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=25,
            width=350,
            bgcolor=ft.Colors.WHITE,
            border_radius=20,
        )
        
        self._blocker_dialog = ft.AlertDialog(
            modal=True,
            content=dialog_content,
            actions_alignment=ft.MainAxisAlignment.CENTER,
        )
        
        self.page.dialog = self._blocker_dialog
        self._blocker_dialog.open = True
        self.page.update()
    
    def check_and_show_blocker(self, page: ft.Page = None) -> bool:
        """Vérifie l'abonnement et affiche un écran de blocage si nécessaire."""
        if page:
            self.page = page
        
        # ✅ Vérifier que sync_service existe
        if self.sync_service is None:
            logger.warning("sync_service est None, impossible de vérifier l'abonnement")
            return False
        
        # ✅ Vérifier que auth_service existe
        if not hasattr(self.sync_service, 'auth_service') or self.sync_service.auth_service is None:
            logger.warning("auth_service est None, impossible de vérifier l'abonnement")
            return False
        
        try:
            is_blocked, block_type, details = self.is_blocked()
        except Exception as e:
            logger.error(f"Erreur is_blocked: {e}")
            return False
        
        # Afficher des infos de debug
        logger.info(f"Vérification abonnement - Bloqué: {is_blocked}, Type: {block_type}")
        
        # Ne pas bloquer si c'est juste un accès limité sans raison majeure
        if is_blocked and block_type == "subscription_expired":
            self.show_blocker_screen(details)
            return True
        elif is_blocked and block_type == "access_limited" and details.get("action") == "sync":
            # Afficher un avertissement mais ne pas bloquer complètement
            self.show_subscription_warning(page)
            return False
        
        return not is_blocked

    def show_subscription_warning(self, page: ft.Page):
        """Affiche un avertissement d'abonnement sans bloquer l'application"""
        def close_warning(e):
            warning_dialog.open = False
            page.update()
        
        def do_sync(e):
            close_warning(e)
            # Lancer la synchronisation
            if hasattr(page, 'sync_data'):
                page.sync_data()
        
        warning_dialog = ft.AlertDialog(
            title=ft.Text("⚠️ Information abonnement", size=18, weight=ft.FontWeight.BOLD),
            content=ft.Text(
                "Votre abonnement est bientôt expiré ou nécessite une synchronisation.\n\n"
                "Synchronisez pour mettre à jour les informations de votre abonnement.",
                size=14
            ),
            actions=[
                ft.TextButton("Plus tard", on_click=close_warning),
                ft.ElevatedButton("Synchroniser", on_click=do_sync, style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_600, color=ft.Colors.WHITE)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        page.dialog = warning_dialog
        warning_dialog.open = True
        page.update()
    
    def show_blocker_screen(self, details: dict):
        """
        Affiche un écran de blocage complet (view séparée).
        """
        
        def do_sync(e):
            sync_button.disabled = True
            progress_ring.visible = True
            status_text.value = "Synchronisation en cours..."
            self.page.update()
            
            def sync_in_thread():
                try:
                    result = self.sync_service.sync_subscription()
                    
                    def update_ui():
                        if result.get("success") and result.get("is_active"):
                            # Nettoyer et recharger
                            self.page.clean()
                            if hasattr(self.page, 'reload_app'):
                                self.page.reload_app()
                        else:
                            sync_button.disabled = False
                            progress_ring.visible = False
                            error_msg = result.get("error", "Erreur inconnue")
                            status_text.value = f"❌ {error_msg}"
                            status_text.color = ft.Colors.RED
                            self.page.update()
                    
                    update_ui()
                    
                except Exception as ex:
                    logger.error(f"Erreur sync: {ex}")
                    def error_ui():
                        sync_button.disabled = False
                        progress_ring.visible = False
                        status_text.value = f"❌ {str(ex)}"
                        status_text.color = ft.Colors.RED
                        self.page.update()
                    error_ui()
            
            thread = threading.Thread(target=sync_in_thread, daemon=True)
            thread.start()
        
        progress_ring = ft.ProgressRing(visible=False)
        status_text = ft.Text("", size=14, color=ft.Colors.BLUE)
        
        sync_button = ft.ElevatedButton(
            content=ft.Row(
                [ft.Icon(ft.Icons.SYNC, size=24), ft.Text("Synchroniser mon abonnement", size=16)],
                spacing=10,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            on_click=do_sync,
            style=ft.ButtonStyle(
                color=ft.Colors.WHITE,
                bgcolor=ft.Colors.BLUE_600,
                padding=20,
                shape=ft.RoundedRectangleBorder(radius=10),
            ),
        )
        
        # Créer la vue de blocage
        blocker_content = ft.Column(
            [
                ft.Icon(ft.Icons.LOCK_OUTLINE, size=100, color=ft.Colors.RED_400),
                ft.Text(
                    details.get("title", "Accès restreint"),
                    size=24,
                    weight=ft.FontWeight.BOLD,
                    color=ft.Colors.RED_700,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Divider(height=20, color=ft.Colors.TRANSPARENT),
                ft.Text(
                    details.get("message", ""),
                    size=16,
                    color=ft.Colors.GREY_700,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Divider(height=30, color=ft.Colors.TRANSPARENT),
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text("🔒 Mode hors ligne", size=14, weight=ft.FontWeight.BOLD),
                            ft.Text(
                                "L'application est actuellement en mode lecture seule.\n"
                                "Pour utiliser toutes les fonctionnalités, synchronisez votre abonnement.",
                                size=13,
                                color=ft.Colors.GREY_600,
                                text_align=ft.TextAlign.CENTER,
                            ),
                        ],
                        spacing=5,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=20,
                    bgcolor=ft.Colors.GREY_100,
                    border_radius=10,
                ),
                ft.Divider(height=30, color=ft.Colors.TRANSPARENT),
                progress_ring,
                status_text,
                ft.Divider(height=20, color=ft.Colors.TRANSPARENT),
                sync_button,
            ],
            spacing=10,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )
        
        # Stocker le conteneur pour pouvoir le supprimer plus tard
        self._blocker_container = ft.Container(
            content=blocker_content,
            expand=True,
            alignment=ft.Alignment.CENTER,
            bgcolor=ft.Colors.WHITE,
        )
        
        # Remplacer le contenu de la page
        self.page.clean()
        self.page.add(self._blocker_container)
        self.page.update()
    
    def get_subscription_status_view(self) -> ft.Container:
        """Retourne une vue d'état de l'abonnement à intégrer dans l'interface"""
        # ✅ Vérification de sécurité
        if self.sync_service is None:
            return ft.Container(
                content=ft.Text("Service indisponible", color=ft.Colors.RED),
                padding=15,
                bgcolor=ft.Colors.GREY_50,
                border_radius=10,
            )
        
        try:
            access = self.sync_service.check_subscription_access()
        except Exception as e:
            logger.error(f"Erreur get_subscription_status_view: {e}")
            return ft.Container(
                content=ft.Text(f"Erreur: {str(e)}", color=ft.Colors.RED),
                padding=15,
                bgcolor=ft.Colors.GREY_50,
                border_radius=10,
            )
        
        if access is None or not isinstance(access, dict):
            return ft.Container(
                content=ft.Text("Informations non disponibles", color=ft.Colors.ORANGE),
                padding=15,
                bgcolor=ft.Colors.GREY_50,
                border_radius=10,
            )
        
        is_active = access.get("is_active", False)
        has_subscription = access.get("has_subscription", False)
        days_remaining = access.get("subscription", {}).get("days_remaining", 0)
        
        if not has_subscription:
            status_color = ft.Colors.RED_400
            status_text = "Aucun abonnement"
            status_icon = ft.Icons.WARNING
            status_message = "Synchronisez pour activer votre abonnement"
        elif not is_active:
            status_color = ft.Colors.RED_400
            status_text = "Abonnement expiré"
            status_icon = ft.Icons.ERROR
            status_message = f"Expiré depuis {abs(days_remaining)} jours"
        elif days_remaining <= 7:
            status_color = ft.Colors.ORANGE_400
            status_text = "Expire bientôt"
            status_icon = ft.Icons.WARNING
            status_message = f"Plus que {days_remaining} jours"
        else:
            status_color = ft.Colors.GREEN_400
            status_text = "Abonnement actif"
            status_icon = ft.Icons.CHECK_CIRCLE
            status_message = f"Valable {days_remaining} jours"
        
        limits = access.get("limits", {})
        usage = access.get("usage", {})
        
        max_products = limits.get("max_products", "Illimité")
        max_users = limits.get("max_users", "Illimité")
        current_products = usage.get("current_products", 0)
        current_users = usage.get("current_users", 0)
        
        products_percentage = usage.get("products_percentage", 0)
        users_percentage = usage.get("users_percentage", 0)
        
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(status_icon, color=status_color, size=24),
                            ft.Column(
                                [
                                    ft.Text(status_text, size=16, weight=ft.FontWeight.BOLD, color=status_color),
                                    ft.Text(status_message, size=12, color=ft.Colors.GREY_600),
                                ],
                                spacing=2,
                            ),
                        ],
                        spacing=10,
                    ),
                    ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
                    ft.Row(
                        [
                            self._build_limit_card(
                                "📦 Produits",
                                f"{current_products} / {max_products}",
                                products_percentage,
                                ft.Colors.BLUE_400
                            ),
                            self._build_limit_card(
                                "👥 Utilisateurs",
                                f"{current_users} / {max_users}",
                                users_percentage,
                                ft.Colors.PURPLE_400
                            ),
                        ],
                        spacing=15,
                        alignment=ft.MainAxisAlignment.SPACE_EVENLY,
                    ),
                ],
                spacing=5,
            ),
            padding=15,
            bgcolor=ft.Colors.GREY_50,
            border_radius=10,
            margin=ft.Margin.only(bottom=10),
        )
    
    def _build_limit_card(self, title: str, value: str, percentage: float, color: str) -> ft.Container:
        """Construit une carte de limite"""
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(title, size=12, color=ft.Colors.GREY_600),
                    ft.Text(value, size=16, weight=ft.FontWeight.BOLD),
                    ft.ProgressBar(value=percentage / 100, width=100, color=color),
                ],
                spacing=5,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=10,
            bgcolor=ft.Colors.WHITE,
            border_radius=8,
            expand=True,
        )


# Instance globale
_subscription_blocker = None


def get_subscription_blocker(sync_service=None, page=None):
    """Récupère l'instance globale du bloqueur d'abonnement"""
    global _subscription_blocker
    if _subscription_blocker is None and sync_service:
        _subscription_blocker = SubscriptionBlocker(sync_service, page)
    return _subscription_blocker


def require_active_subscription(feature: str = None):
    """
    Décorateur pour exiger un abonnement actif.
    Usage: @require_active_subscription(feature="create_sale")
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            blocker = get_subscription_blocker()
            if blocker:
                is_blocked, block_type, details = blocker.is_blocked(feature)
                if is_blocked:
                    logger.warning(f"Fonction {func.__name__} bloquée: {details.get('title')}")
                    blocker.show_blocker_dialog(details)
                    return None
            return func(*args, **kwargs)
        return wrapper
    return decorator