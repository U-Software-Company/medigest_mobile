"""
Écran de configuration de l'application (Flet)
Gère les paramètres généraux, le profil utilisateur et les préférences
Version compatible avec les autres écrans (DashboardScreen, CartScreen)
"""

import flet as ft
from datetime import datetime
import logging
from typing import Optional, Dict, Callable
import threading

from services.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)


class ConfigScreen:
    """Écran de configuration de l'application - Style unifié avec DashboardScreen"""
    
    def __init__(
        self, 
        page: ft.Page,
        db_manager, 
        auth_service, 
        sync_service, 
        on_config_changed: Optional[Callable] = None,
        on_back: Optional[Callable] = None,
        notification_manager: Optional[Callable] = None
    ):
        """
        Initialise l'écran de configuration
        
        Args:
            page: Page Flet
            db_manager: Gestionnaire de base de données
            auth_service: Service d'authentification
            sync_service: Service de synchronisation
            on_config_changed: Callback appelé quand la configuration change
            on_back: Callback pour revenir en arrière
            notification_manager: Gestionnaire de notifications (optionnel)
        """
        self.page = page
        self.db = db_manager
        self.auth_service = auth_service
        self.sync_service = sync_service
        self.on_config_changed = on_config_changed
        self.on_back = on_back
        self.notification_manager = notification_manager
        self.auto_invoice = True
        
        # Connection Manager (Singleton) - Style DashboardScreen
        self.connection_manager = ConnectionManager()
        if sync_service is not None:
            self.connection_manager.set_sync_service(sync_service)
        self.connection_manager.register_observer(self._on_connection_status_changed)
        
        # Configuration par défaut
        self.config = self._load_config()
        
        # Conteneur principal
        self.container = ft.Container(expand=True, padding=0)
        
        # État des contrôles
        self.auto_invoice_switch = ft.Switch(value=self.config.get('auto_invoice', True))
        self.confirm_before_sale_switch = ft.Switch(value=self.config.get('confirm_before_sale', True))
        self.low_stock_alert_switch = ft.Switch(value=self.config.get('low_stock_alert', True))
        self.low_stock_threshold_slider = ft.Slider(
            min=1, 
            max=100, 
            value=float(self.config.get('low_stock_threshold', 10)),
            divisions=99,
            label="{value}"
        )
        self.print_receipt_switch = ft.Switch(value=self.config.get('print_receipt', True))
        self.dark_theme_switch = ft.Switch(value=self.config.get('dark_theme', False))
        self.receipt_copies_dropdown = ft.Dropdown(
            value=str(self.config.get('receipt_copies', 1)),
            options=[ft.dropdown.Option(str(i)) for i in range(1, 6)],
            width=100
        )
        self.language_dropdown = ft.Dropdown(
            value=self.config.get('language', 'fr'),
            options=[
                ft.dropdown.Option("fr", "Français"),
                ft.dropdown.Option("en", "English"),
                ft.dropdown.Option("ar", "العربية"),
            ],
            width=150
        )
        self.date_format_dropdown = ft.Dropdown(
            value=self.config.get('date_format', 'dd/mm/yyyy'),
            options=[
                ft.dropdown.Option("dd/mm/yyyy", "DD/MM/YYYY"),
                ft.dropdown.Option("mm/dd/yyyy", "MM/DD/YYYY"),
                ft.dropdown.Option("yyyy-mm-dd", "YYYY-MM-DD"),
            ],
            width=150
        )
        
        # État pour le confirmer frame
        self.confirm_frame = None
        
        # Composants UI pour le header (style DashboardScreen)
        self.mode_button = None
        self.internet_status_icon = None
        
        # Labels pour les informations utilisateur
        self.name_label = ft.Text("", size=16)
        self.email_label = ft.Text("", size=16)
        self.role_label = ft.Text("", size=16)
        self.user_id_label = ft.Text("", size=14, color=ft.Colors.GREY_600)
        self.last_sync_label = ft.Text("", size=14)
        
        # Labels pour les informations pharmacie
        self.pharmacy_name_label = ft.Text("", size=16)
        self.pharmacy_id_label = ft.Text("", size=14, color=ft.Colors.GREY_600)
        self.branch_name_label = ft.Text("", size=16)
        self.branch_id_label = ft.Text("", size=14, color=ft.Colors.GREY_600)
        
        # Statut de connexion
        self.connection_status_label = ft.Text("", size=14)
        
        # Flag pour vérification internet
        self._checking_started = False
        self._stop_checking = False
        
    # ==================== GESTION STATUT CONNEXION (Style DashboardScreen) ====================
    
    def _on_connection_status_changed(self, is_online: bool, force_mode: Optional[bool]):
        """Callback appelé quand le statut de connexion change"""
        logger.info(f"📡 ConfigScreen: Statut connexion changé - online={is_online}, force={force_mode}")
        if hasattr(self, 'mode_button') and self.mode_button is not None:
            self.update_mode_display()
            if self.page:
                self.page.update()
    
    def check_real_internet_status(self) -> bool:
        """Vérifie le vrai statut de la connexion internet"""
        if self.sync_service is None:
            return False
        try:
            return self.sync_service.check_internet_connection()
        except Exception as e:
            logger.error(f"Erreur check_real_internet_status: {e}")
            return False
    
    def get_current_mode(self) -> str:
        """Retourne le mode actuel (online/offline)"""
        return self.connection_manager.get_current_mode()
    
    def is_online_mode(self) -> bool:
        """Retourne True si on est en mode online"""
        return self.connection_manager.is_online_mode()
    
    def get_internet_display_status(self) -> Dict:
        """Retourne le statut à afficher"""
        status = self.connection_manager.get_display_status()
        
        color_map = {
            "green": ft.Colors.GREEN,
            "blue": ft.Colors.BLUE,
            "orange": ft.Colors.ORANGE,
            "red": ft.Colors.RED,
        }
        
        icon_map = {
            "🌐": ft.Icons.WIFI,
            "🔌": ft.Icons.WIFI,
            "✈️": ft.Icons.WIFI_OFF,
            "📡": ft.Icons.WIFI_OFF,
        }
        
        return {
            "color": color_map.get(status["color"], ft.Colors.GREY),
            "text": status["text"],
            "icon": icon_map.get(status["icon"], ft.Icons.WIFI_OFF),
            "tooltip": status["tooltip"]
        }
    
    def update_mode_display(self):
        """Met à jour l'affichage du bouton de mode (style DashboardScreen)"""
        if not hasattr(self, 'mode_button') or self.mode_button is None:
            return
        
        try:
            status = self.get_internet_display_status()
            force_mode = self.connection_manager.get_force_mode()
            mode = self.get_current_mode()
            
            # Mettre à jour l'icône si elle existe
            if hasattr(self, 'internet_status_icon') and self.internet_status_icon:
                self.internet_status_icon.name = status["icon"]
                self.internet_status_icon.color = status["color"]
                self.internet_status_icon.tooltip = status["tooltip"]
            
            # Mettre à jour le texte du bouton
            is_mobile = self._is_mobile()
            if force_mode is None:
                button_text = f"{'📱' if is_mobile else '🌐'} {mode.upper()[:3] if is_mobile else mode.upper()}"
                button_bg = ft.Colors.GREEN_700 if mode == "online" else ft.Colors.RED_700
            elif force_mode is True:
                button_text = "🔌 ON" if is_mobile else "🔌 ONLINE (Forcé)"
                button_bg = ft.Colors.BLUE_700
            else:
                button_text = "✈️ OFF" if is_mobile else "✈️ OFFLINE (Forcé)"
                button_bg = ft.Colors.ORANGE_700
            
            self.mode_button.content = ft.Text(button_text, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD, size=11)
            self.mode_button.bgcolor = button_bg
            
        except Exception as e:
            logger.error(f"Erreur dans update_mode_display: {e}")
    
    def toggle_mode(self, e):
        """Bascule entre les modes via le ConnectionManager"""
        self.connection_manager.toggle_mode()
        status = self.connection_manager.get_display_status()
        self._show_snackbar(f"Mode: {status['text']}", ft.Colors.BLUE)
        self.update_mode_display()
        if self.page:
            self.page.update()
    
    def _is_mobile(self) -> bool:
        """Détecte si l'appareil est mobile (largeur < 768px)"""
        return (self.page.width or 0) < 768
    
    def _show_snackbar(self, message: str, color, duration=3000):
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
    
    # ==================== CHARGEMENT CONFIGURATION ====================
    
    def _init_config_table(self):
        """Crée la table de configuration si elle n'existe pas"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS app_config (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        updated_at TEXT
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.error(f"Erreur création table app_config: {e}")
    
    def _load_config(self) -> Dict:
        """Charge la configuration depuis la base de données"""
        self._init_config_table()
        
        defaults = {
            'auto_invoice': True,
            'confirm_before_sale': True,
            'low_stock_alert': True,
            'low_stock_threshold': 10,
            'print_receipt': True,
            'dark_theme': False,
            'language': 'fr',
            'receipt_copies': 1,
            'date_format': 'dd/mm/yyyy'
        }
        
        try:
            config = {}
            
            # Utiliser get_connection pour lire la configuration
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Vérifier si la table existe et a des données
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='app_config'")
                if cursor.fetchone():
                    cursor.execute("SELECT key, value FROM app_config")
                    rows = cursor.fetchall()
                    
                    for row in rows:
                        key = row[0]
                        value = row[1]
                        
                        if value.lower() == 'true':
                            config[key] = True
                        elif value.lower() == 'false':
                            config[key] = False
                        elif value.isdigit():
                            config[key] = int(value)
                        else:
                            config[key] = value
            
            # Appliquer les valeurs par défaut pour les clés manquantes
            for key, default_value in defaults.items():
                if key not in config:
                    config[key] = default_value
            
            return config
            
        except Exception as e:
            logger.error(f"Erreur chargement configuration: {e}")
            return defaults
    
    def _save_config(self) -> bool:
        """Sauvegarde la configuration"""
        try:
            config_to_save = {
                'auto_invoice': str(self.auto_invoice_switch.value),
                'confirm_before_sale': str(self.confirm_before_sale_switch.value),
                'low_stock_alert': str(self.low_stock_alert_switch.value),
                'low_stock_threshold': str(int(self.low_stock_threshold_slider.value)),
                'print_receipt': str(self.print_receipt_switch.value),
                'dark_theme': str(self.dark_theme_switch.value),
                'language': self.language_dropdown.value,
                'receipt_copies': str(int(self.receipt_copies_dropdown.value)),
                'date_format': self.date_format_dropdown.value
            }
            
            now = datetime.now().isoformat()
            
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                for key, value in config_to_save.items():
                    cursor.execute(
                        "INSERT OR REPLACE INTO app_config (key, value, updated_at) VALUES (?, ?, ?)",
                        (key, value, now)
                    )
                conn.commit()
            
            # Mettre à jour la config en mémoire (valeurs typées)
            self.config = {
                'auto_invoice': self.auto_invoice_switch.value,
                'confirm_before_sale': self.confirm_before_sale_switch.value,
                'low_stock_alert': self.low_stock_alert_switch.value,
                'low_stock_threshold': int(self.low_stock_threshold_slider.value),
                'print_receipt': self.print_receipt_switch.value,
                'dark_theme': self.dark_theme_switch.value,
                'language': self.language_dropdown.value,
                'receipt_copies': int(self.receipt_copies_dropdown.value),
                'date_format': self.date_format_dropdown.value
            }
            
            # Appliquer le thème
            if self.config['dark_theme']:
                self.page.theme_mode = ft.ThemeMode.DARK
            else:
                self.page.theme_mode = ft.ThemeMode.LIGHT
            
            # Notifier le changement
            if self.on_config_changed:
                self.on_config_changed(self.config)
            
            logger.info("Configuration sauvegardée")
            return True
            
        except Exception as e:
            logger.error(f"Erreur sauvegarde configuration: {e}")
            return False
    
    # ==================== INTERFACE UTILISATEUR ====================
    
    def _create_header(self) -> ft.Container:
        """Crée l'en-tête avec le mode toggle (style DashboardScreen)"""
        status = self.get_internet_display_status()
        force_mode = self.connection_manager.get_force_mode()
        mode = self.get_current_mode()
        is_mobile = self._is_mobile()
        
        # Icône de statut internet
        self.internet_status_icon = ft.Icon(
            status["icon"],
            color=status["color"],
            size=16,
            tooltip=status["tooltip"],
        )
        
        # Déterminer le texte et la couleur du bouton de mode
        if force_mode is None:
            button_text = f"{'📱' if is_mobile else '🌐'} {mode.upper()[:3] if is_mobile else mode.upper()}"
            button_bg = ft.Colors.GREEN_700 if mode == "online" else ft.Colors.RED_700
        elif force_mode is True:
            button_text = "🔌 ON" if is_mobile else "🔌 ONLINE (Forcé)"
            button_bg = ft.Colors.BLUE_700
        else:
            button_text = "✈️ OFF" if is_mobile else "✈️ OFFLINE (Forcé)"
            button_bg = ft.Colors.ORANGE_700
        
        self.mode_button = ft.Button(
            content=ft.Text(button_text, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD, size=11),
            bgcolor=button_bg,
            on_click=self.toggle_mode,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=20),
                padding=ft.Padding.symmetric(horizontal=8, vertical=5),
            ),
            tooltip="Changer le mode (Auto/Online forcé/Offline forcé)",
        )
        
        return ft.Container(
            bgcolor=ft.Colors.BLUE_700,
            padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            content=ft.Row(
                [
                    ft.IconButton(
                        icon=ft.Icons.ARROW_BACK,
                        icon_color=ft.Colors.WHITE,
                        on_click=lambda e: self._go_back(),
                        tooltip="Retour",
                    ),
                    ft.Text(
                        "⚙️ Configuration",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.WHITE,
                        expand=True,
                    ),
                    ft.Container(
                        content=ft.Row(
                            [
                                self.internet_status_icon,
                                ft.Text(
                                    status["text"],
                                    size=11,
                                    color=status["color"],
                                    weight=ft.FontWeight.BOLD,
                                ),
                            ],
                            spacing=3,
                        ),
                        bgcolor=ft.Colors.WHITE,
                        padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                        border_radius=15,
                    ),
                    self.mode_button,
                ],
                alignment=ft.MainAxisAlignment.START,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )
    
    def _create_section(self, title: str, content: ft.Control) -> ft.Container:
        """Crée une section avec titre"""
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(title, size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_GREY_800),
                    ft.Divider(height=5, thickness=1, color=ft.Colors.GREY_300),
                    content,
                ],
                spacing=10,
            ),
            padding=15,
            border=ft.border.all(1, ft.Colors.GREY_200),
            border_radius=10,
            bgcolor=ft.Colors.WHITE,
            margin=ft.Margin.only(bottom=15),
        )
    
    def _create_profile_widgets(self) -> ft.Column:
        """Crée les widgets du profil utilisateur"""
        return ft.Column(
            [
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.PERSON, size=20, color=ft.Colors.BLUE_700),
                            ft.Text("Nom complet:", weight=ft.FontWeight.BOLD, size=14),
                            self.name_label,
                        ],
                        spacing=10,
                    ),
                    padding=ft.Padding.symmetric(vertical=5),
                ),
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.EMAIL, size=20, color=ft.Colors.BLUE_700),
                            ft.Text("Email:", weight=ft.FontWeight.BOLD, size=14),
                            self.email_label,
                        ],
                        spacing=10,
                    ),
                    padding=ft.Padding.symmetric(vertical=5),
                ),
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.WORK, size=20, color=ft.Colors.BLUE_700),
                            ft.Text("Rôle:", weight=ft.FontWeight.BOLD, size=14),
                            self.role_label,
                        ],
                        spacing=10,
                    ),
                    padding=ft.Padding.symmetric(vertical=5),
                ),
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.BADGE, size=20, color=ft.Colors.GREY_600),
                            ft.Text("ID Utilisateur:", size=12, color=ft.Colors.GREY_600),
                            self.user_id_label,
                        ],
                        spacing=10,
                    ),
                    padding=ft.Padding.symmetric(vertical=5),
                ),
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.SYNC, size=20, color=ft.Colors.GREY_600),
                            ft.Text("Dernière synchronisation:", size=12, color=ft.Colors.GREY_600),
                            self.last_sync_label,
                        ],
                        spacing=10,
                    ),
                    padding=ft.Padding.symmetric(vertical=5),
                ),
            ],
            spacing=5,
        )
    
    def _create_pharmacy_widgets(self) -> ft.Column:
        """Crée les widgets des informations de la pharmacie"""
        return ft.Column(
            [
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.LOCAL_PHARMACY, size=20, color=ft.Colors.GREEN_700),
                            ft.Text("Pharmacie:", weight=ft.FontWeight.BOLD, size=14),
                            self.pharmacy_name_label,
                        ],
                        spacing=10,
                    ),
                    padding=ft.Padding.symmetric(vertical=5),
                ),
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.NUMBERS, size=20, color=ft.Colors.GREY_600),
                            ft.Text("ID Pharmacie:", size=12, color=ft.Colors.GREY_600),
                            self.pharmacy_id_label,
                        ],
                        spacing=10,
                    ),
                    padding=ft.Padding.symmetric(vertical=5),
                ),
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.STORE, size=20, color=ft.Colors.ORANGE_700),
                            ft.Text("Branche:", weight=ft.FontWeight.BOLD, size=14),
                            self.branch_name_label,
                        ],
                        spacing=10,
                    ),
                    padding=ft.Padding.symmetric(vertical=5),
                ),
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.STORE_MALL_DIRECTORY, size=20, color=ft.Colors.GREY_600),
                            ft.Text("ID Branche:", size=12, color=ft.Colors.GREY_600),
                            self.branch_id_label,
                        ],
                        spacing=10,
                    ),
                    padding=ft.Padding.symmetric(vertical=5),
                ),
                ft.Button(
                    "🔄 Rafraîchir les informations",
                    icon=ft.Icons.REFRESH,
                    on_click=self._refresh_pharmacy_info,
                    style=ft.ButtonStyle(
                        bgcolor=ft.Colors.BLUE_50,
                        color=ft.Colors.BLUE_900,
                    ),
                ),
            ],
            spacing=5,
        )
    
    def _create_billing_widgets(self) -> ft.Column:
        """Crée les widgets des paramètres de facturation"""
        self.confirm_frame = ft.Container(
            content=ft.Row(
                [
                    self.confirm_before_sale_switch,
                    ft.Text("Demander confirmation avant d'enregistrer la facture"),
                ],
                alignment=ft.MainAxisAlignment.START,
                spacing=10,
            ),
            padding=ft.Padding.only(left=30),
        )
        
        def on_auto_invoice_change(e):
            self.confirm_frame.visible = not self.auto_invoice_switch.value
            self.page.update()
        
        self.auto_invoice_switch.on_change = on_auto_invoice_change
        on_auto_invoice_change(None)
        
        return ft.Column(
            [
                ft.Row(
                    [
                        self.auto_invoice_switch,
                        ft.Text("Générer automatiquement les factures après chaque vente"),
                    ],
                    alignment=ft.MainAxisAlignment.START,
                    spacing=10,
                ),
                self.confirm_frame,
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.INFO, size=16, color=ft.Colors.GREY_500),
                            ft.Text(
                                "Si la génération automatique est désactivée, vous devrez confirmer "
                                "manuellement avant que la facture ne soit enregistrée.",
                                size=12,
                                color=ft.Colors.GREY_600,
                            ),
                        ],
                        spacing=5,
                    ),
                    padding=ft.Padding.only(top=10),
                ),
            ],
            spacing=10,
        )
    
    def _create_alerts_widgets(self) -> ft.Column:
        """Crée les widgets des alertes"""
        threshold_row = ft.Row(
            [
                ft.Text("Seuil d'alerte (stock minimum):", size=14),
                self.low_stock_threshold_slider,
                ft.Text("unités", size=14),
            ],
            spacing=10,
            visible=self.low_stock_alert_switch.value,
        )
        
        def on_low_stock_alert_change(e):
            threshold_row.visible = self.low_stock_alert_switch.value
            self.page.update()
        
        self.low_stock_alert_switch.on_change = on_low_stock_alert_change
        
        return ft.Column(
            [
                ft.Row(
                    [
                        self.low_stock_alert_switch,
                        ft.Text("Activer les alertes de stock bas"),
                    ],
                    alignment=ft.MainAxisAlignment.START,
                    spacing=10,
                ),
                threshold_row,
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.INFO, size=16, color=ft.Colors.GREY_500),
                            ft.Text(
                                "Vous serez alerté sur le tableau de bord quand le stock d'un produit "
                                "descend en dessous de ce seuil.",
                                size=12,
                                color=ft.Colors.GREY_600,
                            ),
                        ],
                        spacing=5,
                    ),
                    padding=ft.Padding.only(top=10),
                ),
            ],
            spacing=10,
        )
    
    def _create_printing_widgets(self) -> ft.Column:
        """Crée les widgets d'impression"""
        return ft.Column(
            [
                ft.Row(
                    [
                        self.print_receipt_switch,
                        ft.Text("Imprimer automatiquement les reçus après chaque vente"),
                    ],
                    alignment=ft.MainAxisAlignment.START,
                    spacing=10,
                ),
                ft.Row(
                    [
                        ft.Text("Nombre de copies:", size=14),
                        self.receipt_copies_dropdown,
                    ],
                    spacing=10,
                ),
            ],
            spacing=10,
        )
    
    def _create_appearance_widgets(self) -> ft.Column:
        """Crée les widgets d'apparence"""
        return ft.Column(
            [
                ft.Row(
                    [
                        self.dark_theme_switch,
                        ft.Text("Activer le thème sombre"),
                    ],
                    alignment=ft.MainAxisAlignment.START,
                    spacing=10,
                ),
                ft.Row(
                    [
                        ft.Text("Langue:", size=14),
                        self.language_dropdown,
                    ],
                    spacing=10,
                ),
                ft.Row(
                    [
                        ft.Text("Format de date:", size=14),
                        self.date_format_dropdown,
                    ],
                    spacing=10,
                ),
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.INFO, size=16, color=ft.Colors.GREY_500),
                            ft.Text(
                                "Le changement de thème nécessite de rouvrir l'application.",
                                size=12,
                                color=ft.Colors.GREY_600,
                            ),
                        ],
                        spacing=5,
                    ),
                    padding=ft.Padding.only(top=10),
                ),
            ],
            spacing=10,
        )
    
    def _create_invoice_sync_widgets(self) -> ft.Column:
        """Crée les widgets de synchronisation des factures"""
        return ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.SYNC, size=20, color=ft.Colors.BLUE),
                        ft.Text("Synchronisation des factures:", size=14, weight=ft.FontWeight.BOLD),
                    ],
                    spacing=10,
                ),
                ft.Row(
                    [
                        ft.Button(
                            "🔄 Synchroniser les factures locales",
                            icon=ft.Icons.SYNC,
                            on_click=self._sync_local_invoices,
                            style=ft.ButtonStyle(
                                bgcolor=ft.Colors.BLUE_50,
                                color=ft.Colors.BLUE_900,
                            ),
                        ),
                    ],
                    spacing=10,
                ),
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.INFO, size=16, color=ft.Colors.GREY_500),
                            ft.Text(
                                "Synchronise les factures générées hors-ligne avec le serveur.",
                                size=12,
                                color=ft.Colors.GREY_600,
                            ),
                        ],
                        spacing=5,
                    ),
                    padding=ft.Padding.only(top=5),
                ),
            ],
            spacing=10,
        )

    def _sync_local_invoices(self, e):
        """Synchronise les factures locales avec le serveur"""
        if not self.connection_manager.is_online_mode():
            self._show_snackbar("❌ Mode OFFLINE - Impossible de synchroniser", ft.Colors.ORANGE_700)
            return
        
        def do_sync():
            try:
                # Créer une instance temporaire de CartScreen pour utiliser sa méthode
                from screens.cart_screen import CartScreen
                temp_cart = CartScreen(
                    self.page, self.db, self.sync_service, 
                    self.auth_service, self.current_user
                )
                temp_cart.sync_invoice_counter_with_server()
                
                self._show_snackbar("✅ Synchronisation des factures terminée", ft.Colors.GREEN_700)
            except Exception as err:
                self._show_snackbar(f"❌ Erreur: {str(err)[:100]}", ft.Colors.RED_700)
        
        threading.Thread(target=do_sync, daemon=True).start()
    
    def _create_sync_widgets(self) -> ft.Column:
        """Crée les widgets de synchronisation"""
        return ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.WIFI, size=20),
                        ft.Text("Statut:", size=14, weight=ft.FontWeight.BOLD),
                        self.connection_status_label,
                    ],
                    spacing=10,
                ),
                ft.Row(
                    [
                        ft.Button(
                            "🔄 Synchroniser maintenant",
                            icon=ft.Icons.SYNC,
                            on_click=self._sync_now,
                        ),
                        ft.OutlinedButton(
                            "📦 Importer les produits",
                            icon=ft.Icons.DOWNLOAD,
                            on_click=self._import_products,
                        ),
                    ],
                    spacing=10,
                ),
            ],
            spacing=10,
        )
    
    # ==================== CHARGEMENT DES DONNÉES ====================
    
    def _load_user_profile(self):
        """Charge et affiche les informations utilisateur"""
        user = self.auth_service.get_current_user()
        if user:
            name = user.get('nom_complet') or user.get('full_name', 'Non défini')
            self.name_label.value = name
            self.email_label.value = user.get('email', 'Non défini')
            
            role = user.get('role', 'Non défini')
            role_map = {
                'admin': 'Administrateur',
                'manager': 'Gestionnaire',
                'cashier': 'Caissier',
                'pharmacist': 'Pharmacien'
            }
            self.role_label.value = role_map.get(role, role)
            self.user_id_label.value = user.get('id', 'Non défini')
            
            pharmacy_name = user.get('pharmacy_name')
            self.pharmacy_name_label.value = pharmacy_name if pharmacy_name else 'Non définie'
            
            pharmacy_id = user.get('pharmacy_id')
            self.pharmacy_id_label.value = pharmacy_id if pharmacy_id else 'Non défini'
            
            branch_name = user.get('branch_name') or user.get('active_branch_name')
            self.branch_name_label.value = branch_name if branch_name else 'Non définie'
            
            branch_id = user.get('branch_id') or user.get('active_branch_id')
            self.branch_id_label.value = branch_id if branch_id else 'Non défini'
            
            last_sync = user.get('last_sync')
            if last_sync:
                try:
                    dt = datetime.fromisoformat(last_sync)
                    sync_text = dt.strftime("%d/%m/%Y %H:%M:%S")
                except:
                    sync_text = last_sync
            else:
                sync_text = "Jamais"
            self.last_sync_label.value = sync_text
        
        is_online = self.connection_manager.is_online_mode()
        self.connection_status_label.value = "✅ Connecté" if is_online else "❌ Hors ligne"
        self.connection_status_label.color = ft.Colors.GREEN_700 if is_online else ft.Colors.RED_700
    
    # ==================== ACTIONS ====================
    
    def _save_and_notify(self, e):
        """Sauvegarde et notifie l'utilisateur"""
        if self._save_config():
            self._show_snackbar("✅ Configuration sauvegardée avec succès !", ft.Colors.GREEN_700)
    
    def _reset_config(self, e):
        """Réinitialise la configuration aux valeurs par défaut"""
        def confirm_reset(e):
            self.auto_invoice_switch.value = True
            self.confirm_before_sale_switch.value = True
            self.low_stock_alert_switch.value = True
            self.low_stock_threshold_slider.value = 10.0
            self.print_receipt_switch.value = True
            self.dark_theme_switch.value = False
            self.language_dropdown.value = 'fr'
            self.receipt_copies_dropdown.value = '1'
            self.date_format_dropdown.value = 'dd/mm/yyyy'
            
            self._show_snackbar("Configuration réinitialisée aux valeurs par défaut. N'oubliez pas de sauvegarder.", ft.Colors.ORANGE_700)
            dialog.open = False
        
        def close_dialog(e):
            dialog.open = False
            self.page.update()
        
        dialog = ft.AlertDialog(
            title=ft.Text("Confirmation"),
            content=ft.Text(
                "Êtes-vous sûr de vouloir réinitialiser tous les paramètres ?\n"
                "Cette action ne peut pas être annulée."
            ),
            actions=[
                ft.TextButton("Annuler", on_click=close_dialog),
                ft.Button("Confirmer", on_click=confirm_reset),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()
    
    def _cancel_changes(self, e):
        """Annule les modifications et recharge la configuration"""
        def confirm_cancel(e):
            self.config = self._load_config()
            self.auto_invoice_switch.value = self.config.get('auto_invoice', True)
            self.confirm_before_sale_switch.value = self.config.get('confirm_before_sale', True)
            self.low_stock_alert_switch.value = self.config.get('low_stock_alert', True)
            self.low_stock_threshold_slider.value = float(self.config.get('low_stock_threshold', 10))
            self.print_receipt_switch.value = self.config.get('print_receipt', True)
            self.dark_theme_switch.value = self.config.get('dark_theme', False)
            self.language_dropdown.value = self.config.get('language', 'fr')
            self.receipt_copies_dropdown.value = str(self.config.get('receipt_copies', 1))
            self.date_format_dropdown.value = self.config.get('date_format', 'dd/mm/yyyy')
            
            self._show_snackbar("Modifications annulées.", ft.Colors.GREY_700)
            dialog.open = False
        
        def close_dialog(e):
            dialog.open = False
            self.page.update()
        
        dialog = ft.AlertDialog(
            title=ft.Text("Confirmation"),
            content=ft.Text("Annuler les modifications non sauvegardées ?"),
            actions=[
                ft.TextButton("Non", on_click=close_dialog),
                ft.Button("Oui", on_click=confirm_cancel),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()
    
    def _refresh_pharmacy_info(self, e):
        """Rafraîchit les informations de la pharmacie"""
        result = self.auth_service.sync_user_branch_from_server()
        
        if result.get('success'):
            self._load_user_profile()
            self._show_snackbar("✅ Informations mises à jour avec succès !", ft.Colors.GREEN_700)
        else:
            self._show_snackbar(f"⚠️ {result.get('error', 'Erreur inconnue')}", ft.Colors.RED_700)
    
    def _sync_now(self, e):
        """Déclenche une synchronisation manuelle"""
        if not self.connection_manager.is_online_mode():
            self._show_snackbar("❌ Mode OFFLINE - Impossible de synchroniser", ft.Colors.ORANGE_700, 4000)
            return
        
        def confirm_sync(e):
            dialog.open = False
            
            progress_bar = ft.ProgressBar(visible=True)
            self.page.add(progress_bar)
            self.page.update()
            
            def do_sync():
                try:
                    result = self.sync_service.sync_all(force_stock=True)
                    
                    if result.get('success', False):
                        self._load_user_profile()
                        self._show_snackbar(
                            f"✅ Synchronisation réussie !\n"
                            f"📦 Produits: {result.get('products_imported', 0)} | "
                            f"💰 Ventes: {result.get('sales_exported', 0)}",
                            ft.Colors.GREEN_700,
                            5000
                        )
                    else:
                        errors = result.get('errors', [])
                        error_text = "\n".join(errors[:3]) if errors else "Erreur inconnue"
                        self._show_snackbar(f"❌ Erreur: {error_text[:100]}", ft.Colors.RED_700)
                except Exception as ex:
                    self._show_snackbar(f"❌ Erreur: {str(ex)[:100]}", ft.Colors.RED_700)
                finally:
                    self.page.remove(progress_bar)
                    self.page.update()
            
            threading.Thread(target=do_sync, daemon=True).start()
        
        def close_dialog(e):
            dialog.open = False
            self.page.update()
        
        dialog = ft.AlertDialog(
            title=ft.Text("Synchronisation"),
            content=ft.Text(
                "Voulez-vous synchroniser toutes les données maintenant ?\n\n"
                "Cela va :\n"
                "✓ Importer les produits depuis le serveur\n"
                "✓ Exporter les ventes non synchronisées\n"
                "✓ Exporter les dépenses et dettes\n\n"
                "Cette opération peut prendre quelques secondes."
            ),
            actions=[
                ft.TextButton("Annuler", on_click=close_dialog),
                ft.Button("Confirmer", on_click=confirm_sync),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()
    
    def _import_products(self, e):
        """Importe uniquement les produits"""
        if not self.connection_manager.is_online_mode():
            self._show_snackbar("❌ Mode OFFLINE - Impossible d'importer", ft.Colors.ORANGE_700, 4000)
            return
        
        def confirm_import(e):
            dialog.open = False
            
            progress_bar = ft.ProgressBar(visible=True)
            self.page.add(progress_bar)
            self.page.update()
            
            def do_import():
                try:
                    result = self.sync_service.import_products_improved()
                    
                    if result.get('success'):
                        self._load_user_profile()
                        self._show_snackbar(f"✅ {result.get('count', 0)} produits importés avec succès !", ft.Colors.GREEN_700)
                    else:
                        self._show_snackbar(f"❌ Erreur: {result.get('error', 'Erreur inconnue')}", ft.Colors.RED_700)
                except Exception as ex:
                    self._show_snackbar(f"❌ Erreur: {str(ex)[:100]}", ft.Colors.RED_700)
                finally:
                    self.page.remove(progress_bar)
                    self.page.update()
            
            threading.Thread(target=do_import, daemon=True).start()
        
        def close_dialog(e):
            dialog.open = False
            self.page.update()
        
        dialog = ft.AlertDialog(
            title=ft.Text("Import des produits"),
            content=ft.Text(
                "Voulez-vous importer tous les produits depuis le serveur ?\n\n"
                "Cela va remplacer les produits locaux par les données du serveur."
            ),
            actions=[
                ft.TextButton("Annuler", on_click=close_dialog),
                ft.Button("Confirmer", on_click=confirm_import),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()
    
    # ==================== AFFICHAGE PRINCIPAL ====================
    
    def _build(self):
        """Construit l'interface utilisateur complète"""
        
        # Contenu scrollable principal
        main_content = ft.Column(
            [
                self._create_header(),
                ft.Container(
                    content=ft.ListView(
                        [
                            self._create_section("👤 Mon profil", self._create_profile_widgets()),
                            self._create_section("🏥 Informations de la pharmacie", self._create_pharmacy_widgets()),
                            self._create_section("🧾 Paramètres de facturation", self._create_billing_widgets()),
                            self._create_section("⚠️ Alertes et stock", self._create_alerts_widgets()),
                            self._create_section("🖨️ Impression", self._create_printing_widgets()),
                            self._create_section("🎨 Apparence", self._create_appearance_widgets()),
                            self._create_section("🔄 Synchronisation", self._create_sync_widgets()),
                            ft.Container(
                                content=ft.Row(
                                    [
                                        ft.Button(
                                            "💾 Sauvegarder",
                                            icon=ft.Icons.SAVE,
                                            on_click=self._save_and_notify,
                                            style=ft.ButtonStyle(
                                                bgcolor=ft.Colors.GREEN_700,
                                                color=ft.Colors.WHITE,
                                            )
                                        ),
                                        ft.OutlinedButton(
                                            "↺ Réinitialiser",
                                            icon=ft.Icons.RESTART_ALT,
                                            on_click=self._reset_config,
                                        ),
                                        ft.TextButton(
                                            "❌ Annuler",
                                            icon=ft.Icons.CANCEL,
                                            on_click=self._cancel_changes,
                                        ),
                                    ],
                                    alignment=ft.MainAxisAlignment.END,
                                    spacing=10,
                                ),
                                padding=ft.Padding.only(top=10, bottom=10),
                            ),
                            ft.Container(
                                content=ft.Text(
                                    "Version 1.0.0 | © 2024 MediGest POS",
                                    size=12,
                                    color=ft.Colors.GREY_500,
                                ),
                                alignment=ft.Alignment.CENTER,
                                padding=ft.Padding.only(top=20),
                            ),
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
        
        # SafeArea pour éviter les bords système
        self.container.content = ft.SafeArea(
            content=main_content,
            expand=True,
        )
    
    def show(self):
        """Affiche l'écran de configuration - style unifié avec les autres écrans"""
        self._build()
        self._load_user_profile()
        self.update_mode_display()
        
        # Nettoyer la page et ajouter le conteneur (comme les autres écrans)
        self.page.clean()
        self.page.add(self.container)
        self.page.update()
        
    def _go_back(self, e=None):
        """Retourne à l'écran précédent"""
        if self.on_back:
            self.on_back()
    
    # === MÉTHODES PUBLIQUES ===
    
    def get_config(self) -> Dict:
        """Retourne la configuration actuelle"""
        return self.config
    
    def is_auto_invoice(self) -> bool:
        """Retourne True si la génération automatique de facture est activée"""
        return self.auto_invoice_switch.value
    
    def is_confirm_before_sale(self) -> bool:
        """Retourne True si la confirmation avant vente est activée"""
        return self.confirm_before_sale_switch.value
    
    def get_low_stock_threshold(self) -> int:
        """Retourne le seuil d'alerte de stock bas"""
        return int(self.low_stock_threshold_slider.value)
    
    def is_print_receipt(self) -> bool:
        """Retourne True si l'impression automatique est activée"""
        return self.print_receipt_switch.value
    
    def get_receipt_copies(self) -> int:
        """Retourne le nombre de copies d'impression"""
        return int(self.receipt_copies_dropdown.value)
    
    def get_language(self) -> str:
        """Retourne la langue sélectionnée"""
        return self.language_dropdown.value
    
    def get_date_format(self) -> str:
        """Retourne le format de date sélectionné"""
        return self.date_format_dropdown.value
    
    def get_theme_mode(self) -> ft.ThemeMode:
        """Retourne le mode de thème"""
        return ft.ThemeMode.DARK if self.dark_theme_switch.value else ft.ThemeMode.LIGHT
    
    def __del__(self):
        """Nettoyage lors de la destruction"""
        try:
            self.connection_manager.unregister_observer(self._on_connection_status_changed)
        except:
            pass