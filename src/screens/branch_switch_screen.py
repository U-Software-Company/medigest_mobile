import flet as ft
import requests


class BranchSwitchScreen:
    def __init__(self, page: ft.Page, db, sync_service, auth_service, current_user):
        self.page = page
        self.db = db
        self.sync_service = sync_service
        self.auth_service = auth_service
        self.current_user = current_user

        self.branches: list[dict] = []
        self.branches_list_view: ft.ListView | None = None

    # =========================================================
    # OUTILS
    # =========================================================
    def show_snackbar(self, message: str, color=ft.Colors.BLUE) -> None:
        snack = ft.SnackBar(
            content=ft.Text(message, color=ft.Colors.WHITE),
            bgcolor=color,
            open=True,
        )
        self.page.snack_bar = snack
        self.page.update()

    def close_dialog(self, dialog: ft.AlertDialog) -> None:
        dialog.open = False
        self.page.update()

    def get_current_branch_id(self):
        return (
            self.current_user.get("active_branch_id")
            or self.current_user.get("branch_id")
        )

    def get_token(self) -> str | None:
        return self.current_user.get("token")

    def get_pharmacy_id(self) -> str | None:
        return self.current_user.get("pharmacy_id")

    # =========================================================
    # AFFICHAGE
    # =========================================================
    def show(self):
        self.page.clean()
        self.page.padding = 0
        self.page.bgcolor = ft.Colors.GREY_100
        self.page.scroll = ft.ScrollMode.AUTO

        self.branches_list_view = ft.ListView(
            expand=True,
            spacing=10,
            padding=10,
        )

        main_content = ft.SafeArea(
            expand=True,
            content=ft.Column(
                expand=True,
                spacing=0,
                controls=[
                    self.build_header(),
                    ft.Container(
                        padding=ft.Padding.all(12),
                        content=ft.Text(
                            "Sélectionnez une succursale",
                            size=16,
                            weight=ft.FontWeight.W_500,
                            color=ft.Colors.BLUE_GREY_900,
                        ),
                    ),
                    self.branches_list_view,
                ],
            ),
        )

        self.page.add(main_content)
        self.load_branches()
        self.page.update()

    def build_header(self) -> ft.Container:
        return ft.Container(
            bgcolor=ft.Colors.BLUE_700,
            padding=ft.Padding.symmetric(horizontal=8, vertical=10),
            content=ft.Row(
                alignment=ft.MainAxisAlignment.START,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.IconButton(
                        icon=ft.Icons.ARROW_BACK,
                        on_click=lambda e: self.go_back(),
                        icon_color=ft.Colors.WHITE,
                        tooltip="Retour",
                    ),
                    ft.Text(
                        "Changer de succursale",
                        size=22,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.WHITE,
                    ),
                ],
            ),
        )

    # =========================================================
    # CHARGEMENT DES SUCCURSALES
    # =========================================================
    def load_branches(self):
        if not self.branches_list_view:
            return

        if not self.sync_service.check_internet_connection():
            self.show_error_message("Connexion Internet requise pour changer de succursale.")
            return

        self.show_loading_state()

        try:
            token = self.get_token()
            pharmacy_id = self.get_pharmacy_id()
            
            if not token:
                self.show_error_message("Token utilisateur introuvable.")
                return
            
            if not pharmacy_id:
                self.show_error_message("ID de pharmacie introuvable.")
                return

            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            }

            # URL corrigée pour récupérer les branches d'une pharmacie spécifique
            api_url = f"{self.sync_service.api_url}/pharmacies/{pharmacy_id}/branches"
            print(f"Chargement des branches depuis: {api_url}")

            response = requests.get(
                api_url,
                headers=headers,
                timeout=30,
            )

            print(f"Status code: {response.status_code}")

            if response.status_code == 200:
                payload = response.json()
                # La réponse est directement la liste des branches
                if isinstance(payload, list):
                    self.branches = payload
                else:
                    self.branches = payload.get("branches", []) or payload.get("items", [])
                
                print(f"Branches récupérées: {len(self.branches)}")
                self.display_branches()
            elif response.status_code == 401:
                self.show_error_message("Session expirée. Reconnecte-toi.")
            elif response.status_code == 403:
                self.show_error_message("Accès refusé aux succursales.")
            elif response.status_code == 404:
                self.show_error_message("Aucune succursale trouvée pour cette pharmacie.")
            else:
                self.show_error_message(
                    f"Erreur lors du chargement des succursales (HTTP {response.status_code})."
                )

        except requests.RequestException as ex:
            print(f"Erreur réseau: {ex}")
            self.show_error_message(f"Erreur réseau : {ex}")
        except Exception as ex:
            print(f"Erreur: {ex}")
            self.show_error_message(f"Erreur : {ex}")

    def show_loading_state(self):
        if not self.branches_list_view:
            return

        self.branches_list_view.controls.clear()
        self.branches_list_view.controls.append(
            ft.Container(
                expand=True,
                alignment=ft.Alignment.CENTER,
                padding=20,
                content=ft.Column(
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=12,
                    controls=[
                        ft.ProgressRing(),
                        ft.Text(
                            "Chargement des succursales...",
                            size=14,
                            color=ft.Colors.GREY_700,
                        ),
                    ],
                ),
            )
        )
        self.page.update()

    def display_branches(self):
        if not self.branches_list_view:
            return

        self.branches_list_view.controls.clear()

        if not self.branches:
            self.branches_list_view.controls.append(
                ft.Container(
                    expand=True,
                    alignment=ft.alignment.center,
                    padding=20,
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=10,
                        controls=[
                            ft.Icon(ft.icons.STORE, size=64, color=ft.Colors.GREY_400),
                            ft.Text(
                                "Aucune succursale disponible",
                                size=16,
                                color=ft.Colors.GREY_700,
                            ),
                            ft.Text(
                                "Contactez votre administrateur pour créer une succursale.",
                                size=12,
                                color=ft.Colors.GREY_500,
                            ),
                        ],
                    ),
                )
            )
        else:
            current_branch_id = self.get_current_branch_id()

            for branch in self.branches:
                branch_id = branch.get("id")
                is_current = branch_id == current_branch_id
                self.branches_list_view.controls.append(
                    self.create_branch_card(branch, is_current)
                )

        self.page.update()

    # =========================================================
    # UI
    # =========================================================
    def create_branch_card(self, branch: dict, is_current: bool) -> ft.Card:
        branch_name = branch.get("name", "Succursale sans nom")
        branch_code = branch.get("code", "")
        branch_address = branch.get("address") or "Adresse non spécifiée"
        branch_city = branch.get("city") or ""
        branch_phone = branch.get("phone") or "N/A"
        branch_email = branch.get("email") or ""
        is_main_branch = branch.get("is_main_branch", False)

        # Construire l'adresse complète
        full_address = branch_address
        if branch_city:
            full_address = f"{branch_address}, {branch_city}" if branch_address else branch_city

        def on_select(e):
            if not is_current:
                self.switch_branch(branch)

        # Action control (bouton ou icône de vérification)
        if is_current:
            action_control = ft.Container(
                content=ft.Column(
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=2,
                    controls=[
                        ft.Icon(
                            ft.Icons.CHECK_CIRCLE,
                            color=ft.Colors.GREEN,
                            size=32,
                        ),
                        ft.Text(
                            "Actuelle",
                            size=10,
                            color=ft.Colors.GREEN,
                            weight=ft.FontWeight.BOLD,
                        ),
                    ],
                ),
            )
        else:
            action_control = ft.Button(
                content=ft.Text("Changer", size=12),
                on_click=on_select,
                style=ft.ButtonStyle(
                    bgcolor=ft.Colors.BLUE_700,
                    color=ft.Colors.WHITE,
                    padding=ft.Padding.symmetric(horizontal=16, vertical=8),
                    shape=ft.RoundedRectangleBorder(radius=8),
                ),
            )

        # Badge pour la branche principale
        main_badge = None
        if is_main_branch:
            main_badge = ft.Container(
                content=ft.Text("Principale", size=10, color=ft.Colors.WHITE),
                bgcolor=ft.Colors.ORANGE_700,
                border_radius=4,
                padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                margin=ft.Margin.only(left=8),
            )

        return ft.Card(
            elevation=2,
            margin=ft.Margin.symmetric(horizontal=4, vertical=4),
            content=ft.Container(
                padding=15,
                bgcolor=ft.Colors.BLUE_50 if is_current else ft.Colors.WHITE,
                border_radius=16,
                content=ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Column(
                            expand=True,
                            spacing=6,
                            controls=[
                                ft.Row(
                                    spacing=4,
                                    controls=[
                                        ft.Text(
                                            branch_name,
                                            size=16,
                                            weight=ft.FontWeight.BOLD,
                                            color=ft.Colors.BLUE_GREY_900,
                                        ),
                                        main_badge if main_badge else ft.Text(),
                                    ],
                                ),
                                ft.Text(
                                    full_address if full_address else "Adresse non spécifiée",
                                    size=12,
                                    color=ft.Colors.GREY_700,
                                ),
                                ft.Row(
                                    spacing=12,
                                    controls=[
                                        ft.Row(
                                            spacing=4,
                                            controls=[
                                                ft.Icon(ft.Icons.PHONE, size=12, color=ft.Colors.GREY_600),
                                                ft.Text(branch_phone, size=12, color=ft.Colors.GREY_700),
                                            ],
                                        ),
                                        ft.Row(
                                            spacing=4,
                                            controls=[
                                                ft.Icon(ft.Icons.EMAIL, size=12, color=ft.Colors.GREY_600),
                                                ft.Text(branch_email if branch_email else "N/A", size=12, color=ft.Colors.GREY_700),
                                            ],
                                        ) if branch_email else ft.Text(),
                                    ],
                                ),
                                ft.Text(
                                    f"Code: {branch_code}" if branch_code else "",
                                    size=11,
                                    color=ft.Colors.GREY_500,
                                ),
                            ],
                        ),
                        action_control,
                    ],
                ),
            ),
        )

    # =========================================================
    # CHANGEMENT DE SUCCURSALE
    # =========================================================
    def switch_branch(self, new_branch: dict):
        branch_name = new_branch.get("name", "cette succursale")
        branch_id = new_branch.get("id")

        def confirm_switch(e):
            self.close_dialog(dialog)

            try:
                updated_user = self.current_user.copy()
                updated_user["active_branch_id"] = branch_id
                updated_user["branch_id"] = branch_id
                updated_user["branch_name"] = branch_name

                # Sauvegarder l'utilisateur mis à jour
                self.auth_service.save_user(updated_user)
                self.current_user = updated_user

                self.show_snackbar(
                    "Chargement des produits de la nouvelle succursale...",
                    ft.Colors.BLUE,
                )

                # Re-synchroniser les produits pour la nouvelle branche
                self.sync_service.import_products()

                from screens.dashboard_screen import DashboardScreen

                dashboard = DashboardScreen(
                    self.page,
                    self.db,
                    self.sync_service,
                    self.auth_service,
                    updated_user,
                )
                dashboard.show()

                self.show_snackbar(
                    f"Succursale changée : {branch_name}",
                    ft.Colors.GREEN,
                )

            except Exception as ex:
                print(f"Erreur lors du changement: {ex}")
                self.show_snackbar(f"Erreur lors du changement : {ex}", ft.Colors.RED)

        dialog = ft.AlertDialog(
            title=ft.Text("Changer de succursale"),
            content=ft.Text(
                f"Voulez-vous passer à la succursale « {branch_name} » ?\n\n"
                "Les produits seront re-synchronisés pour cette succursale."
            ),
            actions=[
                ft.TextButton(
                    "Annuler",
                    on_click=lambda e: self.close_dialog(dialog),
                ),
                ft.Button(
                    "Confirmer",
                    on_click=confirm_switch,
                    style=ft.ButtonStyle(
                        bgcolor=ft.Colors.BLUE_700,
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
    # ERREURS
    # =========================================================
    def show_error_message(self, message: str):
        if not self.branches_list_view:
            return

        self.branches_list_view.controls.clear()
        self.branches_list_view.controls.append(
            ft.Container(
                expand=True,
                alignment=ft.Alignment.CENTER,
                padding=20,
                content=ft.Column(
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=16,
                    controls=[
                        ft.Icon(
                            ft.Icons.ERROR_OUTLINE,
                            size=72,
                            color=ft.Colors.RED,
                        ),
                        ft.Text(
                            message,
                            size=16,
                            color=ft.Colors.RED,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Button(
                            content=ft.Text("Réessayer"),
                            on_click=lambda e: self.load_branches(),
                        ),
                    ],
                ),
            )
        )
        self.page.update()

    # =========================================================
    # NAVIGATION
    # =========================================================
    def go_back(self):
        from screens.dashboard_screen import DashboardScreen

        dashboard = DashboardScreen(
            self.page,
            self.db,
            self.sync_service,
            self.auth_service,
            self.current_user,
        )
        dashboard.show()