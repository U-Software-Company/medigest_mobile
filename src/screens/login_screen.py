# screens/login_screen.py - Version finale avec sauvegarde robuste
"""
Écran de connexion - MediGestPro Mobile

Architecture:
1. Vérifie la connexion internet (requise pour la première connexion)
2. Authentifie l'utilisateur via l'API
3. Sauvegarde les données utilisateur dans SQLite via AuthService
4. Synchronise l'abonnement, la branche et les produits
5. Redirige vers le Dashboard

Cycle de vie:
- PREMIÈRE CONNEXION → Sauvegarde complète dans SQLite
- CONNEXIONS SUIVANTES → L'utilisateur est déjà dans SQLite (skip login)
- DÉCONNEXION → AuthService.logout() efface les données
"""

import flet as ft
import requests
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any

# Configuration du logger
logger = logging.getLogger(__name__)


class LoginScreen:
    """
    Écran de connexion de l'application.
    
    Responsabilités:
    - Afficher le formulaire de connexion
    - Authentifier l'utilisateur via l'API backend
    - Sauvegarder les données localement (offline-first)
    - Synchroniser l'abonnement, la branche et les produits
    - Rediriger vers le Dashboard
    """
    
    def __init__(
        self,
        page: ft.Page,
        db,
        sync_service,
        auth_service,
        on_login_success=None
    ):
        """
        Initialise l'écran de connexion.
        
        Args:
            page: La page Flet
            db: DatabaseManager pour le stockage local
            sync_service: SyncService pour la synchronisation
            auth_service: AuthService pour la gestion locale
            on_login_success: Callback optionnel après connexion réussie
        """
        self.page = page
        self.db = db
        self.sync_service = sync_service
        self.auth_service = auth_service
        self.on_login_success = on_login_success
        
        # Composants UI
        self.username_field = None
        self.password_field = None
        self.error_text = None
        self.loading = None
        self.login_button = None
        
        # État
        self.is_logging_in = False
    
    # =========================================================================
    # AFFICHAGE
    # =========================================================================
    
    def show(self):
        """
        Affiche l'écran de connexion.
        
        Vérifie d'abord l'utilisateur dans le cache local.
        Si déjà connecté → Dashboard directement.
        Sinon → Formulaire de connexion.
        """
        logger.info("📱 Affichage de l'écran de connexion")
        
        # ✅ VÉRIFIER D'ABORD SI L'UTILISATEUR EST DÉJÀ CONNECTÉ
        existing_user = self.auth_service.get_current_user()
        if existing_user and existing_user.get('token'):
            logger.info(f"👤 Utilisateur déjà connecté: {existing_user.get('username')}")
            logger.info("⏭️ Redirection directe vers le Dashboard")
            self._go_to_dashboard(existing_user)
            return
        
        # Vérifier la connexion internet pour le formulaire
        try:
            has_internet = self.sync_service.check_internet_connection()
        except Exception as e:
            logger.error(f"Erreur vérification internet: {e}")
            has_internet = False
        
        if not has_internet and not existing_user:
            self._show_no_internet_message()
            return
        
        # Nettoyer la page
        self.page.clean()
        self.page.bgcolor = ft.Colors.WHITE
        
        # Construire l'interface
        self._build_ui()
        self.page.update()
        
        logger.info("✅ Écran de connexion affiché")
    
    def _build_ui(self):
        """Construit l'interface utilisateur."""
        
        # --- En-tête ---
        header = ft.Container(
            content=ft.Column([
                ft.Container(
                    content=ft.Icon(
                        ft.Icons.HEALING, 
                        size=60, 
                        color=ft.Colors.WHITE
                    ),
                    bgcolor=ft.Colors.BLUE_700,
                    border_radius=40,
                    padding=20,
                ),
                ft.Text(
                    "MediGest Pro", 
                    size=32, 
                    weight=ft.FontWeight.BOLD, 
                    color=ft.Colors.BLUE_700
                ),
                ft.Text(
                    "Application de gestion de pharmacie", 
                    size=14, 
                    color=ft.Colors.GREY_600
                ),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
            margin=ft.Margin.only(top=40, bottom=30),
        )
        
        # --- Formulaire ---
        self.username_field = ft.TextField(
            label="Email ou nom d'utilisateur",
            hint_text="exemple@pharmacie.com",
            prefix_icon=ft.Icons.PERSON,
            width=320,
            border_radius=10,
            border_color=ft.Colors.BLUE_200,
            focused_border_color=ft.Colors.BLUE_700,
            autofocus=True,
            text_size=14,
            on_submit=lambda e: self.password_field.focus(),
        )
        
        self.password_field = ft.TextField(
            label="Mot de passe",
            hint_text="Votre mot de passe",
            prefix_icon=ft.Icons.LOCK,
            password=True,
            can_reveal_password=True,
            width=320,
            border_radius=10,
            border_color=ft.Colors.BLUE_200,
            focused_border_color=ft.Colors.BLUE_700,
            text_size=14,
            on_submit=self._handle_login,
        )
        
        self.error_text = ft.Text(
            "", 
            color=ft.Colors.RED_600, 
            size=12, 
            visible=False,
            text_align=ft.TextAlign.CENTER,
        )
        
        self.login_button = ft.ElevatedButton(
            content=ft.Row([
                ft.Text("Se connecter", size=16, weight=ft.FontWeight.BOLD),
            ], alignment=ft.MainAxisAlignment.CENTER),
            on_click=self._handle_login,
            width=320,
            height=48,
            style=ft.ButtonStyle(
                color=ft.Colors.WHITE,
                bgcolor=ft.Colors.BLUE_700,
                shape=ft.RoundedRectangleBorder(radius=10),
                elevation=2,
            ),
        )
        
        self.loading = ft.ProgressBar(
            width=320, 
            visible=False, 
            color=ft.Colors.BLUE_700,
            bgcolor=ft.Colors.BLUE_100,
        )
        
        # --- Formulaire complet ---
        form = ft.Column([
            self.username_field,
            self.password_field,
            self.error_text,
            ft.Container(height=10),
            self.login_button,
            self.loading,
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12)
        
        # --- Pied de page ---
        footer = ft.Container(
            content=ft.Column([
                ft.Divider(height=1, color=ft.Colors.GREY_300),
                ft.Text(
                    "Première connexion : connexion Internet requise\n"
                    "Connexions suivantes : mode hors-ligne disponible",
                    size=11, 
                    color=ft.Colors.GREY_500,
                    text_align=ft.TextAlign.CENTER,
                ),
            ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            margin=ft.Margin.only(top=40),
        )
        
        # --- Assemblage ---
        self.page.add(
            ft.Container(
                content=ft.Column([
                    header,
                    ft.Container(
                        content=form,
                        padding=30,
                        bgcolor=ft.Colors.WHITE,
                        border_radius=15,
                        shadow=ft.BoxShadow(
                            spread_radius=1,
                            blur_radius=15,
                            color=ft.Colors.GREY_300,
                        ),
                    ),
                    footer,
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                expand=True,
                alignment=ft.Alignment.CENTER,
                gradient=ft.LinearGradient(
                    begin=ft.Alignment(0, -1),
                    end=ft.Alignment(0, 1),
                    colors=[ft.Colors.BLUE_50, ft.Colors.WHITE],
                ),
            )
        )
    
    # =========================================================================
    # GESTION CONNEXION INTERNET
    # =========================================================================
    
    def _show_no_internet_message(self):
        """
        Affiche un message quand il n'y a pas d'internet.
        Vérifie si un utilisateur existe dans le cache local.
        """
        # Vérifier le cache local
        cached_user = self.auth_service.get_current_user()
        
        if cached_user and cached_user.get('token'):
            logger.info("👤 Utilisateur trouvé dans le cache - connexion hors-ligne possible")
            self._go_to_dashboard(cached_user)
            return
        
        # Aucun utilisateur en cache → nécessite internet
        self.page.clean()
        self.page.add(
            ft.Container(
                content=ft.Column([
                    ft.Icon(ft.Icons.WIFI_OFF, size=80, color=ft.Colors.ORANGE_400),
                    ft.Text(
                        "Connexion Internet requise", 
                        size=22, 
                        weight=ft.FontWeight.BOLD
                    ),
                    ft.Text(
                        "La première connexion nécessite une connexion Internet\n"
                        "pour authentifier votre compte.",
                        size=14, 
                        color=ft.Colors.GREY_600,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Container(height=20),
                    ft.ElevatedButton(
                        "Réessayer",
                        icon=ft.Icons.REFRESH,
                        on_click=lambda e: self.show(),
                        width=250,
                    ),
                    ft.Container(height=10),
                    ft.TextButton(
                        "Utiliser le mode hors-ligne",
                        visible=False,  # Caché car pas d'utilisateur en cache
                        on_click=lambda e: self._go_to_dashboard(cached_user),
                    ),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
                expand=True,
                alignment=ft.Alignment.CENTER,
                padding=30,
            )
        )
        self.page.update()
    
    # =========================================================================
    # AUTHENTIFICATION
    # =========================================================================
    
    def _handle_login(self, e):
        """
        Gère le clic sur le bouton de connexion.
        
        Étapes:
        1. Valide les champs
        2. Appelle l'API de login
        3. Sauvegarde les données utilisateur dans SQLite
        4. Synchronise l'abonnement, la branche et les produits
        5. Redirige vers le Dashboard
        """
        # Empêcher le double-clic
        if self.is_logging_in:
            logger.warning("⚠️ Connexion déjà en cours - action ignorée")
            return
        
        email_or_username = (self.username_field.value or '').strip()
        password = self.password_field.value or ''
        
        # Validation
        if not email_or_username:
            self._show_error("Veuillez entrer votre email ou nom d'utilisateur")
            self.username_field.focus()
            return
        
        if not password:
            self._show_error("Veuillez entrer votre mot de passe")
            self.password_field.focus()
            return
        
        if len(password) < 4:
            self._show_error("Le mot de passe doit contenir au moins 4 caractères")
            self.password_field.focus()
            return
        
        # Démarrer la connexion
        self.is_logging_in = True
        self._set_loading(True)
        self._show_error("")  # Effacer les erreurs précédentes
        
        try:
            # Étape 1: Authentification via l'API
            logger.info(f"🔐 Tentative de connexion pour: {email_or_username}")
            
            login_result = self._call_login_api(email_or_username, password)
            
            if not login_result.get("success"):
                error_msg = login_result.get("error", "Erreur d'authentification")
                self._show_error(error_msg)
                return
            
            user_data = login_result.get("data", {})
            logger.info(f"✅ Authentification réussie pour: {email_or_username}")
            
            # Étape 2: Sauvegarder l'utilisateur dans SQLite
            logger.info("💾 Sauvegarde des données utilisateur dans SQLite...")
            save_success = self.auth_service.save_user_from_login(user_data)
            
            if not save_success:
                self._show_error("Erreur lors de la sauvegarde des données. Veuillez réessayer.")
                logger.error("❌ Échec de la sauvegarde utilisateur")
                return
            
            logger.info("✅ Données utilisateur sauvegardées avec succès")
            
            # Étape 3: Synchronisation post-connexion
            self._show_snackbar("Synchronisation des données en cours...", duration=3000)
            
            sync_success = self._perform_initial_sync(user_data)
            
            if not sync_success:
                logger.warning("⚠️ Synchronisation initiale incomplète - passage en mode dégradé")
                self._show_snackbar(
                    "Connecté en mode hors-ligne. Synchronisation automatique dès que possible.",
                    duration=4000
                )
            
            # Étape 4: Récupérer l'utilisateur sauvegardé
            saved_user = self.auth_service.get_current_user()
            
            if not saved_user:
                self._show_error("Erreur critique: utilisateur non trouvé après sauvegarde")
                logger.error("❌ Utilisateur introuvable après sauvegarde")
                return
            
            # Étape 5: Rediriger vers le Dashboard
            logger.info(f"🎉 Connexion réussie - Redirection vers le Dashboard")
            self._go_to_dashboard(saved_user)
            
        except requests.ConnectionError:
            self._show_error("Impossible de se connecter au serveur. Vérifiez votre connexion internet.")
            logger.error("❌ Erreur de connexion au serveur")
        except requests.Timeout:
            self._show_error("Le serveur met trop de temps à répondre. Veuillez réessayer.")
            logger.error("❌ Timeout de connexion")
        except Exception as e:
            self._show_error(f"Erreur inattendue: {str(e)}")
            logger.error(f"❌ Erreur inattendue: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.is_logging_in = False
            self._set_loading(False)
    
    def _call_login_api(self, email_or_username: str, password: str) -> Dict[str, Any]:
        """
        Appelle l'API de connexion.
        
        Args:
            email_or_username: Email ou nom d'utilisateur
            password: Mot de passe
            
        Returns:
            Dict avec 'success' et 'data' ou 'error'
        """
        api_url = f"{self.sync_service.base_url}/api/v1/auth/login"
        
        # Déterminer si c'est un email ou un username
        if '@' in email_or_username:
            payload = {"email": email_or_username, "password": password}
        else:
            payload = {"username": email_or_username, "password": password}
        
        logger.info(f"📤 Envoi requête login à: {api_url}")
        
        try:
            response = requests.post(
                api_url,
                json=payload,
                timeout=30,
                verify=False  # Désactiver SSL pour le développement
            )
            
            logger.info(f"📥 Réponse login: status={response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                
                # Logger les clés reçues (pour debug)
                if isinstance(data, dict):
                    logger.info(f"📋 Clés reçues: {list(data.keys())}")
                    
                    # Vérifier la présence des données essentielles
                    if 'user' in data:
                        logger.info(f"   user.id: {data['user'].get('id')}")
                        logger.info(f"   user.username: {data['user'].get('username')}")
                    if 'access_token' in data:
                        logger.info(f"   token présent: Oui ({len(data['access_token'])} chars)")
                    if 'current_branch' in data:
                        logger.info(f"   current_branch: {data['current_branch'].get('name')}")
                    if 'current_pharmacy' in data:
                        logger.info(f"   current_pharmacy: {data['current_pharmacy'].get('name')}")
                    if 'subscription' in data:
                        logger.info(f"   subscription présente: Oui")
                
                return {"success": True, "data": data}
            else:
                # Extraire le message d'erreur
                error_msg = "Email ou mot de passe incorrect"
                try:
                    error_data = response.json()
                    if isinstance(error_data, dict):
                        error_msg = (
                            error_data.get('detail') or 
                            error_data.get('message') or 
                            str(error_data)
                        )
                except:
                    pass
                
                logger.warning(f"⚠️ Échec authentification: {response.status_code} - {error_msg}")
                return {"success": False, "error": error_msg}
                
        except requests.ConnectionError as e:
            logger.error(f"❌ Erreur de connexion: {e}")
            raise
        except requests.Timeout as e:
            logger.error(f"❌ Timeout: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ Erreur inattendue: {e}")
            raise
    
    def _perform_initial_sync(self, user_data: Dict[str, Any]) -> bool:
        """
        Effectue la synchronisation initiale après la connexion.
        
        Étapes:
        1. Synchroniser l'abonnement
        2. Synchroniser la branche
        3. Importer les produits
        
        Returns:
            True si la synchronisation a réussi (même partiellement)
        """
        all_success = True
        
        try:
            # 1. Synchroniser l'abonnement
            logger.info("🔄 [1/3] Synchronisation de l'abonnement...")
            sub_result = self.sync_service.sync_subscription()
            
            if sub_result.get('success'):
                is_active = sub_result.get('is_active', False)
                logger.info(f"   ✅ Abonnement: actif={is_active}")
                if sub_result.get('cached'):
                    logger.info(f"   ⚠️ Utilisation du cache: {sub_result.get('warning', '')}")
            else:
                logger.warning(f"   ⚠️ Sync abonnement: {sub_result.get('error')}")
                all_success = False
            
            # 2. Synchroniser la branche
            logger.info("🔄 [2/3] Synchronisation de la branche...")
            branch_result = self.auth_service.sync_user_branch_from_server()
            
            if branch_result.get('success'):
                logger.info(f"   ✅ Branche: {branch_result.get('branch_name')} ({branch_result.get('branch_id')})")
            else:
                logger.warning(f"   ⚠️ Sync branche: {branch_result.get('error')}")
                all_success = False
            
            # 3. Importer les produits
            logger.info("🔄 [3/3] Import des produits...")
            branch_id = branch_result.get('branch_id') or self.auth_service.get_user_branch_id()
            
            if branch_id:
                product_result = self.sync_service.import_products_improved(branch_id)
                
                if product_result.get('success'):
                    count = product_result.get('count', 0)
                    logger.info(f"   ✅ {count} produits importés")
                else:
                    logger.warning(f"   ⚠️ Import produits: {product_result.get('error', '')}")
                    all_success = False
            else:
                logger.warning("   ⚠️ Pas de branch_id - import produits ignoré")
                all_success = False
            
            if all_success:
                logger.info("✅ Synchronisation initiale terminée avec succès")
            else:
                logger.warning("⚠️ Synchronisation initiale partielle")
            
            return all_success
            
        except Exception as e:
            logger.error(f"❌ Erreur synchronisation initiale: {e}")
            return False
    
    # =========================================================================
    # NAVIGATION
    # =========================================================================
    
    def _go_to_dashboard(self, user_data: Dict[str, Any]):
        """
        Redirige vers le Dashboard.
        
        Args:
            user_data: Données de l'utilisateur (depuis SQLite)
        """
        logger.info(f"🏠 Redirection vers Dashboard pour: {user_data.get('username')}")
        
        try:
            # Importer ici pour éviter les imports circulaires
            from screens.dashboard_screen import DashboardScreen
            
            # Créer et afficher le dashboard
            dashboard = DashboardScreen(
                page=self.page,
                db=self.db,
                sync_service=self.sync_service,
                auth_service=self.auth_service,
                current_user=user_data,
                notification_manager=None  # Sera initialisé dans main.py
            )
            dashboard.show()
            
            # Appeler le callback si défini
            if self.on_login_success:
                self.on_login_success(user_data)
                
        except Exception as e:
            logger.error(f"❌ Erreur redirection Dashboard: {e}")
            self._show_error(f"Erreur lors du chargement du tableau de bord: {e}")
    
    # =========================================================================
    # HELPERS UI
    # =========================================================================
    
    def _set_loading(self, loading: bool):
        """Active/désactive l'état de chargement."""
        if self.loading:
            self.loading.visible = loading
        if self.login_button:
            self.login_button.disabled = loading
            if loading:
                self.login_button.content = ft.Row([
                    ft.ProgressRing(width=16, height=16, color=ft.Colors.WHITE),
                    ft.Text("Connexion...", size=16),
                ], alignment=ft.MainAxisAlignment.CENTER)
            else:
                self.login_button.content = ft.Row([
                    ft.Text("Se connecter", size=16, weight=ft.FontWeight.BOLD),
                ], alignment=ft.MainAxisAlignment.CENTER)
        
        try:
            self.page.update()
        except:
            pass
    
    def _show_error(self, message: str):
        """Affiche un message d'erreur."""
        if self.error_text:
            if message:
                self.error_text.value = message
                self.error_text.visible = True
            else:
                self.error_text.visible = False
        
        try:
            self.page.update()
        except:
            pass
    
    def _show_snackbar(self, message: str, duration: int = 3000):
        """Affiche une barre de notification temporaire."""
        try:
            self.page.snack_bar = ft.SnackBar(
                content=ft.Text(message, size=13),
                duration=duration,
                behavior=ft.SnackBarBehavior.FLOATING,
            )
            self.page.snack_bar.open = True
            self.page.update()
        except Exception as e:
            logger.error(f"Erreur affichage snackbar: {e}")