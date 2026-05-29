import flet as ft
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class ExpenseScreen:
    def __init__(self, page: ft.Page, db, sync_service, auth_service, current_user, connection_manager=None):
        self.page = page
        self.db = db
        self.sync_service = sync_service
        self.auth_service = auth_service
        self.current_user = current_user
        self.connection_manager = connection_manager

        self.description_field = None
        self.amount_field = None
        self.category_dropdown = None
        self.date_field = None
        
        # S'abonner aux changements de connexion si connection_manager est fourni
        if self.connection_manager:
            self.connection_manager.register_observer(self._on_connection_changed)

    # =========================================================
    # GESTION DE LA CONNEXION
    # =========================================================
    def _on_connection_changed(self, is_online: bool, force_mode):
        """Callback appelé quand l'état de connexion change"""
        if hasattr(self, 'info_card') and self.info_card:
            self._update_connection_status_display(is_online, force_mode)
    
    def _update_connection_status_display(self, is_online: bool, force_mode=None):
        """Met à jour l'affichage du statut de connexion"""
        if not hasattr(self, 'info_card'):
            return
        
        status = self.connection_manager.get_display_status() if self.connection_manager else {
            "color": "green" if is_online else "red",
            "text": "Online" if is_online else "Offline",
            "icon": "🌐" if is_online else "📡",
            "tooltip": ""
        }
        
        # Mettre à jour la carte d'information avec le statut
        try:
            self.info_card.content.controls[0] = ft.Row(
                controls=[
                    ft.Icon(ft.Icons.WIFI if is_online else ft.Icons.WIFI_OFF, 
                           color=ft.Colors.GREEN if is_online else ft.Colors.RED),
                    ft.Text(f"Statut: {status['text']}", size=12, weight=ft.FontWeight.BOLD),
                ],
                spacing=8,
            )
            self.page.update()
        except Exception as e:
            logger.error(f"Erreur mise à jour statut connexion: {e}")

    def is_online(self) -> bool:
        """Vérifie si on est en mode online"""
        if self.connection_manager:
            return self.connection_manager.is_online_mode()
        return self.sync_service and self.sync_service.check_internet_connection()

    # =========================================================
    # OUTILS
    # =========================================================
    def _branch_id(self):
        branch_id = (self.current_user.get("active_branch_id") or 
                    self.current_user.get("branch_id") or
                    self.current_user.get("current_branch_id"))
        
        if branch_id is None:
            print("⚠️ ATTENTION: branch_id est None dans ExpenseScreen!")
            user = self.auth_service.get_current_user()
            if user:
                branch_id = user.get("active_branch_id") or user.get("branch_id")
        
        return branch_id

    def _safe_float(self, value, default=0.0):
        try:
            if value is None:
                return default
            text = str(value).strip().replace(" ", "").replace(",", "")
            if not text:
                return default
            return float(text)
        except Exception:
            return default

    def _format_money(self, amount):
        try:
            return f"{float(amount):,.0f} FC"
        except Exception:
            return "0 FC"

    def show_snackbar(self, message: str, color, duration=4000):
        snack = ft.SnackBar(
            content=ft.Text(message),
            bgcolor=color,
            duration=duration,
            show_close_icon=True,
        )
        self.page.snack_bar = snack
        snack.open = True
        self.page.update()

    def show_error(self, message: str, duration=4000):
        self.show_snackbar(message, ft.Colors.RED, duration)

    def show_success(self, message: str, duration=4000):
        self.show_snackbar(message, ft.Colors.GREEN, duration)

    def show_warning(self, message: str, duration=4000):
        self.show_snackbar(message, ft.Colors.ORANGE, duration)

    def show_info(self, message: str, duration=4000):
        self.show_snackbar(message, ft.Colors.BLUE, duration)

    # =========================================================
    # VIDER LES CHAMPS
    # =========================================================
    def clear_form_fields(self):
        """Vide tous les champs du formulaire"""
        if self.description_field:
            self.description_field.value = ""
        if self.amount_field:
            self.amount_field.value = ""
        if self.category_dropdown:
            self.category_dropdown.value = None
        if self.date_field:
            self.date_field.value = datetime.now().strftime("%d/%m/%Y")
        self.page.update()

    # =========================================================
    # ÉCRAN PRINCIPAL
    # =========================================================
    def show(self):
        self.page.clean()

        header = ft.Container(
            content=ft.Row(
                controls=[
                    ft.IconButton(
                        icon=ft.Icons.ARROW_BACK,
                        on_click=lambda e: self.go_back(),
                        icon_color=ft.Colors.WHITE,
                    ),
                    ft.Text(
                        "Nouvelle dépense",
                        size=24,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.WHITE,
                        expand=True,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.HISTORY,
                        on_click=lambda e: self.show_expense_history(),
                        icon_color=ft.Colors.WHITE,
                        tooltip="Historique",
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=10,
            bgcolor=ft.Colors.RED_700,
            border_radius=10,
        )

        self.description_field = ft.TextField(
            label="Description / Motif",
            hint_text="Ex: Achat de matériel, Eau, Électricité...",
            multiline=True,
            min_lines=2,
            max_lines=4,
            expand=True,
        )

        self.amount_field = ft.TextField(
            label="Montant (FC)",
            hint_text="Ex: 25000",
            keyboard_type=ft.KeyboardType.NUMBER,
            expand=True,
        )

        self.category_dropdown = ft.Dropdown(
            label="Catégorie",
            hint_text="Choisir une catégorie",
            options=[
                ft.dropdown.Option("Achat stock", "Achat stock"),
                ft.dropdown.Option("Loyer", "Loyer"),
                ft.dropdown.Option("Électricité", "Électricité"),
                ft.dropdown.Option("Eau", "Eau"),
                ft.dropdown.Option("Internet", "Internet"),
                ft.dropdown.Option("Transport", "Transport"),
                ft.dropdown.Option("Marketing", "Marketing"),
                ft.dropdown.Option("Salaire", "Salaire"),
                ft.dropdown.Option("Maintenance", "Maintenance"),
                ft.dropdown.Option("Impôts", "Impôts"),
                ft.dropdown.Option("Divers", "Divers"),
            ],
            expand=True,
        )

        self.date_field = ft.TextField(
            label="Date",
            hint_text="JJ/MM/AAAA",
            value=datetime.now().strftime("%d/%m/%Y"),
            expand=True,
        )

        receipt_upload = ft.Button(
            content=ft.Text("Ajouter un reçu"),
            icon=ft.Icons.ATTACH_FILE,
            on_click=self.upload_receipt,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_200),
        )

        save_button = ft.Button(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.SAVE),
                    ft.Text("Enregistrer la dépense", size=16),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            on_click=self.save_expense,
            height=50,
            style=ft.ButtonStyle(
                bgcolor=ft.Colors.RED_700,
                color=ft.Colors.WHITE,
            ),
        )

        form = ft.Container(
            content=ft.Column(
                controls=[
                    self.description_field,
                    self.amount_field,
                    self.category_dropdown,
                    self.date_field,
                    receipt_upload,
                    ft.Divider(height=20),
                    save_button,
                ],
                spacing=15,
            ),
            padding=20,
            bgcolor=ft.Colors.WHITE,
            border_radius=10,
            margin=10,
        )

        # Statut de connexion (sans budget)
        status = self.connection_manager.get_display_status() if self.connection_manager else {
            "color": "green", "text": "Online", "icon": "🌐", "tooltip": ""
        }
        is_online = self.is_online()

        self.info_card = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.WIFI if is_online else ft.Icons.WIFI_OFF, 
                                   color=ft.Colors.GREEN if is_online else ft.Colors.RED),
                            ft.Text(f"Statut: {status['text']}", size=12, weight=ft.FontWeight.BOLD),
                        ],
                        spacing=8,
                    ),
                    ft.Divider(height=5, color=ft.Colors.TRANSPARENT),
                    ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.INFO, color=ft.Colors.BLUE),
                            ft.Text("Informations", size=14, weight=ft.FontWeight.BOLD),
                        ],
                        spacing=8,
                    ),
                    ft.Text(
                        f"Mode: {'En ligne' if is_online else 'Hors-ligne'} - "
                        f"La dépense sera {'immédiatement synchronisée' if is_online else 'enregistrée localement'}",
                        size=11,
                        color=ft.Colors.GREY_600,
                        italic=True,
                    ),
                ],
                spacing=8,
            ),
            padding=10,
            bgcolor=ft.Colors.BLUE_50,
            border_radius=10,
            margin=10,
        )

        self.page.add(header, self.info_card, form)
        self.page.update()

    # =========================================================
    # ENREGISTREMENT AU SERVEUR
    # =========================================================
    def save_expense_to_server(self, expense_data: dict) -> dict:
        """
        Envoie la dépense directement au serveur via l'API
        """
        try:
            headers = self.sync_service._get_headers() if self.sync_service else None
            if not headers:
                return {"success": False, "error": "Non authentifié"}
            
            user = self.auth_service.get_current_user()
            branch_id = self._branch_id()
            
            if not branch_id:
                logger.error("branch_id est None - impossible d'enregistrer la dépense")
                return {"success": False, "error": "ID de branche manquant"}
            
            amount = self._safe_float(expense_data.get("amount", 0))
            if amount <= 0:
                return {"success": False, "error": f"Montant invalide: {amount}"}
            
            # Formatage de la date (YYYY-MM-DD)
            expense_date = expense_data.get("expense_date")
            if expense_date:
                try:
                    if 'T' in str(expense_date):
                        expense_date = expense_date.split('T')[0]
                    elif '/' in str(expense_date):
                        parts = expense_date.split('/')
                        if len(parts) == 3:
                            expense_date = f"{parts[2]}-{parts[1]}-{parts[0]}"
                    elif hasattr(expense_date, 'isoformat'):
                        expense_date = expense_date.isoformat()
                except Exception as e:
                    logger.warning(f"Erreur formatage date: {e}")
                    expense_date = datetime.now().date().isoformat()
            else:
                expense_date = datetime.now().date().isoformat()
            
            # Mapping des catégories vers les valeurs ACCEPTÉES PAR LE SERVEUR (expense.py)
            # Valeurs valides: salaire, loyer, electricite, eau, internet, telephone, 
            # fournitures, marketing, transport, maintenance, logiciel, assurance, 
            # frais_bancaires, impots, diverse
            category = expense_data.get("category", "Divers")
            category_lower = str(category).lower().strip()
            
            type_mapping = {
                # Salaires
                'salaire': 'salaire', 'salary': 'salaire',
                
                # Loyer
                'loyer': 'loyer', 'rent': 'loyer',
                
                # Utilitaires
                'electricite': 'electricite', 'électricité': 'electricite', 'electricité': 'electricite',
                'eau': 'eau', 'water': 'eau',
                'internet': 'internet',
                'telephone': 'telephone', 'phone': 'telephone',
                
                # Fournitures
                'fournitures': 'fournitures', 'supplies': 'fournitures',
                'fourniture': 'fournitures', 'achat stock': 'fournitures', 'stock_purchase': 'fournitures',
                
                # Marketing
                'marketing': 'marketing', 'publicite': 'marketing', 'advertising': 'marketing',
                
                # Transport
                'transport': 'transport',
                
                # Maintenance
                'maintenance': 'maintenance', 'reparation': 'maintenance', 'repair': 'maintenance',
                
                # Logiciel
                'logiciel': 'logiciel', 'software': 'logiciel', 'abonnement': 'logiciel', 'subscription': 'logiciel',
                
                # Assurance
                'assurance': 'assurance', 'insurance': 'assurance',
                
                # Frais bancaires
                'frais bancaire': 'frais_bancaires', 'frais_bancaires': 'frais_bancaires', 'bank_fees': 'frais_bancaires',
                
                # Impôts
                'impots': 'impots', 'taxes': 'impots', 'taxe': 'impots',
                
                # Équipement (dans fournitures)
                'equipment': 'fournitures', 'materiel': 'fournitures',
                
                # Formation
                'training': 'fournitures', 'formation': 'fournitures',
                
                # Consulting
                'consulting': 'fournitures', 'consultant': 'fournitures',
                
                # Autres
                'divers': 'diverse', 'diverse': 'diverse', 'other': 'diverse', 'autre': 'diverse',
            }
            
            expense_type = type_mapping.get(category_lower, 'diverse')
            
            description = str(expense_data.get("description", "")).strip()
            if not description:
                description = f"Dépense {expense_type}"
            
            # ✅ CORRECTION: Respecter exactement le schéma ExpenseCreate
            expense_payload = {
                "expense_type": expense_type,  # enum: salaire, loyer, electricite, eau, internet, telephone, fournitures, marketing, transport, maintenance, logiciel, assurance, frais_bancaires, impots, diverse
                "amount": amount,
                "description": description,
                "expense_date": expense_date,
                "branch_id": str(branch_id),
            }
            
            # 🔑 Champs optionnels (ne les envoyer que s'ils existent et sont non vides)
            notes = expense_data.get("notes", "")
            if notes and notes.strip():
                expense_payload["notes"] = notes.strip()[:500]
            
            supplier = expense_data.get("supplier", "")
            if supplier and supplier.strip():
                expense_payload["supplier"] = supplier.strip()[:200]
            
            payment_method = expense_data.get("payment_method", "cash")
            if payment_method:
                # Le serveur attend: cash, mobile_money, virement, cheque, carte
                payment_mapping = {
                    'cash': 'cash',
                    'especes': 'cash',
                    'espèces': 'cash',
                    'mobile_money': 'mobile_money',
                    'mobile money': 'mobile_money',
                    'virement': 'virement',
                    'cheque': 'cheque',
                    'carte': 'carte',
                    'card': 'carte',
                }
                expense_payload["payment_method"] = payment_mapping.get(payment_method.lower(), 'cash')
            
            logger.info(f"📤 Envoi au serveur: {expense_payload}")
            
            response = self.sync_service.session.post(
                f"{self.sync_service.api_url}/expenses",
                headers=headers,
                json=expense_payload,
                timeout=30
            )
            
            logger.info(f"Réponse serveur: status={response.status_code}")
            
            if response.status_code in [200, 201]:
                data = response.json()
                return {
                    "success": True,
                    "server_id": data.get("id"),
                    "message": "Dépense enregistrée sur le serveur",
                    "response": data
                }
            else:
                error_msg = f"Erreur serveur: {response.status_code}"
                try:
                    error_data = response.json()
                    if isinstance(error_data, dict):
                        detail = error_data.get('detail')
                        if isinstance(detail, list) and len(detail) > 0:
                            # Format FastAPI validation error
                            errors_list = []
                            for err in detail:
                                if isinstance(err, dict):
                                    loc = " -> ".join(str(x) for x in err.get('loc', []))
                                    msg = err.get('msg', '')
                                    errors_list.append(f"{loc}: {msg}")
                            if errors_list:
                                error_msg = "; ".join(errors_list)
                            else:
                                error_msg = str(detail)
                        elif detail:
                            error_msg = str(detail)
                        else:
                            error_msg = str(error_data)
                    elif isinstance(error_data, list) and len(error_data) > 0:
                        error_msg = str(error_data[0].get('msg', error_msg))
                except Exception as parse_err:
                    logger.warning(f"Erreur parsing erreur: {parse_err}")
                    error_msg = response.text[:500]
                
                logger.error(f"❌ Erreur serveur: {error_msg}")
                return {"success": False, "error": error_msg}
                        
        except Exception as e:
            logger.error(f"Erreur save_expense_to_server: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    # =========================================================
    # ENREGISTREMENT LOCAL
    # =========================================================
    def save_expense_locally(self, expense: dict) -> dict:
        """Enregistre la dépense localement"""
        try:
            expense_id = self.db.add_expense_from_dict(expense)
            if expense_id:
                return {"success": True, "expense_id": expense_id, "message": "Dépense enregistrée localement"}
            return {"success": False, "error": "Erreur lors de l'enregistrement local"}
        except Exception as err:
            logger.error(f"Erreur save_expense_locally: {err}")
            return {"success": False, "error": str(err)}

    # =========================================================
    # ENREGISTREMENT PRINCIPAL
    # =========================================================
    def save_expense(self, e):
        description = (self.description_field.value or "").strip()
        amount_text = (self.amount_field.value or "").strip()
        category = self.category_dropdown.value or "Divers"
        date_str = (self.date_field.value or "").strip()

        # Validation des champs
        if not description:
            self.show_error("Veuillez entrer une description")
            return

        if not amount_text:
            self.show_error("Veuillez entrer un montant")
            return

        amount_float = self._safe_float(amount_text, 0.0)
        if amount_float <= 0:
            self.show_error("Montant invalide")
            return

        try:
            expense_date = datetime.strptime(date_str, "%d/%m/%Y")
            expense_date_iso = expense_date.isoformat()
        except Exception:
            expense_date = datetime.now()
            expense_date_iso = expense_date.isoformat()

        branch_id = self._branch_id()
        is_online = self.is_online()
        
        expense = {
            "description": description,
            "amount": amount_float,
            "expense_date": expense_date_iso,
            "category": category,
            "branch_id": branch_id,
            "reference": f"EXP-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        }

        formatted_amount = self._format_money(amount_float)
        success_message = f"✅ Dépense enregistrée !\n📝 {description[:30]}{'...' if len(description) > 30 else ''}\n💰 {formatted_amount} - {category}"
        server_success = False
        expense_id = None

        # =========================================================
        # ENREGISTREMENT SUR LE SERVEUR (SI EN LIGNE)
        # =========================================================
        if is_online and self.sync_service:
            self.show_info("🔄 Enregistrement de la dépense sur le serveur...")
            
            server_result = self.save_expense_to_server(expense)
            
            if server_result.get("success"):
                server_success = True
                expense_id = server_result.get("server_id")
                
                # Message de succès
                self.show_success(success_message + "\n☁️ Synchronisée avec le serveur")
                
                # Vider les champs
                self.clear_form_fields()
                
                # Demander l'impression
                self.show_print_receipt_dialog(expense_id, expense, server_success=True)
                return
            else:
                error_msg = server_result.get("error", "Erreur inconnue")
                self.show_error(f"❌ Échec enregistrement serveur: {error_msg[:100]}")
                
                # Proposer l'enregistrement local
                self._ask_save_locally(expense, error_msg)
                return
        
        # =========================================================
        # ENREGISTREMENT LOCAL (SI HORS LIGNE)
        # =========================================================
        else:
            if not is_online:
                self.show_warning("📡 Mode hors-ligne - Enregistrement local")
            
            local_result = self.save_expense_locally(expense)
            
            if local_result.get("success"):
                expense_id = local_result.get("expense_id")
                
                # Message de succès avec mention de la synchronisation ultérieure
                if not is_online:
                    self.show_success(success_message + "\n🔄 Sera synchronisée automatiquement")
                else:
                    self.show_success(success_message)
                
                # Vider les champs
                self.clear_form_fields()
                
                # Tentative de synchronisation différée si online mais pas de serveur
                if is_online and self.sync_service:
                    try:
                        if hasattr(self.sync_service, "export_expenses"):
                            self.sync_service.export_expenses()
                    except Exception as sync_err:
                        logger.error(f"Erreur export différé: {sync_err}")
                
                self.show_print_receipt_dialog(expense_id, expense, server_success=False)
                return
            else:
                self.show_error(f"❌ Erreur: {local_result.get('error', 'Enregistrement impossible')}")
                return

    def _ask_save_locally(self, expense: dict, server_error: str):
        """Demande à l'utilisateur s'il veut enregistrer localement après échec serveur"""
        
        def save_locally(e):
            dialog.open = False
            self.page.update()
            
            local_result = self.save_expense_locally(expense)
            
            if local_result.get("success"):
                expense_id = local_result.get("expense_id")
                formatted_amount = self._format_money(expense['amount'])
                
                self.show_success(
                    f"💾 Dépense enregistrée localement!\n"
                    f"💰 {formatted_amount} - {expense.get('category', 'Divers')}\n"
                    f"🔄 Sera synchronisée automatiquement"
                )
                
                # Vider les champs
                self.clear_form_fields()
                
                # Marquer pour synchronisation ultérieure
                if hasattr(self.sync_service, "export_expenses"):
                    try:
                        self.sync_service.export_expenses()
                    except Exception:
                        pass
                
                self.show_print_receipt_dialog(expense_id, expense, server_success=False)
            else:
                self.show_error(f"❌ Erreur: {local_result.get('error', 'Enregistrement impossible')}")
        
        def cancel(e):
            dialog.open = False
            self.page.update()
            self.show_error("❌ Dépense non enregistrée")

        dialog = ft.AlertDialog(
            title=ft.Text("⚠️ Problème de connexion au serveur"),
            content=ft.Column(
                controls=[
                    ft.Text(
                        f"❌ Impossible d'enregistrer la dépense sur le serveur.\n\n"
                        f"📡 Erreur: {server_error[:200]}\n\n"
                        f"💡 Souhaitez-vous enregistrer la dépense localement ?\n"
                        f"   Elle sera synchronisée automatiquement lorsque la connexion sera rétablie.",
                        size=14,
                    ),
                ],
                tight=True,
                spacing=10,
            ),
            actions=[
                ft.TextButton(
                    content=ft.Text("Annuler"),
                    on_click=cancel,
                ),
                ft.Button(
                    content=ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.SAVE),
                            ft.Text("Enregistrer localement"),
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                    on_click=save_locally,
                    style=ft.ButtonStyle(
                        bgcolor=ft.Colors.GREEN,
                        color=ft.Colors.WHITE,
                    ),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()

    # =========================================================
    # DIALOG REÇU
    # =========================================================
    def show_print_receipt_dialog(self, expense_id, expense, server_success=False):
        from screens.receipt_export_screen import ReceiptExportScreen

        def close_dialog(e):
            dialog.open = False
            self.page.update()
            self.go_back()

        def print_receipt(e):
            dialog.open = False
            self.page.update()

            receipt_screen = ReceiptExportScreen(
                self.page,
                self.db,
                self.sync_service,
                self.auth_service,
                self.current_user,
            )
            receipt_screen.show_expense_receipt(expense_id, expense)

        # Message personnalisé selon le mode d'enregistrement
        if server_success:
            title = "✅ Dépense synchronisée"
            content_text = "La dépense a été enregistrée sur le serveur.\nVoulez-vous imprimer le reçu ?"
        else:
            title = "💾 Dépense enregistrée localement"
            content_text = "La dépense a été enregistrée localement.\nElle sera synchronisée automatiquement.\nVoulez-vous imprimer le reçu ?"

        dialog = ft.AlertDialog(
            title=ft.Text(title),
            content=ft.Text(content_text),
            actions=[
                ft.TextButton(
                    content=ft.Text("Non"),
                    on_click=close_dialog,
                ),
                ft.Button(
                    content=ft.Text("Oui, imprimer"),
                    on_click=print_receipt,
                    style=ft.ButtonStyle(
                        bgcolor=ft.Colors.BLUE,
                        color=ft.Colors.WHITE,
                    ),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        self.page.dialog = dialog
        dialog.open = True
        self.page.update()

    # =========================================================
    # HISTORIQUE
    # =========================================================
    def show_expense_history(self):
        self.show_expense_history_simple()

    def show_expense_history_simple(self):
        self.page.clean()

        header = ft.Container(
            content=ft.Row(
                controls=[
                    ft.IconButton(
                        icon=ft.Icons.ARROW_BACK,
                        on_click=lambda e: self.show(),
                        icon_color=ft.Colors.WHITE,
                    ),
                    ft.Text(
                        "Historique des dépenses",
                        size=24,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.WHITE,
                        expand=True,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=10,
            bgcolor=ft.Colors.RED_700,
            border_radius=10,
        )

        branch_id = self._branch_id()
        expenses = []

        if hasattr(self.db, "get_expenses_by_branch"):
            try:
                expenses = self.db.get_expenses_by_branch(branch_id)
            except Exception as err:
                print(f"Erreur historique dépenses: {err}")
                expenses = []

        expenses_list = ft.ListView(expand=True, spacing=10, padding=10)

        if not expenses:
            expenses_list.controls.append(
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Icon(ft.Icons.MONEY_OFF, size=80, color=ft.Colors.GREY_400),
                            ft.Text("Aucune dépense enregistrée", size=16, color=ft.Colors.GREY_600),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=10,
                    ),
                    alignment=ft.Alignment.CENTER,
                    expand=True,
                )
            )
        else:
            total = 0.0

            for expense in expenses:
                total += self._safe_float(expense.get("amount", 0), 0.0)
                expenses_list.controls.append(self.create_expense_card(expense))

            total_card = ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Text("Total des dépenses:", size=16, weight=ft.FontWeight.BOLD),
                        ft.Text(
                            self._format_money(total),
                            size=18,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.RED_700,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                padding=15,
                bgcolor=ft.Colors.GREY_100,
                border_radius=10,
                margin=10,
            )
            expenses_list.controls.append(total_card)

        self.page.add(header, expenses_list)
        self.page.update()

    def create_expense_card(self, expense):
        expense_date_raw = expense.get("expense_date")
        try:
            expense_date = (
                datetime.fromisoformat(expense_date_raw).strftime("%d/%m/%Y %H:%M")
                if expense_date_raw
                else "Date inconnue"
            )
        except Exception:
            expense_date = str(expense_date_raw or "Date inconnue")

        is_synced = expense.get("is_synced", 0)
        sync_icon = ft.Icon(
            ft.Icons.CLOUD_DONE if is_synced else ft.Icons.SYNC_PROBLEM,
            size=12,
            color=ft.Colors.GREEN if is_synced else ft.Colors.ORANGE,
        )

        return ft.Card(
            content=ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Column(
                            controls=[
                                ft.Text(
                                    expense.get("description", "Sans description"),
                                    size=14,
                                    weight=ft.FontWeight.BOLD,
                                ),
                                ft.Text(
                                    f"Catégorie: {expense.get('category', 'Divers')}",
                                    size=12,
                                    color=ft.Colors.GREY_600,
                                ),
                                ft.Row(
                                    controls=[
                                        sync_icon,
                                        ft.Text(
                                            expense_date,
                                            size=11,
                                            color=ft.Colors.GREY_500,
                                        ),
                                    ],
                                    spacing=5,
                                ),
                            ],
                            expand=True,
                            spacing=4,
                        ),
                        ft.Column(
                            controls=[
                                ft.Text(
                                    self._format_money(expense.get("amount", 0)),
                                    size=16,
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.RED_700,
                                ),
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.END,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=10,
            ),
            margin=5,
        )

    # =========================================================
    # DIVERS
    # =========================================================
    def upload_receipt(self, e):
        self.show_snackbar("Fonctionnalité d'upload de reçu à venir", ft.Colors.ORANGE)

    def go_back(self):
        from screens.dashboard_screen import DashboardScreen

        dashboard = DashboardScreen(
            self.page,
            self.db,
            self.sync_service,
            self.auth_service,
            self.current_user,
            self.connection_manager,
        )
        dashboard.show()