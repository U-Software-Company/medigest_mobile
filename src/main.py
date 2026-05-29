# main.py - Version corrigée

import flet as ft
import logging
import threading
import time
from typing import Optional, Dict

from database.db_manager import DatabaseManager
from services.auth_service import AuthService
from services.sync_service import SyncService
from services.notification_manager import NotificationManager
from services.connection_manager import ConnectionManager
from screens.login_screen import LoginScreen
from screens.dashboard_screen import DashboardScreen
from utils.subscription_blocker import SubscriptionBlocker

# Configuration du logger
logger = logging.getLogger(__name__)


class MediGestApp:
    """
    Classe principale de l'application MediGestPro Mobile.
    """
    
    def __init__(self, page: ft.Page):
        self.page = page
        self._setup_page()
        
        # Initialisation des services
        self.db = DatabaseManager()
        logger.info("✅ DatabaseManager initialisé")
        
        self.auth_service = AuthService(self.db)
        logger.info("✅ AuthService initialisé")
        
        self.sync_service = SyncService(self.db, self.auth_service)
        logger.info("✅ SyncService initialisé")
        
        self.connection_manager = ConnectionManager()
        self.connection_manager.set_sync_service(self.sync_service)
        logger.info("✅ ConnectionManager initialisé")
        
        self.subscription_blocker = SubscriptionBlocker(self.sync_service, self.page)
        logger.info("✅ SubscriptionBlocker initialisé")
        
        self.notification_manager = NotificationManager(
            self.page, self.db, self.auth_service, self.sync_service
        )
        logger.info("✅ NotificationManager initialisé")
        
        # Vérification de l'utilisateur existant
        self.current_user = self.auth_service.get_current_user()
        
        # AFFICHER LE DIAGNOSTIC COMPLET
        self.debug_auth_state()
        
        if self.current_user:
            logger.info(f"👤 Utilisateur trouvé dans le cache local: {self.current_user.get('username')}")
            logger.info(f"   Branche: {self.current_user.get('branch_name')} ({self.current_user.get('active_branch_id')})")
            logger.info(f"   Pharmacie: {self.current_user.get('pharmacy_name')}")
            logger.info(f"   Token présent: {'✓' if self.current_user.get('token') else '✗'}")
        else:
            logger.info("👤 Aucun utilisateur dans le cache local - Login requis")
        
        # Vérifications périodiques
        self._start_subscription_checker()
        self._check_subscription_on_startup()
    
    # =========================================================================
    # CONFIGURATION DE LA PAGE
    # =========================================================================
    
    def _setup_page(self):
        self.page.title = "MediGestPro Mobile"
        self.page.theme_mode = ft.ThemeMode.LIGHT
        self.page.padding = 0
        self.page.bgcolor = ft.Colors.WHITE
        self.page.reload_app = self.reload_app
        self.page.on_subscription_updated = self.on_subscription_updated
        self.page.on_close = self._on_close
        logger.info("✅ Page configurée")
    
    # =========================================================================
    # DIAGNOSTIC (DÉPLACÉ DANS LA CLASSE)
    # =========================================================================
    
    def debug_auth_state(self):
        """Affiche l'état de l'authentification pour le débogage."""
        logger.info("=" * 60)
        logger.info("🔍 DIAGNOSTIC AUTHENTIFICATION")
        logger.info("=" * 60)
        
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Lister toutes les tables
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = cursor.fetchall()
                logger.info(f"📋 Tables dans la base: {[t[0] for t in tables]}")
                
                if any(t[0] == 'user' for t in tables):
                    cursor.execute("SELECT COUNT(*) FROM user")
                    count = cursor.fetchone()[0]
                    logger.info(f"📊 Nombre d'utilisateurs: {count}")
                    
                    if count > 0:
                        cursor.execute("SELECT id, username, branch_name, pharmacy_name, "
                                      "CASE WHEN token IS NOT NULL AND token != '' THEN '✓' ELSE '✗' END as token_status "
                                      "FROM user")
                        rows = cursor.fetchall()
                        for row in rows:
                            logger.info(f"   - ID: {row[0]}, Username: {row[1]}, Branche: {row[2]}, "
                                      f"Pharmacie: {row[3]}, Token: {row[4]}")
                    else:
                        logger.info("   ❌ Table 'user' vide")
                else:
                    logger.info("❌ Table 'user' n'existe pas")
                    
        except Exception as e:
            logger.error(f"Erreur diagnostic: {e}")
            import traceback
            traceback.print_exc()
        
        logger.info("=" * 60)
    
    # =========================================================================
    # VÉRIFICATION DE L'ABONNEMENT
    # =========================================================================
    
    def _start_subscription_checker(self):
        def checker_loop():
            logger.info("🔄 Vérificateur d'abonnement démarré (intervalle: 60s)")
            while True:
                try:
                    time.sleep(60)
                    self.current_user = self.auth_service.get_current_user()
                    if not self.current_user:
                        continue
                    if not self.sync_service.check_internet_connection():
                        continue
                    # ✅ CORRECTION: Utiliser check_subscription_status au lieu de check_subscription_status
                    result = self.sync_service.check_subscription_status()
                    if result.get("active") is False:
                        logger.warning("⚠️ Abonnement expiré détecté en arrière-plan")
                        self.page.run_task(self._show_subscription_blocker)
                    else:
                        self.page.run_task(self._hide_subscription_blocker)
                except Exception as e:
                    logger.error(f"Erreur dans le vérificateur d'abonnement: {e}")
        
        thread = threading.Thread(target=checker_loop, daemon=True, name="SubscriptionChecker")
        thread.start()
        

    async def _show_subscription_blocker(self):
        try:
            self.subscription_blocker.show_blocker(self.page)
            logger.info("🛑 Bloqueur d'abonnement affiché")
        except Exception as e:
            logger.error(f"Erreur affichage bloqueur: {e}")
    
    async def _hide_subscription_blocker(self):
        try:
            self.subscription_blocker.hide_blocker(self.page)
            logger.info("✅ Bloqueur d'abonnement caché")
        except Exception as e:
            logger.error(f"Erreur masquage bloqueur: {e}")

    def _check_subscription_on_startup(self):
        if self.current_user:
            logger.info("🔍 Vérification de l'abonnement au démarrage...")
            if self.sync_service.check_internet_connection():
                logger.info("🌐 Internet disponible - synchronisation de l'abonnement")
                result = self.sync_service.sync_subscription()
                if result.get("success"):
                    logger.info("✅ Abonnement synchronisé avec le serveur")
                    sub_status = self.auth_service.get_subscription_status()
                    is_active = sub_status.get("is_active", True)
                    logger.info(f"📋 Statut abonnement: {'actif' if is_active else 'expiré'}")
                else:
                    logger.warning(f"⚠️ Échec synchronisation abonnement: {result.get('error')}")
            else:
                logger.info("📡 Pas d'internet - utilisation du cache local")
            
            if not self.subscription_blocker.check_and_show_blocker(self.page):
                logger.warning("⚠️ Abonnement expiré - mode lecture seule")
                self.page.update()
                return
        
        self._show_main_screen()

    # =========================================================================
    # TRANSITIONS D'ÉCRANS
    # =========================================================================
    
    def _show_main_screen(self):
        if self.current_user:
            logger.info(f"📱 Affichage du Dashboard pour {self.current_user.get('username')}")
            dashboard = DashboardScreen(
                page=self.page,
                db=self.db,
                sync_service=self.sync_service,
                auth_service=self.auth_service,
                current_user=self.current_user,
                notification_manager=self.notification_manager
            )
            dashboard.show()
        else:
            logger.info("🔐 Affichage de l'écran de login")
            login = LoginScreen(
                page=self.page,
                db=self.db,
                sync_service=self.sync_service,
                auth_service=self.auth_service
            )
            login.show()
        
        self.page.update()
        logger.info("✅ Écran principal affiché")

    # =========================================================================
    # CALLBACKS
    # =========================================================================
    
    def on_subscription_updated(self):
        logger.info("🔄 Abonnement mis à jour - rechargement de l'application")
        self.reload_app()

    def reload_app(self):
        logger.info("🔄 Rechargement complet de l'application...")
        self.page.clean()
        self.page.views.clear()
        self.current_user = self.auth_service.get_current_user()
        
        if self.current_user:
            logger.info(f"👤 Utilisateur après rechargement: {self.current_user.get('username')}")
            if self.subscription_blocker.check_and_show_blocker(self.page):
                dashboard = DashboardScreen(
                    page=self.page,
                    db=self.db,
                    sync_service=self.sync_service,
                    auth_service=self.auth_service,
                    current_user=self.current_user,
                    notification_manager=self.notification_manager
                )
                dashboard.show()
        else:
            logger.info("🔐 Aucun utilisateur - retour au login")
            login = LoginScreen(
                page=self.page,
                db=self.db,
                sync_service=self.sync_service,
                auth_service=self.auth_service
            )
            login.show()
        
        self.page.update()
        logger.info("✅ Application rechargée")

    # =========================================================================
    # FERMETURE
    # =========================================================================
    
    def _on_close(self):
        logger.info("👋 Fermeture de l'application")
        logger.info("📌 Données utilisateur conservées dans SQLite")
        logger.info("📌 L'utilisateur sera automatiquement reconnecté au prochain lancement")
        self.connection_manager.stop_internet_checking()
        logger.info("✅ Vérifications périodiques arrêtées")

    # =========================================================================
    # PROPRIÉTÉS UTILES
    # =========================================================================
    
    @property
    def is_authenticated(self) -> bool:
        return self.auth_service.is_authenticated()
    
    @property
    def is_online(self) -> bool:
        return self.connection_manager.is_online_mode()
    
    @property
    def subscription_status(self) -> Dict:
        return self.auth_service.get_subscription_status()


