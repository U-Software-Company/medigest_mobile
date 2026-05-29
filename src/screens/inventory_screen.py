# Créer un fichier screens/inventory_screen.py temporaire
# screens/inventory_screen.py
import flet as ft

class InventoryScreen:
    def __init__(self, page, db, sync_service, auth_service, current_user, notification_manager=None):
        self.page = page
        self.db = db
        
    def show(self):
        snack = ft.SnackBar(content=ft.Text("📋 Écran d'inventaire - Fonctionnalité à venir"))
        self.page.snack_bar = snack
        snack.open = True
        self.page.update()