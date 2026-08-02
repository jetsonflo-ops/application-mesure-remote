"""Tests unitaires pour les modeles."""
import pytest
import os
import sys
from datetime import datetime, timedelta

# Ajouter le dossier parent au path Python
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models.user import User, AuthManager, validate_password_strength
from src.models.tool import Tool, ToolsRepository
from src.models.measurement import Measurement, MeasurementsRepository


class TestUser:
    """Tests pour la classe User."""
    
    def test_user_creation(self):
        user = User(username="test", role="supervision")
        assert user.username == "test"
        assert user.role == "supervision"
        assert user.created_at is not None
    
    def test_user_to_dict(self):
        user = User(user_id=1, username="admin", role="supervision")
        data = user.to_dict()
        assert data['username'] == "admin"
        assert data['role'] == "supervision"
    
    def test_user_must_change_password(self):
        user = User(username="test", role="operateur", must_change_password=True)
        assert user.must_change_password is True
        data = user.to_dict()
        assert data['must_change_password'] is True


class TestPasswordStrength:
    """Tests pour la validation de force du mot de passe."""
    
    def test_valid_password(self):
        valid, msg = validate_password_strength("MonMot2passe!")
        assert valid is True
        assert msg == ""
    
    def test_too_short(self):
        valid, msg = validate_password_strength("Ab1!")
        assert valid is False
        assert "8 caracteres" in msg
    
    def test_no_uppercase(self):
        valid, msg = validate_password_strength("monmot2passe!")
        assert valid is False
        assert "majuscule" in msg
    
    def test_no_lowercase(self):
        valid, msg = validate_password_strength("MONMOT2PASSE!")
        assert valid is False
        assert "minuscule" in msg
    
    def test_no_digit(self):
        valid, msg = validate_password_strength("MonMotPasse!")
        assert valid is False
        assert "chiffre" in msg
    
    def test_no_special_char(self):
        valid, msg = validate_password_strength("MonMot2passe")
        assert valid is False
        assert "special" in msg
    
    def test_all_requirements_met(self):
        valid, _ = validate_password_strength("Str0ng!Pass")
        assert valid is True


class TestTool:
    """Tests pour la classe Tool."""
    
    def test_tool_creation(self):
        tool = Tool(name="Regle 500mm", unit="mm")
        assert tool.name == "Regle 500mm"
        assert tool.unit == "mm"
        assert tool.status == "disconnected"
    
    def test_tool_to_dict(self):
        tool = Tool(tool_id=1, name="Micrometre", unit="um")
        data = tool.to_dict()
        assert data['tool_id'] == 1
        assert data['name'] == "Micrometre"


class TestMeasurement:
    """Tests pour la classe Measurement."""
    
    def test_measurement_creation(self):
        measurement = Measurement(tool_id=1, value=1.234, unit="mm")
        assert measurement.tool_id == 1
        assert measurement.value == 1.234
        assert measurement.unit == "mm"
        assert measurement.status == "OK"
    
    def test_measurement_timestamp(self):
        measurement = Measurement(tool_id=1, value=0.5, unit="mm")
        assert measurement.timestamp is not None


class TestToolsRepository:
    """Tests pour l'outil de stockage des outils."""
    
    def test_repository_creation(self):
        repo = ToolsRepository("config/test_tools_temp.json")
        assert isinstance(repo.tools, list)
        
        if os.path.exists("config/test_tools_temp.json"):
            os.remove("config/test_tools_temp.json")
    
    def test_default_tools(self):
        repo = ToolsRepository("config/test_tools_temp.json")
        assert len(repo.tools) > 0


class TestMeasurementsRepository:
    """Tests pour le stockage des mesures."""
    
    def test_repository_creation(self):
        repo = MeasurementsRepository("config/test_measures_temp.json")
        assert isinstance(repo.measurements, list)
        
        if os.path.exists("config/test_measures_temp.json"):
            os.remove("config/test_measures_temp.json")
    
    def test_add_measurement(self):
        repo = MeasurementsRepository("config/test_measures_temp.json")
        measurement = Measurement(tool_id=1, value=1.0, unit="mm")
        repo.add_measurement(measurement)
        
        assert len(repo.measurements) == 1
        assert repo.measurements[0].value == 1.0
        
        if os.path.exists("config/test_measures_temp.json"):
            os.remove("config/test_measures_temp.json")


class TestAuthManager:
    """Tests pour le gestionnaire d'authentification."""
    
    def test_auth_manager_creation(self):
        auth = AuthManager("config/test_users_temp.db")
        assert auth is not None
        
        if os.path.exists("config/test_users_temp.db"):
            os.remove("config/test_users_temp.db")
    
    def test_default_credentials(self):
        auth = AuthManager("config/test_users_temp.db")
        
        user = auth.authenticate("admin", "SPlate-shop")
        assert user is not None
        assert user.role == "supervision"

        user2 = auth.authenticate("operateur", "Plate-shop")
        assert user2 is not None
        assert user2.role == "operateur"
        
        if os.path.exists("config/test_users_temp.db"):
            os.remove("config/test_users_temp.db")
    
    def test_must_change_password_on_default(self):
        auth = AuthManager("config/test_users_temp2.db")
        user = auth.authenticate("admin", "SPlate-shop")
        assert user is not None
        assert user.must_change_password is True
        
        if os.path.exists("config/test_users_temp2.db"):
            os.remove("config/test_users_temp2.db")
    
    def test_password_change_clears_must_change(self):
        auth = AuthManager("config/test_users_temp3.db")
        user = auth.authenticate("admin", "SPlate-shop")
        assert user is not None
        
        ok, msg = auth.change_password("admin", "SPlate-shop", "N0uveau!Pass")
        assert ok is True
        
        user2 = auth.authenticate("admin", "N0uveau!Pass")
        assert user2 is not None
        assert user2.must_change_password is False
        
        if os.path.exists("config/test_users_temp3.db"):
            os.remove("config/test_users_temp3.db")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