# =============================================================================
# POINT D'ENTRÉE
# =============================================================================

def main(page: ft.Page):
    """Point d'entrée principal de l'application Flet."""
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('medigest_pro.log', encoding='utf-8')
        ]
    )
    
    logger.info("=" * 60)
    logger.info("🚀 DÉMARRAGE DE MEDIGESTPRO MOBILE")
    logger.info("=" * 60)
    logger.info(f"📱 Plateforme: {page.platform}")
    logger.info(f"📱 Thème: {page.theme_mode}")
    
    try:
        app = MediGestApp(page)
        page.app = app
        logger.info("✅ Application initialisée avec succès")
    except Exception as e:
        logger.error(f"❌ Erreur fatale au démarrage: {e}")
        import traceback
        traceback.print_exc()
        
        page.add(
            ft.Container(
                content=ft.Column([
                    ft.Icon(ft.Icons.ERROR, size=64, color=ft.Colors.RED),
                    ft.Text("Erreur de démarrage", size=24, weight=ft.FontWeight.BOLD),
                    ft.Text(str(e), size=14, color=ft.Colors.RED),
                    ft.Button("Réessayer", on_click=lambda _: main(page))
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                alignment=ft.Alignment(0, 0),
                padding=20
            )
        )


if __name__ == "__main__":
    logger.info("🏁 Lancement de l'application Flet...")
    ft.run(main)