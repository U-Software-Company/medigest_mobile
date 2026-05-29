# screens/user_management_screen.py
import flet as ft

class UserManagementScreen:
    def __init__(self, page, db, sync_service, auth_service, current_user, notification_manager=None):
        self.page = page
        self.db = db
        
    def show(self):
        snack = ft.SnackBar(content=ft.Text("👥 Gestion des utilisateurs - Fonctionnalité à venir"))
        self.page.snack_bar = snack
        snack.open = True
        self.page.update()