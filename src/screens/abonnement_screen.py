# screens/abonnement_screen.py
"""
Écran d'affichage des informations d'abonnement
"""

import flet as ft
from datetime import datetime, date
from typing import Dict, Optional
import threading
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.paths import get_app_dir


class AbonnementScreen:
    """Écran affichant les détails de l'abonnement de l'utilisateur"""
    
    def __init__(self, page: ft.Page, db, sync_service, auth_service, current_user, notification_manager=None):
        self.page = page
        self.db = db
        self.sync_service = sync_service
        self.auth_service = auth_service
        self.current_user = current_user
        self.notification_manager = notification_manager
        self.subscription_data = None
        self.is_loading = False
        self.subscription_cache_file = os.path.join(get_app_dir(), "subscription_cache.json")
    
    def load_subscription_from_cache(self) -> Dict:
        """Charge les données d'abonnement depuis auth_service (SQLite) ou fallback JSON"""
        try:
            # 🔄 PRIORITÉ 1: Lire depuis auth_service (SQLite)
            subscription_info = self.auth_service.get_subscription_info()
            
            if subscription_info and isinstance(subscription_info, dict) and subscription_info.get('info'):
                # Format stocké par auth_service.save_subscription_info()
                info = subscription_info.get('info', {})
                if info:
                    return self._format_subscription_data(info, subscription_info)
            
            # 🔄 PRIORITÉ 2: Lire depuis get_current_user (SQLite)
            user = self.auth_service.get_current_user()
            if user and user.get('subscription_data'):
                try:
                    sub_data = user.get('subscription_data')
                    if isinstance(sub_data, str):
                        sub_data = json.loads(sub_data)
                    
                    if sub_data and isinstance(sub_data, dict):
                        info = sub_data.get('info', {})
                        if info:
                            return self._format_subscription_data(info, sub_data)
                except Exception as e:
                    print(f"Erreur parsing subscription_data: {e}")
            
            # 🔄 PRIORITÉ 3: Lire depuis subscription_cache.json (fallback)
            cache_path = self.subscription_cache_file
            if os.path.exists(cache_path):
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                
                info = cache_data.get('info', {})
                if info:
                    return self._format_subscription_data(info, cache_data)
            
            # Valeurs par défaut
            return self._get_default_subscription_data()
            
        except Exception as e:
            print(f"Erreur chargement abonnement: {e}")
            return self._get_default_subscription_data()
    
    def _format_subscription_data(self, info: Dict, cache_data: Dict = None) -> Dict:
        """Formate les données d'abonnement pour l'affichage"""
        
        subscription = info.get('subscription', {})
        limits = info.get('limits', {})
        usage = info.get('usage', {})
        
        # Récupérer les informations principales
        days_remaining = subscription.get('days_remaining', 0)
        is_active = info.get('is_active', False)
        has_subscription = info.get('has_subscription', True)
        access_mode = info.get('access_mode', 'full')
        
        # Récupérer le nom du plan
        plan_name = subscription.get('plan_name', 'Standard')
        plan_type = subscription.get('plan_type', subscription.get('plan', 'professional'))
        is_trial = subscription.get('is_trial', False)
        trial_days_remaining = subscription.get('trial_days_remaining', 0)
        
        # Récupérer les limites
        max_products = limits.get('max_products', 'Illimité')
        max_users = limits.get('max_users', 'Illimité')
        max_branches = limits.get('max_branches', 'Illimité')
        max_storage_mb = limits.get('max_storage_mb', 0)
        
        # Convertir MB en GB si nécessaire
        if max_storage_mb and isinstance(max_storage_mb, (int, float)) and max_storage_mb > 0:
            max_storage_gb = round(max_storage_mb / 1024, 1)
        else:
            max_storage_gb = 'Illimité'
        
        # Récupérer l'utilisation
        current_products = usage.get('current_products', 0)
        current_users = usage.get('current_users', 0)
        current_branches = usage.get('current_branches', 1)
        current_storage_mb = usage.get('current_storage_mb', 0)
        
        # Convertir l'utilisation en GB
        if current_storage_mb > 0:
            current_storage_gb = round(current_storage_mb / 1024, 1)
        else:
            current_storage_gb = 0
        
        # Liste des fonctionnalités selon le plan
        features = self._get_features_for_plan(plan_type, is_trial)
        
        # Déterminer le statut et le message
        status_message = self._get_status_message(is_active, days_remaining, is_trial, trial_days_remaining)
        
        return {
            "has_subscription": has_subscription,
            "is_active": is_active,
            "plan": plan_type,
            "plan_name": plan_name,
            "is_trial": is_trial,
            "trial_days_remaining": trial_days_remaining,
            "start_date": subscription.get('current_period_start') or subscription.get('start_date'),
            "end_date": subscription.get('current_period_end') or subscription.get('end_date'),
            "days_remaining": days_remaining,
            "limits": {
                "max_products": max_products,
                "max_users": max_users,
                "max_branches": max_branches,
                "max_storage_gb": max_storage_gb,
                "features": features
            },
            "usage": {
                "current_products": current_products,
                "current_users": current_users,
                "current_branches": current_branches,
                "current_storage_gb": current_storage_gb
            },
            "has_full_access": access_mode == 'full',
            "access_mode": access_mode,
            "message": status_message,
            "last_update": info.get('synced_at') or info.get('last_update') or (cache_data.get('last_update') if cache_data else None),
            "subscription_id": subscription.get('id'),
            "auto_renew": subscription.get('auto_renew', False),
            "billing_cycle": subscription.get('billing_cycle', 'monthly'),
            "price": subscription.get('price', 0),
            "currency": subscription.get('currency', 'EUR')
        }
    
    def _get_features_for_plan(self, plan_type: str, is_trial: bool = False) -> list:
        """Retourne la liste des fonctionnalités selon le plan"""
        
        # Fonctionnalités de base (tous les plans)
        base_features = [
            "✅ Ventes et facturation",
            "✅ Gestion des produits",
            "✅ Historique des ventes",
            "✅ Gestion des clients",
            "✅ Rapports quotidiens"
        ]
        
        # Fonctionnalités avancées
        pro_features = [
            "✅ Gestion multi-branches",
            "✅ Gestion des stocks avancée",
            "✅ Alertes stock bas",
            "✅ Export de rapports",
            "✅ Sauvegarde automatique"
        ]
        
        # Fonctionnalités premium
        premium_features = [
            "✅ Support prioritaire",
            "✅ API personnalisée",
            "✅ Formation incluse",
            "✅ Personnalisation avancée"
        ]
        
        # Pendant la période d'essai, toutes les fonctionnalités sont disponibles
        if is_trial:
            return base_features + pro_features + premium_features + ["✨ Période d'essai - Toutes les fonctionnalités"]
        
        # Sinon, selon le plan
        plan_lower = str(plan_type).lower()
        if plan_lower in ['premium', 'enterprise']:
            return base_features + pro_features + premium_features
        elif plan_lower in ['pro', 'business', 'professional']:
            return base_features + pro_features
        else:
            return base_features
    
    def _get_status_message(self, is_active: bool, days_remaining: int, is_trial: bool, trial_days_remaining: int) -> str:
        """Retourne un message de statut approprié"""
        if not is_active:
            return "⚠️ Abonnement expiré - Mode lecture seule"
        elif is_trial and trial_days_remaining > 0:
            return f"🎉 Période d'essai - Plus que {trial_days_remaining} jour(s)"
        elif days_remaining <= 7 and days_remaining > 0:
            return f"⏰ Expire dans {days_remaining} jour(s) - Pensez à renouveler"
        elif days_remaining > 0:
            return f"✅ Abonnement actif - Valable {days_remaining} jours"
        else:
            return "✅ Abonnement actif"
    
    def _get_default_subscription_data(self) -> Dict:
        """Retourne des données d'abonnement par défaut (mode hors ligne)"""
        return {
            "has_subscription": True,
            "is_active": True,
            "plan": "professional",
            "plan_name": "Standard",
            "is_trial": False,
            "trial_days_remaining": 0,
            "start_date": None,
            "end_date": None,
            "days_remaining": 30,
            "limits": {
                "max_products": "Illimité",
                "max_users": "Illimité",
                "max_branches": "Illimité",
                "max_storage_gb": "Illimité",
                "features": ["✅ Ventes et facturation", "✅ Gestion des produits", "✅ Synchronisation cloud"]
            },
            "usage": {
                "current_products": 0,
                "current_users": 1,
                "current_branches": 1,
                "current_storage_gb": 0
            },
            "has_full_access": True,
            "access_mode": "full",
            "message": "Synchronisez pour obtenir les informations à jour",
            "last_update": None
        }
    
    def sync_subscription(self, e=None):
        """Synchronise les données d'abonnement avec le serveur"""
        if self.is_loading:
            return
        
        def sync_in_background():
            self.is_loading = True
            
            try:
                if hasattr(self.sync_service, 'sync_subscription'):
                    result = self.sync_service.sync_subscription()
                    
                    if result.get('success'):
                        # Forcer la mise à jour du cache dans auth_service
                        subscription_info = result.get('subscription', {})
                        if subscription_info:
                            self.auth_service.save_subscription_info(subscription_info)
                        
                        # Recharger les données depuis auth_service
                        self.subscription_data = self.load_subscription_from_cache()
                        
                        # Mettre à jour l'affichage
                        def update_ui():
                            self.refresh_display()
                            if self.subscription_data.get('is_active'):
                                msg = "✅ Abonnement synchronisé avec succès"
                                if self.subscription_data.get('is_trial'):
                                    days = self.subscription_data.get('trial_days_remaining', 0)
                                    msg = f"🎉 Période d'essai - {days} jours restants"
                                self.show_snackbar(msg, ft.Colors.GREEN)
                            else:
                                self.show_snackbar("⚠️ Abonnement expiré ou inactif", ft.Colors.ORANGE)
                            self.is_loading = False
                            self.page.update()
                        
                        self.page.run_task(update_ui)
                    else:
                        error = result.get('error', 'Erreur inconnue')
                        self.show_snackbar(f"❌ Erreur: {error}", ft.Colors.RED)
                        self.is_loading = False
                else:
                    self.show_snackbar("⚠️ Service de synchronisation non disponible", ft.Colors.ORANGE)
                    self.is_loading = False
                    
            except Exception as e:
                print(f"Erreur synchronisation abonnement: {e}")
                self.show_snackbar(f"❌ Erreur: {str(e)}", ft.Colors.RED)
                self.is_loading = False
        
        self.show_snackbar("🔄 Synchronisation en cours...", ft.Colors.BLUE)
        thread = threading.Thread(target=sync_in_background, daemon=True)
        thread.start()
    
    def refresh_display(self):
        """Rafraîchit l'affichage des données"""
        self.content_container.content = self._build_main_content()
        self.page.update()
    
    def show_snackbar(self, message: str, color, duration=3000):
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
    
    def show(self):
        """Affiche l'écran d'abonnement"""
        self.page.clean()
        
        # Charger les données depuis auth_service
        self.subscription_data = self.load_subscription_from_cache()
        
        # Header
        header = ft.Container(
            content=ft.Row([
                ft.IconButton(
                    icon=ft.Icons.ARROW_BACK,
                    icon_color=ft.Colors.WHITE,
                    on_click=lambda e: self.go_back(),
                ),
                ft.Text("Mon abonnement", size=22, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE, expand=True),
                ft.IconButton(
                    icon=ft.Icons.SYNC,
                    icon_color=ft.Colors.WHITE,
                    on_click=self.sync_subscription,
                    tooltip="Synchroniser",
                ),
            ]),
            padding=15,
            bgcolor=ft.Colors.BLUE_700,
        )
        
        # Contenu principal
        self.content_container = ft.Container(
            content=self._build_main_content(),
            expand=True,
            padding=15,
        )
        
        # Layout principal
        main_content = ft.Column([
            header,
            self.content_container,
        ], expand=True, spacing=0)
        
        self.page.add(main_content)
        self.page.update()
    
    def go_back(self):
        """Retour à l'écran précédent"""
        from screens.dashboard_screen import DashboardScreen
        dashboard = DashboardScreen(
            self.page, self.db, self.sync_service, 
            self.auth_service, self.current_user,
            self.notification_manager
        )
        dashboard.show()
    
    def _build_main_content(self) -> ft.Column:
        """Construit le contenu principal de l'écran"""
        data = self.subscription_data
        
        # Carte principale d'état
        status_card = self._build_status_card(data)
        
        # Carte des limites
        limits_card = self._build_limits_card(data)
        
        # Carte d'utilisation
        usage_card = self._build_usage_card(data)
        
        # Informations de synchronisation
        sync_info = self._build_sync_info(data)
        
        # Actions
        actions = self._build_actions(data)
        
        # Détails de l'abonnement (pour les périodes d'essai)
        trial_info = self._build_trial_info(data) if data.get('is_trial') else None
        
        children = [
            status_card,
            ft.Divider(height=20, color=ft.Colors.TRANSPARENT),
            ft.Text("📊 Utilisation", size=16, weight=ft.FontWeight.BOLD),
            ft.Container(height=5),
            usage_card,
            ft.Divider(height=20, color=ft.Colors.TRANSPARENT),
            ft.Text("⚙️ Limites du plan", size=16, weight=ft.FontWeight.BOLD),
            ft.Container(height=5),
            limits_card,
        ]
        
        if trial_info:
            children.extend([
                ft.Divider(height=20, color=ft.Colors.TRANSPARENT),
                trial_info
            ])
        
        children.extend([
            ft.Divider(height=20, color=ft.Colors.TRANSPARENT),
            sync_info,
            actions,
        ])
        
        return ft.Column(children, spacing=0)
    
    def _build_trial_info(self, data: Dict) -> ft.Card:
        """Construit la carte d'information pour la période d'essai"""
        trial_days = data.get('trial_days_remaining', 0)
        
        return ft.Card(
            content=ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.CELEBRATION, size=24, color=ft.Colors.PURPLE_600),
                        ft.Text("Période d'essai", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.PURPLE_600),
                    ], spacing=10),
                    ft.Text(f"Plus que {trial_days} jour(s) d'essai", size=14),
                    ft.Text(
                        "Profitez de toutes les fonctionnalités premium pendant votre période d'essai",
                        size=12,
                        color=ft.Colors.GREY_600,
                    ),
                ], spacing=10),
                padding=15,
                bgcolor=ft.Colors.PURPLE_50,
                border_radius=10,
            ),
            elevation=1,
        )
    
    def _build_status_card(self, data: Dict) -> ft.Card:
        """Construit la carte d'état de l'abonnement"""
        
        is_active = data.get('is_active', True)
        has_subscription = data.get('has_subscription', True)
        plan_name = data.get('plan_name', 'Standard')
        days_remaining = data.get('days_remaining')
        end_date = data.get('end_date')
        is_trial = data.get('is_trial', False)
        
        # Déterminer les couleurs et icônes
        if is_trial:
            status_color = ft.Colors.PURPLE_600
            status_icon = ft.Icons.CELEBRATION
            status_text = "Période d'essai active"
            status_subtext = f"Plus que {data.get('trial_days_remaining', 0)} jours"
        elif not has_subscription:
            status_color = ft.Colors.ORANGE_600
            status_icon = ft.Icons.WARNING
            status_text = "Aucun abonnement actif"
            status_subtext = "Synchronisez pour activer votre abonnement"
        elif not is_active:
            status_color = ft.Colors.RED_600
            status_icon = ft.Icons.ERROR
            status_text = "Abonnement expiré"
            status_subtext = "Veuillez renouveler votre abonnement"
        elif days_remaining is not None and days_remaining <= 7:
            status_color = ft.Colors.ORANGE_600
            status_icon = ft.Icons.WARNING_AMBER
            status_text = f"Expire dans {days_remaining} jour(s)"
            status_subtext = "Pensez à renouveler prochainement"
        else:
            status_color = ft.Colors.GREEN_600
            status_icon = ft.Icons.CHECK_CIRCLE
            status_text = "Abonnement actif"
            status_subtext = "Toutes les fonctionnalités sont disponibles"
        
        # Formater la date de fin
        end_date_text = ""
        if end_date:
            try:
                if isinstance(end_date, str):
                    if 'T' in end_date:
                        end_date = end_date.split('T')[0]
                    end_date_text = f"Valable jusqu'au {end_date}"
            except:
                pass
        
        # Construction de la colonne du contenu
        content_controls = [
            ft.Row([
                ft.Icon(status_icon, color=status_color, size=48),
                ft.Column([
                    ft.Text(plan_name, size=20, weight=ft.FontWeight.BOLD),
                    ft.Text(status_text, size=14, color=status_color),
                    ft.Text(status_subtext, size=12, color=ft.Colors.GREY_600),
                    ft.Text(end_date_text, size=12, color=ft.Colors.GREY_500) if end_date_text else ft.Container(),
                ], spacing=5, expand=True),
            ], spacing=15)
        ]
        
        # Ajouter la progression si nécessaire
        if days_remaining is not None and has_subscription and not is_trial and days_remaining > 0 and days_remaining < 365:
            progress_value = max(0, min(1, days_remaining / 365))
            content_controls.append(ft.Container(height=10))
            content_controls.append(ft.Text(f"Jours restants: {days_remaining}", size=14))
            content_controls.append(
                ft.ProgressBar(
                    value=progress_value,
                    height=8,
                    color=status_color,
                    bgcolor=ft.Colors.GREY_200,
                )
            )
        elif is_trial:
            trial_days = data.get('trial_days_remaining', 14)
            if trial_days > 0:
                progress_value = max(0, min(1, trial_days / 14))
                content_controls.append(ft.Container(height=10))
                content_controls.append(ft.Text(f"Jours d'essai restants: {trial_days} / 14", size=14))
                content_controls.append(
                    ft.ProgressBar(
                        value=progress_value,
                        height=8,
                        color=ft.Colors.PURPLE_400,
                        bgcolor=ft.Colors.GREY_200,
                    )
                )
        
        return ft.Card(
            content=ft.Container(
                content=ft.Column(content_controls),
                padding=20,
            ),
            elevation=2,
        )
    
    def _build_limits_card(self, data: Dict) -> ft.GridView:
        """Construit la carte des limites du plan"""
        
        limits = data.get('limits', {})
        
        limit_items = [
            ("📦 Produits", limits.get('max_products', 'Illimité'), ft.Colors.BLUE_400),
            ("👥 Utilisateurs", limits.get('max_users', 'Illimité'), ft.Colors.PURPLE_400),
            ("🏢 Succursales", limits.get('max_branches', 'Illimité'), ft.Colors.GREEN_400),
            ("💾 Stockage", limits.get('max_storage_gb', 'Illimité'), ft.Colors.ORANGE_400),
        ]
        
        cards = []
        for title, value, color in limit_items:
            display_value = str(value)
            if isinstance(value, (int, float)) and value > 0:
                if value >= 1000:
                    display_value = f"{value/1000:.0f}k"
                else:
                    display_value = str(value)
            
            cards.append(
                ft.Container(
                    content=ft.Column([
                        ft.Text(title, size=12, color=ft.Colors.GREY_600),
                        ft.Text(display_value, size=20, weight=ft.FontWeight.BOLD, color=color),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=5),
                    padding=15,
                    bgcolor=ft.Colors.GREY_50,
                    border_radius=10,
                )
            )
        
        return ft.GridView(
            controls=cards,
            runs_count=2,
            max_extent=150,
            spacing=10,
            run_spacing=10,
        )
    
    def _build_usage_card(self, data: Dict) -> ft.Card:
        """Construit la carte d'utilisation actuelle"""
        
        usage = data.get('usage', {})
        limits = data.get('limits', {})
        
        max_products = limits.get('max_products', 'Illimité')
        max_users = limits.get('max_users', 'Illimité')
        max_branches = limits.get('max_branches', 'Illimité')
        max_storage = limits.get('max_storage_gb', 'Illimité')
        
        current_products = usage.get('current_products', 0)
        current_users = usage.get('current_users', 0)
        current_branches = usage.get('current_branches', 0)
        current_storage = usage.get('current_storage_gb', 0)
        
        def get_percent(current, max_val):
            if isinstance(max_val, (int, float)) and max_val > 0:
                return min(100, (current / max_val * 100))
            return 0
        
        def build_usage_row(title: str, current, max_val, percent: float, color: str):
            max_display = str(max_val) if max_val != 'Illimité' else '∞'
            current_display = str(current)
            
            bar_color = color
            if percent >= 90:
                bar_color = ft.Colors.RED_400
            elif percent >= 75:
                bar_color = ft.Colors.ORANGE_400
            
            return ft.Column([
                ft.Row([
                    ft.Text(title, size=13, weight=ft.FontWeight.BOLD, expand=True),
                    ft.Text(f"{current_display} / {max_display}", size=13, color=bar_color if percent >= 75 else ft.Colors.GREY_700),
                ]),
                ft.ProgressBar(value=min(1, percent / 100), height=6, color=bar_color, bgcolor=ft.Colors.GREY_200),
            ], spacing=5)
        
        usage_items = []
        
        if max_products != 'Illimité' and max_products != '?':
            products_percent = get_percent(current_products, max_products)
            usage_items.append(build_usage_row("Produits", current_products, max_products, products_percent, ft.Colors.BLUE_400))
        
        if max_users != 'Illimité' and max_users != '?':
            users_percent = get_percent(current_users, max_users)
            usage_items.append(build_usage_row("Utilisateurs", current_users, max_users, users_percent, ft.Colors.PURPLE_400))
        
        if max_branches != 'Illimité' and max_branches != '?':
            branches_percent = get_percent(current_branches, max_branches)
            usage_items.append(build_usage_row("Succursales", current_branches, max_branches, branches_percent, ft.Colors.GREEN_400))
        
        if max_storage != 'Illimité' and max_storage != '?' and isinstance(max_storage, (int, float)):
            storage_percent = get_percent(current_storage, max_storage)
            usage_items.append(build_usage_row("Stockage (Go)", current_storage, max_storage, storage_percent, ft.Colors.ORANGE_400))
        
        features = limits.get('features', [])
        
        features_grid = ft.GridView(
            controls=[
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.CHECK_CIRCLE, size=16, color=ft.Colors.GREEN_600),
                        ft.Text(feature.replace("✅ ", ""), size=12, color=ft.Colors.GREY_700),
                    ], spacing=5),
                    padding=ft.Padding.only(right=15, bottom=5),
                ) for feature in features
            ],
            runs_count=2,
            max_extent=200,
            spacing=5,
            run_spacing=5,
        )
        
        content_controls = [
            ft.Text("📈 Utilisation actuelle", size=14, weight=ft.FontWeight.BOLD),
            ft.Divider(height=10),
        ]
        
        if usage_items:
            content_controls.extend(usage_items)
        else:
            content_controls.append(ft.Text("Aucune limite définie", size=12, color=ft.Colors.GREY_500))
        
        if features:
            content_controls.extend([
                ft.Divider(height=15),
                ft.Text("✨ Fonctionnalités incluses", size=13, weight=ft.FontWeight.BOLD),
                features_grid,
            ])
        
        return ft.Card(
            content=ft.Container(
                content=ft.Column(content_controls),
                padding=15,
            ),
            elevation=1,
        )
    
    def _build_sync_info(self, data: Dict) -> ft.Container:
        """Construit les informations de synchronisation"""
        
        last_update = data.get('last_update')
        access_mode = data.get('access_mode', 'full')
        message = data.get('message', '')
        
        last_update_text = "Jamais synchronisé"
        if last_update:
            try:
                if isinstance(last_update, str):
                    last_update = last_update.replace('Z', '+00:00')
                    dt = datetime.fromisoformat(last_update)
                    last_update_text = f"Dernière sync: {dt.strftime('%d/%m/%Y %H:%M')}"
            except:
                pass
        
        mode_color = ft.Colors.GREEN_600 if access_mode == 'full' else ft.Colors.ORANGE_600
        mode_text = "Mode complet" if access_mode == 'full' else "Mode lecture seule"
        
        content_controls = [
            ft.Row([
                ft.Icon(ft.Icons.INFO_OUTLINE, size=18, color=ft.Colors.GREY_500),
                ft.Text(last_update_text, size=12, color=ft.Colors.GREY_500),
            ], spacing=5),
            ft.Row([
                ft.Icon(ft.Icons.MODE, size=18, color=mode_color),
                ft.Text(f"Mode: {mode_text}", size=12, color=mode_color),
            ], spacing=5)
        ]
        
        if message:
            content_controls.append(
                ft.Text(message, size=12, color=ft.Colors.ORANGE_600, italic=True)
            )
        
        return ft.Container(
            content=ft.Column(content_controls, spacing=8),
            padding=10,
            bgcolor=ft.Colors.GREY_50,
            border_radius=10,
        )
    
    def _build_actions(self, data: Dict) -> ft.Row:
        """Construit les boutons d'action"""
        
        is_active = data.get('is_active', True)
        is_trial = data.get('is_trial', False)
        
        actions = []
        
        actions.append(
            ft.Button(
                content=ft.Row([
                    ft.Icon(ft.Icons.SYNC, size=18),
                    ft.Text("Synchroniser", size=14),
                ], spacing=8),
                on_click=self.sync_subscription,
                style=ft.ButtonStyle(
                    color=ft.Colors.WHITE,
                    bgcolor=ft.Colors.BLUE_600,
                    padding=12,
                    shape=ft.RoundedRectangleBorder(radius=8),
                ),
            )
        )
        
        if not is_trial and (not is_active or (data.get('days_remaining') is not None and data.get('days_remaining') <= 7)):
            actions.append(
                ft.Button(
                    content=ft.Row([
                        ft.Icon(ft.Icons.SHOPPING_CART, size=18),
                        ft.Text("Renouveler", size=14),
                    ], spacing=8),
                    on_click=self.go_to_renewal,
                    style=ft.ButtonStyle(
                        color=ft.Colors.WHITE,
                        bgcolor=ft.Colors.GREEN_600,
                        padding=12,
                        shape=ft.RoundedRectangleBorder(radius=8),
                    ),
                )
            )
        
        return ft.Row(actions, alignment=ft.MainAxisAlignment.CENTER, spacing=15)
    
    def go_to_renewal(self, e):
        """Redirige vers la page de renouvellement"""
        self.show_snackbar(
            "📞 Contactez le support pour renouveler votre abonnement +243820586551",
            ft.Colors.BLUE,
            5000
        )