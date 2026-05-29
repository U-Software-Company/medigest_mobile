# screens/dashboard_details_screen.py

import flet as ft
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Any
import logging
import requests

logger = logging.getLogger(__name__)


class DashboardDetailsScreen:
    """Écran d'affichage des détails spécifiques au tableau de bord"""
    
    def __init__(
        self, 
        page: ft.Page, 
        db, 
        sync_service, 
        auth_service, 
        current_user, 
        notification_manager=None,
        title: str = None,
        detail_type: str = None,
        data: Dict = None
    ):
        self.page = page
        self.db = db
        self.sync_service = sync_service
        self.auth_service = auth_service
        self.current_user = current_user
        self.notification_manager = notification_manager
        self.title = title
        self.detail_type = detail_type
        self.data = data or {}
        
        # État
        self.is_mobile = (page.width or 0) < 768
        self.is_online = self._check_internet_connection()
        
        # Cache pour les données
        self.sales_details_cache = {}
        self.sellers_cache = []
        
    def _check_internet_connection(self) -> bool:
        """Vérifie la connexion internet via sync_service"""
        if self.sync_service and hasattr(self.sync_service, 'check_internet_connection'):
            return self.sync_service.check_internet_connection()
        return False
    
    def _get_headers(self) -> Optional[Dict]:
        """Récupère les headers d'authentification"""
        user = self.auth_service.get_current_user() if self.auth_service else self.current_user
        if not user:
            return None
        
        token = user.get('token')
        if not token:
            return None
        
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
    
    def _get_api_base_url(self) -> str:
        """Récupère l'URL de base de l'API"""
        if self.sync_service and hasattr(self.sync_service, 'api_url'):
            return self.sync_service.api_url
        return "https://my-backend-ydit.onrender.com/api/v1"
    
    def _safe_number(self, value, default=0.0) -> float:
        """Convertit une valeur en nombre de manière sécurisée"""
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            # Nettoyer la chaîne (enlever les espaces, FC, etc.)
            cleaned = value.replace(' ', '').replace('FC', '').replace(',', '').strip()
            try:
                return float(cleaned) if cleaned else default
            except ValueError:
                return default
        return default
    
    # ==================== RÉCUPÉRATION DES DONNÉES ====================
    
    def _fetch_sales_from_server(self, sale_id: str = None, filters: Dict = None) -> Dict:
        """Récupère les ventes depuis le serveur (dashboard.py, sales.py)"""
        headers = self._get_headers()
        if not headers:
            return {"success": False, "error": "Non authentifié", "items": []}
        
        api_url = self._get_api_base_url()
        
        try:
            if sale_id:
                # Détail d'une vente spécifique
                response = self.sync_service.session.get(
                    f"{api_url}/sales/{sale_id}",
                    headers=headers,
                    timeout=30
                )
            else:
                # Liste des ventes avec filtres
                params = {}
                if filters:
                    params.update(filters)
                
                response = self.sync_service.session.get(
                    f"{api_url}/sales",
                    headers=headers,
                    params=params,
                    timeout=30
                )
            
            if response.status_code == 200:
                data = response.json()
                if sale_id:
                    return {"success": True, "sale": data}
                else:
                    items = data.get("items", data.get("sales", []))
                    # Convertir les montants en nombres
                    for item in items:
                        item["total_amount"] = self._safe_number(item.get("total_amount", 0))
                    return {"success": True, "items": items, "total": data.get("total", len(items))}
            else:
                return {"success": False, "error": f"Erreur {response.status_code}", "items": []}
                
        except Exception as e:
            logger.error(f"Erreur fetch_sales_from_server: {e}")
            return {"success": False, "error": str(e), "items": []}
    
    def _fetch_sales_from_local(self, sale_id: str = None, filters: Dict = None) -> Dict:
        """Récupère les ventes depuis la base locale"""
        try:
            if sale_id:
                # Récupérer une vente spécifique
                sale = self.db.get_sale_by_id(sale_id)
                if sale:
                    items = self.db.get_sale_items(sale_id)
                    return {
                        "success": True,
                        "sale": {
                            "id": str(sale.id),
                            "reference": getattr(sale, 'reference', ''),
                            "total_amount": self._safe_number(getattr(sale, 'total_amount', 0)),
                            "created_at": getattr(sale, 'created_at', datetime.now()).isoformat(),
                            "customer_name": getattr(sale, 'customer_name', ''),
                            "seller_name": getattr(sale, 'seller_name', ''),
                            "payment_method": getattr(sale, 'payment_method', ''),
                            "subtotal": self._safe_number(getattr(sale, 'subtotal', 0)),
                            "total_discount": self._safe_number(getattr(sale, 'total_discount', 0)),
                            "total_tva": self._safe_number(getattr(sale, 'total_tva', 0)),
                            "items": [
                                {
                                    "product_name": item.get('product_name', ''),
                                    "quantity": item.get('quantity', 0),
                                    "unit_price": self._safe_number(item.get('unit_price', 0)),
                                    "total": self._safe_number(item.get('total', 0))
                                }
                                for item in items
                            ]
                        }
                    }
            else:
                # Récupérer la liste des ventes
                sales = self.db.get_all_sales(filters)
                items = []
                for s in sales:
                    total_amount = self._safe_number(getattr(s, 'total_amount', 0))
                    items.append({
                        "id": str(s.id),
                        "reference": getattr(s, 'reference', ''),
                        "total_amount": total_amount,
                        "created_at": getattr(s, 'created_at', datetime.now()).isoformat(),
                        "customer_name": getattr(s, 'customer_name', ''),
                        "seller_name": getattr(s, 'seller_name', '')
                    })
                return {
                    "success": True,
                    "items": items,
                    "total": len(items)
                }
        except Exception as e:
            logger.error(f"Erreur fetch_sales_from_local: {e}")
            return {"success": False, "error": str(e), "items": []}
    
    def _fetch_sellers_from_server(self) -> List[Dict]:
        """Récupère la liste des vendeurs depuis le serveur (users.py)"""
        headers = self._get_headers()
        if not headers:
            return []
        
        api_url = self._get_api_base_url()
        
        try:
            response = self.sync_service.session.get(
                f"{api_url}/users/sellers",
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                self.sellers_cache = data.get("users", data.get("sellers", []))
                return self.sellers_cache
            else:
                return []
                
        except Exception as e:
            logger.error(f"Erreur fetch_sellers_from_server: {e}")
            return []
    
    def _fetch_sellers_from_local(self) -> List[Dict]:
        """Récupère la liste des vendeurs depuis la base locale"""
        try:
            users = self.db.get_users_by_role(["vendeur", "caissier", "gerant"])
            return [
                {
                    "id": str(u.id),
                    "name": getattr(u, 'nom_complet', getattr(u, 'name', '')),
                    "email": getattr(u, 'email', ''),
                    "role": getattr(u, 'role', 'vendeur')
                }
                for u in users
            ]
        except Exception as e:
            logger.error(f"Erreur fetch_sellers_from_local: {e}")
            return []
    
    def _fetch_sale_details_from_server(self, sale_id: str) -> Dict:
        """Récupère les détails complets d'une vente depuis le serveur"""
        return self._fetch_sales_from_server(sale_id, None)
    
    def _fetch_sale_details_from_local(self, sale_id: str) -> Dict:
        """Récupère les détails complets d'une vente depuis la base locale"""
        return self._fetch_sales_from_local(sale_id, None)
    
    # ==================== CONSTRUCTION DE L'INTERFACE ====================
    
    def show(self):
        """Affiche l'écran de détails"""
        self.page.clean()
        self.page.bgcolor = ft.Colors.GREY_50
        self.page.padding = 0
        
        # Mettre à jour l'état de connexion
        self.is_online = self._check_internet_connection()
        
        # Header
        header = self._build_header()
        
        # Contenu principal - Utiliser Column avec scroll comme dans sale_screen
        main_content = ft.Column(
            [
                header,
                ft.Container(
                    content=self._build_content(),
                    expand=True,
                    padding=10,
                ),
            ],
            expand=True,
            spacing=0,
            scroll=ft.ScrollMode.AUTO,  # Scroll sur la colonne principale
        )
        
        self.page.add(main_content)
        self.page.update()
    
    def _build_header(self):
        """Construit l'en-tête avec titre et bouton retour"""
        
        # Titre par défaut si non fourni
        if not self.title:
            titles = {
                "sales": "Ventes",
                "expenses": "Dépenses",
                "debts": "Dettes",
                "expiring": "Produits expirés/proches de péremption",
                "low_stock": "Produits en rupture de stock",
                "never_sold": "Produits jamais vendus",
                "sale_detail": "Détail de la vente",
                "sellers": "Vendeurs",
                "sales_list": "Liste des ventes"
            }
            self.title = titles.get(self.detail_type, "Détails")
        
        # Indicateur de connexion
        connection_indicator = ft.Row(
            [
                ft.Icon(
                    ft.Icons.WIFI if self.is_online else ft.Icons.WIFI_OFF,
                    size=16,
                    color=ft.Colors.GREEN if self.is_online else ft.Colors.RED_400,
                ),
                ft.Text(
                    "Online" if self.is_online else "Offline",
                    size=12,
                    color=ft.Colors.WHITE,
                ),
            ],
            spacing=4,
        )
        
        return ft.Container(
            bgcolor=ft.Colors.BLUE_700,
            padding=ft.Padding.symmetric(horizontal=12, vertical=15),
            content=ft.Row(
                [
                    ft.IconButton(
                        icon=ft.Icons.ARROW_BACK,
                        icon_color=ft.Colors.WHITE,
                        on_click=self._go_back,
                        tooltip="Retour",
                    ),
                    ft.Text(
                        self.title,
                        size=18,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.WHITE,
                        expand=True,
                    ),
                    connection_indicator,
                ],
                alignment=ft.MainAxisAlignment.START,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )
    
    def _build_content(self):
        """Construit le contenu selon le type de détail"""
        
        if self.detail_type == "sales":
            return self._build_sales_list_content()
        elif self.detail_type == "sale_detail":
            return self._build_sale_detail_content()
        elif self.detail_type == "expenses":
            return self._build_expenses_content()
        elif self.detail_type == "debts":
            return self._build_debts_content()
        elif self.detail_type == "expiring":
            return self._build_expiring_content()
        elif self.detail_type == "low_stock":
            return self._build_low_stock_content()
        elif self.detail_type == "never_sold":
            return self._build_never_sold_content()
        elif self.detail_type == "sellers":
            return self._build_sellers_content()
        else:
            return self._build_default_content()
    
    # ==================== CONTENU DES VENTES ====================
    
    def _build_sales_list_content(self):
        """Contenu pour la liste des ventes"""
        
        # Récupérer les paramètres de filtre
        filters = self.data.get("filters", {})
        period = self.data.get("period", "today")
        
        period_text = {
            "today": "aujourd'hui",
            "week": "cette semaine",
            "month": "ce mois",
            "all": "toutes les ventes"
        }.get(period, "aujourd'hui")
        
        # Conteneur pour les ventes avec scroll
        sales_container = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO)
        
        # Variable pour stocker le total
        total_amount = ft.Text("0 FC", size=28, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_700)
        
        # Fonction pour charger les ventes
        def load_sales():
            if self.is_online:
                result = self._fetch_sales_from_server(filters=filters)
            else:
                result = self._fetch_sales_from_local(filters=filters)
            
            items = result.get("items", [])
            
            # Calculer le total en s'assurant que les valeurs sont des nombres
            total = 0
            for item in items:
                total += self._safe_number(item.get("total_amount", 0))
            
            # Mettre à jour le total
            total_amount.value = f"{total:,.0f} FC"
            
            # Construire la liste des ventes
            sales_container.controls.clear()
            
            if not items:
                sales_container.controls.append(
                    self._build_empty_state("Aucune vente pour cette période")
                )
            else:
                for sale in items:
                    sale_card = self._build_sale_card(sale)
                    sales_container.controls.append(sale_card)
            
            self.page.update()
        
        # Premier chargement
        load_sales()
        
        return ft.Column(
            [
                ft.Card(
                    content=ft.Container(
                        content=ft.Column([
                            ft.Text(
                                f"Total des ventes {period_text}",
                                size=14,
                                color=ft.Colors.GREY_700,
                            ),
                            total_amount,
                        ], spacing=5),
                        padding=20,
                    ),
                    elevation=2,
                ),
                ft.Text(
                    f"Liste des ventes",
                    size=16,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Row(
                    [
                        ft.Button(
                            "Actualiser",
                            icon=ft.Icons.REFRESH,
                            on_click=lambda e: load_sales(),
                            style=ft.ButtonStyle(
                                color=ft.Colors.BLUE_700,
                                bgcolor=ft.Colors.BLUE_50,
                            ),
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.END,
                ),
                sales_container,
            ],
            expand=True,
            spacing=15,
        )
    
    def _build_sale_card(self, sale: Dict) -> ft.Card:
        """Construit une carte pour une vente"""
        
        sale_id = sale.get("id", "")
        reference = sale.get("reference", sale.get("invoice_number", "N/A"))
        amount = self._safe_number(sale.get("total_amount", 0))
        date_str = sale.get("created_at", "")
        if date_str and len(date_str) > 10:
            date_str = date_str[:10]
        customer = sale.get("customer_name", "Client")
        seller = sale.get("seller_name", "Vendeur")
        
        return ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(ft.Icons.RECEIPT, size=20, color=ft.Colors.BLUE_700),
                                ft.Text(
                                    reference,
                                    size=14,
                                    weight=ft.FontWeight.BOLD,
                                    expand=True,
                                ),
                                ft.Text(
                                    f"{amount:,.0f} FC",
                                    size=14,
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.GREEN_700,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Row(
                            [
                                ft.Icon(ft.Icons.CALENDAR_TODAY, size=14, color=ft.Colors.GREY_500),
                                ft.Text(date_str, size=12, color=ft.Colors.GREY_500),
                                ft.Icon(ft.Icons.PERSON, size=14, color=ft.Colors.GREY_500),
                                ft.Text(customer, size=12, color=ft.Colors.GREY_500),
                            ],
                            spacing=5,
                        ),
                        ft.Row(
                            [
                                ft.Icon(ft.Icons.SELL, size=14, color=ft.Colors.GREY_500),
                                ft.Text(seller, size=12, color=ft.Colors.GREY_500),
                            ],
                            spacing=5,
                        ),
                        ft.Divider(height=1, color=ft.Colors.GREY_200),
                        ft.Row(
                            [
                                ft.TextButton(
                                    "Voir les détails",
                                    icon=ft.Icons.INFO,
                                    on_click=lambda e, sid=sale_id: self._show_sale_details(sid),
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.END,
                        ),
                    ],
                    spacing=8,
                ),
                padding=ft.Padding.all(12),
            ),
            elevation=2,
        )
    
    def _show_sale_details(self, sale_id: str):
        """Affiche les détails d'une vente spécifique"""
        
        details_screen = DashboardDetailsScreen(
            page=self.page,
            db=self.db,
            sync_service=self.sync_service,
            auth_service=self.auth_service,
            current_user=self.current_user,
            notification_manager=self.notification_manager,
            title="Détail de la vente",
            detail_type="sale_detail",
            data={"sale_id": sale_id}
        )
        details_screen.show()
    
    # ==================== CONTENU DÉTAIL D'UNE VENTE ====================
    
    def _build_sale_detail_content(self):
        """Contenu pour le détail d'une vente spécifique"""
        
        sale_id = self.data.get("sale_id")
        
        if not sale_id:
            return self._build_empty_state("ID de vente non spécifié")
        
        # Conteneur avec scroll
        content_container = ft.Column(spacing=15, scroll=ft.ScrollMode.AUTO)
        loading_indicator = ft.ProgressBar(visible=True)
        
        def load_sale_detail():
            content_container.controls.clear()
            content_container.controls.append(loading_indicator)
            
            if self.is_online:
                result = self._fetch_sale_details_from_server(sale_id)
            else:
                result = self._fetch_sale_details_from_local(sale_id)
            
            content_container.controls.clear()
            
            if not result.get("success"):
                content_container.controls.append(
                    self._build_empty_state(f"Erreur: {result.get('error', 'Vente non trouvée')}")
                )
                self.page.update()
                return
            
            sale = result.get("sale", {})
            items = sale.get("items", [])
            
            # Informations générales
            content_container.controls.append(
                ft.Card(
                    content=ft.Container(
                        content=ft.Column(
                            [
                                ft.Text("Informations générales", size=16, weight=ft.FontWeight.BOLD),
                                self._build_info_row("Référence", sale.get("reference", sale.get("invoice_number", "N/A"))),
                                self._build_info_row("Date", sale.get("created_at", "")[:19] if sale.get("created_at") else "N/A"),
                                self._build_info_row("Client", sale.get("customer_name", "N/A")),
                                self._build_info_row("Vendeur", sale.get("seller_name", "N/A")),
                                self._build_info_row("Mode de paiement", sale.get("payment_method", "N/A")),
                                ft.Divider(),
                                ft.Text("Détails des articles", size=16, weight=ft.FontWeight.BOLD),
                            ],
                            spacing=12,
                        ),
                        padding=20,
                    ),
                    elevation=2,
                )
            )
            
            # Liste des articles
            if items:
                items_card = ft.Card(
                    content=ft.Container(
                        content=ft.Column(
                            [
                                self._build_item_row(item)
                                for item in items
                            ],
                            spacing=8,
                        ),
                        padding=20,
                    ),
                    elevation=1,
                )
                content_container.controls.append(items_card)
            else:
                content_container.controls.append(
                    ft.Text("Aucun article trouvé", color=ft.Colors.GREY_500)
                )
            
            # Totaux
            subtotal = self._safe_number(sale.get("subtotal", 0))
            discount = self._safe_number(sale.get("total_discount", 0))
            tva = self._safe_number(sale.get("total_tva", 0))
            total = self._safe_number(sale.get("total_amount", 0))
            
            totals_card = ft.Card(
                content=ft.Container(
                    content=ft.Column(
                        [
                            ft.Text("Récapitulatif", size=16, weight=ft.FontWeight.BOLD),
                            self._build_info_row("Sous-total", f"{subtotal:,.0f} FC", is_total=False),
                            self._build_info_row("Remise", f"- {discount:,.0f} FC", is_total=False, text_color=ft.Colors.RED_700),
                            self._build_info_row("TVA", f"{tva:,.0f} FC", is_total=False),
                            ft.Divider(),
                            self._build_info_row("TOTAL", f"{total:,.0f} FC", is_total=True),
                        ],
                        spacing=10,
                    ),
                    padding=20,
                ),
                elevation=2,
            )
            content_container.controls.append(totals_card)
            
            self.page.update()
        
        # Charger les données
        load_sale_detail()
        
        return content_container
    
    def _build_info_row(self, label: str, value: str, is_total: bool = False, text_color: str = None) -> ft.Row:
        """Construit une ligne d'information"""
        return ft.Row(
            [
                ft.Text(label, size=14, weight=ft.FontWeight.W_500 if is_total else ft.FontWeight.NORMAL),
                ft.Text(
                    value,
                    size=14 if not is_total else 18,
                    weight=ft.FontWeight.BOLD if is_total else ft.FontWeight.NORMAL,
                    color=text_color or (ft.Colors.BLUE_700 if is_total else ft.Colors.GREY_800),
                    text_align=ft.TextAlign.RIGHT,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
    
    def _build_item_row(self, item: Dict) -> ft.Row:
        """Construit une ligne d'article"""
        name = item.get("product_name", "Produit")
        quantity = self._safe_number(item.get("quantity", 0))
        unit_price = self._safe_number(item.get("unit_price", 0))
        total = self._safe_number(item.get("total", 0))
        
        return ft.Row(
            [
                ft.Column(
                    [
                        ft.Text(name, size=14, weight=ft.FontWeight.W_500),
                        ft.Text(f"{int(quantity)} x {unit_price:,.0f} FC", size=12, color=ft.Colors.GREY_500),
                    ],
                    expand=True,
                    spacing=2,
                ),
                ft.Text(f"{total:,.0f} FC", size=14, weight=ft.FontWeight.BOLD),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
    
    # ==================== CONTENU VENDEURS ====================
    
    def _build_sellers_content(self):
        """Contenu pour la liste des vendeurs"""
        
        sellers_container = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO)
        
        # Variable pour le compteur
        count_text = ft.Text("0", size=28, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_700)
        
        def load_sellers():
            if self.is_online:
                sellers = self._fetch_sellers_from_server()
            else:
                sellers = self._fetch_sellers_from_local()
            
            count_text.value = str(len(sellers))
            sellers_container.controls.clear()
            
            if not sellers:
                sellers_container.controls.append(
                    self._build_empty_state("Aucun vendeur trouvé")
                )
            else:
                for seller in sellers:
                    seller_card = self._build_seller_card(seller)
                    sellers_container.controls.append(seller_card)
            
            self.page.update()
        
        load_sellers()
        
        return ft.Column(
            [
                ft.Card(
                    content=ft.Container(
                        content=ft.Column([
                            ft.Text(
                                "Vendeurs actifs",
                                size=14,
                                color=ft.Colors.GREY_700,
                            ),
                            count_text,
                        ], spacing=5),
                        padding=20,
                    ),
                    elevation=2,
                ),
                ft.Row(
                    [
                        ft.Button(
                            "Actualiser",
                            icon=ft.Icons.REFRESH,
                            on_click=lambda e: load_sellers(),
                            style=ft.ButtonStyle(
                                color=ft.Colors.BLUE_700,
                                bgcolor=ft.Colors.BLUE_50,
                            ),
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.END,
                ),
                sellers_container,
            ],
            expand=True,
            spacing=15,
        )
    
    def _build_seller_card(self, seller: Dict) -> ft.Card:
        """Construit une carte pour un vendeur"""
        
        name = seller.get("name", seller.get("nom_complet", "Inconnu"))
        email = seller.get("email", "")
        role = seller.get("role", "vendeur")
        
        role_colors = {
            "vendeur": ft.Colors.BLUE_700,
            "caissier": ft.Colors.GREEN_700,
            "gerant": ft.Colors.PURPLE_700,
            "admin": ft.Colors.RED_700,
        }
        role_color = role_colors.get(role.lower(), ft.Colors.GREY_700)
        
        return ft.Card(
            content=ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(
                            ft.Icons.PERSON,
                            size=32,
                            color=role_color,
                        ),
                        ft.Column(
                            [
                                ft.Text(name, size=16, weight=ft.FontWeight.BOLD),
                                ft.Text(email, size=12, color=ft.Colors.GREY_500),
                                ft.Container(
                                    content=ft.Text(role.capitalize(), size=11, color=ft.Colors.WHITE),
                                    bgcolor=role_color,
                                    padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                                    border_radius=12,
                                ),
                            ],
                            expand=True,
                            spacing=2,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.START,
                ),
                padding=ft.Padding.all(12),
            ),
            elevation=1,
        )
    
    # ==================== AUTRES CONTENUS ====================
    
    def _build_expenses_content(self):
        """Contenu pour les dépenses"""
        expenses = self.data.get("items", [])
        total = self._safe_number(self.data.get("total", 0))
        period = self.data.get("period", "today")
        
        period_text = {
            "today": "aujourd'hui",
            "week": "cette semaine",
            "month": "ce mois"
        }.get(period, "aujourd'hui")
        
        if not expenses:
            return self._build_empty_state("Aucune dépense enregistrée pour cette période")
        
        expenses_list = ft.Column(
            [
                self._build_expense_row(expense)
                for expense in expenses
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
        )
        
        return ft.Column(
            [
                ft.Card(
                    content=ft.Container(
                        content=ft.Column([
                            ft.Text(
                                f"Total des dépenses {period_text}",
                                size=14,
                                color=ft.Colors.GREY_700,
                            ),
                            ft.Text(
                                f"{total:,.0f} FC",
                                size=28,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.RED_700,
                            ),
                        ], spacing=5),
                        padding=20,
                    ),
                    elevation=2,
                ),
                ft.Text(
                    f"Détails des dépenses ({len(expenses)})",
                    size=16,
                    weight=ft.FontWeight.BOLD,
                ),
                expenses_list,
            ],
            expand=True,
            spacing=15,
        )
    
    def _build_debts_content(self):
        """Contenu pour les dettes"""
        debts = self.data.get("items", [])
        total = self._safe_number(self.data.get("total", 0))
        period = self.data.get("period", "today")
        
        period_text = {
            "today": "aujourd'hui",
            "week": "cette semaine",
            "month": "ce mois"
        }.get(period, "aujourd'hui")
        
        if not debts:
            return self._build_empty_state("Aucune dette enregistrée pour cette période")
        
        debts_list = ft.Column(
            [
                self._build_debt_row(debt)
                for debt in debts
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
        )
        
        return ft.Column(
            [
                ft.Card(
                    content=ft.Container(
                        content=ft.Column([
                            ft.Text(
                                f"Total des dettes créées {period_text}",
                                size=14,
                                color=ft.Colors.GREY_700,
                            ),
                            ft.Text(
                                f"{total:,.0f} FC",
                                size=28,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.PURPLE_700,
                            ),
                        ], spacing=5),
                        padding=20,
                    ),
                    elevation=2,
                ),
                ft.Text(
                    f"Détails des dettes ({len(debts)})",
                    size=16,
                    weight=ft.FontWeight.BOLD,
                ),
                debts_list,
            ],
            expand=True,
            spacing=15,
        )
    
    def _build_expiring_content(self):
        """Contenu pour les produits expirés/proches de péremption"""
        expired = self.data.get("expired", [])
        expiring = self.data.get("expiring", [])
        
        if not expired and not expiring:
            return self._build_empty_state("Aucun produit avec des problèmes de péremption")
        
        products_content = ft.Column(
            [
                self._build_product_category_section(
                    "📅 Produits expirés",
                    expired,
                    ft.Colors.RED_700
                ),
                ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
                self._build_product_category_section(
                    "⚠️ Produits proches de péremption (30 jours)",
                    expiring,
                    ft.Colors.ORANGE
                ),
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
        )
        
        return ft.Column(
            [
                self._build_status_summary(expired, expiring),
                products_content,
            ],
            expand=True,
            spacing=15,
        )
    
    def _build_low_stock_content(self):
        """Contenu pour les produits en rupture de stock"""
        products = self.data.get("items", [])
        count = self.data.get("count", len(products))
        
        if not products:
            return self._build_empty_state("Aucun produit en rupture de stock")
        
        products_list = ft.Column(
            [
                self._build_low_stock_row(product)
                for product in products
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
        )
        
        return ft.Column(
            [
                ft.Card(
                    content=ft.Container(
                        content=ft.Column([
                            ft.Text(
                                "Produits en rupture de stock",
                                size=14,
                                color=ft.Colors.GREY_700,
                            ),
                            ft.Text(
                                str(count),
                                size=28,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.RED_700,
                            ),
                        ], spacing=5),
                        padding=20,
                    ),
                    elevation=2,
                ),
                ft.Text(
                    f"Liste des produits (stock ≤ 0)",
                    size=16,
                    weight=ft.FontWeight.BOLD,
                ),
                products_list,
            ],
            expand=True,
            spacing=15,
        )
    
    def _build_never_sold_content(self):
        """Contenu pour les produits jamais vendus"""
        products = self.data.get("items", [])
        count = self.data.get("count", len(products))
        
        if not products:
            return self._build_empty_state("Tous les produits ont déjà été vendus")
        
        products_list = ft.Column(
            [
                self._build_never_sold_row(product)
                for product in products
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
        )
        
        return ft.Column(
            [
                ft.Card(
                    content=ft.Container(
                        content=ft.Column([
                            ft.Text(
                                "Produits jamais vendus",
                                size=14,
                                color=ft.Colors.GREY_700,
                            ),
                            ft.Text(
                                str(count),
                                size=28,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.BLUE_700,
                            ),
                        ], spacing=5),
                        padding=20,
                    ),
                    elevation=2,
                ),
                ft.Text(
                    f"Liste des produits (jamais vendus)",
                    size=16,
                    weight=ft.FontWeight.BOLD,
                ),
                products_list,
            ],
            expand=True,
            spacing=15,
        )
    
    # ==================== COMPOSANTS RÉUTILISABLES ====================
    
    def _build_expense_row(self, expense: Dict) -> ft.Card:
        """Construit une ligne de dépense"""
        amount = self._safe_number(expense.get("amount", 0))
        return ft.Card(
            content=ft.Container(
                content=ft.Row(
                    [
                        ft.Column([
                            ft.Text(
                                expense.get("description", "Sans description"),
                                size=14,
                                weight=ft.FontWeight.W_500,
                            ),
                            ft.Row([
                                ft.Icon(ft.Icons.CALENDAR_TODAY, size=12, color=ft.Colors.GREY_500),
                                ft.Text(
                                    expense.get("expense_date", ""),
                                    size=11,
                                    color=ft.Colors.GREY_500,
                                ),
                                ft.Text(
                                    expense.get("category", ""),
                                    size=11,
                                    color=ft.Colors.BLUE_700,
                                ),
                            ], spacing=5),
                        ], expand=True, spacing=3),
                        ft.Text(
                            f"{amount:,.0f} FC",
                            size=14,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.RED_700,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                padding=ft.Padding.all(12),
            ),
            elevation=1,
        )
    
    def _build_debt_row(self, debt: Dict) -> ft.Card:
        """Construit une ligne de dette"""
        remaining = self._safe_number(debt.get("remaining_amount", 0))
        original = self._safe_number(debt.get("amount", 0))
        
        progress_value = (original - remaining) / original if original > 0 else 0
        
        return ft.Card(
            content=ft.Container(
                content=ft.Column([
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.PERSON, size=16, color=ft.Colors.PURPLE),
                            ft.Text(
                                debt.get("customer_name", "Client"),
                                size=14,
                                weight=ft.FontWeight.W_500,
                                expand=True,
                            ),
                            ft.Text(
                                f"{remaining:,.0f} FC",
                                size=14,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.PURPLE_700,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Row([
                        ft.Icon(ft.Icons.ACCESS_TIME, size=12, color=ft.Colors.GREY_500),
                        ft.Text(
                            f"À payer avant le: {debt.get('due_date', 'Non spécifiée')}",
                            size=11,
                            color=ft.Colors.GREY_500,
                        ),
                        ft.Text(
                            f"Créé le: {debt.get('created_at', '')[0:10] if debt.get('created_at') else ''}",
                            size=11,
                            color=ft.Colors.GREY_500,
                        ),
                    ], spacing=5),
                    ft.ProgressBar(
                        value=progress_value,
                        color=ft.Colors.GREEN,
                        bgcolor=ft.Colors.GREY_300,
                        height=6,
                        border_radius=3,
                    ),
                ], spacing=8),
                padding=ft.Padding.all(12),
            ),
            elevation=1,
        )
    
    def _build_status_summary(self, expired: List, expiring: List) -> ft.Card:
        """Construit le résumé des statuts"""
        return ft.Card(
            content=ft.Container(
                content=ft.Row(
                    [
                        ft.Container(
                            content=ft.Column([
                                ft.Text("Expirés", size=12, color=ft.Colors.RED),
                                ft.Text(str(len(expired)), size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.RED),
                            ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                            expand=True,
                            bgcolor=ft.Colors.RED_50,
                            border_radius=8,
                            padding=10,
                        ),
                        ft.Container(
                            content=ft.Column([
                                ft.Text("Proches expiration", size=12, color=ft.Colors.ORANGE),
                                ft.Text(str(len(expiring)), size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.ORANGE),
                            ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                            expand=True,
                            bgcolor=ft.Colors.ORANGE_50,
                            border_radius=8,
                            padding=10,
                        ),
                    ],
                    spacing=10,
                ),
                padding=ft.Padding.all(15),
            ),
            elevation=2,
        )
    
    def _build_product_category_section(self, title: str, products: List[Dict], color: str) -> ft.Column:
        """Construit une section de catégorie de produits"""
        if not products:
            return ft.Container(
                content=ft.Text(f"✅ Aucun produit", size=13, color=ft.Colors.GREY_500),
                padding=ft.Padding.all(10),
            )
        
        return ft.Column(
            [
                ft.Text(title, size=15, weight=ft.FontWeight.BOLD, color=color),
                ft.Column(
                    [self._build_product_row(p, color) for p in products],
                    spacing=6,
                ),
            ],
            spacing=8,
        )
    
    def _build_product_row(self, product: Dict, color: str) -> ft.Card:
        """Construit une ligne de produit"""
        quantity = self._safe_number(product.get("quantity", 0))
        return ft.Card(
            content=ft.Container(
                content=ft.Row(
                    [
                        ft.Column([
                            ft.Text(
                                product.get("name", "Inconnu"),
                                size=14,
                                weight=ft.FontWeight.W_500,
                            ),
                            ft.Row([
                                ft.Text(f"Code: {product.get('code', 'N/A')}", size=10, color=ft.Colors.GREY_500),
                                ft.Text(f"Qté: {int(quantity)}", size=10, color=ft.Colors.GREY_500),
                            ], spacing=8),
                        ], expand=True, spacing=3),
                        ft.Text(
                            product.get("status_text", product.get("status", "")),
                            size=11,
                            color=color,
                            weight=ft.FontWeight.BOLD,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                padding=ft.Padding.all(10),
            ),
            elevation=1,
        )
    
    def _build_low_stock_row(self, product: Dict) -> ft.Card:
        """Construit une ligne de produit en rupture de stock"""
        quantity = self._safe_number(product.get("quantity", 0))
        return ft.Card(
            content=ft.Container(
                content=ft.Row(
                    [
                        ft.Column([
                            ft.Text(
                                product.get("name", "Inconnu"),
                                size=14,
                                weight=ft.FontWeight.W_500,
                            ),
                            ft.Text(f"Code: {product.get('code', 'N/A')}", size=11, color=ft.Colors.GREY_500),
                        ], expand=True, spacing=3),
                        ft.Container(
                            content=ft.Text(
                                f"Stock: {int(quantity)}",
                                size=12,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.WHITE,
                            ),
                            bgcolor=ft.Colors.RED_700,
                            padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                            border_radius=12,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                padding=ft.Padding.all(12),
            ),
            elevation=1,
        )
    
    def _build_never_sold_row(self, product: Dict) -> ft.Card:
        """Construit une ligne de produit jamais vendu"""
        quantity = self._safe_number(product.get("quantity", 0))
        return ft.Card(
            content=ft.Container(
                content=ft.Row(
                    [
                        ft.Column([
                            ft.Text(
                                product.get("name", "Inconnu"),
                                size=14,
                                weight=ft.FontWeight.W_500,
                            ),
                            ft.Text(f"Code: {product.get('code', 'N/A')}", size=11, color=ft.Colors.GREY_500),
                        ], expand=True, spacing=3),
                        ft.Container(
                            content=ft.Text(
                                f"Stock: {int(quantity)}",
                                size=12,
                                color=ft.Colors.BLUE_700,
                            ),
                            padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                            border=ft.border.all(1, ft.Colors.BLUE_200),
                            border_radius=12,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                padding=ft.Padding.all(12),
            ),
            elevation=1,
        )
    
    def _build_default_content(self):
        """Contenu par défaut"""
        return ft.Container(
            expand=True,
            alignment=ft.Alignment.CENTER,
            content=ft.Text("Aucune donnée disponible", size=16, color=ft.Colors.GREY_500),
        )
    
    def _build_empty_state(self, message: str) -> ft.Container:
        """État vide"""
        return ft.Container(
            expand=True,
            alignment=ft.Alignment.CENTER,
            content=ft.Column(
                [
                    ft.Icon(ft.Icons.INFO, size=48, color=ft.Colors.GREY_400),
                    ft.Text(message, size=16, color=ft.Colors.GREY_500, text_align=ft.TextAlign.CENTER),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=10,
            ),
        )
    
    def _go_back(self, e):
        """Retour à l'écran précédent"""
        from screens.dashboard_screen import DashboardScreen
        
        dashboard = DashboardScreen(
            self.page, self.db, self.sync_service, 
            self.auth_service, self.current_user, self.notification_manager
        )
        dashboard.show_dashboard()